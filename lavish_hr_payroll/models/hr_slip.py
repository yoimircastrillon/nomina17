# -*- coding: utf-8 -*-
from odoo import models, fields, api, _, SUPERUSER_ID , tools
from odoo.exceptions import UserError, ValidationError
from odoo.tools import float_compare, float_is_zero, float_round, date_utils
from collections import defaultdict
from datetime import datetime, timedelta, date, time
from odoo.tools.misc import format_date

from collections import defaultdict, Counter
from dateutil.relativedelta import relativedelta
import ast
from odoo import api, Command, fields, models, _
from .browsable_object import BrowsableObject, InputLine, WorkedDays, Payslips, ResultRules
from .browsable_object import ResultRules_co
from odoo.exceptions import UserError, ValidationError
from odoo.osv.expression import AND
from odoo.tools import float_round, date_utils, convert_file, html2plaintext, is_html_empty, format_amount
from odoo.tools.float_utils import float_compare
from odoo.tools.misc import format_date
from odoo.tools.safe_eval import safe_eval

import logging
_logger = logging.getLogger(__name__)
class Hr_payslip(models.Model):
    _inherit = 'hr.payslip'
    def convert_tuples_to_dict(self,tuple_list):
        data_list = ast.literal_eval(tuple_list)
        return data_list

    def days_between(self,start_date,end_date):
        s1, e1 =  start_date , end_date + timedelta(days=1)
        #Convert to 360 days
        s360 = (s1.year * 12 + s1.month) * 30 + s1.day
        e360 = (e1.year * 12 + e1.month) * 30 + e1.day
        #Count days between the two 360 dates and return tuple (months, days)
        res = divmod(e360 - s360, 30)
        return ((res[0] * 30) + res[1]) or 0

    #obligaciones_ids = fields.One2many('hr.payslip.obligacion.tributaria.line', 'payslip_id', 'Obligaciones Tributarias', readonly=True, ondelete='cascade')
    periodo = fields.Char('Periodo', compute="_periodo")
    extrahours_ids = fields.One2many('hr.overtime', 'payslip_run_id',  string='Horas Extra Detallada', )
    novedades_ids = fields.One2many('hr.novelties.different.concepts', 'payslip_id',  string='Novedades Detalladas')
    payslip_old_ids = fields.Many2many('hr.payslip', 'hr_payslip_rel', 'current_payslip_id', 'old_payslip_id', string='Nominas relacionadas')
    resulados_op = fields.Html('Resultados')
    resulados_rt = fields.Text('Resultados RT')

    def _periodo(self):
        for rec in self:
            if rec.date_to:
                rec.periodo = rec.date_to.strftime("%Y%m")
            else:
                rec.periodo = ''
    
    def old_payslip_moth(self):
        # 1. Busca las nóminas de tipo vacaciones o prima.
        payslip_objs = self.env['hr.payslip'].search([('struct_id.process', 'in', ['vacaciones', 'prima'])])
        # 2. Asigna esos registros al campo many2many.
        for record in self:
            record.payslip_old_ids = [(6, 0, payslip_objs.ids)]

    def _assign_old_payslips(self):
        for payslip in self:
            # Considera el mes actual del payslip
            start_date = payslip.date_from.replace(day=1)
            end_date = (start_date + relativedelta(months=1, days=-1))
            
            # Busca las nóminas de tipo 'vacaciones' o 'prima', que pertenezcan al mismo mes, empleado y contrato
            domain = [
                ('id', '!=', payslip.id),  # Para excluir la nómina actual
                ('employee_id', '=', payslip.employee_id.id),
                ('contract_id', '=', payslip.contract_id.id),
                ('date_from', '>=', start_date.strftime('%Y-%m-%d')),
                ('date_to', '<=', end_date.strftime('%Y-%m-%d')),
                ('struct_id.process', 'in', ['vacaciones', 'prima']),
            ]
            old_payslips = self.env['hr.payslip'].search(domain)
            # Asigna esos registros al campo many2many
            payslip.payslip_old_ids = [(6, 0, old_payslips.ids)]

    def _compute_extra_hours(self):
        for payslip in self:
            if payslip.struct_id.process in ('nomina', 'contrato', 'otro'):
                query = """
                UPDATE hr_overtime
                SET payslip_run_id = %s
                WHERE 
                    (state = 'validated' OR payslip_run_id IS NULL)
                    AND date_end BETWEEN %s AND %s
                    AND employee_id = %s
                """
                self.env.cr.execute(query, (payslip.id, payslip.date_from, payslip.date_to, payslip.employee_id.id))

    def _compute_novedades(self):
        for payslip in self:
            query_params = [payslip.id, payslip.employee_id.id]
            date_conditions = ""
            if payslip.struct_id.process in ('nomina', 'contrato', 'otro', 'prima'):
                date_conditions = "AND date >= %s AND date <= %s"
                query_params.extend([payslip.date_from, payslip.date_to])

            query = """
            UPDATE hr_novelties_different_concepts
            SET payslip_id = %s
            WHERE payslip_id IS NULL 
            AND employee_id = %s 
            """ + date_conditions
            self.env.cr.execute(query, tuple(query_params))


    def get_worked_day_lines(self):
        payslip = self

        contract = payslip.contract_id
        hp_type = payslip.struct_process
        vac = payslip.struct_process == 'vacaciones'
        # String format
        start_period = payslip.date_from.replace(day=1)
        end_period = payslip.date_to
        k_start_date = contract.date_start
        k_end_date = contract.date_end
        annual_parameters = self.env['hr.annual.parameters'].search([('year', '=', end_period.year)])
        wdayst = self.env['hr.work.entry.type'].search([("code", "=", "WORK_D")], limit=1)
        wdays = self.env['hr.work.entry.type'].search([("code", "=", "WORK100")], limit=1)
        outdays = self.env['hr.work.entry.type'].search([("code", "=", "OUT")], limit=1)
        prevdays = self.env['hr.work.entry.type'].search([("code", "=", "PREV_PAYS")], limit=1)
        # Date format
        dt_sp = start_period
        dt_ep = end_period
        dt_ksd = k_start_date
        dt_ked = k_end_date if k_end_date else False
        ps_types = ['nomina', 'contrato']
        if not payslip.company_id.fragment_vac:
            ps_types.append('Vacaciones')
        res = []
        if hp_type in ps_types:
            w_days = {
                'work_entry_type_id': wdayst.id,
                'name': 'Total dias periodo',
                'sequence': 1,
                'symbol': '',
                'number_of_days': 0.0,
                'number_of_hours': 0.0,
                'contract_id': contract.id
            }
            paid_rest = {
                'name': _("LICENCIA REMUNERADA"),
                'sequence': 4,
                'code': 'LICENCIA_REMUNERADA',
                'symbol': '+',
                'number_of_days': 0.0,
                'number_of_hours': 0.0,
                'contract_id': contract.id
            }

            calendar = contract.resource_calendar_id
            w_hours = annual_parameters.hours_daily
            sch_pay = contract.method_schedule_pay
            lab_days = payslip.days_between(start_period,end_period) #period_obj.get_schedule_days(sch_pay)
            w_days['number_of_days'] = lab_days
            w_days['number_of_hours'] = w_hours * lab_days

            # Dias trabajados, en principio se deben asumir iguales a los laborables
            worked = lab_days
            
            # Deduccion por inicio de contrato
            if dt_ksd > dt_sp:
                if dt_ep >= dt_ksd:
                    ded_start_days = (dt_ksd - dt_sp).days
                else:
                    ded_start_days = lab_days
                name = _("Deduccion por Inicio de contrato")    
                ded_start = {
                    'work_entry_type_id': outdays.id,
                    'name': name,
                    'sequence': 2,
                    'symbol': '-',
                    'number_of_days': ded_start_days,
                    'number_of_hours': ded_start_days * w_hours,
                    'contract_id': contract.id
                }
                res += [ded_start]
                worked -= ded_start_days
            # Deduccion por fin de contrato
            if dt_ked and dt_ked <= dt_ep:
                ded_end_days = payslip.days_between(dt_ked,dt_ep) -1
                if dt_ep.day == 31 and ded_end_days:
                    ded_end_days -= 1
                if dt_ked.month == 2 and (contract.method_schedule_pay == 'monthly' or (contract.method_schedule_pay == 'bi-weekly')):
                        #Febrero y Febrero bisiesto
                        day_febrero = 30 - dt_ep.day if ded_end_days else 0
                        ded_end_days += day_febrero
                if ded_end_days:
                    ded_end = {
                        'work_entry_type_id': outdays.id,
                        'name': _("Deduccion por fin de contrato"),
                        'sequence': 2,
                        'symbol': '-',
                        'number_of_days': ded_end_days,
                        'number_of_hours': ded_end_days * w_hours,
                        'contract_id': contract.id
                    }

                    if dt_ep.month == 2 and (sch_pay == 'bi-weekly' or sch_pay == 'monthtly'):
                        ded_end['number_of_days'] += 2
                        ded_end['number_of_hours'] += 2 * w_hours
                        worked -= 2
                    res += [ded_end]
                worked -= ded_end_days
                dom31 =  end_period.day == 31 and end_period.weekday() == 6
                apr = contract.modality_salary == 'sostenimiento'
                undef = contract.contract_type == 'indefinido'
                l_kw_day = int(calendar.attendance_ids[-1].dayofweek)
                if dt_ked.weekday() == l_kw_day and undef and not apr:
                    days_workable = len(set([x.dayofweek for x in calendar.attendance_ids]))
                    if days_workable == 5:
                        c_day = 2
                        if dom31 and k_end_date[8:10] == '29':
                            c_day = 1
                    elif days_workable == 7:
                        c_day = 0
                    else:  # 6 days of week
                        c_day = 1
                    paid_rest['number_of_days'] = c_day
                    paid_rest['number_of_hours'] = c_day * w_hours
                    worked += c_day
                    res += [paid_rest]

            leaves_worked_lines = {}
            sch_pay == 'bi-monthly' and dt_ep.month == 2 and payslip.struct_process == 'vacaciones'
            # Ausencias
            prev_pays = {
                'work_entry_type_id': prevdays.id,
                'sequence': 3,
                'code': 'PREV_PAYS',
                'symbol': '-',
                'number_of_days': 0,
                'number_of_hours': 0,
                'contract_id': contract.id
            }
            prev_aus = {
                'name': _("Ausencias de otros periodos"),
                'sequence': 3,
                'code': 'PREV_AUS',
                'symbol': '+',
                'number_of_days': 0,
                'number_of_hours': 0,
                'contract_id': contract.id
            }
            if payslip.company_id.aus_prev:
                for leave in payslip.leave_ids:
                    if leave.holiday_status_id.sub_wd:
                        for leave_day in leave.line_ids:
                            prev_period = leave_day.name < start_period
                            not_payed = leave_day.state == 'validate'
                            if start_period <= leave.approve_date <= end_period:
                                if prev_period and not_payed:
                                    prev_pays['number_of_days'] += leave_day.days_payslip
                                    prev_pays['number_of_hours'] += leave_day.hours 
                                    prev_aus['number_of_days'] += leave_day.days_payslip
                                    prev_aus['number_of_hours'] += leave_day.hours

            # Ausencias por dias
            for leave in payslip.leave_days_ids:
                if leave.days_payslip <= 0:
                    continue
                qty_days = leave.days_payslip
                qty_hours = leave.hours
                if leave.leave_id.holiday_status_id.is_vacation and leave.state == 'paid':
                    prev_pays['number_of_days'] += qty_days
                    prev_pays['number_of_hours'] += qty_hours 
                    worked -= qty_days
                    continue
                pay_day_31 = True if leave.leave_id.holiday_status_id.apply_day_31 else False
                #if (not pay_day_31 and leave.sequence == '31') or leave.state != "validate":
                #    continue
                #elif pay_day_31 and leave.sequence == '31':
                #    worked += 1
                if leave.leave_id.holiday_status_id.sub_wd:
                    worked -= qty_days
                key = (leave.leave_id.holiday_status_id.id, '-')
                if key not in leaves_worked_lines:
                    l_hol_name = leave.leave_id.holiday_status_id.name
                    name = (u"Días %s") % l_hol_name.capitalize()
                    leaves_worked_lines[key] = {
                        'work_entry_type_id': leave.leave_id.holiday_status_id.work_entry_type_id.id,
                        'name': name,
                        'sequence': 4,
                        'code': (leave.leave_id.holiday_status_id.code or 'nocode'),
                        'symbol': '-',
                        'number_of_days': qty_days,
                        'number_of_hours': qty_hours,
                        'contract_id': contract.id,
                    }
                else:
                    leaves_worked_lines[key]['number_of_days'] += qty_days
                    leaves_worked_lines[key]['number_of_hours'] += qty_hours

            leaves_worked_lines = [value for key, value in leaves_worked_lines.items()]
            # Dias pagados en otras nominas
            query = """
            SELECT
                SUM(wd.number_of_days) AS number_of_days,
                wd.symbol,
                hw.code
            FROM hr_payslip_worked_days wd
            INNER JOIN hr_payslip hp ON hp.id = wd.payslip_id
            LEFT JOIN hr_work_entry_type hw on hw.id = wd.work_entry_type_id
            WHERE hp.date_from >= %s
                AND hp.date_to <= %s
                AND hp.contract_id = %s
                AND hp.id != %s
                AND hw.code NOT IN ('WORK_D', 'LICENCIA_REMUNERADA')
                AND hp.struct_process IN ('vacaciones', 'nomina', 'contrato')
                AND hp.state in ('done','paid')
            GROUP BY wd.symbol, hw.code
            """
            
            params = (start_period, end_period, contract.id, payslip.id)
            self._cr.execute(query, params)
            wd_other_data = self._cr.fetchall()
            #_logger.error(f'\ aquiii\{wd_other_data}\\')
            # Inicializar variables
            wd_other = 0
            wd_plus = 0
            wd_prev = 0
            wd_minus = 0
            
            # Procesar los datos
            for number_of_days, symbol, code in wd_other_data:

                if code == 'WORK_D':
                    wd_other += number_of_days
                else:
                    if code in ('PREV_AUS', 'PREV_PAYS'):
                        wd_prev += 0#number_of_days
                    elif symbol in ('-', '') and code not in ('OUT', 'VAC', 'VACDISFRUTADAS'):
                        wd_minus += number_of_days
            
            sum_wdo = wd_plus + wd_minus - wd_prev
            #_logger.error(f'\ por aca aquiii\{sum_wdo}\\')
            wd_other = sum_wdo
            # #############################################

            if wd_other:
                prev_pays['number_of_days'] += wd_other
                prev_pays['number_of_hours'] += wd_other * w_hours
                worked -= wd_other

            if not payslip.company_id.fragment_vac:
                vac_flag, vac_end = False, False
                if vac:
                    for leave in payslip.leave_ids:
                        ldt = leave.date_to[0:10]
                        if leave.holiday_status_id.vacaciones and ldt < dt_ep:
                            vac_flag = True
                            vac_end = ldt

                if vac_flag and vac_end:
                    fix = 1 if dt_ep.day == 31 else 0
                    wd_vacnom = (dt_ep - vac_end).days - fix
                    worked -= wd_vacnom
                    worked = 0 if worked < 0 else worked
            wd_days = {
                'work_entry_type_id': wdays.id,
                'name': _("Días Trabajados"),
                'sequence': 5,
                'code': 'WORK100',
                'symbol': '',
                'number_of_days': worked,
                'number_of_hours': worked * w_hours,
                'contract_id': contract.id
            }
            res += [wd_days, w_days] + leaves_worked_lines
            if prev_aus['number_of_days'] > 0:
                res += [prev_aus]
            if prev_pays['number_of_days'] > 0:
                res += [prev_pays]
        return res
    
    def get_worked_day_lines(self):
        res = []
        for rec in self:
            contract = rec.contract_id
            date_from = rec.date_from
            start_period = rec.date_from.replace(day=1)
            date_to = rec.date_to
            wage_changes_sorted = sorted(contract.change_wage_ids, key=lambda x: x.date_start)
            last_wage_change = max((change for change in wage_changes_sorted if change.date_start < date_from), default=None)
            current_wage_day = last_wage_change.wage / 30 if last_wage_change else contract.wage / 30
            leaves_worked_lines = {}
            worked_days = 0
            worked_aux_days = 0
            hp_type = rec.struct_process
            annual_parameters = self.env['hr.annual.parameters'].search([('year', '=', date_to.year)])
            w_hours = annual_parameters.hours_daily
            outdays = self.env['hr.work.entry.type'].search([("code", "=", "OUT")], limit=1)
            wdays = self.env['hr.work.entry.type'].search([("code", "=", "WORK100")], limit=1)
            wdayst = self.env['hr.work.entry.type'].search([("code", "=", "WORK_D")], limit=1)
            prevdays = self.env['hr.work.entry.type'].search([("code", "=", "PREV_PAYS")], limit=1)
            ps_types = ['nomina', 'contrato']
            if not rec.company_id.fragment_vac:
                ps_types.append('Vacaciones')

            # Línea de total de días del periodo
            if hp_type in ps_types:
                lab_days = rec.days_between(start_period, date_to)
                res.append({
                    'work_entry_type_id': wdayst.id,
                    'name': 'Total dias periodo',
                    'sequence': 1,
                    'code': 'TOTAL_DIAS',
                    'symbol': '',
                    'number_of_days': lab_days,
                    'number_of_hours': w_hours * lab_days,
                    'contract_id': contract.id
                })
                query = """
                        SELECT
                            SUM(wd.number_of_days) AS number_of_days,
                            wd.symbol,
                            hw.code
                        FROM hr_payslip_worked_days wd
                        INNER JOIN hr_payslip hp ON hp.id = wd.payslip_id
                        LEFT JOIN hr_work_entry_type hw on hw.id = wd.work_entry_type_id
                        WHERE hp.date_from >= %s
                            AND hp.date_to <= %s
                            AND hp.contract_id = %s
                            AND hp.id != %s
                            AND hw.code NOT IN ('WORK_D', 'LICENCIA_REMUNERADA')
                            AND hp.struct_process IN ('vacaciones', 'nomina', 'contrato')
                            AND hp.state in ('done', 'paid')
                        GROUP BY wd.symbol, hw.code
                        """
                params = (date_from, date_to, contract.id, rec.id)
                self._cr.execute(query, params)
                wd_other_data = self._cr.fetchall()
                wd_other = 0
                wd_plus = 0
                wd_prev = 0
                wd_minus = 0
                for number_of_days, symbol, code in wd_other_data:
                    if code == 'WORK_D':
                        wd_other += number_of_days
                    else:
                        if code in ('PREV_AUS', 'PREV_PAYS'):
                            wd_prev += number_of_days
                        elif symbol in ('-', '') and code not in ('OUT', 'VAC', 'VACDISFRUTADAS'):
                            wd_minus += number_of_days
                
                sum_wdo = wd_plus + wd_minus - wd_prev
                wd_other = sum_wdo
                
                # Calcular días trabajados y ausencias
                date_tmp = date_from
                while date_tmp <= date_to:
                    is_absence_day = any(
                        leave.date_from.date() <= date_tmp <= leave.date_to.date()
                        for leave in rec.leave_ids.leave_id
                    )
                    is_within_contract = contract.date_start <= date_tmp <= (contract.date_end or date_tmp)
                    wage_change_today = next((change for change in wage_changes_sorted if change.date_start == date_tmp), None)
                    if wage_change_today:
                        current_wage_day = wage_change_today.wage / 30

                    if is_within_contract:
                        if is_absence_day:
                            leave = next(leave for leave in rec.leave_ids.leave_id if leave.date_from.date() <= date_tmp <= leave.date_to.date())
                            key = (leave.holiday_status_id.id, '-')
                            if key not in leaves_worked_lines:
                                leaves_worked_lines[key] = {
                                    'work_entry_type_id': leave.holiday_status_id.work_entry_type_id.id,
                                    'name': f"Días {leave.holiday_status_id.name.capitalize()}",
                                    'sequence': 5,
                                    'code': leave.holiday_status_id.code or 'nocode',
                                    'symbol': '-',
                                    'number_of_days': 1,
                                    'number_of_hours': w_hours,
                                    'contract_id': contract.id,
                                }
                            else:
                                leaves_worked_lines[key]['number_of_days'] += 1
                                leaves_worked_lines[key]['number_of_hours'] += w_hours
                            if not leave.holiday_status_id.sub_wd:
                                worked_days +=1
                            #if leave.holiday_status_id.sub_not_aux:
                            #    worked_aux_days +=1
                        else:
                            if date_tmp.month == 2:
                                last_day_of_february = calendar.monthrange(date_tmp.year, 2)[1]
                                if date_tmp.day == last_day_of_february:
                                    if date_tmp.day ==  28:
                                        worked_days += 3
                                        worked_aux_days +=3
                                    else:
                                        worked_days += 2
                                        worked_aux_days +=2
                                else:
                                    worked_days += 1
                            elif date_tmp.month in [1, 3, 5, 7, 8, 10, 12] and date_tmp.day == 31:
                                worked_days -= 0
                                worked_aux_days +=0
                            else:
                                worked_days += 1
                                worked_aux_days +=1
                    else:
                        # Días fuera de contrato
                        description = 'Deducción por inicio de contrato' if date_tmp < contract.date_start else 'Deducción por fin de contrato'
                        res.append({
                            'work_entry_type_id': outdays.id,
                            'name': description,
                            'sequence': 2,
                            'code': 'OUT',
                            'symbol': '-',
                            'number_of_days': 1,
                            'number_of_hours': w_hours,
                            'contract_id': contract.id,
                        })

                    date_tmp += timedelta(days=1)

                # Agregar líneas de ausencias
                res.extend(leaves_worked_lines.values())
                
                # Línea de días trabajados
                res.append({
                    'work_entry_type_id': wdays.id,
                    'name': 'Días Trabajados',
                    'sequence': 6,
                    'code': 'WORK100',
                    'symbol': '+',
                    'number_of_days': worked_days,
                    'number_of_hours': worked_days * w_hours,
                 #   'number_of_days_aux':worked_aux_days,
                  #  'number_of_hours_aux':worked_aux_days * w_hours,
                    'contract_id': contract.id
                })
                if wd_other:
                    res.append({
                        'work_entry_type_id': prevdays.id,
                        'name': 'Días Previos',
                        'sequence': 7,
                        'code': 'PREV_PAYS',
                        'symbol': '-',
                      #  'number_of_days': wd_other,
                      #  'number_of_hours': wd_other * w_hours,
                        'contract_id': contract.id
                    })
                if (lab_days - worked_days - wd_other) > 0:
                    res.append({
                        'work_entry_type_id': outdays.id,
                        'name': 'Días Sin Asignar',
                        'sequence': 8,
                        'code': 'OUT',
                        'symbol': '-',
                        'number_of_days': lab_days - worked_days - wd_other,
                        'number_of_hours': (lab_days - worked_days - wd_other) * w_hours,
                        'contract_id': contract.id
                    })
        return res
    



    def compute_slip(self):
        # Convertir a tupla para uso seguro en SQL y reducir las consultas en el bucle
        self_ids = tuple(self._ids)
        if not self_ids:
            return True  # Salir si no hay IDs para procesar

        query_s2comp = """
        SELECT id FROM hr_payslip
        WHERE id IN %s AND state IN ('draft', 'verify')
        """
        self._cr.execute(query_s2comp, (self_ids,))
        slips2comp_ids = [x[0] for x in self._cr.fetchall()]
        
        if not slips2comp_ids:
            return True  # Salir si no hay recibos de pago para procesar

        slips2comp = self.browse(slips2comp_ids)
        today = fields.Date.today()
        for slip in slips2comp:
            constraint = """
            SELECT COUNT(id) FROM hr_payslip
            WHERE contract_id = %s AND date_from >= %s AND date_to <= %s
            AND struct_process = %s AND id != %s
            """
            self._cr.execute(constraint, (slip.contract_id.id, slip.date_from, slip.date_to, slip.struct_process, slip.id))
            duplicated = self._cr.fetchone()[0] > 0
            
            if duplicated and slip.struct_process not in ('vacaciones', 'contrato', 'otro'):
                raise UserError("No puede existir más de una nómina del mismo tipo y periodo para el empleado {}".format(slip.employee_id.name))
            
            # Los siguientes procesos se asumen que son métodos existentes en `self` o en `slip`
            # y no son optimizados aquí sin más contexto.
            number = slip.number or self.env['ir.sequence'].next_by_code('salary.slip')
            name = 'Nomina de ' + slip.contract_id.name
            slip.write({'number': number, 'name': name, 'state': 'verify',
                'compute_date': today})
            # slip.reckon_extrahours()
            # slip.reckon_novedades()
            # slip.reckon_loans()
            slip.leave_ids.unlink()
            slip.compute_sheet_leave()
            slip._compute_extra_hours()
            slip._compute_novedades()
            
            # Eliminar líneas de días trabajados en un solo comando antes de recrearlos
            self._cr.execute("DELETE FROM hr_payslip_worked_days WHERE payslip_id = %s", (slip.id,))
            self._cr.execute("DELETE FROM hr_payslip_line WHERE slip_id = %s", (slip.id,))
            worked_days_line_ids = slip.get_worked_day_lines()
            _logger.error(worked_days_line_ids)
            slip.worked_days_line_ids = [(0, 0, line) for line in worked_days_line_ids]
            
            #slip.compute_concepts()
            self.env['hr.payslip.line'].create(slip._get_payslip_lines_lavish())
            slip.renderizar_plantilla_qweb()
        return True
    
    def _get_localdict_payslip(self):
        self.ensure_one()
        worked_days_dict = {line.code: line for line in self.worked_days_line_ids if line.code}
        date_from = self.date_from
        start_period = date_from.replace(day=1)
        date_to = self.date_to
        date_from_time = datetime.combine(date_from, datetime.min.time())
        date_to_time = datetime.combine(date_to, datetime.max.time())
        # Check for multiple inputs of the same type and keep a copy of
        # them because otherwise they are lost when building the dict
        input_list = [line.code for line in self.input_line_ids if line.code]
        cnt = Counter(input_list)
        multi_input_lines = [k for k, v in cnt.items() if v > 1]
        same_type_input_lines = {line_code: [line for line in self.input_line_ids if line.code == line_code] for line_code in multi_input_lines}

        inputs_dict = {line.code: line for line in self.input_line_ids if line.code}
        employee = self.employee_id
        contract = self.contract_id
        wage = False
        annual_parameters = self.env['hr.annual.parameters'].search([('year', '=', date_to.year)])
        pslp_query = """
            SELECT hp.id
            FROM hr_payslip AS hp
            WHERE hp.contract_id = %s
                AND hp.date_from >= %s
                AND hp.date_to <= %s
                AND hp.id != %s
                AND hp.state in ('done','paid')
        """
        params = (contract.id, start_period, date_to, self.id)
        self._cr.execute(pslp_query, params)
        payslip_ids = [row[0] for row in self._cr.fetchall()]
        payslips_month = self.env['hr.payslip'].browse(payslip_ids) if payslip_ids else self.env['hr.payslip'].browse()
        if not annual_parameters:
            raise UserError('Falta Configurar los parametros anuales ir a --> Configuracion/ Parametros anuales')
        wage = contract.wage
        obj_wage = self.env['hr.contract.change.wage'].search([('contract_id', '=', contract.id), ('date_start', '<', date_to)])
        for change in sorted(obj_wage, key=lambda x: x.date_start):
            if float(change.wage) > 0:
                wage = change.wage 
               
        if wage <= 0:
            raise UserError('El sueldo no puede ser igual a 0 o menor')
        localdict = {
            **self._get_base_local_dict(),
            **{
                'categories': BrowsableObject(employee.id, {}, self.env),
                'rules_computed': BrowsableObject(employee.id, {}, self.env),
                'rules': BrowsableObject(employee.id, {}, self.env),
                'payslip': Payslips(employee.id, self, self.env),
                'worked_days': WorkedDays(employee.id, worked_days_dict, self.env),
                'inputs': InputLine(employee.id, inputs_dict, self.env),
                'employee': employee,
                'contract': contract,
                'result_rules': ResultRules(employee.id, {}, self.env),
                'result_rules_co': ResultRules_co(employee.id, {}, self.env),
                'same_type_input_lines': same_type_input_lines,
                'wage':wage,
                'slip': self,
                'annual_parameters': annual_parameters,
                'date_to_time':date_to_time,
                'date_from_time':date_from_time,
                'payslips_month':payslips_month,
            }
        }
        return localdict

    def _get_payslip_lines_lavish(self):
        def _sum_salary_rule_category(localdict, category, amount):
            if category.parent_id:
                localdict = _sum_salary_rule_category(localdict, category.parent_id, amount)
            localdict['categories'].dict[category.code] = localdict['categories'].dict.get(category.code, 0) + amount
            return localdict
        
        def _sum_salary_rule(localdict, rule, amount):
            localdict['rules_computed'].dict[rule.code] = localdict['rules_computed'].dict.get(rule.code, 0) + amount
            return localdict
        line_vals = []
        line_not_vals = []
        for payslip in self:
            if not payslip.contract_id:
                raise UserError(_("There's no contract set on payslip %s for %s. Check that there is at least a contract set on the employee form.", payslip.name, payslip.employee_id.name))

            localdict = self.env.context.get('force_payslip_localdict', None)
            if localdict is None:
                localdict = payslip._get_localdict_payslip()

            rules_dict = localdict['rules'].dict
            result_rules_dict = localdict['result_rules'].dict
            result_rules_dict_co = localdict['result_rules_co'].dict
            blacklisted_rule_ids = self.env.context.get('prevent_payslip_computation_line_ids', [])

            result = {}
            result_not = {}
            def calculate_total_rule(concept, date_from, worked_days_line_ids, employee):
                tot_rule = concept.amount

                if concept.input_id.dev_or_ded == 'deduccion':
                    tot_rule = -tot_rule

                if concept.input_id.modality_value == "fijo":
                    if concept.aplicar == "0":
                        return tot_rule
                    elif concept.aplicar == "15" and date_from.day <= 15:
                        return tot_rule
                    elif concept.aplicar == "30" and date_from.day > 16:
                        return tot_rule

                elif concept.input_id.modality_value == "diario":
                    qty = 1  # Default value
                    for linea in worked_days_line_ids:
                        if linea.work_entry_type_id.code == 'WORK100':
                            qty = linea.number_of_days

                    if concept.aplicar == "0":
                        return (tot_rule / 30) * qty
                    elif concept.aplicar == "15" and date_from.day <= 15:
                        return (tot_rule / 30) * qty
                    elif concept.aplicar == "30" and date_from.day > 16:
                        start_date = self.date_to.replace(day=1)  # Primer día del mes
                        end_date = start_date + relativedelta(months=1) - relativedelta(days=1)  # Último
                        dias = self.env['hr.payslip.worked_days'].search([
                                ('payslip_id.employee_id.id', '=', employee.id),
                                ('payslip_id.date_to', '>=', start_date),
                                ('payslip_id.date_to', '<=', end_date),
                                ('payslip_id.struct_id.process', '=', 'nomina'),
                                ('work_entry_type_id.code','=','WORK100')])
                        for linea in self.worked_days_line_ids:
                            if dias:
                                qty = sum(d.number_of_days for d in dias)
                                tot_rule = (tot_rule/30) * qty
                        return (tot_rule / 30) * qty

                elif concept.input_id.modality_value == "diario_efectivo":
                    qty = 1  # Default value
                    dias_trabajados = self.dias360(self.date_from, self.date_to)
                    dias_ausencias =  sum([i.number_of_days for i in self.env['hr.leave'].search([('date_from','>=',self.date_from),('date_to','<=',self.date_to),('state','=','validate'),('employee_id','=',self.employee_id.id),('unpaid_absences','=',True)])])
                    qty = dias_trabajados - dias_ausencias
                    return (tot_rule / 30) * qty
            obj_concept = localdict['contract'].concepts_ids #self.env['hr.contract.concepts'].search([('contract_id', '=', contract.id),('state','=','done')]) 
            for concept in obj_concept.filtered(lambda l: l.state == 'done'):
                entity_id = concept.partner_id.id
                loan_id = concept.loan_id.id 
                date_start_concept = concept.date_start if concept.date_start else datetime.strptime('01/01/1900', '%d/%m/%Y').date()
                date_end_concept = concept.date_end if concept.date_end else datetime.strptime('31/12/2080', '%d/%m/%Y').date()
                previous_amount = concept.input_id.code in localdict and localdict[concept.input_id.code] or 0.0
                if (concept.state == 'done' and 
                    date_start_concept <= localdict['slip'].date_to and 
                    date_end_concept >= localdict['slip'].date_from and 
                    concept.amount != 0 and 
                    #inherit_prima == 0 and 
                    concept.input_id.amount_select != "code" and self.settle_payroll_concepts ):
                    #localdict.update({'id_contract_concepts': concept.id})
                    tot_rule = calculate_total_rule(concept, self.date_from, self.worked_days_line_ids, localdict['employee'])
                    #LIQUIDACION DE CONTRATO SOLO DEV OR DED DEPENDIENTO SU ORIGEN
                    #if (inherit_contrato_dev != 0 or inherit_contrato_ded != 0) and self.novelties_payroll_concepts == False and not concept.input_id.code in ['TOTALDEV','TOTALDED','NET','IBC_R','IBC_A','IBC_P']:
                    #    tot_rule = 0
                    #if inherit_contrato_dev != 0 and concept.input_id.dev_or_ded != 'devengo':                            
                    #    tot_rule = 0
                    #if inherit_contrato_ded != 0 and concept.input_id.dev_or_ded != 'deduccion'and not concept.input_id.code in ['TOTALDEV','NET',]:                            
                    #    tot_rule = 0
                    if tot_rule != 0:
                        localdict[concept.input_id.code+'-PCD' + str(concept.id)] = tot_rule
                        rules_dict[concept.input_id.code+'-PCD' + str(concept.id)] = concept.input_id
                        rule = concept.input_id
                        result_rules_dict[rule.code +'-PCD'+str(concept.id)] = {'total': tot_rule, 'amount': tot_rule, 'quantity': 1, 'base_prima':rule.base_prima, 'base_cesantias':rule.base_cesantias,  'base_vacaciones':rule.base_vacaciones,'base_vacaciones_dinero':rule.base_vacaciones_dinero}
                        result_rules_dict_co[rule.code +'-PCD'+str(concept.id)] = {'total': tot_rule, 'amount': tot_rule, 'quantity': 1, 'base_seguridad_social': rule.base_seguridad_social, 'base_prima':rule.base_prima, 'base_cesantias':rule.base_cesantias,  'base_vacaciones':rule.base_vacaciones,'base_vacaciones_dinero':rule.base_vacaciones_dinero}
                        # sum the amount for its salary category
                        localdict = _sum_salary_rule_category(localdict, concept.input_id.category_id, tot_rule - previous_amount)
                        localdict = _sum_salary_rule(localdict, concept.input_id, tot_rule)
                        #Guardar valores de ausencias dependiendo parametrización
                        if concept.input_id.is_leave:
                            amount_leave = tot_rule if concept.input_id.deduct_deductions == 'all' else 0
                            localdict['values_leaves_all'] = localdict['values_leaves_all'] + amount_leave
                            amount_leave_law = tot_rule if concept.input_id.deduct_deductions == 'law' else 0
                            localdict['values_leaves_law'] = localdict['values_leaves_law'] + amount_leave_law
                    result_item = concept.input_id.code + '-PCD' + str(concept.id)
                    # Utiliza el contador para generar una clave única para el diccionario result
                    result[result_item] = {
                        'sequence': concept.input_id.sequence,
                        'code': concept.input_id.code,
                        'name': concept.input_id.name,
                        #'note': concept.input_id.note,
                        'salary_rule_id': concept.input_id.id,
                        'contract_id': localdict['contract'].id,
                        'employee_id': localdict['employee'].id,
                        'entity_id': entity_id,
                        'loan_id': loan_id,
                        'amount': tot_rule,
                        'quantity': 1.00,
                        'rate': 100,
                        'slip_id': self.id,
                    }
            obj_novelties = self.env['hr.novelties.different.concepts'].search([('employee_id', '=', localdict['employee'].id), ('date', '>=', localdict['slip'].date_from),('date', '<=', localdict['slip'].date_to)])
            for concepts in obj_novelties:
                if concepts.amount != 0:
                    previous_amount = concepts.salary_rule_id.code in localdict and localdict[concepts.salary_rule_id.code] or 0.0
                    #set/overwrite the amount computed for this rule in the localdict
                    tot_rule = concepts.amount * 1.0 * 100 / 100.0
                    #LIQUIDACION DE CONTRATO SOLO DEV OR DED DEPENDIENTO SU ORIGEN
                    # if (inherit_contrato_dev != 0 or inherit_contrato_ded != 0) and self.novelties_payroll_concepts == False and not concepts.salary_rule_id.code in ['TOTALDEV','TOTALDED','NET','IBC_R','IBC_A','IBC_P']:
                    #     tot_rule = 0
                    # if inherit_contrato_dev != 0 and concepts.salary_rule_id.dev_or_ded != 'devengo':                            
                    #     tot_rule = 0
                    # if inherit_contrato_ded != 0 and concepts.salary_rule_id.dev_or_ded != 'deduccion'and not concepts.salary_rule_id.code in ['TOTALDEV','NET',]:                            
                    #     tot_rule = 0
                    if tot_rule != 0:
                        localdict[concepts.salary_rule_id.code+'-PCD'] = tot_rule
                        rules_dict[concepts.salary_rule_id.code+'-PCD'] = concepts.salary_rule_id
                        # sum the amount for its salary category
                        localdict = _sum_salary_rule_category(localdict, concepts.salary_rule_id.category_id, tot_rule - previous_amount)
                        localdict = _sum_salary_rule(localdict, concepts.salary_rule_id, tot_rule)
                        rule = concepts.salary_rule_id
                        result_rules_dict[rule.code +'-PCD'+str(concepts.id)] = {'total': tot_rule, 'amount': tot_rule, 'quantity': 1, 'base_prima':rule.base_prima, 'base_cesantias':rule.base_cesantias,  'base_vacaciones':rule.base_vacaciones,'base_vacaciones_dinero':rule.base_vacaciones_dinero}
                        result_rules_dict_co[rule.code +'-PCD'+str(concepts.id)] = {'total': tot_rule, 'amount': tot_rule, 'quantity': 1, 'base_seguridad_social': rule.base_seguridad_social, 'base_prima':rule.base_prima, 'base_cesantias':rule.base_cesantias,  'base_vacaciones':rule.base_vacaciones,'base_vacaciones_dinero':rule.base_vacaciones_dinero}
                        #Guardar valores de ausencias dependiendo parametrización
                        if concepts.salary_rule_id.is_leave:
                            amount_leave = tot_rule if concepts.salary_rule_id.deduct_deductions == 'all' else 0
                            localdict['values_leaves_all'] = localdict['values_leaves_all'] + amount_leave
                            amount_leave_law = tot_rule if concepts.salary_rule_id.deduct_deductions == 'law' else 0
                            localdict['values_leaves_law'] = localdict['values_leaves_law'] + amount_leave_law
                        result_item = concepts.salary_rule_id.code+'-PCD'+str(concepts.id)
                        result[result_item] = {
                            'sequence': concepts.salary_rule_id.sequence,
                            'code': concepts.salary_rule_id.code,
                            'name': concepts.salary_rule_id.name,
                           # 'note': concepts.salary_rule_id.note,
                            'salary_rule_id': concepts.salary_rule_id.id,
                            'contract_id': localdict['contract'].id,
                            'employee_id': localdict['employee'].id,
                            'entity_id': concepts.partner_id.id if concepts.partner_id else False,
                            'amount': tot_rule,
                            'quantity': 1.0,
                            'rate': 100,
                            'slip_id': self.id,}
            for rule in sorted(payslip.struct_id.rule_ids, key=lambda x: x.sequence):
                if rule.id in blacklisted_rule_ids:
                    continue
                localdict.update({
                    'result': None,
                    'result_qty': 1.0,
                    'result_rate': 100,
                    'result_name': False
                })
                entity_id = False
                if rule._satisfy_condition(localdict):
                    # Retrieve the line name in the employee's lang
                    employee_lang = payslip.employee_id.sudo().work_contact_id.lang
                    # This actually has an impact, don't remove this line
                    context = {'lang': employee_lang}
                    amount, qty, rate, name, log , data = rule._compute_rule_lavish(localdict)
                    if rule.category_id.code == 'SSOCIAL':
                        for entity in localdict['employee'].social_security_entities:
                            if entity.contrib_id.type_entities == 'eps' and rule.code == 'SSOCIAL001': # SALUD 
                                entity_id = entity.partner_id.id
                            if entity.contrib_id.type_entities == 'pension' and (rule.code == 'SSOCIAL002' or rule.code == 'SSOCIAL003' or rule.code == 'SSOCIAL004'): # Pension
                                entity_id = entity.partner_id.id
                            if entity.contrib_id.type_entities == 'subsistencia' and rule.code == 'SSOCIAL003': # Subsistencia 
                                entity_id = entity.partner_id.id
                            if entity.contrib_id.type_entities == 'solidaridad' and rule.code == 'SSOCIAL004': # Solidaridad 
                                entity_id = entity.partner_id.id
                    #check if there is already a rule computed with that code
                    previous_amount = rule.code in localdict and localdict[rule.code] or 0.0
                    #set/overwrite the amount computed for this rule in the localdict
                    tot_rule = amount * qty * rate / 100.0
                    localdict[rule.code] = tot_rule
                    result_rules_dict[rule.code] = {'total': tot_rule, 'amount': amount, 'quantity': qty, 'base_prima':rule.base_prima, 'base_cesantias':rule.base_cesantias,  'base_vacaciones':rule.base_vacaciones,'base_vacaciones_dinero':rule.base_vacaciones_dinero}
                    result_rules_dict_co[rule.code] = {'total': tot_rule, 'amount': amount, 'quantity': qty, 'base_seguridad_social': rule.base_seguridad_social, 'base_prima':rule.base_prima, 'base_cesantias':rule.base_cesantias,  'base_vacaciones':rule.base_vacaciones,'base_vacaciones_dinero':rule.base_vacaciones_dinero}
                    rules_dict[rule.code] = rule
                    # sum the amount for its salary category
                    localdict = _sum_salary_rule_category(localdict, rule.category_id, tot_rule - previous_amount)
                    localdict = _sum_salary_rule(localdict, rule, tot_rule)
                    # create/overwrite the rule in the temporary results
                    if tot_rule !=0.0:
                        result[rule.code] = {
                            'sequence': rule.sequence,
                            'code': rule.code,
                            'name':  name or rule.name,
                         #   'note': log,
                            'salary_rule_id': rule.id,
                            'contract_id': localdict['contract'].id,
                            'employee_id': localdict['employee'].id,
                            'entity_id': entity_id,
                            'amount': amount,
                            'quantity': qty,
                            'rate': rate,
                            'slip_id': payslip.id,
                            'run_id': payslip.payslip_run_id.id,
                        }
            line_vals += list(result.values())
        return line_vals


    def get_payslip_category(self, category):
        """
        Obtiene la suma total de los conceptos de nómina de una categoría específica para esta nómina.

        Args:
            category (str): Categoría de los conceptos de nómina a sumar.

        Returns:
            float: Suma total de los conceptos de nómina de la categoría especificada.
        """
        query = """
            SELECT SUM(total) AS total
            FROM hr_payslip_line AS pl 
            INNER JOIN hr_salary_rule_category hc ON pl.category_id = hc.id 
            LEFT JOIN hr_salary_rule_category hc_parent ON hc.parent_id = hc_parent.id 
            WHERE (hc.code = %s OR hc_parent.code = %s)
            AND slip_id = %s
        """
        params = (category, category, self.id)
        self._cr.execute(query, params)
        result = self._cr.fetchone()
        return result[0] if result and result[0] is not None else 0.0
    
    def get_payslip_concept_total(self, concept):
        """
        Obtiene el total de un concepto de nómina específico para esta nómina.

        Args:
            concept (str): Código del concepto de nómina.

        Returns:
            float: Valor total del concepto de nómina.
        """
        query = """
            SELECT total
            FROM hr_payslip_line
            WHERE code = %s
                AND slip_id = %s
        """
        params = (concept, self.id)
        self._cr.execute(query, params)
        result = self._cr.fetchone()
        return result[0] if result and result[0] is not None else 0.0

    def get_payslip_concept(self, concept):
        query = """
            SELECT id
            FROM hr_payslip_line
            WHERE code = %s
                AND slip_id = %s
            LIMIT 1
        """
        params = (concept, self.id)
        self.env.cr.execute(query, params)
        result = self.env.cr.fetchone()
        if result:
            concept_id = result[0]
            return self.env['hr.payslip.line'].browse(concept_id)
        return False

    def get_interval_concept_qty(self, concept, start, end, contract=False):
        contract_id = contract.id

        query = """
            SELECT SUBSTRING(hp.date_from::VARCHAR, 1, 7), SUM(hpc.total), SUM(hpc.quantity)
            FROM hr_payslip_line hpc
            INNER JOIN hr_payslip hp ON hpc.payslip_id = hp.id
            WHERE hpc.code = %s
                AND hp.date_to >= %s
                AND hp.date_from <= %s
                AND hp.contract_id = %s
            GROUP BY SUBSTRING(hp.date_from::VARCHAR, 1, 7)
        """

        params = (concept, start, end, contract_id)
        self.env.cr.execute(query, params)
        res = self.env.cr.fetchall()
        return 


    def renderizar_plantilla_qweb(self):
        for rec in self:
            pass
            # ir_ui_view = self.env['ir.ui.view']
            # rendered_html = ir_ui_view._render_template('lavish_hr_payroll.report_views_compute',{'docs': rec})  # Pasamos los datos del modelo al contexto de la plantilla
            # rec.resulados_rt = rendered_html



    def get_pend_vac_upd(self, date_calc=False, sus=0):
        for k in self:
            if k.type_id.type_class == 'apr':
                k.pending_vac = 0
                continue

            init_vac_date = self.env.company.init_vac_date

            # Consulta para obtener vacaciones pagadas
            vac_sql = """
                SELECT hh.id, hh.business_days, hh.payed_vac, hh.payslip_id
                FROM hr_holidays hh
                LEFT JOIN hr_leave_type hhs ON hhs.id = hh.holiday_status_id
                WHERE hh.employee_id = %s
                AND hh.date_to > %s
                AND hhs.is_vacation = True
                AND hh.state in ('paid','validate')
            """
            self._cr.execute(vac_sql, (k.employee_id.id, init_vac_date))
            vacs = self._cr.fetchall()

            upd_book = []
            for v in vacs:
                payslip_id = v[3]
                if payslip_id:
                    enjoyed = abs(v[1]) if v[1] is not None else 0
                    payed = abs(v[2]) if v[2] is not None else 0
                    upd_book.append({
                        'enjoyed': enjoyed,
                        'payed': payed,
                        'payslip_id': payslip_id,
                        'contract_id': k.id,
                    })

            # Consulta para obtener días de vacaciones pagadas en liquidaciones
            vac_liq_sql = """
                SELECT HPC.qty, HP.id
                FROM hr_payslip_concept AS HPC
                INNER JOIN hr_payslip AS HP ON HP.id = HPC.payslip_id
                INNER JOIN payslip_period AS PP ON PP.id = HP.payslip_period_id
                WHERE HPC.code = 'VAC_LIQ' AND HP.state = 'done'
                AND HP.contract_id = %s AND PP.start_period >= %s
                LIMIT 1
            """
            self._cr.execute(vac_liq_sql, (k.id, init_vac_date))
            vac_liq_slip = self._cr.fetchone()
            if vac_liq_slip:
                upd_book.append({
                    'enjoyed': vac_liq_slip[0],
                    'payslip_id': vac_liq_slip[1],
                    'contract_id': k.id,
                })

            # Consulta para obtener días de suspensión pagada
            sus_sql = """
                SELECT SUM(HHD.days_payslip), HHD.payslip_id
                FROM hr_holidays_days AS HHD
                INNER JOIN hr_holidays_status HHS ON HHS.id = HHD.holiday_status_id AND HHS.no_payable
                WHERE HHD.name >= %s AND HHD.state = 'paid' AND HHD.contract_id = %s
                GROUP BY HHD.payslip_id
            """
            self._cr.execute(sus_sql, (init_vac_date, k.id))
            sus_paids = self._cr.fetchall()
            for sus_paid in sus_paids:
                upd_book.append({
                    'licences': sus_paid[0] or 0,
                    'payslip_id': sus_paid[1],
                    'contract_id': k.id
                })

            # Eliminar registros antiguos de libro de vacaciones
            vac_book_old_sql = """
                DELETE FROM hr_vacation_book
                WHERE contract_id = %s AND payslip_id IS NOT NULL
            """
            self._cr.execute(vac_book_old_sql, (k.id,))

            # Insertar registros actualizados en el libro de vacaciones
            self.env['hr.vacation'].create(upd_book)
            # Actualizar pendiente de vacaciones
            dv_pend = k.get_pend_vac(date_calc=date_calc, sus=sus)
            k.pending_vac = dv_pend
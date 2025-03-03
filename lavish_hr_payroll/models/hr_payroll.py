# -*- coding: utf-8 -*-
from odoo import models, fields, api, _, SUPERUSER_ID , tools
from odoo.exceptions import UserError, ValidationError
from .browsable_object import BrowsableObject, InputLine, WorkedDays, Payslips, LeavedDays, ResultRules
from .browsable_object import ResultRules_co
import math
from collections import defaultdict, Counter
import calendar
from datetime import datetime, timedelta, date, time
from calendar import monthrange
from odoo.tools import float_round, date_utils
from odoo.tools.misc import format_date
from odoo import registry as registry_get
import math
import pytz
import odoo
import threading
import logging
import time
from odoo.tools import float_round, date_utils, float_is_zero
from odoo.tools.float_utils import float_compare
from odoo.tools.misc import format_date
from dateutil.relativedelta import relativedelta
from collections import defaultdict
_logger = logging.getLogger(__name__)
DAY_TYPE = [
    ('W', 'Trabajado'),
    ('A', 'Ausencia'),
    ('X', 'Sin contrato'), 
]

#---------------------------LIQUIDACIÓN DE NÓMINA-------------------------------#
class HrPayslipRun(models.Model):
    _name = 'hr.absence.days'
    _description = 'Ausencias'

    sequence = fields.Integer(string='Secuencia',required=True, index=True, default=5,
                              help='Use to arrange calculation sequence')
    payroll_id = fields.Many2one('hr.payslip', string='Payroll')
    employee_id = fields.Many2one('hr.employee', string='Employee')
    leave_type = fields.Char(string='Leave Type')
    total_days = fields.Float(string='Dias Totales')
    days_used = fields.Float(string='Dias a usar')
    days = fields.Float(string='Dias Usado',compute="_days_used")
    total = fields.Float(string='pendiente', compute="_total_leave")
    leave_id = fields.Many2one('hr.leave', string='Novedad')
    work_entry_type_id = fields.Many2one('hr.work.entry.type', related="leave_id.holiday_status_id.work_entry_type_id", string='Type', required=True, help="The code that can be used in the salary rules")

    
    @api.depends('total_days','days_used')
    def _total_leave(self):
        for rec in self:
            rec.total = rec.days_used + rec.days

    @api.depends('total_days', 'days_used')
    def _days_used(self):
        self.days = 0.0
        # leave_obj = self.env['hr.absence.days'] 

        # for rec in self:
        #     if not rec.payroll_id.date_to:
        #         continue  # Si no hay fecha 'date_to', pasamos al siguiente registro
            
        #     # Obtiene todos los leaves que cumplen con la condición sin iterar sobre ellos
        #     leaves = leave_obj.search([
        #         ('id', 'in', rec.leave_id.leave_ids.ids),
        #         ('payroll_id.date_to', '<', rec.payroll_id.date_to)
        #     ])
        #     # Calcula la suma de days_used
        #     total_days = sum(leave.days_used + (1 if leave.payroll_id.date_to and leave.payroll_id.date_to.day == 31 else 0) for leave in leaves)
            
        #     rec.days = total_days


class HrPayslipRun(models.Model):
    _name = 'hr.payslip.run'
    _inherit = ['hr.payslip.run','mail.thread', 'mail.activity.mixin']
    @api.model
    def _get_default_structure(self):
        return self.env['hr.payroll.structure'].search([('process','=','nomina')],limit=1)

    time_process = fields.Char(string='Tiempo ejecución')
    observations = fields.Text('Observaciones')
    definitive_plan = fields.Boolean(string='Plano definitivo generado')
    hr_payslip_line_ids = fields.One2many('hr.payslip.line', 'run_id')
    move_line_ids = fields.One2many('account.move.line', 'run_id')
    date_liquidacion = fields.Date('Fecha liquidación de contrato')
    date_prima = fields.Date('Fecha liquidación de prima')
    date_cesantias = fields.Date('Fecha liquidación de cesantías')
    pay_cesantias_in_payroll = fields.Boolean('¿Liquidar Interese de cesantia en nómina?')
    pay_primas_in_payroll = fields.Boolean('¿Liquidar Primas en nómina?')
    structure_id = fields.Many2one('hr.payroll.structure', string='Tipo de nomina', default=_get_default_structure)
    struct_process = fields.Selection(related='structure_id.process', string='Proceso', store=True)
    method_schedule_pay  = fields.Selection([('bi-weekly', 'Quincenal'),
                                            ('monthly', 'Mensual'),
                                            ('other', 'Ambos')], 'Frecuencia de Pago', default='other')
    analytic_account_ids = fields.Many2many('account.analytic.account', string='Cuentas analíticas')
    branch_ids = fields.Many2many('lavish.res.branch', string='Sucursales')
    state_contract = fields.Selection([('open','En Proceso'),('finished','Finalizado Por Liquidar')], string='Estado Contrato', default='open')
    settle_payroll_concepts = fields.Boolean('Liquida conceptos de nómina', default=True)
    novelties_payroll_concepts = fields.Boolean('Liquida conceptos de novedades', default=True)
    prima_run_reverse_id = fields.Many2one('hr.payslip.run', string='Lote de prima a ajustar')
    account_move_count = fields.Integer(compute='_compute_account_move_count')
    def compute_sheet(self):
        for rec in self:
            for line in rec.slip_ids:
                if line.state in ('draft', 'verify'):
                    line.compute_sheet()

    def compute_sheet_2(self):
        for rec in self:
            for line in rec.slip_ids:
                if line.state in ('draft', 'verify'):
                    line.compute_sheet_2()
    
    def action_payslip_done_2(self):
        for rec in self:
            for line in rec.slip_ids:
                if line.state in ('draft', 'verify','done'):
                    line.action_payslip_done_2()


    def assign_status_verify(self):
        for record in self:
            if len(record.slip_ids) > 0:
                record.write({'state':'verify'})
            else:
                raise ValidationError(_("No existen nóminas asociadas a este lote, no es posible pasar a estado verificar."))

    def action_validate(self):
        settings_batch_account = self.env['ir.config_parameter'].sudo().get_param('lavish_hr_payroll.module_hr_payroll_batch_account') or False
        slips_original = self.mapped('slip_ids').filtered(lambda slip: slip.state != 'cancel')
        if settings_batch_account == '1':  # Si en ajustes tiene configurado 'Crear movimiento contable por empleado' ejecutar maximo 200 por envio
            slips = slips_original.filtered(lambda x: len(x.move_id) == 0 or x.move_id == False)[0:200]
        else:
            slips = slips_original
        slips.action_payslip_done()
        if len(slips_original.filtered(lambda x: len(x.move_id) == 0 or x.move_id == False)) == 0:
            self.action_close()

    def restart_payroll_batch(self):
        self.mapped('slip_ids').action_payslip_cancel()
        self.mapped('slip_ids').unlink()
        return self.write({'state': 'draft','observations':False,'time_process':False})

    def restart_payroll_account_batch(self):
        for payslip in self.slip_ids:
            #Eliminar contabilización y el calculo
            payslip.mapped('move_id').unlink()
            #Eliminar historicos
            self.env['hr.vacation'].search([('payslip', '=', payslip.id)]).unlink()
            self.env['hr.history.prima'].search([('payslip', '=', payslip.id)]).unlink()
            self.env['hr.history.cesantias'].search([('payslip', '=', payslip.id)]).unlink()
            #Reversar Liquidación
            payslip.write({'state': 'verify'})
        return self.write({'state': 'verify'})

    def restart_full_payroll_batch(self):
        for payslip in self.slip_ids:
            #Eliminar contabilización
            payslip.mapped('move_id').unlink() 
            #Eliminar historicos            
            self.env['hr.vacation'].search([('payslip', '=', payslip.id)]).unlink()
            self.env['hr.history.prima'].search([('payslip', '=', payslip.id)]).unlink()
            self.env['hr.history.cesantias'].search([('payslip', '=', payslip.id)]).unlink()
            #Reversar Liquidación
            payslip.write({'state':'verify'})
            payslip.action_payslip_cancel()
            payslip.unlink()
        return self.write({'state': 'draft'})

    def _compute_account_move_count(self):
        for payslip_run in self:
            payslip_run.account_move_count = len(self.slip_ids.mapped('move_id'))

    def action_open_account_move(self):
        self.ensure_one()
        views = [(self.env.ref('account.view_move_tree').id, 'tree'),
                 (self.env.ref('account.view_move_form').id, 'form')]
        return {
            'name': _('Account Move'),
            'view_mode': 'tree,form',
            'res_model': 'account.move',
            'view_id': False,
            'views': views,
            'type': 'ir.actions.act_window',
            'domain': [['id', 'in', self.slip_ids.mapped('move_id').ids]],
        }


class HrPayslipEmployees(models.TransientModel):
    _inherit = 'hr.payslip.employees'	

    @api.model
    def _get_default_structure(self):
        return self.env['hr.payroll.structure'].search([('process','=','nomina')],limit=1)


    date_liquidacion = fields.Date('Fecha liquidación de contrato')
    date_prima = fields.Date('Fecha liquidación de prima')
    date_cesantias = fields.Date('Fecha liquidación de cesantías')
    pay_cesantias_in_payroll = fields.Boolean('¿Liquidar Interese de cesantia en nómina?')
    pay_primas_in_payroll = fields.Boolean('¿Liquidar Primas en nómina?')

    structure_id = fields.Many2one('hr.payroll.structure', string='Salary Structure', default=_get_default_structure)
    struct_process = fields.Selection(related='structure_id.process', string='Proceso', store=True)
    method_schedule_pay  = fields.Selection([('bi-weekly', 'Quincenal'),
                                          ('monthly', 'Mensual'),
                                          ('other', 'Ambos')], 'Frecuencia de Pago', default='other')
    analytic_account_ids = fields.Many2many('account.analytic.account', string='Cuentas analíticas')
    branch_ids = fields.Many2many('lavish.res.branch', string='Sucursales')
    state_contract = fields.Selection([('open','En Proceso'),('finished','Finalizado Por Liquidar')], string='Estado Contrato', default='open')
    settle_payroll_concepts = fields.Boolean('Liquida conceptos de nómina', default=True)
    novelties_payroll_concepts = fields.Boolean('Liquida conceptos de novedades', default=True)
    prima_run_reverse_id = fields.Many2one('hr.payslip.run', string='Lote de prima a ajustar')

    def _get_available_contracts_domain(self):
        domain = [('contract_id.state', '=', self.state_contract or 'open'), ('company_id', '=', self.env.company.id)]
        if self.method_schedule_pay and self.method_schedule_pay != 'other':
            domain.append(('contract_id.method_schedule_pay','=',self.method_schedule_pay))
        if len(self.analytic_account_ids) > 0:
            domain.append(('contract_id.employee_id.analytic_account_id', 'in', self.analytic_account_ids.ids))
        if len(self.branch_ids) > 0:
            domain.append(('branch_id', 'in', self.branch_ids.ids))
        if self.prima_run_reverse_id:
            employee_ids = self.env['hr.payslip'].search([('payslip_run_id', '=', self.prima_run_reverse_id.id)]).employee_id.ids
            domain.append(('id','in',employee_ids))
        if self.structure_id.process in ('cesantia','prima'):
            domain.append(('contract_id.modality_salary','!=','integral'))
            domain.append(('contract_id.employee_id.tipo_coti_id.code','not in', ['12', '19']))
        return domain

    @api.depends('structure_id','department_id','method_schedule_pay','analytic_account_ids','branch_ids','state_contract','prima_run_reverse_id')
    def _compute_employee_ids(self):
        for wizard in self:
            domain = wizard._get_available_contracts_domain()
            if wizard.department_id:
                domain.append(('department_id', 'child_of', self.department_id.id))
            wizard.employee_ids = self.env['hr.employee'].search(domain)

    def _check_undefined_slots(self, work_entries, payslip_run):
        """
        Check if a time slot in the contract's calendar is not covered by a work entry
        """
        calendar_is_not_covered = self.env['hr.contract']
        work_entries_by_contract = defaultdict(lambda: self.env['hr.work.entry'])
        for work_entry in work_entries:
            work_entries_by_contract[work_entry.contract_id] |= work_entry

        for contract, work_entries in work_entries_by_contract.items():
            calendar_start = pytz.utc.localize(datetime.combine(max(contract.date_start, payslip_run.date_start), datetime.min.time()))
            calendar_end = pytz.utc.localize(datetime.combine(min(contract.date_end or date.max, payslip_run.date_end), datetime.max.time()))
            outside = contract.resource_calendar_id._attendance_intervals_batch(calendar_start, calendar_end)[False] - work_entries._to_intervals()
            if outside:
                calendar_is_not_covered |= contract
                #calendar_is_not_covered.append(contract.id)
                #raise UserError(_("Some part of %s's calendar is not covered by any work entry. Please complete the schedule.") % contract.employee_id.name)

        return calendar_is_not_covered

    def _filter_contracts(self, contracts):
        # Could be overriden to avoid having 2 'end of the year bonus' payslips, etc.
        return contracts

    def compute_slip(self):
        self.ensure_one()
        if not self.env.context.get('active_id'):
            from_date = fields.Date.to_date(self.env.context.get('default_date_start'))
            end_date = fields.Date.to_date(self.env.context.get('default_date_end'))
            today = fields.date.today()
            first_day = today + relativedelta(day=1)
            last_day = today + relativedelta(day=31)
            if from_date == first_day and end_date == last_day:
                batch_name = from_date.strftime('%B %Y')
            else:
                batch_name = _('From %s to %s', format_date(self.env, from_date), format_date(self.env, end_date))
            payslip_run = self.env['hr.payslip.run'].create({
                'name': batch_name,
                'date_start': from_date,
                'date_end': end_date,
            })
        else:
            payslip_run = self.env['hr.payslip.run'].browse(self.env.context.get('active_id'))

        employees = self.with_context(active_test=False).employee_ids
        if not employees:
            raise UserError(_("You must select employee(s) to generate payslip(s)."))

        #Prevent a payslip_run from having multiple payslips for the same employee
        employees -= payslip_run.slip_ids.employee_id
        success_result = {
                'type': 'ir.actions.act_window',
                'res_model': 'hr.payslip.run',
                'views': [[False, 'form']],
                'res_id': payslip_run.id,
            }
        #try:
        payslips = self.env['hr.payslip']
        Payslip = self.env['hr.payslip']

        if self.structure_id.process == 'contrato':
            contracts = employees._get_contracts(payslip_run.date_start, payslip_run.date_end, states=['open', 'finished'])
        else:
            contracts = employees._get_contracts(payslip_run.date_start, payslip_run.date_end, states=['open']) 

        default_values = Payslip.default_get(Payslip.fields_get())
        payslips_vals = []
        for contract in self._filter_contracts(contracts):
            values = dict(default_values, **{
                'name': _('New Payslip'),
                'employee_id': contract.employee_id.id,
                'payslip_run_id': payslip_run.id,
                'date_from': payslip_run.date_start,
                'date_to': payslip_run.date_end,
                'date_liquidacion': self.date_liquidacion,
                'date_prima': self.date_prima,
                'date_cesantias': self.date_cesantias,
                'pay_cesantias_in_payroll': self.pay_cesantias_in_payroll,
                'pay_primas_in_payroll': self.pay_primas_in_payroll,
                'contract_id': contract.id,
                'struct_id': self.structure_id.id or contract.structure_type_id.default_struct_id.id,
            })
            payslips_vals.append(values)
            if self.structure_id.process == 'contrato':
                payslips_vals[-1]['date_liquidacion'] = payslip_run.date_end
                #Obtener fecha prima
                date_prima = contract.date_start     
                obj_prima = self.env['hr.history.prima'].search([('employee_id', '=', contract.employee_id.id),('contract_id', '=', contract.id)])
                if obj_prima:
                    for history in sorted(obj_prima, key=lambda x: x.final_accrual_date):
                        date_prima = history.final_accrual_date + timedelta(days=1) if history.final_accrual_date > date_prima else date_prima  
                if date_prima < payslip_run.date_end - timedelta(days=184):  # 180 días es aproximadamente 6 meses
                    date_prima = payslip_run.date_end - timedelta(days=184)           
                payslips_vals[-1]['date_prima'] = date_prima
                #Obtener fecha vacaciones
                date_vacation = contract.date_start     
                obj_vacation = self.env['hr.vacation'].search([('employee_id', '=', contract.employee_id.id),('contract_id', '=', contract.id)])
                if obj_vacation:
                    for history in sorted(obj_vacation, key=lambda x: x.final_accrual_date):
                        if history.leave_id:
                            if history.leave_id.holiday_status_id.unpaid_absences == False:
                                date_vacation = history.final_accrual_date + timedelta(days=1) if history.final_accrual_date > date_vacation else date_vacation
                        else:
                            date_vacation = history.final_accrual_date + timedelta(days=1) if history.final_accrual_date > date_vacation else date_vacation
                payslips_vals[-1]['date_vacaciones'] = date_vacation
                #Obtener fecha cesantias
                date_cesantias = contract.date_start     
                obj_cesantias = self.env['hr.history.cesantias'].search([('employee_id', '=', contract.employee_id.id),('contract_id', '=', contract.id)])
                if obj_cesantias:
                    for history in sorted(obj_cesantias, key=lambda x: x.final_accrual_date):
                        date_cesantias = history.final_accrual_date + timedelta(days=1) if history.final_accrual_date > date_cesantias else date_cesantias             
                payslips_vals[-1]['date_cesantias'] = date_cesantias
        payslips = Payslip.with_context(tracking_disable=True).create(payslips_vals)
        payslips.compute_slip()
        payslip_run.state = 'verify'

        return success_result

    def clean_employees(self):   
        self.employee_ids = [(5,0,0)]
        return {
            'context': self.env.context,
            'view_type': 'form',
            'view_mode': 'form',
            'res_model': 'hr.payslip.employees',
            'res_id': self.id,
            'type': 'ir.actions.act_window',
            'target': 'new',
        }
class hr_payslip_worked_days(models.Model):
    _inherit = 'hr.payslip.worked_days'
    symbol = fields.Char('+/-', size=8)
    number_of_days = fields.Float(digits='Payroll')
    number_of_hours = fields.Float(digits='Payroll')
class Hr_payslip_line(models.Model):
    _inherit = 'hr.payslip.line'

    entity_id = fields.Many2one('hr.employee.entities', string="Entidad")
    loan_id = fields.Many2one('hr.loans', 'Prestamo', readonly=True)
    days_unpaid_absences = fields.Integer(string='Días de ausencias no pagadas',readonly=True)
    amount_base = fields.Float('Base')
    is_history_reverse = fields.Boolean(string='Es historico para reversar')
    run_id = fields.Many2one('hr.payslip.run', 'Lote de nomina')
    ex_rent = fields.Boolean('Aporte voluntario o ingreso exento de renta')
    afc = fields.Boolean('AFC')
    computation = fields.Html('Log computación')
    #Campos informe detalle
    branch_employee_id = fields.Many2one(related='employee_id.branch_id', string='Sucursal', store=True)
    state_slip = fields.Selection(related='slip_id.state', string='Estado Nómina', store=True)
    analytic_account_slip_id = fields.Many2one(related='slip_id.analytic_account_id', string='Cuenta Analitica', store=True)
    struct_slip_id = fields.Many2one(related='slip_id.struct_id', string='Estructura', store=True)
    subtotal =  fields.Float('Subtotal')
                
    def count_category_ids(self):
        count_category_ids = self.env['hr.payslip.line'].search_count([('slip_id', '=', self.slip_id.id), ('category_id', '=', self.category_id.id)])
        return count_category_ids

    @api.depends('quantity', 'amount', 'rate','subtotal')
    def _compute_total(self):
        round_payroll = bool(self.env['ir.config_parameter'].sudo().get_param('lavish_hr_payroll.round_payroll')) or False
        for line in self:
            if line.subtotal != 0.0:
                line.total = line.subtotal
            else:
                amount_total_original = float(line.quantity) * line.amount * line.rate / 100
                line.total = amount_total_original

class Hr_payslip_not_line(models.Model):
    _name = 'hr.payslip.not.line'
    _description = 'Reglas no aplicadas' 

    name = fields.Char(string='Nombre',required=True, translate=True)
    note = fields.Text(string='Descripción')
    sequence = fields.Integer(string='Secuencia',required=True, index=True, default=5,
                              help='Use to arrange calculation sequence')
    run_id = fields.Many2one('hr.payslip.run', 'Lote de nomina')
    code = fields.Char(string='Código',required=True)
    slip_id = fields.Many2one('hr.payslip', string='Nómina', required=True, ondelete='cascade')
    salary_rule_id = fields.Many2one('hr.salary.rule', string='Regla', required=True)
    category_id = fields.Many2one(related='salary_rule_id.category_id', string='Categoría',readonly=True, store=True)
    contract_id = fields.Many2one('hr.contract', string='Contrato', required=True, index=True)
    employee_id = fields.Many2one('hr.employee', string='Empleado', required=True)
    entity_id = fields.Many2one('hr.employee.entities', string="Entidad")
    loan_id = fields.Many2one('hr.loans', 'Prestamo', readonly=True)   
    rate = fields.Float(string='Porcentaje (%)', digits='Payroll Rate', default=100.0)
    amount = fields.Float(string='Importe',digits='Payroll')
    quantity = fields.Float(string='Cantidad',digits='Payroll', default=1.0)
    total = fields.Float(compute='_compute_total', string='Total', digits='Payroll', store=True) 
    subtotal =  fields.Float('Subtotal')

    @api.depends('quantity', 'amount', 'rate','subtotal')
    def _compute_total(self):
        for line in self:
            if line.subtotal != 0.0:
                line.total = line.subtotal
            else:
                line.total = float(line.quantity) * line.amount * line.rate / 100

    @api.model_create_multi
    def create(self, vals_list):
        for values in vals_list:
            if 'employee_id' not in values or 'contract_id' not in values:
                payslip = self.env['hr.payslip'].browse(values.get('slip_id'))
                values['employee_id'] = values.get('employee_id') or payslip.employee_id.id
                values['contract_id'] = values.get('contract_id') or payslip.contract_id and payslip.contract_id.id
                if not values['contract_id']:
                    raise UserError(_('You must set a contract to create a payslip line.'))
        return super(Hr_payslip_not_line, self).create(vals_list)

class Hr_payslip(models.Model):
    _inherit = 'hr.payslip'

    leave_ids = fields.One2many('hr.absence.days', 'payroll_id', string='Novedades', readonly=True)
    leave_days_ids =fields.One2many('hr.leave.line', 'payslip_id', string='Detalle de Ausencia', readonly=True)
    payslip_day_ids = fields.One2many(comodel_name='hr.payslip.day', inverse_name='payslip_id', string='Días de Nómina', readonly=True)
    rtefte_id = fields.Many2one('hr.employee.rtefte', 'RteFte', readonly=True)
    not_line_ids = fields.One2many('hr.payslip.not.line', 'slip_id', string='Reglas no aplicadas', readonly=True)
    observation = fields.Text(string='Observación')
    analytic_account_id = fields.Many2one('account.analytic.account', string='Cuenta analítica')
    struct_process = fields.Selection(related='struct_id.process', string='Proceso', store=True)
    employee_branch_id = fields.Many2one(related='employee_id.branch_id', string='Sucursal empleado', store=True)
    definitive_plan = fields.Boolean(string='Plano definitivo generado')
    #Fechas liquidación de contrato
    date_liquidacion = fields.Date('Fecha liquidación de contrato')
    date_prima = fields.Date('Fecha liquidación de prima')
    date_cesantias = fields.Date('Fecha liquidación de cesantías')
    date_vacaciones = fields.Date('Fecha liquidación de vacaciones')
    worked_days_line_ids = fields.One2many('hr.payslip.worked_days', 'payslip_id', compute=False, )
    pay_cesantias_in_payroll = fields.Boolean('¿Liquidar Interese de cesantia en nómina?')
    pay_primas_in_payroll = fields.Boolean('¿Liquidar Primas en nómina?')
    pay_vacations_in_payroll = fields.Boolean('¿Liquidar vacaciones en nómina?')
    provisiones = fields.Boolean('Provisiones')
    journal_struct_id = fields.Many2one('account.journal', string='Salary Journal', domain="[('company_id', '=', company_id)]")
    earnings_ids = fields.One2many(comodel_name='hr.payslip.line', compute="_compute_concepts_category", string='Conceptos de Nómina / Devengos')
    deductions_ids = fields.One2many(comodel_name='hr.payslip.line', compute="_compute_concepts_category", string='Conceptos de Nómina / Deducciones')
    bases_ids = fields.One2many(comodel_name='hr.payslip.line', compute="_compute_concepts_category", string='Conceptos de Nómina / Bases')
    provisions_ids = fields.One2many(comodel_name='hr.payslip.line', compute="_compute_concepts_category", string='Conceptos de Nómina / Provisiones')
    outcome_ids = fields.One2many(comodel_name='hr.payslip.line', compute="_compute_concepts_category", string='Conceptos de Nómina / Totales')
    date_from = fields.Date(
        string='From', readonly=False, required=True, tracking=True,
        compute=False, store=True, precompute=False)
    date_to = fields.Date(
        string='To', readonly=False, required=True, tracking=True,
        compute=False, store=True, precompute=False)



    @api.depends('line_ids')
    def _compute_concepts_category(self):
        category_mapping = {
            'EARNINGS': ['BASIC', 'AUX', 'AUS', 'ALW', 'ACCIDENTE_TRABAJO', 'DEV_NO_SALARIAL', 'DEV_SALARIAL', 'TOTALDEV', 'HEYREC', 'COMISIONES', 'INCAPACIDAD', 'LICENCIA_MATERNIDAD', 'LICENCIA_NO_REMUNERADA', 'LICENCIA_REMUNERADA', 'PRESTACIONES_SOCIALES', 'PRIMA', 'VACACIONES'],
            'DEDUCTIONS': ['DED', 'DEDUCCIONES', 'TOTALDED', 'SANCIONES', 'DESCUENTO_AFC', 'SSOCIAL'],
            'PROVISIONS': ['PROV'],
            'OUTCOME': ['NET']}
        categorized_lines = {
            'EARNINGS': [],
            'DEDUCTIONS': [],
            'PROVISIONS': [],
            'BASES': [],
            'OUTCOME': []}
        for payslip_line in self.line_ids:
            category_found = False
            for category, codes in category_mapping.items():
                if payslip_line.category_id.code in codes or payslip_line.category_id.parent_id.code in codes:
                    categorized_lines[category].append(payslip_line.id)
                    category_found = True
                    break
            if not category_found:
                categorized_lines['BASES'].append(payslip_line.id)
        for category, line_ids in categorized_lines.items():
            setattr(self, f'{category.lower()}_ids', self.env['hr.payslip.line'].browse(line_ids))
    
    def compute_sheet_leave(self):
        for rec in self:
            # Unlink existing leave_ids
            rec.leave_ids.unlink()
            rec.payslip_day_ids.unlink()
            date_from = datetime.combine(rec.date_from, datetime.min.time())
            date_to = datetime.combine(rec.date_to, datetime.max.time())
            employee_id = rec.employee_id.id
            # Search for relevant work entries
            work_entries = self.env['hr.leave'].search([
                ('state', 'not in', ['cancel', 'refuse']),
                ('date_to', '>=', date_from),
                ('date_from', '<=', date_to),
                ('employee_id', '=', employee_id),
            ])
            # Prepare values for bulk creation/update
            leave_vals = [{
                'leave_id': leave.id,
                'leave_type': leave.holiday_status_id.name,
                'employee_id': employee_id,
                'total_days': leave.number_of_days,
                'payroll_id': rec.id,
            } for leave in work_entries]
            # Bulk create/update leave_ids if there are any leaves
            if leave_vals:
                leave_records = self.env['hr.absence.days'].create(leave_vals) # Replace 'leave.model' with actual model name
                leave_records._days_used()

                # Update payslip_id in a bulk operation
                relevant_lines = leave_records.mapped('leave_id.line_ids').filtered(lambda l: l.date >= rec.date_from and l.date <= rec.date_to and l.state == 'validated')
                relevant_lines.write({'payslip_id': rec.id})

            # Compute worked days
            self.compute_worked_days()      

    def compute_worked_days(self):
        for rec in self:
            payslip_day_ids = []
            # Sort the wage changes by date for efficient processing
            wage_changes_sorted = sorted(rec.contract_id.change_wage_ids, key=lambda x: x.date_start)
            # Find the last wage rate before the payslip period
            last_wage_change_before_payslip = max((change for change in wage_changes_sorted if change.date_start < rec.date_from), default=None)
            current_wage_day = last_wage_change_before_payslip.wage / 30 if last_wage_change_before_payslip else rec.contract_id.wage / 30
            date_tmp = rec.date_from
            while date_tmp <= rec.date_to:
                is_absence_day = any(leave.date_from.date() <= date_tmp <= leave.date_to.date() for leave in rec.leave_ids.leave_id)
                is_within_contract = rec.contract_id.date_start <= date_tmp <= (rec.contract_id.date_end or date_tmp)
                # Update the wage if there is a change on this date
                wage_change_today = next((change for change in wage_changes_sorted if change.date_start == date_tmp), None)
                if wage_change_today:
                    current_wage_day = wage_change_today.wage / 30
                if is_within_contract:
                    day_type = 'A' if is_absence_day else 'W'
                    payslip_day_data = {'payslip_id': rec.id, 'day': date_tmp.day, 'day_type': day_type}
                    if not is_absence_day:
                        payslip_day_data['subtotal'] = current_wage_day
                    payslip_day_ids.append(payslip_day_data)
                else:
                    payslip_day_ids.append({'payslip_id': rec.id, 'day': date_tmp.day, 'day_type': 'X'})
                date_tmp += timedelta(days=1)
            # Create payslip day records in bulk
            rec.payslip_day_ids.create(payslip_day_ids)
        return True


    def name_get(self):
        result = []
        for record in self:
            if record.payslip_run_id:
                result.append((record.id, "{} - {}".format(record.payslip_run_id.name,record.employee_id.name)))
            else:
                result.append((record.id, "{} - {} - {}".format(record.struct_id.name,record.employee_id.name,str(record.date_from))))
        return result

    def get_hr_payslip_reports_template(self):
        type_report = self.struct_process if self.struct_process != 'otro' else 'nomina'
        obj = self.env['hr.payslip.reports.template'].search([('company_id','=',self.employee_id.company_id.id),('type_report','=',type_report)])
        if len(obj) == 0:
            raise ValidationError(_('No tiene configurada plantilla de liquidacion. Por favor verifique!'))
        return obj

    def get_pay_vacations_in_payroll(self):
        return bool(self.env['ir.config_parameter'].sudo().get_param('lavish_hr_payroll.pay_vacations_in_payroll')) or False

    def get_increase(self):
        return True

    @api.onchange('employee_id', 'struct_id', 'contract_id', 'date_from', 'date_to')
    def _onchange_employee(self):
        if (not self.employee_id) or (not self.date_from) or (not self.date_to):
            return

        employee = self.employee_id
        date_from = self.date_from
        date_to = self.date_to

        self.company_id = employee.company_id
        if not self.contract_id or self.employee_id != self.contract_id.employee_id:  # Add a default contract if not already defined
            contracts = employee._get_contracts(date_from, date_to)

            if not contracts or not contracts[0].structure_type_id.default_struct_id:
                self.contract_id = False
                self.struct_id = False
                return
            self.contract_id = contracts[0]
            self.struct_id = contracts[0].structure_type_id.default_struct_id

        payslip_name = self.struct_id.payslip_name or _('Recibo de Salario')

        mes = self.date_from.month
        month_name = self.env['hr.birthday.list'].get_name_month(mes)

        date_name = month_name + ' ' + str(self.date_from.year)
        #date_name = format_date(self.env, self.date_from, date_format="MMMM y")

        self.name = '%s - %s - %s' % (payslip_name, self.employee_id.name or '', date_name)
        self.analytic_account_id = self.contract_id.analytic_account_id

        if date_to > date_utils.end_of(fields.Date.today(), 'month'):
            self.warning_message = _(
                "This payslip can be erroneous! Work entries may not be generated for the period from %s to %s." %
                (date_utils.add(date_utils.end_of(fields.Date.today(), 'month'), days=1), date_to))
        else:
            self.warning_message = False

        #self.worked_days_line_ids = self._get_new_worked_days_lines()

    def compute_sheet(self):
        for payslip in self.filtered(lambda slip: slip.state not in ['cancel', 'done','paid']):
            payslip.line_ids.unlink()
            payslip.not_line_ids.unlink()
            payslip.leave_ids.unlink()
            payslip.compute_sheet_leave()
            #payslip._compute_worked_days_line_ids()
            payslip._compute_extra_hours()
            payslip._compute_novedades()
            payslip._assign_old_payslips()
            payslip.get_increase()
           #payslip.input_line_ids = payslip.get_inputs(payslip.date_from, payslip.date_to, payslip.struct_id.process)
            number = payslip.number or self.env['ir.sequence'].next_by_code('salary.slip')
            #Seleccionar proceso a ejecutar
            lines = []
            self._cr.execute("DELETE FROM hr_payslip_worked_days WHERE payslip_id = %s", (payslip.id,))
            constraint = """
            SELECT COUNT(id) FROM hr_payslip
            WHERE contract_id = %s AND date_from >= %s AND date_to <= %s
            AND struct_process = %s AND id != %s
            """
            self._cr.execute(constraint, (payslip.contract_id.id, payslip.date_from, payslip.date_to, payslip.struct_process, payslip.id))
            duplicated = self._cr.fetchone()[0] > 0
            
            if duplicated and payslip.struct_process not in ('vacaciones', 'contrato', 'otro'):
                raise UserError("No puede existir más de una nómina del mismo tipo y periodo para el empleado {}".format(payslip.employee_id.name))
            worked_days_line_ids = payslip.get_worked_day_lines()
            payslip.worked_days_line_ids = [(0, 0, line) for line in worked_days_line_ids]
            if payslip.struct_id.process == 'nomina':
                lines = [(0, 0, line) for line in payslip._get_payslip_lines()]
            elif payslip.struct_id.process == 'vacaciones':
                lines = [(0, 0, line) for line in payslip._get_payslip_lines()]
            elif payslip.struct_id.process == 'cesantias' or payslip.struct_id.process == 'intereses_cesantias':
                lines = [(0, 0, line) for line in payslip._get_payslip_lines_cesantias()]
            elif payslip.struct_id.process == 'prima':
                lines = [(0, 0, line) for line in payslip._get_payslip_lines_prima()]
            elif payslip.struct_id.process == 'contrato':                
                lines = [(0, 0, line) for line in payslip._get_payslip_lines()]                
            elif payslip.struct_id.process == 'otro':
                lines = [(0, 0, line) for line in payslip._get_payslip_lines_other()]
            else:
                raise ValidationError(_('La estructura seleccionada se encuentra en desarrollo.'))
            if lines:
                payslip.write({'line_ids': lines,  'number': number, 'state': 'verify', 'compute_date': fields.Date.today()})
            #payslip.renderizar_plantilla_qweb()
        return True

    def action_payslip_draft(self):
        for payslip in self:
            payslip.payslip_day_ids.unlink()
            for line in payslip.input_line_ids:
                if line.loan_line_id:
                    line.loan_line_id.paid = False
                    line.loan_line_id.payslip_id = False
                    line.loan_line_id.loan_id._compute_loan_amount()
            payslip.leave_ids.leave_id.line_ids.filtered(lambda l: l.date <= payslip.date_to).write({'payslip_id': False})
        return self.write({'state': 'draft'})

    def restart_payroll(self):
        for payslip in self:
            for line in payslip.input_line_ids:
                if line.loan_line_id:
                    line.loan_line_id.paid = False
                    line.loan_line_id.payslip_id = False
                    line.loan_line_id.loan_id._compute_loan_amount()
            #Eliminar contabilización y el calculo
            payslip.leave_ids.leave_id.line_ids.filtered(lambda l: l.date <= payslip.date_to).write({'payslip_id': False})
            payslip.mapped('move_id').unlink()
            # Modificar cuotas de prestamos pagadas
            obj_payslip_line = self.env['hr.payslip.line'].search(
                [('slip_id', '=', payslip.id), ('loan_id', '!=', False)])
            for payslip_line in obj_payslip_line:
                obj_loan_line = self.env['hr.loans.line'].search(
                    [('employee_id', '=', payslip_line.employee_id.id), ('prestamo_id', '=', payslip_line.loan_id.id),
                     ('payslip_id', '>=', payslip.id)])
                if payslip.struct_id.process == 'contrato' and payslip_line.loan_id.final_settlement_contract == True:
                    obj_loan_line.unlink()
                else:
                    obj_loan_line.write({
                        'paid': False,
                        'payslip_id': False
                    })
                obj_loan = self.env['hr.loans'].search(
                    [('employee_id', '=', payslip_line.employee_id.id), ('id', '=', payslip_line.loan_id.id)])
                if obj_loan.balance_amount > 0:
                    self.env['hr.contract.concepts'].search([('loan_id', '=', payslip_line.loan_id.id)]).write(
                        {'state': 'done'})
            payslip.line_ids.unlink()
            payslip.not_line_ids.unlink()
            #Eliminar historicos            
            self.env['hr.vacation'].search([('payslip', '=', payslip.id)]).unlink()
            self.env['hr.history.prima'].search([('payslip', '=', payslip.id)]).unlink()
            self.env['hr.history.cesantias'].search([('payslip', '=', payslip.id)]).unlink()
            #Reversar Liquidación            
            payslip.action_payslip_draft()            

    #--------------------------------------------------LIQUIDACIÓN DE LA NÓMINA PERIÓDICA---------------------------------------------------------#

    
    def _get_worked_day_lines_values(self, domain=None):
        res = super()._get_worked_day_lines_values(domain=domain)
        wm = self.env['hr.work.entry.type'].search([("code", "=", "VACATIONS_MONEY")], limit=1)
        vacations_money = self.env['hr.leave'].search([
            ('employee_id', '=', self.employee_id.id),
            ('holiday_status_id.code', '=', 'VACATIONS_MONEY'),
            ("request_date_from", ">=", self.date_from),
            ("request_date_to", "<=", self.date_to),
            ('state', '=', 'validate')
        ])
        if vacations_money:
            vacations_money_days = sum(vacations_money.mapped('number_of_days'))
            vacations_money_hours = vacations_money_days * self.contract_id.resource_calendar_id.hours_per_day
            res.append({
                'sequence': wm.sequence,
                'work_entry_type_id': wm.id,
                'number_of_days': vacations_money_days,
                'number_of_hours': vacations_money_hours,
            })
        return res

    def _get_new_worked_days_lines(self):
        if self.struct_id.use_worked_day_lines:
            # computation of the salary worked days
            worked_days_line_values = self._get_worked_day_lines()
            worked_days_lines = self.worked_days_line_ids.browse([])
            for r in worked_days_line_values:
                worked_days_lines |= worked_days_lines.new(r)
            # Validar que al ser el mes de febrero modifique los días trabajados para que sean igual a un mes de 30 días
            if self.date_to.month == 2 and self.date_to.day in (28,29):
                february_worked_days = worked_days_lines.filtered(lambda l: l.work_entry_type_id.code == 'WORK100')
            days_summary = 2 if self.date_to.day == 28 else 1
            hours_summary = 16 if self.date_to.day == 28 else 8
            if len(february_worked_days) > 0:
                for february_days in worked_days_lines:
                    if february_days.work_entry_type_id.code == 'WORK100':
                        february_days.number_of_days = february_days.number_of_days + days_summary # Se agregan 2 días
                        february_days.number_of_hours = february_days.number_of_hours + hours_summary # Se agregan 16 horas
            else:
                #Ultimo día de febrero
                work_hours = self.contract_id._get_work_hours(self.date_to, self.date_to)
                work_hours_ordered = sorted(work_hours.items(), key=lambda x: x[1])
                biggest_work = work_hours_ordered[-1][0] if work_hours_ordered else 0
                #Primer día de marzo
                march_date_from = self.date_to + timedelta(days=1)
                march_date_to = self.date_to + timedelta(days=1)
                march_work_hours = self.contract_id._get_work_hours(march_date_from, march_date_to)
                march_work_hours_ordered = sorted(march_work_hours.items(), key=lambda x: x[1])
                march_biggest_work = march_work_hours_ordered[-1][0] if march_work_hours_ordered else 0
                #Proceso a realizar
                if march_biggest_work == 0 or biggest_work != march_biggest_work: #Si la ausencia no continua hasta marzo se agregan 2 días trabajados para completar los 30 días en febrero
                    work_entry_type = self.env['hr.work.entry.type'].search([('code','=','WORK100')])
                    attendance_line = {
                        'sequence': work_entry_type.sequence,
                        'work_entry_type_id': work_entry_type.id,
                        'number_of_days': days_summary,
                        'number_of_hours': hours_summary,
                        'amount': 0,
                    }
                    worked_days_lines |= worked_days_lines.new(attendance_line)
                else: #Si la ausencia continua hasta marzo se agregan 2 días de la ausencia para completar los 30 días en febrero
                    work_entry_type = self.env['hr.work.entry.type'].search([('id', '=', biggest_work)])
                    for february_days in worked_days_lines:
                        if february_days.work_entry_type_id.code == work_entry_type.code:
                            february_days.number_of_days = february_days.number_of_days + days_summary  # Se agregan 2 días
                            february_days.number_of_hours = february_days.number_of_hours + hours_summary  # Se agregan 16 horas
            if self.date_to.day == 31:
                worked_days = worked_days_lines.filtered(lambda l: l.work_entry_type_id.code == 'WORK100')
                days_summary = 1
                hours_summary = 8
                if len(worked_days) > 0:
                    for days in worked_days_lines:
                        if days.work_entry_type_id.code == 'WORK100':
                            days.number_of_days = days.number_of_days - days_summary # Se quita 1 días
                            days.number_of_hours = days.number_of_hours - hours_summary # Se quita 8 horas
            return worked_days_lines
        else:
            return [(5, False, False)]

    def _get_payslip_lines(self,inherit_vacation=0,inherit_prima=0,inherit_contrato_dev=0, inherit_contrato_ded_bases=0,inherit_contrato_ded=0,localdict=None):
        def _sum_salary_rule_category(localdict, category, amount):
            if category.parent_id:
                localdict = _sum_salary_rule_category(localdict, category.parent_id, amount)
            localdict['categories'].dict[category.code] = localdict['categories'].dict.get(category.code, 0) + amount
            return localdict
        def _sum_salary_rule(localdict, rule, amount):
            localdict['rules_computed'].dict[rule.code] = localdict['rules_computed'].dict.get(rule.code, 0) + amount
            return localdict
        self.ensure_one()
        round_payroll = bool(self.env['ir.config_parameter'].sudo().get_param('lavish_hr_payroll.round_payroll')) or False
        result = {}
        result_not = {}
        rules_dict = {}
        if inherit_contrato_ded_bases + inherit_contrato_ded + inherit_contrato_dev == 1 and self.date_from == self.date_to:
            worked_days_dict = {}
        else:
            worked_days_dict = {line.code: line for line in self.worked_days_line_ids if line.code}
        blacklisted_rule_ids = self.env.context.get('prevent_payslip_computation_line_ids', [])
        localdict = self.env.context.get('force_payslip_localdict', None)
        leaved_days_dict = {line.leave_id.holiday_status_id.code: line for line in self.leave_ids if line.leave_id.holiday_status_id.code}
        worked_days_dict = {line.code: line for line in self.worked_days_line_ids if line.code}
        inputs_dict = {line.code: line for line in self.input_line_ids if line.code}
        pay_vacations_in_payroll = bool(self.env['ir.config_parameter'].sudo().get_param('lavish_hr_payroll.pay_vacations_in_payroll')) or False
        pay_cesantias_in_payroll = bool(self.env['ir.config_parameter'].sudo().get_param('lavish_hr_payroll.pay_cesantias_in_payroll')) or False
        pay_primas_in_payroll = bool(self.env['ir.config_parameter'].sudo().get_param('lavish_hr_payroll.pay_primas_in_payroll')) or False        
        vacation_days_calculate_absences = int(self.env['ir.config_parameter'].sudo().get_param('lavish_hr_payroll.vacation_days_calculate_absences')) or 5
        worked_days_entry = 0
        leaves_days_law = 0
        leaves_days_all = 0
        for days in self.worked_days_line_ids:
            worked_days_entry = worked_days_entry + (days.number_of_days if days.work_entry_type_id.is_leave == False else 0)
            leaves_days_law = leaves_days_law + (days.number_of_days if days.work_entry_type_id.is_leave and days.work_entry_type_id.deduct_deductions == 'law' else 0)
            leaves_days_all = leaves_days_all + (days.number_of_days if days.work_entry_type_id.is_leave and days.work_entry_type_id.deduct_deductions == 'all' else 0)
        employee = self.employee_id
        contract = self.contract_id
        year = self.date_from.year
        annual_parameters = self.env['hr.annual.parameters'].search([('year', '=', year)])
        #Se eliminan registros actuales para el periodo ejecutado de Retención en la fuente
        self.env['hr.employee.deduction.retention'].search([('employee_id', '=', employee.id),('year', '=', self.date_from.year),('month', '=', self.date_from.month)]).unlink()
        self.env['hr.employee.rtefte'].search([('employee_id', '=', employee.id),('year', '=', self.date_from.year),('month', '=', self.date_from.month)]).unlink()

        #Se obtienen las entradas de trabajo
        date_from = datetime.combine(self.date_from, datetime.min.time())
        date_to = datetime.combine(self.date_to, datetime.max.time())
        #Primero, encontró una entrada de trabajo que no excedió el intervalo.
        work_entries = self.env['hr.work.entry'].search([('state', 'in', ['validated', 'draft']),
                ('date_start', '>=', date_from),
                ('date_stop', '<=', date_to),
                ('contract_id', '=', contract.id),
                ('leave_id','!=',False)])
        #En segundo lugar, encontró entradas de trabajo que exceden el intervalo y calculan la duración correcta. 
        work_entries += self.env['hr.work.entry'].search(['&', '&',
                ('state', 'in', ['validated', 'draft']),
                ('contract_id', '=', contract.id),
                '|', '|', '&', '&',
                ('date_start', '>=', date_from),
                ('date_start', '<', date_to),
                ('date_stop', '>', date_to),
                '&', '&',
                ('date_start', '<', date_from),
                ('date_stop', '<=', date_to),
                ('date_stop', '>', date_from),
                '&',
                ('date_start', '<', date_from),
                ('date_stop', '>', date_to),
            ])
        #Validar incapacidades de mas de 180 dias
        leaves = {}
        lst_leave_ids = []
        wage = contract.wage
        obj_wage = self.env['hr.contract.change.wage'].search([('contract_id', '=', contract.id), ('date_start', '<', date_to)])
        for change in sorted(obj_wage, key=lambda x: x.date_start):
            if float(change.wage) > 0:
                wage = change.wage 
            else:    
                wage = contract.wage
        if wage <= 0:
            raise UserError('El sueldo no puede ser igual a 0 o menor')
        for leave in work_entries:
            if leave.leave_id:
                if leave.leave_id.id not in lst_leave_ids:
                    lst_leave_ids.append(leave.leave_id.id)
                    es_continuidad = 1
                    number_of_days = leave.leave_id.number_of_days
                    number_of_days_total = leave.leave_id.number_of_days
                    holiday_status_id = leave.leave_id.holiday_status_id.id
                    request_date_to = leave.leave_id.request_date_from - timedelta(days=1)
                    #Fecha Ausencia pertenecientes a la liquidación
                    start_leave = True if leave.leave_id.request_date_from >= self.date_from else False
                    end_leave = True if leave.leave_id.request_date_to <= self.date_to else False
                    initial_date = leave.leave_id.request_date_from if leave.leave_id.request_date_from >= self.date_from else self.date_from
                    end_date = leave.leave_id.request_date_to if leave.leave_id.request_date_to <= self.date_to else self.date_to
                    number_of_days = (end_date-initial_date).days + 1
                    if leaves.get(leave.work_entry_type_id.code,False):
                        leaves[leave.work_entry_type_id.code+'_TOTAL'] += number_of_days_total
                        leaves[leave.work_entry_type_id.code] += number_of_days
                    else:
                        leaves[leave.work_entry_type_id.code+'_TOTAL'] = number_of_days_total
                        leaves[leave.work_entry_type_id.code] = number_of_days
                    #Guardar dias que asume la compañia
                    obj_leave_type = self.env['hr.leave.type'].search([('code', '=', leave.work_entry_type_id.code)],limit=1)
                    if len(obj_leave_type) > 0:
                        if obj_leave_type.num_days_no_assume > 0:
                            if start_leave or (start_leave and end_leave):
                                days_company = obj_leave_type.num_days_no_assume if number_of_days >= obj_leave_type.num_days_no_assume else number_of_days
                                days_partner = number_of_days - obj_leave_type.num_days_no_assume if number_of_days >= obj_leave_type.num_days_no_assume else 0
                            if end_leave and not start_leave:
                                num_days_no_assume = (((initial_date - leave.leave_id.request_date_from).days + 1)-obj_leave_type.num_days_no_assume)
                                if num_days_no_assume > 0:
                                    days_company = 0
                                    days_partner = number_of_days
                                else:
                                    num_days_no_assume = 1 if abs(num_days_no_assume)==0 else num_days_no_assume
                                    num_days_no_assume = obj_leave_type.num_days_no_assume if abs(num_days_no_assume)>=obj_leave_type.num_days_no_assume else num_days_no_assume
                                    days_company = abs(num_days_no_assume)
                                    days_partner = number_of_days - abs(num_days_no_assume) if number_of_days >= abs(num_days_no_assume) else 0
                            if not start_leave and not end_leave:
                                days_company = 0
                                days_partner = number_of_days
                            if leaves.get(leave.work_entry_type_id.code+'_COMPANY', False):
                                leaves[leave.work_entry_type_id.code+'_COMPANY'] += days_company
                            else:
                                leaves[leave.work_entry_type_id.code + '_COMPANY'] = days_company
                            if leaves.get(leave.work_entry_type_id.code + '_PARTNER', False):
                                leaves[leave.work_entry_type_id.code + '_PARTNER'] += days_partner
                            else:
                                leaves[leave.work_entry_type_id.code + '_PARTNER'] = days_partner
        start_period = date_from.replace(day=1)
        date_to = self.date_to
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
        date_from = self.date_from

        date_from_time = datetime.combine(date_from, datetime.min.time())
        date_to_time = datetime.combine(date_to, datetime.max.time())
        if localdict == None:
            localdict = {
                **self._get_base_local_dict(),
                **{
                    'categories': BrowsableObject(employee.id, {}, self.env),
                    'rules_computed': BrowsableObject(employee.id, {}, self.env),
                    'rules': BrowsableObject(employee.id, rules_dict, self.env),
                    'payslip': Payslips(employee.id, self, self.env),
                    'worked_days': WorkedDays(employee.id, worked_days_dict, self.env),
                    'inputs': InputLine(employee.id, inputs_dict, self.env),
                    'leaves':  BrowsableObject(employee.id, leaves, self.env),
                    'leaved_days': LeavedDays(employee.id, leaved_days_dict, self.env),   
                    'employee': employee,
                    'contract': contract,
                    'annual_parameters': annual_parameters,
                    'values_leaves_all' : 0.0,
                    'values_leaves_law' : 0.0,
                    'wage':wage,
                    'result_rules_co': ResultRules_co(employee.id, {}, self.env),
                    #Sumatoria de valores que son base para los procesos
                    'values_base_prima': 0.0,
                    'values_base_cesantias': 0.0,
                    'values_base_int_cesantias': 0.0,
                    'values_base_vacremuneradas': 0.0,
                    'values_base_seguridad_social': 0.0,
                    'values_base_seguridad_social_no_salarial': 0.0,
                    'values_base_provisiones': 0.0,
                    'values_base_vacaciones': 0.0,
                    'values_base_vacdisfrutadas': 0.0,
                    'id_contract_concepts':0.0,
                    'inherit_contrato':inherit_contrato_ded+inherit_contrato_dev,
                    'inherit_prima':inherit_prima,
                    'slip': self,
                    'annual_parameters': annual_parameters,
                    'date_to_time':date_to_time,
                    'date_from_time':date_from_time,
                    'payslips_month':payslips_month,
                }
            }
        else:
            localdict.update({
                'worked_days': WorkedDays(employee.id, worked_days_dict, self.env),
                'inputs': InputLine(employee.id, inputs_dict, self.env),
                'values_leaves_all' : localdict.get('values_leaves_all',0),
                'values_leaves_law' : localdict.get('values_leaves_law',0),
                #Sumatoria de valores que son base para los procesos
                'result_rules_co': ResultRules_co(employee.id, {}, self.env),
                'values_base_prima': localdict.get('values_base_prima',0),
                'values_base_cesantias': localdict.get('values_base_cesantias',0),
                'values_base_int_cesantias': localdict.get('values_base_int_cesantias',0),
                'values_base_compensation': localdict.get('values_base_compensation',0),
                'values_base_vacremuneradas': localdict.get('values_base_vacremuneradas',0),
                'values_base_vacdisfrutadas': localdict.get('values_base_vacdisfrutadas',0),
                'inherit_contrato':inherit_contrato_ded_bases+inherit_contrato_ded+inherit_contrato_dev,
                'inherit_prima':inherit_prima,
                'annual_parameters': annual_parameters,
                'date_to_time':date_to_time,
                'date_from_time':date_from_time,
                'payslips_month':payslips_month,})
            if localdict.get('leaves',False) == False:
                localdict.update({'leaves': BrowsableObject(employee.id, leaves, self.env), })
        result_rules_dict_co = localdict['result_rules_co'].dict 
        #Ejecutar vacaciones dentro de la nómina - 16/02/2022
        if (pay_vacations_in_payroll == True and inherit_vacation == 0 and inherit_contrato_ded+inherit_contrato_dev == 0 and inherit_prima == 0):
            struct_original = self.struct_id.id
            #Vacaciones
            obj_struct_vacation = self.env['hr.payroll.structure'].search([('process', '=', 'vacaciones')])
            self.struct_id = obj_struct_vacation.id
            localdict, result_vac = self._get_payslip_lines_vacation(inherit_contrato=0, localdict=localdict, inherit_nomina=1)
            localdict.update({'leaves': BrowsableObject(employee.id, leaves, self.env)})
            #Continuar con la nómina
            self.struct_id = struct_original
            worked_days_dict = {line.code: line for line in self.worked_days_line_ids if line.code}
            inputs_dict = {line.code: line for line in self.input_line_ids if line.code}
            localdict.update({'worked_days': WorkedDays(employee.id, worked_days_dict, self.env),
                              'inputs': InputLine(employee.id, inputs_dict, self.env),
                              'leaves': BrowsableObject(employee.id, leaves, self.env)})
        else:
            result_vac = {}
        if (self.struct_id.process == 'contrato'):
            struct_original = self.struct_id.id
            #Vacaciones
            obj_struct_payroll = self.env['hr.payroll.structure'].search([('process','=','vacaciones')])
            self.struct_id = obj_struct_payroll.id
            localdict, result_vac_l = self._get_payslip_lines_vacation(inherit_contrato=1,localdict=localdict)
            #Continuar con la nómina
            self.struct_id = struct_original
        else:
            result_vac_l = {}
        #Cargar novedades por conceptos diferentes
        if (contract.modality_salary != 'integral' or contract.contract_type != 'aprendizaje') :
            if (pay_cesantias_in_payroll == True and self.pay_cesantias_in_payroll == True) or (self.struct_id.process == 'contrato'):
                struct_original = self.struct_id.id
                obj_struct_payroll = self.env['hr.payroll.structure'].search([('process', '=', 'intereses_cesantias')])
                if (self.struct_id.process == 'contrato'):
                    obj_struct_payroll = self.env['hr.payroll.structure'].search([('process','=','cesantias')])
                self.struct_id = obj_struct_payroll.id
                localdict, result_intcesantias = self.with_context(direct=True)._get_payslip_lines_cesantias(inherit_contrato=1, localdict=localdict)
                #Continuar con la nómina
                self.struct_id = struct_original
            else:
                result_intcesantias = {}
            if (pay_primas_in_payroll == True and self.pay_primas_in_payroll == True) or (self.struct_id.process == 'contrato'):
                struct_original = self.struct_id.id
                obj_struct_payroll = self.env['hr.payroll.structure'].search([('process','=','prima')])
                self.struct_id = obj_struct_payroll.id
                localdict, result_prima = self._get_payslip_lines_prima(inherit_contrato=1,localdict=localdict)
                self.struct_id = struct_original
            else:
                result_prima = {}
        obj_novelties = self.env['hr.novelties.different.concepts'].search([('employee_id', '=', employee.id), ('date', '>=', self.date_from),('date', '<=', self.date_to)])
        for concepts in obj_novelties:
            if concepts.amount != 0 and inherit_prima == 0:
                previous_amount = concepts.salary_rule_id.code in localdict and localdict[concepts.salary_rule_id.code] or 0.0
                #set/overwrite the amount computed for this rule in the localdict
                tot_rule = concepts.amount * 1.0 * 100 / 100.0
                #LIQUIDACION DE CONTRATO SOLO DEV OR DED DEPENDIENTO SU ORIGEN
                if (inherit_contrato_dev != 0 or inherit_contrato_ded != 0) and self.novelties_payroll_concepts == False and not concepts.salary_rule_id.code in ['TOTALDEV','TOTALDED','NET','IBD','IBC_A','IBC_P']:
                    tot_rule = 0
                if inherit_contrato_dev != 0 and concepts.salary_rule_id.dev_or_ded != 'devengo':                            
                    tot_rule = 0
                if inherit_contrato_ded != 0 and concepts.salary_rule_id.dev_or_ded != 'deduccion'and not concepts.salary_rule_id.code in ['TOTALDEV','NET',]:                            
                    tot_rule = 0
                if tot_rule != 0:
                    rule = concepts.salary_rule_id
                    result_rules_dict_co[rule.code +'-PCD'+str(concepts.id)] = {'total': tot_rule, 'amount': tot_rule, 'quantity': 1, 'base_seguridad_social': rule.base_seguridad_social, 'base_prima':rule.base_prima, 'base_cesantias':rule.base_cesantias,  'base_vacaciones':rule.base_vacaciones,'base_vacaciones_dinero':rule.base_vacaciones_dinero}
                    localdict[concepts.salary_rule_id.code+'-PCD'] = tot_rule
                    rules_dict[concepts.salary_rule_id.code+'-PCD'] = concepts.salary_rule_id
                    # sum the amount for its salary category
                    localdict = _sum_salary_rule_category(localdict, concepts.salary_rule_id.category_id, tot_rule - previous_amount)
                    localdict = _sum_salary_rule(localdict, concepts.salary_rule_id, tot_rule)
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
                        #'note': concepts.salary_rule_id.note,
                        'salary_rule_id': concepts.salary_rule_id.id,
                        'contract_id': contract.id,
                        'employee_id': employee.id,
                        'entity_id': concepts.partner_id.id if concepts.partner_id else False,
                        'amount': tot_rule,
                        'quantity': 1.0,
                        'rate': 100,
                        'total': tot_rule,
                        'slip_id': self.id,}
        def calculate_total_rule(concept, date_from, worked_days_line_ids, employee):
            tot_rule = concept.amount
            if concept.input_id.dev_or_ded == 'deduccion':
                tot_rule = -tot_rule

            if concept.input_id.modality_value == "fijo":
                if concept.aplicar == "0" or (concept.aplicar == "15" and date_from.day <= 15) or (concept.aplicar == "30" and date_from.day > 16):
                    return tot_rule

            elif concept.input_id.modality_value in ["diario", "diario_efectivo"]:
                qty = 1  # Default value

                if concept.input_id.modality_value == "diario":
                    for linea in worked_days_line_ids:
                        if linea.work_entry_type_id.code == 'WORK100':
                            qty = linea.number_of_days

                    if concept.aplicar == "30" and date_from.day > 16:
                        start_date = self.date_to.replace(day=1)  # Primer día del mes
                        end_date = start_date + relativedelta(months=1) - relativedelta(days=1)  # Último día del mes

                        dias = self.env['hr.payslip.worked_days'].search([
                            ('payslip_id.employee_id.id', '=', employee.id),
                            ('payslip_id.date_to', '>=', start_date),
                            ('payslip_id.date_to', '<=', end_date),
                            ('payslip_id.struct_id.process', '=', 'nomina'),
                            ('work_entry_type_id.code', '=', 'WORK100')
                        ])

                        if dias:
                            qty = sum(d.number_of_days for d in dias)

                elif concept.input_id.modality_value == "diario_efectivo":
                    dias_trabajados = self.dias360(self.date_from, self.date_to)
                    dias_ausencias = sum([i.number_of_days for i in self.env['hr.leave'].search([
                        ('date_from', '>=', self.date_from),
                        ('date_to', '<=', self.date_to),
                        ('state', '=', 'validate'),
                        ('employee_id', '=', self.employee_id.id),
                        ('unpaid_absences', '=', True)
                    ])])
                    qty = dias_trabajados - dias_ausencias

                return (tot_rule / 30) * qty
        obj_concept = contract.concepts_ids #self.env['hr.contract.concepts'].search([('contract_id', '=', contract.id),('state','=','done')]) 
        for concept in obj_concept.filtered(lambda l: l.state == 'done'):
            entity_id = concept.partner_id.id
            loan_id = concept.loan_id.id 
            date_start_concept = concept.date_start if concept.date_start else datetime.strptime('01/01/1900', '%d/%m/%Y').date()
            date_end_concept = concept.date_end if concept.date_end else datetime.strptime('31/12/2080', '%d/%m/%Y').date()
            previous_amount = concept.input_id.code in localdict and localdict[concept.input_id.code] or 0.0
            if (concept.state == 'done' and 
                date_start_concept <= date_to and 
                date_end_concept >= date_from and 
                concept.amount != 0 and 
                inherit_prima == 0 and 
                concept.input_id.amount_select != "code" and self.settle_payroll_concepts ):
                #localdict.update({'id_contract_concepts': concept.id})
                tot_rule = calculate_total_rule(concept, self.date_from, self.worked_days_line_ids, employee)
                #LIQUIDACION DE CONTRATO SOLO DEV OR DED DEPENDIENTO SU ORIGEN
                if (inherit_contrato_dev != 0 or inherit_contrato_ded != 0) and self.novelties_payroll_concepts == False and not concept.input_id.code in ['TOTALDEV','TOTALDED','NET','IBD','IBC_A','IBC_P']:
                    tot_rule = 0
                if inherit_contrato_dev != 0 and concept.input_id.dev_or_ded != 'devengo':                            
                    tot_rule = 0
                if inherit_contrato_ded != 0 and concept.input_id.dev_or_ded != 'deduccion'and not concept.input_id.code in ['TOTALDEV','NET',]:                            
                    tot_rule = 0
                if tot_rule != 0:
                    localdict[concept.input_id.code+'-PCD' + str(concept.id)] = tot_rule
                    rules_dict[concept.input_id.code+'-PCD' + str(concept.id)] = concept.input_id
                    rule = concept.input_id
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
                   # 'note': concept.input_id.note,
                    'salary_rule_id': concept.input_id.id,
                    'contract_id': contract.id,
                    'employee_id': employee.id,
                    'entity_id': entity_id,
                    'loan_id': loan_id,
                    'amount': tot_rule,
                    'quantity': 1.00,
                    'rate': 100,
                    'total': tot_rule,
                    'slip_id': self.id,
                }
                # Incrementa el contador
        #Ejecutar las reglas salariales y su respectiva lógica
        all_rules = self.env['hr.salary.rule'].browse([])
        if not self.struct_id.process == 'vacaciones':
            all_rules = self.struct_id.rule_ids
        specific_rules = self.env['hr.salary.rule'].browse([])
        obj_struct_payroll = self.env['hr.payroll.structure'].search([('process', '=', 'nomina')])
        if obj_struct_payroll:
            if (self.settle_payroll_concepts and self.struct_id.process == 'contrato'):
                all_rules |= obj_struct_payroll.mapped('rule_ids')
                
            if self.struct_id.process in ('vacaciones',):
            # Fetching rules with specific codes
                specific_rule_codes = ['IBD', 'TOTALDEV', 'TOTALDED', 'NET']
                specific_rules = self.env['hr.salary.rule'].search([
                    '|',('code', 'in', specific_rule_codes),
                    ('type_concepts', '=', 'ley'),  
                    ('id', 'in', obj_struct_payroll.mapped('rule_ids').ids)  # Asegura que solo consideramos reglas en la estructura que encontramos
                ])
            if not self.settle_payroll_concepts  and  self.struct_id.process in ('contrato'):
            # Fetching rules with specific codes
                specific_rule_codes = ['TOTALDEV', 'TOTALDED', 'NET']
                specific_rules = self.env['hr.salary.rule'].search([
                    '|',('code', 'in', specific_rule_codes),
                    ('type_concepts', '=', 'ley'),  
                    ('id', 'in', obj_struct_payroll.mapped('rule_ids').ids)  # Asegura que solo consideramos reglas en la estructura que encontramos
                ])
                all_rules |= specific_rules
        #for rule in sorted(self.struct_id.rule_ids, key=lambda x: x.sequence):
        for rule in sorted(all_rules, key=lambda x: x.sequence):
            if rule.id in blacklisted_rule_ids:
                continue
            localdict.update({
                'result': None,
                
                'result_qty': 1.0,

                'result_rate': 100,
                
                'result_name': False
            })
            if rule._satisfy_condition(localdict):
                entity_id,loan_id = 0,0
                #Obtener entidades de seguridad social
                if rule.category_id.code == 'SSOCIAL':
                    for entity in employee.social_security_entities:
                        if entity.contrib_id.type_entities == 'eps' and rule.code == 'SSOCIAL001': # SALUD 
                            entity_id = entity.partner_id.id
                        if entity.contrib_id.type_entities == 'pension' and (rule.code == 'SSOCIAL002' or rule.code == 'SSOCIAL003' or rule.code == 'SSOCIAL004'): # Pension
                            entity_id = entity.partner_id.id
                        if entity.contrib_id.type_entities == 'subsistencia' and rule.code == 'SSOCIAL003': # Subsistencia 
                            entity_id = entity.partner_id.id
                        if entity.contrib_id.type_entities == 'solidaridad' and rule.code == 'SSOCIAL004': # Solidaridad 
                            entity_id = entity.partner_id.id
                #Valida que si la regla esta en la pestaña de Devengo & Deducciones del contrato
                amount, qty, rate, name,log,data  = rule._compute_rule(localdict)
                #Validar si no tiene dias trabajados, si no tiene revisar las ausencias y sus caracteristicas para calcular la deducción
                if rule.dev_or_ded == 'deduccion' and rule.type_concepts != 'ley' and (worked_days_entry + leaves_days_all) == 0 and inherit_prima==0:
                    amount, qty, rate  = 0,1.0,100 
                #LIQUIDACION DE CONTRATO SOLO DEV OR DED DEPENDIENTO SU ORIGEN
                if str(rule.amount_python_compute).find('get_overtime') != -1: #Verficiar si la regla utiliza la tabla hr.overtime por ende es un concepto de novedad del menu horas extras
                    if (inherit_contrato_dev != 0 or inherit_contrato_ded != 0) and self.novelties_payroll_concepts == False and not rule.code in ['TOTALDEV','TOTALDED','NET','IBC_A','IBC_P']:
                        amount, qty, rate = 0,1.0,100
                else:
                    if (inherit_contrato_dev != 0 or inherit_contrato_ded != 0) and self.settle_payroll_concepts == False and rule.type_concepts != 'ley' and not rule.code in ['TOTALDEV','TOTALDED','NET','IBC_A','IBC_P']:
                        amount, qty, rate = 0,1.0,100
                # PRIMA SOLAMENTE DEDUCCIONES QUE ESTEN CONFIGURADAS
                # VACACIONES SOLAMENTE DEDUCCIONES
                if (inherit_contrato_dev != 0 and rule.dev_or_ded != 'devengo')\
                        or (inherit_contrato_ded != 0 and rule.dev_or_ded != 'deduccion' and not rule.code in ['TOTALDEV','NET']) \
                        or (inherit_prima != 0 and rule.dev_or_ded != 'deduccion' and not rule.code in ['TOTALDEV','NET']) \
                        or (inherit_prima != 0 and rule.dev_or_ded == 'deduccion' and rule.deduction_applies_bonus == False) \
                        or (inherit_vacation != 0 and rule.dev_or_ded != 'deduccion' and not rule.code in ['TOTALDEV','NET','IBC_A','IBC_P']):
                    amount, qty, rate  = 0,1.0,100
                #check if there is already a rule computed with that code
                previous_amount = rule.code in localdict and localdict[rule.code] or 0.0
                tot_rule = (amount * qty * rate / 100.0) + previous_amount
                if not round_payroll:
                    tot_rule = round(tot_rule,0) 
                localdict[rule.code] = tot_rule
                rules_dict[rule.code] = rule
                # sum the amount for its salary category
                result_rules_dict_co[rule.code] = {'total': tot_rule, 'amount': amount, 'quantity': qty, 'base_seguridad_social': rule.base_seguridad_social, 'base_prima':rule.base_prima, 'base_cesantias':rule.base_cesantias,  'base_vacaciones':rule.base_vacaciones,'base_vacaciones_dinero':rule.base_vacaciones_dinero}
                localdict = _sum_salary_rule_category(localdict, rule.category_id, tot_rule - previous_amount) 
                localdict = _sum_salary_rule(localdict, rule, tot_rule)
                #Guardar valores de ausencias dependiendo parametrización
                if rule.is_leave:
                    amount_leave = (float(qty) * amount * rate / 100) if rule.deduct_deductions == 'all' else 0
                    localdict['values_leaves_all'] = localdict['values_leaves_all'] + amount_leave
                    amount_leave_law = (float(qty) * amount * rate / 100) if rule.deduct_deductions == 'law' else 0
                    localdict['values_leaves_law'] = localdict['values_leaves_law'] + amount_leave_law
                
                # create/overwrite the rule in the temporary results
                if amount != 0:
                    if rule.dev_or_ded == 'deduccion' and inherit_prima == 0:
                        if rule.type_concepts == 'ley':
                            value_tmp_neto = localdict['categories'].dict.get('DEV_SALARIAL',0) + localdict['categories'].dict.get('DEV_NO_SALARIAL',0) + localdict['categories'].dict.get('PRESTACIONES_SOCIALES',0) + localdict['categories'].dict.get('DEDUCCIONES',0)
                        else:
                            value_tmp_neto = (localdict['categories'].dict.get('DEV_SALARIAL',0) + localdict['categories'].dict.get('DEV_NO_SALARIAL',0) + localdict['categories'].dict.get('PRESTACIONES_SOCIALES',0) + localdict['categories'].dict.get('DEDUCCIONES',0)) - localdict['values_leaves_law']
                    else:
                        value_tmp_neto = 1
                    subtotal = (amount * qty) * rate / 100
                    if not round_payroll:
                        subtotal = round((amount * qty) * rate / 100,0) 
                    if value_tmp_neto >= 0:
                        result[rule.code] = {
                            'sequence': rule.sequence,
                            'code': rule.code,
                            'name': name or rule.name,
                          #  'note': rule.note,
                            'salary_rule_id': rule.id,
                            'contract_id': contract.id,
                            'employee_id': employee.id,
                            'entity_id': entity_id,
                            'loan_id': loan_id,
                            'amount': amount, #Se redondean los decimales de todas las reglas
                            'quantity': qty,
                            'rate': rate,
                            'subtotal':subtotal,
                            'total': tot_rule,
                            'slip_id': self.id,
                        }
                    else:
                        localdict = _sum_salary_rule_category(localdict, rule.category_id, (tot_rule - previous_amount)*-1) 
                        localdict = _sum_salary_rule(localdict, rule, (tot_rule)*-1)
                        result_not[rule.code] = {
                            'sequence': rule.sequence,
                            'code': rule.code,
                            'name': name or  rule.name,
                           # 'note': rule.note,
                            'salary_rule_id': rule.id,
                            'contract_id': contract.id,
                            'employee_id': employee.id,
                            'entity_id': entity_id,
                            'loan_id': loan_id,
                            'amount': amount, #Se redondean los decimales de todas las reglas
                            'quantity': qty,
                            'rate': rate,
                            'subtotal':subtotal,
                            'total': tot_rule,
                            'slip_id': self.id}
        #_logger.info(localdict.items())
        #Cargar detalle retención en la fuente si tuvo
        ranges = {
            (1, 4): "Ingreso Base",
            (5, 8): "Menos Deducciones",
            (9, 13): "Subtotal 1",
            (14, 21): "Subtotal 2",
            (23, 30): "Subtotal 3",
            (31, 37): "Subtotal 4",
            (38, 38): "Retención Anterior",
            (39, 41): "Total"
        }
        obj_rtefte = self.env['hr.employee.rtefte'].search([
            ('employee_id', '=', employee.id),
            ('year', '=', self.date_from.year),
            ('month', '=', self.date_from.month)
        ])

        # Diccionario para rastrear deducciones procesadas
        processed_deductions = {}

        if obj_rtefte:
            html_report = """
            <table border="1" style="width: 100%; border-collapse: collapse;">
                <thead>
                    <tr>
                        <th>Concept Deduction Code</th>
                        <th>Result Calculation</th>
                    </tr>
                </thead>
                <tbody>
            """
            current_range = None

            for rtefte in obj_rtefte:
                for deduction in sorted(rtefte.deduction_retention, key=lambda x: x.concept_deduction_order):
                    # Verificar si la deducción ya fue procesada
                    if deduction.concept_deduction_code in processed_deductions:
                        continue
                    processed_deductions[deduction.concept_deduction_code] = True

                    # Encuentra el rango actual
                    for r, title in ranges.items():
                        if r[0] <= deduction.concept_deduction_order <= r[1]:
                            if current_range != r:
                                html_report += f"""
                                <tr>
                                    <td colspan="2" style="text-align:center; background-color: #f2f2f2;">{title}</td>
                                </tr>
                                """
                                current_range = r
                            break

                    # Agrega el registro actual
                    html_report += f"""
                    <tr>
                        <td>{deduction.concept_deduction_code}</td>
                        <td>${deduction.result_calculation:,.2f}</td>
                    </tr>
                    """

            html_report += """
                </tbody>
            </table>
            """

            self.resulados_rt = html_report
            self.rtefte_id = rtefte.id
        # Agregar reglas no aplicadas
        not_lines = [(0, 0, not_line) for not_line in result_not.values()]
        self.not_line_ids = not_lines
        #Retornar resultado final de la liquidación de nómina
        if inherit_vacation != 0 or inherit_prima != 0:
            return result            
        elif inherit_contrato_dev != 0 or inherit_contrato_ded != 0:  
            return localdict,result
        else:
            result_finally = {**result, **result_vac, **result_vac_l, **result_intcesantias, **result_prima}
            return result_finally.values()

    @api.depends('line_ids.total')
    def _compute_basic_net(self):
        line_values = (self._origin)._get_line_values(['BASIC', 'BASIC002', 'BASIC003', 'GROSS',  'TOTALDEV', 'NET'])
        for payslip in self:
            payslip.basic_wage = line_values['BASIC'][payslip._origin.id]['total'] + line_values['BASIC002'][payslip._origin.id]['total'] + line_values['BASIC003'][payslip._origin.id]['total']
            payslip.gross_wage = line_values['GROSS'][payslip._origin.id]['total'] + line_values['TOTALDEV'][payslip._origin.id]['total']
            payslip.net_wage = line_values['NET'][payslip._origin.id]['total']


    def _get_payslip_lines_cesantias(self,inherit_contrato=0,localdict=None):
        def _sum_salary_rule_category(localdict, category, amount):
            if category.parent_id:
                localdict = _sum_salary_rule_category(localdict, category.parent_id, amount)
            localdict['categories'].dict[category.code] = localdict['categories'].dict.get(category.code, 0) + amount
            return localdict

        def _sum_salary_rule(localdict, rule, amount):
            localdict['rules_computed'].dict[rule.code] = localdict['rules_computed'].dict.get(rule.code, 0) + amount
            return localdict
        date_cesantias = self.contract_id.date_start
        round_payroll = bool(self.env['ir.config_parameter'].sudo().get_param('lavish_hr_payroll.round_payroll')) or False
        self.ensure_one()
        result = {}
        rules_dict = {}
        worked_days_dict = {line.code: line for line in self.worked_days_line_ids if line.code}
        inputs_dict = {line.code: line for line in self.input_line_ids if line.code}
        cesantias_salary_take = bool(self.env['ir.config_parameter'].sudo().get_param('lavish_hr_payroll.cesantias_salary_take')) or False

        employee = self.employee_id
        contract = self.contract_id
        ctx = self._context or {}
        if contract.modality_salary == 'integral' or contract.contract_type == 'aprendizaje' or contract.subcontract_type == 'obra_integral' and inherit_contrato == 0:
            return localdict, result
        if contract.modality_salary == 'integral' or contract.contract_type == 'aprendizaje' or contract.subcontract_type == 'obra_integral':
            return result.values()

        year = self.date_liquidacion.year or  self.date_from.year
        annual_parameters = self.env['hr.annual.parameters'].search([('year', '=', int(year))])
        date_from = self.date_from
        date_to = self.date_to
        start_period = date_from.replace(day=1)
        date_to = self.date_to
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
        
        wage = contract.wage
        obj_wage = self.env['hr.contract.change.wage'].search([('contract_id', '=', contract.id), ('date_start', '<', date_to)])
        for change in sorted(obj_wage, key=lambda x: x.date_start):
            if float(change.wage) > 0:
                wage = change.wage 
            else:    
                wage = contract.wage
        if wage <= 0:
            raise UserError('El sueldo no puede ser igual a 0 o menor')
        date_from_time = datetime.combine(date_from, datetime.min.time())
        date_to_time = datetime.combine(date_to, datetime.max.time())
        year = self.date_from.year
        annual_parameters = self.env['hr.annual.parameters'].search([('year', '=', year)])
        leaves = {}
        if localdict == None:
            localdict = {
                **self._get_base_local_dict(),
                **{
                    'categories': BrowsableObject(employee.id, {}, self.env),
                    'rules_computed': BrowsableObject(employee.id, {}, self.env),
                    'rules': BrowsableObject(employee.id, rules_dict, self.env),
                    'payslip': Payslips(employee.id, self, self.env),
                    'worked_days': WorkedDays(employee.id, worked_days_dict, self.env),
                    'result_rules': ResultRules(employee.id, {}, self.env),
                    'result_rules_co': ResultRules_co(employee.id, {}, self.env),
                    'inputs': InputLine(employee.id, inputs_dict, self.env),
                    'leaves':  BrowsableObject(employee.id, leaves, self.env),                       
                    'employee': employee,
                    'contract': contract,
                    'slip': self,
                    'wage':wage,
                    'annual_parameters': annual_parameters,
                    'inherit_contrato':inherit_contrato,   
                    'values_base_cesantias': 0,
                    'values_base_int_cesantias': 0,   
                    'id_contract_concepts':0,
                    'date_to_time':date_to_time,
                    'date_from_time':date_from_time,
                    'payslips_month':payslips_month,                
                }
            }
        else:
            localdict.update({
                'date_to_time':date_to_time,
                'date_from_time':date_from_time,
                'payslips_month':payslips_month,     
                'slip': self,
                'wage':wage,
                'result_rules': ResultRules(employee.id, {}, self.env),
                'result_rules_co': ResultRules_co(employee.id, {}, self.env),
                'inherit_contrato':inherit_contrato,})        
        result_rules_dict_co = localdict['result_rules_co'].dict
        date_ref = self.date_to - relativedelta(years=1)
        date_ces = date_ref.replace(month=1, day=1)
        date_ces_to = date_ref.replace(month=12, day=31)
        if date_ces < contract.date_start:
            date_ces = contract.date_start
        self.date_cesantias = date_ces
        #Ejecutar las reglas salariales y su respectiva lógica
        for rule in sorted(self.struct_id.rule_ids, key=lambda x: x.sequence):
            localdict.update({                
                'result': None,
                'result_qty': 1.0,
                'result_rate': 100})
            if rule._satisfy_condition(localdict) or rule.code == 'CESANTIAS' or rule.code == 'INTCESANTIAS':                
                amount, qty, rate, name,log,prima_data  = rule._compute_rule(localdict)
                tot_rule = round(amount * qty * rate / 100.0,0)
                if not round_payroll:
                    amount = round(amount,0) 
                entity_cesantias = False
                if rule.code == 'CESANTIAS':
                    for entity in self.employee_id.social_security_entities:
                        if entity.contrib_id.type_entities == 'cesantias':
                            entity_cesantias = entity.partner_id

                previous_amount = rule.code in localdict and localdict[rule.code] or 0.0

                if (rule.code == 'CESANTIAS' or rule.code == 'INTCESANTIAS'): 
                    tot_rule = amount 
                if not round_payroll:
                    tot_rule = round(tot_rule,0) 
                tot_rule += previous_amount
                localdict[rule.code] = tot_rule
                rules_dict[rule.code] = rule
                localdict = _sum_salary_rule_category(localdict, rule.category_id, tot_rule - previous_amount) 
                localdict = _sum_salary_rule(localdict, rule, tot_rule)
                # create/overwrite the rule in the temporary results
                if amount != 0 and  (rule.code == 'CESANTIAS' or rule.code == 'INTCESANTIAS'):                       
                    result[rule.code] = {
                        'sequence': rule.sequence,
                        'code': rule.code,
                        'name': name or rule.name,
                       # 'note': log or rule.note,
                        'salary_rule_id': rule.id,
                        'contract_id': contract.id,
                        'employee_id': employee.id,
                        'amount_base': prima_data['base'],
                        'amount': amount,
                        'quantity': prima_data['days'],
                        'rate': rate,
                        'subtotal':amount,
                        'total': tot_rule,
                        'days_unpaid_absences':prima_data['susp'],
                        'slip_id': self.id,
                    }
                if amount != 0 or rule.code != 'CESANTIAS' or rule.code != 'INTCESANTIAS':                        
                    result[rule.code] = {
                        'sequence': rule.sequence,
                        'code': rule.code,
                        'name': name or rule.name,
                       # 'note': log or rule.note,
                        'salary_rule_id': rule.id,
                        'contract_id': contract.id,
                        'employee_id': employee.id,
                        #'amount_base': prima_data['base'],
                        'amount': amount,
                        'quantity': qty,
                        'rate': rate,
                        'subtotal':amount,
                        'total': tot_rule,
                        #'days_unpaid_absences':prima_data['susp'],
                        'slip_id': self.id,
                    }

                # Historico de cesantias/int.cesantias a tener encuenta
                for payments in self.severance_payments_reverse:
                    if rule.code == 'CESANTIAS' and payments.type_history in ('cesantias','all'):
                        previous_amount = rule.code in localdict and localdict[rule.code] or 0.0
                        # set/overwrite the amount computed for this rule in the localdict
                        tot_rule = payments.severance_value + previous_amount
                        localdict[rule.code] = tot_rule
                        rules_dict[rule.code] = rule
                        # sum the amount for its salary category
                        localdict = _sum_salary_rule_category(localdict, rule.category_id, tot_rule - previous_amount)
                        localdict = _sum_salary_rule(localdict, rule, tot_rule)
                        # create/overwrite the rule in the temporary results
                        if amount != 0:
                            result['His_'+str(payments.id)+'_'+rule.code] = {
                                'sequence': rule.sequence,
                                'code': rule.code,
                                'name': rule.name + ' ' + str(payments.final_accrual_date.year),
                               # 'note': rule.note,
                                'salary_rule_id': rule.id,
                                'contract_id': contract.id,
                                'employee_id': employee.id,
                                'amount_base': payments.base_value,
                                'amount': payments.severance_value,
                                'quantity': 1,
                                'rate': 100,
                                'subtotal':(amount * qty) * rate / 100,
                                'total': tot_rule,
                                'entity_id': entity_cesantias.id if entity_cesantias != False else entity_cesantias,
                                'slip_id': self.id,
                                'is_history_reverse': True,
                            }
                    if rule.code == 'INTCESANTIAS' and payments.type_history in ('intcesantias','all'):
                        previous_amount = rule.code in localdict and localdict[rule.code] or 0.0
                        # set/overwrite the amount computed for this rule in the localdict
                        tot_rule = payments.severance_interest_value + previous_amount
                        localdict[rule.code] = tot_rule
                        rules_dict[rule.code] = rule
                        # sum the amount for its salary category
                        localdict = _sum_salary_rule_category(localdict, rule.category_id, tot_rule - previous_amount)
                        localdict = _sum_salary_rule(localdict, rule, tot_rule)
                        # create/overwrite the rule in the temporary results
                        if amount != 0:
                            result['His_' + str(payments.id) + '_' + rule.code] = {
                                'sequence': rule.sequence,
                                'code': rule.code,
                                'name': rule.name + ' ' + str(payments.final_accrual_date.year),
                              #  'note': rule.note,
                                'salary_rule_id': rule.id,
                                'contract_id': contract.id,
                                'employee_id': employee.id,
                                'amount_base': payments.base_value if payments.type_history == 'intcesantias' else payments.severance_value,
                                'amount': payments.severance_interest_value,
                                'quantity': 1,
                                'rate': 100,
                                'subtotal':(amount * qty),
                                'total': tot_rule,
                                'entity_id': entity_cesantias.id if entity_cesantias != False else entity_cesantias,
                                'slip_id': self.id,
                                'is_history_reverse': True,
                            }

        
        if inherit_contrato == 0:
            return result.values()  
        else:
            return localdict,result  
            #Vacaciones

    def action_payslip_done(self):
        #res = super(Hr_payslip, self).action_payslip_done()
        if any(slip.state == 'cancel' for slip in self):
            raise ValidationError(_("You can't validate a cancelled payslip."))
        self.write({'state' : 'done', })
        self.mapped('payslip_run_id').action_close()
        pay_vacations_in_payroll = bool(self.env['ir.config_parameter'].sudo().get_param(
            'lavish_hr_payroll.pay_vacations_in_payroll')) or False
        
         
        #Contabilización
        self._action_create_account_move()
        #Actualizar en la tabla de prestamos la cuota pagada

        for record in self:
            for line in record.input_line_ids:
                if line.loan_line_id:
                    line.loan_line_id.paid = True
                    line.loan_line_id.payslip_id = record.id
                    line.loan_line_id.loan_id._compute_loan_amount()
            obj_payslip_line = self.env['hr.payslip.line'].search([('slip_id', '=', record.id),('loan_id', '!=', False)])
            for payslip_line in obj_payslip_line:
                obj_loan_line = self.env['hr.loans.line'].search([('employee_id', '=', payslip_line.employee_id.id),('prestamo_id', '=', payslip_line.loan_id.id),
                                                                    ('date','>=',record.date_from),('date','<=',record.date_to)])
                data = {
                    'paid':True,
                    'payslip_id': record.id
                }
                obj_loan_line.write(data)
                
                obj_loan = self.env['hr.loans'].search([('employee_id', '=', payslip_line.employee_id.id),('id', '=', payslip_line.loan_id.id)])
                if obj_loan.balance_amount <= 0:
                    self.env['hr.contract.concepts'].search([('loan_id', '=', payslip_line.loan_id.id)]).write({'state':'cancel'})

            if record.struct_id.process == 'vacaciones' or (pay_vacations_in_payroll == True and record.struct_id.process != 'contrato'):
                history_vacation = []
                for line in sorted(record.line_ids.filtered(lambda filter: filter.initial_accrual_date), key=lambda x: x.initial_accrual_date):                
                    if line.code == 'VACDISFRUTADAS':
                        info_vacation = {
                            'employee_id': record.employee_id.id,
                            'contract_id': record.contract_id.id,
                            'initial_accrual_date': line.initial_accrual_date,
                            'final_accrual_date': line.final_accrual_date,
                            'departure_date': record.date_from if not line.vacation_departure_date else line.vacation_departure_date,
                            'return_date': record.date_to if not line.vacation_return_date else line.vacation_return_date,
                            'business_units': line.business_units + line.business_31_units,
                            'value_business_days': line.business_units * line.amount,
                            'holiday_units': line.holiday_units + line.holiday_31_units,
                            'holiday_value': line.holiday_units * line.amount,                            
                            'base_value': line.amount_base,
                            'total': (line.business_units * line.amount)+(line.holiday_units * line.amount),
                            'payslip': record.id,
                            'leave_id': False if not line.vacation_leave_id else line.vacation_leave_id.id
                        }
                    if line.code == 'VACREMUNERADAS':
                        info_vacation = {
                            'employee_id': record.employee_id.id,
                            'contract_id': record.contract_id.id,
                            'initial_accrual_date': line.initial_accrual_date,
                            'final_accrual_date': line.final_accrual_date,
                            'departure_date': record.date_from,
                            'return_date': record.date_to,                            
                            'units_of_money': line.quantity,
                            'money_value': line.total,
                            'base_value_money': line.amount_base,
                            'total': line.total,
                            'payslip': record.id
                        }
                    if line.code == 'VACATIONS_MONEY':
                        info_vacation = {
                            'employee_id': record.employee_id.id,
                            'contract_id': record.contract_id.id,
                            'initial_accrual_date': line.initial_accrual_date,
                            'final_accrual_date': line.final_accrual_date,
                            'departure_date': record.date_from,
                            'return_date': record.date_to,                            
                            'units_of_money': line.quantity,
                            'money_value': line.total,
                            'base_value_money': line.amount_base,
                            'total': line.total,
                            'payslip': record.id
                        }

                    if pay_vacations_in_payroll == True:
                        #Si el historico ya existe no vuelva a crearlo
                        obj_history_vacation_exists = self.env['hr.vacation'].search([('employee_id','=',record.employee_id.id),
                                                                                      ('contract_id','=',record.contract_id.id),
                                                                                      ('initial_accrual_date','=',line.initial_accrual_date),
                                                                                      ('final_accrual_date','=',line.final_accrual_date),
                                                                                      ('leave_id','=',line.vacation_leave_id.id)])
                        if len(obj_history_vacation_exists) == 0:
                            history_vacation.append(info_vacation)
                    else:
                        history_vacation.append(info_vacation)

                if history_vacation: 
                    for history in history_vacation:
                        self.env['hr.vacation'].create(history) 

            if record.struct_id.process == 'cesantias' or record.struct_id.process == 'intereses_cesantias':
                his_cesantias = {}         
                his_intcesantias = {}

                for line in record.line_ids:                
                    #Historico cesantias                
                    if line.code == 'CESANTIAS' and line.is_history_reverse == False:
                        his_cesantias = {
                            'employee_id': record.employee_id.id,
                            'contract_id': record.contract_id.id,
                            'type_history': 'cesantias',
                            'initial_accrual_date': record.date_from,
                            'final_accrual_date': record.date_to,
                            'settlement_date': record.date_to,                        
                            'time': line.quantity,
                            'base_value':line.amount_base,
                            'severance_value': line.total,                        
                            'payslip': record.id
                        }             

                    if line.code == 'INTCESANTIAS' and line.is_history_reverse == False:
                        his_intcesantias = {
                            'employee_id': record.employee_id.id,
                            'contract_id': record.contract_id.id,
                            'type_history': 'intcesantias',
                            'initial_accrual_date': record.date_from,
                            'final_accrual_date': record.date_to,
                            'settlement_date': record.date_to,
                            'time': line.quantity,
                            'base_value': line.amount_base,
                            'severance_interest_value': line.total,
                            'payslip': record.id
                        }

                info_cesantias = {**his_cesantias,**his_intcesantias}        
                if info_cesantias:
                    self.env['hr.history.cesantias'].create(info_cesantias) 

            if record.struct_id.process == 'prima':            
                for line in record.line_ids:                
                    if line.code == 'PRIMA':
                        his_prima = {
                            'employee_id': record.employee_id.id,
                            'contract_id': record.contract_id.id,
                            'initial_accrual_date': record.date_from,
                            'final_accrual_date': record.date_to,
                            'settlement_date': record.date_to,  
                            'time': line.quantity,
                            'base_value':line.amount_base,
                            'bonus_value': line.total,                        
                            'payslip': record.id                      
                        }
                        self.env['hr.history.prima'].create(his_prima) 

            if record.struct_id.process == 'contrato' or record.struct_id.process == 'nomina':  
                his_cesantias = {}         
                his_intcesantias = {}

                for line in record.line_ids:                                
                    #Historico vacaciones
                    if line.code == 'VACCONTRATO':
                        info_vacation = {
                            'employee_id': record.employee_id.id,
                            'contract_id': record.contract_id.id,
                            'initial_accrual_date': line.initial_accrual_date,
                            'final_accrual_date': line.final_accrual_date,
                            'departure_date': record.date_liquidacion,
                            'return_date': record.date_liquidacion,                            
                            'units_of_money': (line.quantity*15)/360,
                            'money_value': line.total,
                            'base_value_money': line.amount_base,
                            'total': line.total,
                            'payslip': record.id
                        }
                        self.env['hr.vacation'].create(info_vacation) 
                    
                    #Historico prima
                    if line.code == 'PRIMA':
                        his_prima = {
                            'employee_id': record.employee_id.id,
                            'contract_id': record.contract_id.id,
                            'initial_accrual_date': record.date_prima,
                            'final_accrual_date': record.date_liquidacion,
                            'settlement_date': record.date_liquidacion,  
                            'time': line.quantity,
                            'base_value':line.amount_base,
                            'bonus_value': line.total,                        
                            'payslip': record.id                      
                        }
                        self.env['hr.history.prima'].create(his_prima) 

                    #Historico cesantias                
                    if line.code == 'CESANTIAS' and line.is_history_reverse == False:
                        his_cesantias = {
                            'employee_id': record.employee_id.id,
                            'contract_id': record.contract_id.id,
                            'initial_accrual_date': record.date_cesantias,
                            'final_accrual_date': record.date_liquidacion,
                            'settlement_date': record.date_liquidacion,                        
                            'time': line.quantity,
                            'base_value':line.amount_base,
                            'severance_value': line.total,                        
                            'payslip': record.id
                        }               

                    if line.code == 'INTCESANTIAS' and line.is_history_reverse == False:
                        his_intcesantias = {
                            'severance_interest_value': line.total,
                        }

                info_cesantias = {**his_cesantias,**his_intcesantias}        
                if info_cesantias:
                    self.env['hr.history.cesantias'].create(info_cesantias) 

                if record.struct_id.process == 'contrato':
                    obj_contrato = self.env['hr.contract'].search([('id','=',record.contract_id.id)])
                    values_update = {'retirement_date':record.date_liquidacion,
                                    'state':'close'}
                    obj_contrato.write(values_update) 

        #return res

            #Validar Historico de cesantias/int.cesantias a tener encuenta
            #Una vez confirmado va a la liquidacion asociado y deja en 0 el valor de CESANTIAS y INT CESANTIAS
            #Para evitar la duplicidad de los valores ya que fueron heredados a esta liquidación
            for payments in record.severance_payments_reverse:
                if payments.payslip:
                    value_cesantias = 0
                    value_intcesantias = 0
                    for line in payments.payslip.line_ids:
                        if line.code == 'CESANTIAS':
                            value_cesantias = line.total
                            line.write({'amount':0})
                        if line.code == 'INTCESANTIAS':
                            value_intcesantias = line.total
                            line.write({'amount':0})
                        if line.code == 'NET':
                            amount = line.total - (value_cesantias+value_intcesantias)
                            line.write({'amount':amount})

                    if payments.payslip.observation:
                        payments.payslip.write({'observation':payments.payslip.observation+ '\n El valor se trasladó a la liquidación '+ record.number+' de '+record.struct_id.name })
                    else:
                        payments.payslip.write({'observation': 'El valor se trasladó a la liquidación ' + record.number + ' de ' + record.struct_id.name})




class HrPayslipDay(models.Model):
    _name = 'hr.payslip.day'
    _description = 'Días de Nómina'
    _order = 'day'

    payslip_id = fields.Many2one(comodel_name='hr.payslip', string='Nómina', required=True,ondelete='cascade')
    day_type = fields.Selection(string='Tipo', selection=DAY_TYPE)
    day = fields.Integer(string='Día')
    name = fields.Char(string='Nombre', compute="_compute_name")
    subtotal =  fields.Float('Subtotal')
    @api.depends('day', 'day_type')
    def _compute_name(self):
        for record in self:
            record.name = str(record.day) + record.day_type
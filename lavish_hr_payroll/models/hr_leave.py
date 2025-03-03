from odoo import api, fields, models, SUPERUSER_ID, tools, _
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tools import float_compare
from odoo.osv import expression
from datetime import datetime, timedelta, date
from calendar import monthrange
from dateutil.relativedelta import relativedelta
from collections import defaultdict

from odoo.osv.expression import AND
from odoo.tools import format_date
from operator import itemgetter
import pytz
STATE = [
    ('validated', 'Validada'),
    ('paid', 'Pagada')
]




class HrWorkEntryType(models.Model):    
    _inherit = "hr.work.entry.type"
    
    deduct_deductions = fields.Selection([('all', 'Todas las deducciones'),
                                          ('law', 'Solo las deducciones de ley')],'Tener en cuenta al descontar', default='all')    #Vacaciones
    not_contribution_base = fields.Boolean(string='No es base de aportes',help='Este tipo de ausencia no es base para seguridad social')
    short_name = fields.Char(string='Nombre corto/reportes')

class HolidaysRequest(models.Model):    
    _inherit = "hr.leave"



    sequence = fields.Char('Numero')
    employee_identification = fields.Char('Identificación empleado')
    branch_id = fields.Many2one(related='employee_id.branch_id', string='Sucursal', store=True)
    unpaid_absences = fields.Boolean(related='holiday_status_id.unpaid_absences', string='Ausencia no remunerada',store=True)
    discounting_bonus_days = fields.Boolean(related='holiday_status_id.discounting_bonus_days', string='Descontar días en prima',store=True,tracking=True)
    contract_id = fields.Many2one(comodel_name='hr.contract', string='Contrato', compute='_inverse_get_contract',store=True)
    #Campos para vacaciones
    is_vacation = fields.Boolean(related='holiday_status_id.is_vacation', string='Es vacaciones',store=True)
    business_days = fields.Integer(string='Días habiles')
    holidays = fields.Integer(string='Días festivos')
    days_31_business = fields.Integer(string='Días 31 habiles', help='Este día no se tiene encuenta para el calculo del pago pero si afecta su historico de vacaciones.')
    days_31_holidays = fields.Integer(string='Días 31 festivos', help='Este día no se tiene encuenta para el calculo del pago ni afecta su historico de vacaciones.')
    alert_days_vacation = fields.Boolean(string='Alerta días vacaciones')
    accumulated_vacation_days = fields.Float(string='Días acumulados de vacaciones')
    #Creación de ausencia
    type_of_entity = fields.Many2one('hr.contribution.register', 'Tipo de Entidad',tracking=True)
    entity = fields.Many2one('hr.employee.entities', 'Entidad',tracking=True)
    diagnostic = fields.Many2one('hr.leave.diagnostic', 'Diagnóstico',tracking=True)
    radicado = fields.Char('Radicado #',tracking=True)
    is_recovery = fields.Boolean('Es recobro',tracking=True)
    evaluates_day_off = fields.Boolean('Evalúa festivos')
    apply_day_31 = fields.Boolean(string='Aplica día 31')
    discount_rest_day = fields.Boolean(string='Descontar día de descanso')
    payroll_value = fields.Float('Valor a pagado',tracking=True)
    ibc = fields.Float('IBC',tracking=True)
    force_ibc = fields.Boolean('Forzar IBC ausencia',tracking=True)
    force_porc = fields.Float('Forzar Porcentaje',tracking=True)
    leave_ids = fields.One2many('hr.absence.days', 'leave_id', string='Novedades', readonly=True)
    line_ids = fields.One2many(comodel_name='hr.leave.line', inverse_name='leave_id', readonly=True, string='Lineas de Ausencia')
    eps_value = fields.Float('Valor pagado por la EPS',tracking=True)
    payment_date = fields.Date ('Fecha de pago',tracking=True)
    # Campos fecha real
    date_real_from = fields.Date('Fecha real desde',tracking=True)
    date_real_to = fields.Date('Fecha real hasta',tracking=True)
    real_number_of_days = fields.Integer('Duración real (Días)', compute='_onchange_real_leave_dates')
    qty_extension = fields.Integer('Prorrogas',tracking=True,default=0)
    #Prorroga
    leave_extension_ids = fields.One2many('lavish.hr.leave.extension.wizard', 'leave_id', 'Prorroga')
    payroll_value_with_extension = fields.Float('Valor pagado en nómina con prorrogas', compute='get_values_with_extension', store=True, tracking=True)
    eps_value_with_extension = fields.Float('Valor pagado por la EPS  con prorrogas', compute='get_values_with_extension', store=True, tracking=True)
    is_extension = fields.Boolean(string='Es prórroga', default=False)
    extension_id = fields.Many2one(
        comodel_name='hr.leave',
        domain="[('state', '=', 'validate'),('holiday_status_id', '=', holiday_status_id), ('employee_id', '=', employee_id),]",
        string='Prórroga')
    payroll_id = fields.Many2one('hr.payslip')
    days_used = fields.Float(string='Dias a usar',compute="_days_used")

#####################
    state = fields.Selection([
        ('draft', 'Borrador'),
        ('confirm', 'Confirmada'),
        ('validate', 'Validada'),
        ('refuse', 'Rechazada'),
        ('cancel', 'Cancelada'),
        ('paid', 'Pagada'),
        ('validate1', 'Segunda Validacion'),
    ], string='Estado', readonly=True, default='draft')
    approve_date = fields.Datetime('Aprobación', readonly=True,
                                   states={'draft': [('readonly', False)], 'confirm': [('readonly', False)]})
    payed_vac = fields.Float('Vacaciones en dinero')
    special_vac_base = fields.Boolean('Disfrutadas con todo')
#####################
    def action_draft(self):
        [record._clean_leave() for record in self]
        return super(HolidaysRequest, self).action_draft()


    @api.depends('employee_id','employee_ids','date_from')
    def _inverse_get_contract(self):
        for record in self:
            if not record.employee_id or not record.date_from or not record.date_to:
                record.contract_id = False
                continue
            # Add a default contract if not already defined or invalid
            if record.contract_id and record.employee_id == record.contract_id.employee_id:
                continue
            contracts = record.employee_id._get_contracts(record.date_from.date(), record.date_to.date())
            record.contract_id = contracts[0] if contracts else False

    @api.constrains('date_from', 'date_to', 'employee_id')
    def _check_contract(self):
        for record in self:
            contract_id = self.env['hr.contract'].search([('employee_id', '=', record.employee_id.id),('state', '=', 'open')])
            #if not contract_id:
            #    raise ValidationError('El emplado %s No tiene contratos en proceso' % (record.employee_id.name))
    
    @api.depends('leave_ids', 'leave_ids.days_used')
    def _days_used(self):
        for rec in self:
            rec.days_used += sum(value for value in rec.leave_ids.mapped('days_used') if isinstance(value, (int, float)))
    @api.onchange('ibc','force_ibc', 'number_of_days', 'date_from', 'date_to',)
    def force_ibc_amt(self):
        for record in self:
            if record.force_ibc and record.ibc != 0:
                record.payroll_value = (record.ibc / 30) * record.number_of_days
            else:
                record.get_amount_license()

    @api.onchange('date_from', 'date_to', 'employee_id', 'holiday_status_id', 'number_of_days')
    def get_amount_license(self):
        for record in self:
            contracts = record.env['hr.contract'].search([('employee_id', '=', record.employee_id.id),('state','=','open')])
            ibc = 0.0
            amount = 0.0
            if contracts and self.date_to:
                if record.holiday_status_id.liquidacion_value == 'IBC':
                    ibc = self.GetIBCSLastMonth(self.date_to.date(), contracts) or 0.0
                elif record.holiday_status_id.liquidacion_value == 'WAGE':
                    ibc = self.get_wage_in_date(self.date_to.date(), contracts) or 0.0
                elif record.holiday_status_id.liquidacion_value == 'YEAR':
                    ibc = self.get_average_last_year(contracts) or 0.0
                else:
                    ibc = contracts.wage
                record.payroll_value = (ibc/30) * record.number_of_days
                record.ibc = ibc
                #if record.date_from and record.date_to:
                #    self._prepare_leave_line()
                if record.line_ids:
                    record.payroll_value = sum(x.amount for x in record.line_ids)

    def get_wage_in_date(self,process_date,contracts):
        wage_in_date = contracts.wage
        for change in sorted(contracts.change_wage_ids, key=lambda x: x.date_start):
            if process_date >= change.date_start:
                wage_in_date = change.wage
        return wage_in_date

    def GetIBCSLastMonth(self,date_to,contract_id):
        date_actual = date_to
        month = date_to.month - 1
        year = date_to.year
        if month == 0:
            month = 12
            year -= 1
        day = 30 if month != 2 else 28
        from_date = datetime(year, month, 1).date()
        to_date = datetime(year, month, day).date()
        annual_parameters = self.env['hr.annual.parameters'].search([('year', '=', self.date_to.year)])
        # Find payslip lines for the given code and date range
        PayslipLine = self.env['hr.payslip.line']
        payslip_lines = PayslipLine.search([
            ('slip_id.state', 'in', ['done', 'paid']),
            ('slip_id.contract_id', '=', contract_id.id),
            ('slip_id.date_to', '>', from_date),
            ('slip_id.date_from', '<', to_date),
            #('salary_rule_id.code', '=', code)
        ])
        value_base = 0
        base_40 = 0
        value_base_no_dev = 0
        # Calculate the IBC by summing up the totals of matching payslip lines
        for line in payslip_lines:
            value_base += abs(line.total) if line.salary_rule_id.category_id.code == 'DEV_SALARIAL' or line.salary_rule_id.category_id.parent_id.code == 'DEV_SALARIAL' else 0
            value_base_no_dev += abs(line.total) if line.salary_rule_id.category_id.code == 'DEV_NO_SALARIAL' or line.salary_rule_id.category_id.parent_id.code == 'DEV_NO_SALARIAL' else 0
        gran_total = value_base + value_base_no_dev 
        statute_value = gran_total*(annual_parameters.value_porc_statute_1395/100)
        total_statute = value_base_no_dev-statute_value 
        if total_statute > 0: 
            base_40 = total_statute     
        ibc = value_base + base_40
        # If IBC is not zero, return it
        if ibc:
            return ibc
        # Check for custom IBC (u_ibc) on the contract, if it matches the IBC date
        if contract_id.fecha_ibc and from_date.year == contract_id.fecha_ibc.year and from_date.month == contract_id.fecha_ibc.month:
            return contract_id.u_ibc
        # If no IBC is found, return the contract's wage
        return contract_id.wage

    def days360(self, start_date, end_date):
        s1, e1 =  start_date , end_date + timedelta(days=1)
        s360 = (s1.year * 12 + s1.month) * 30 + s1.day
        e360 = (e1.year * 12 + e1.month) * 30 + e1.day
        res = divmod(e360 - s360, 30)
        return ((res[0] * 30) + res[1]) or 0

    def get_average_last_year(self, contract):
        if self.date_to and self.date_from:
            date_to = self.date_to.date() 
            first_day_of_current_month = date_to.replace(day=1)
            last_day_of_previous_month = first_day_of_current_month - timedelta(days=1)
            to_date = last_day_of_previous_month 
            date_start = date_to + relativedelta(months=-11)
            date_from = date(date_start.year,date_start.month,1)
            initial_process_date = contract.date_start
            initial_process_date = initial_process_date if date_from < initial_process_date else date_from
            wage = 0
            payslips = self.env['hr.payslip.line'].search([('date_from','>=',date_from),('date_from','<',to_date),('employee_id', '=', contract.employee_id.id),('category_id.code','in', ('DEV_SALARIAL', 'COMISIONES', 'INCAPACIDAD', 'LICENCIA_MATERNIDAD', 'AUS', 'HEYREC'))], order="date_from desc")
            hr_accumula = self.env['hr.accumulated.payroll'].search([('date','>=',date_from),('date','<',to_date),('employee_id', '=', contract.employee_id.id),('salary_rule_id.category_id.code','in', ('DEV_SALARIAL', 'COMISIONES', 'INCAPACIDAD', 'LICENCIA_MATERNIDAD', 'AUS', 'HEYREC'))], order="date desc")
            obj_wage = self.env['hr.contract.change.wage'].search([('contract_id', '=', contract.id), ('date_start', '>=', initial_process_date), ('date_start', '<=', to_date)])
            dias_trabajados = self.dias360(initial_process_date, to_date)
            dias_ausencias =  sum([i.number_of_days for i in self.env['hr.leave'].search([('date_from','>=',initial_process_date),('date_to','<=',to_date),('state','=','validate'),('employee_id','=',self.employee_id.id),('unpaid_absences','=',True)])])
            dias_ausencias += sum([i.days for i in self.env['hr.absence.history'].search([('star_date', '>=', initial_process_date), ('end_date', '<=', to_date),('employee_id', '=', self.employee_id.id),('leave_type_id.unpaid_absences', '=', True)])])
            dias_liquidacion = dias_trabajados - dias_ausencias
            if len(obj_wage) > 0:
                wage_average = 0
                while initial_process_date <= to_date:
                    if initial_process_date.day != 31:
                        if initial_process_date.month == 2 and  initial_process_date.day == 28 and (initial_process_date + timedelta(days=1)).day != 29:
                            wage_average += (contract.get_wage_in_date(initial_process_date) / 30)*3
                        elif initial_process_date.month == 2 and initial_process_date.day == 29:
                            wage_average += (contract.get_wage_in_date(initial_process_date) / 30)*2
                        else:
                            wage_average += contract.get_wage_in_date(initial_process_date)/30
                    initial_process_date = initial_process_date + timedelta(days=1)
                if dias_trabajados != 0:
                    wage = contract.wage if wage_average == 0 else (wage_average/dias_trabajados)*30
                else:
                    wage = 0
            amount=0
            
            if payslips:
                for payslip in payslips:
                    amount += payslip.total
                if hr_accumula:
                    for hr in hr_accumula:
                        amount += hr.amount
                return ((amount+((wage/30)*dias_liquidacion))/dias_liquidacion)*30
            else:
                return 0
            date_to = self.date_from.date() - relativedelta(months=1)
            date_to = date_to.replace(day=monthrange(date_to.year, date_to.month)[1])
            date_from = date_to.replace(day=1) - relativedelta(years=1)
            if contract.date_start > date_from:
                date_from = contract.date_start

            payslip_lines = self.env['hr.payslip.line'].sudo()
            accumulated_payroll = self.env['hr.accumulated.payroll'].sudo()
            leaves = self.env['hr.leave']
            absence_history = self.env['hr.absence.history']
            average_parcial = 1
            dias_total = 1
            # Consulta 1
            average_nove = payslip_lines.search([
                ('date_from', '>=', date_from),
                ('category_id.code', 'in', ('DEV_SALARIAL', 'COMISIONES', 'INCAPACIDAD', 'LICENCIA_MATERNIDAD', 'AUS', 'HEYREC')),
                ('date_to', '<', date_to),
                ('employee_id', '=', contract.employee_id.id)
            ], order="date_from desc")

            if not average_nove:
                # Consulta 2 desde la fecha inicial
                average_acumulado = accumulated_payroll.search([
                    ('date', '>=', date_from),
                    ('salary_rule_id.category_id.code', 'in', ('DEV_SALARIAL', 'COMISIONES', 'INCAPACIDAD', 'LICENCIA_MATERNIDAD', 'AUS', 'HEYREC')),
                    ('date', '<', date_to),
                    ('employee_id', '=', contract.employee_id.id)
                ], order="date desc")
            else:
                # Consulta 2 desde el último date_to de la consulta 1
                average_acumulado = accumulated_payroll.search([
                    ('date', '>=', average_nove[-1].date_to),
                    ('salary_rule_id.category_id.code', 'in', ('DEV_SALARIAL', 'COMISIONES', 'INCAPACIDAD', 'LICENCIA_MATERNIDAD', 'AUS', 'HEYREC')),
                    ('date', '<', date_to),
                    ('employee_id', '=', contract.employee_id.id)
                ], order="date desc")

            average = self.get_wage_in_date(date_to, contract)
            days = self.days360(date_from, date_to)

            # Cálculo de días de ausencias
            leave_ausencias = leaves.search([
                ('date_from', '>=', date_from),
                ('date_to', '<=', date_to),
                ('state', '=', 'validate'),
                ('employee_id', '=', self.employee_id.id),
                ('unpaid_absences', '=', True)
            ])
            dias_ausencias = sum(leave.number_of_days for leave in leave_ausencias)

            absence_histories = absence_history.search([
                ('star_date', '>=', date_from),
                ('end_date', '<=', date_to),
                ('employee_id', '=', self.employee_id.id),
                ('leave_type_id.unpaid_absences', '=', True)
            ])
            dias_ausencias += sum(absence.days for absence in absence_histories)

            dias_total = (days - dias_ausencias)

            average_parcial = sum(category.total for category in average_nove) + sum(category.amount for category in average_acumulado)
            if dias_total == 0 or average_parcial == 0:
                average_end = contract.wage
            else:
                average_end = ((average_parcial / dias_total) * 30) + average or contract.wage
            return average_end 

    @api.onchange('is_extension')
    def _onchange_extension_id(self):
        for rec in self:
            if rec.date_to and rec.is_extension:
                last_leave = self.env['hr.leave'].search([('date_to', '<', rec.date_to),('state', '=', 'validate'),('holiday_status_id','=',rec.holiday_status_id.id),('employee_id','=',rec.employee_id.id)], order='date_to desc', limit=1)
                rec.extension_id = last_leave.id
            else:
                rec.extension_id = False


    @api.onchange('employee_id','holiday_status_id')
    def _onchange_info_entity(self):
        for record in self:
            if record.employee_id and record.holiday_status_id:
                record.type_of_entity = record.holiday_status_id.type_of_entity_association.id
                for entities in record.employee_id.social_security_entities:
                    if entities.contrib_id.id == record.holiday_status_id.type_of_entity_association.id:                        
                        record.entity = entities.partner_id.id
            else:
                record.type_of_entity = False
                record.entity = False
                record.diagnostic = False

    @api.onchange('number_of_days','request_date_from')
    def onchange_number_of_days_vacations(self):   
        for record in self:
            original_number_of_days = record.number_of_days
            if record.holiday_status_id.is_vacation and record.request_date_from:
                lst_days = [5,6] if record.employee_id.sabado == False else [6]
                date_to = record.request_date_from - timedelta(days=1)
                cant_days = record.number_of_days
                holidays = 0
                business_days = 0
                days_31_b = 0
                days_31_h = 0
                while cant_days > 0:
                    date_add = date_to + timedelta(days=1)
                    if not date_add.weekday() in lst_days:
                        obj_holidays = self.env['resource.calendar.leaves'].search([('date_from', '=', date_add)])
                        if obj_holidays:
                            holidays += 1
                            days_31_h += 1 if date_add.day == 31 else 0
                            date_to = date_add
                        else:
                            cant_days = cant_days - 1     
                            business_days += 1
                            days_31_b += 1 if date_add.day == 31 else 0
                            date_to = date_add
                    else:
                        holidays += 1
                        days_31_h += 1 if date_add.day == 31 else 0
                        date_to = date_add                    
                #Guardar calculo en el campo fecha final
                record.business_days = business_days - days_31_b
                record.holidays = holidays - days_31_h
                record.days_31_business = days_31_b
                record.days_31_holidays = days_31_h
                #record.request_date_to = date_to
                days_31 = days_31_b+days_31_h
                #record.number_of_days = (business_days + holidays) - days_31
                #Verficar alerta
                obj_contract = self.env['hr.contract'].search(
                    [('employee_id', '=', record.employee_id.id), ('state', '=', 'open')])
                if not obj_contract:
                #    raise ValidationError(_('El empleado ' + record.employee_id.name + 'No tiene Contracto'))
                    if business_days > obj_contract.get_accumulated_vacation_days():
                        record.accumulated_vacation_days = obj_contract.get_accumulated_vacation_days()
                        record.alert_days_vacation =  True
                    else:
                        record.accumulated_vacation_days = obj_contract.get_accumulated_vacation_days()
                        record.alert_days_vacation = False




    def action_force_paid(self):
        #Validación adjunto
        for holiday in self:
            holiday.line_ids.write({'state': 'paid'})
    def action_confirm(self):
        obj = super(HolidaysRequest, self).action_confirm()
        #Creación registro en el historico de vacaciones cuando es una ausencia no remunerada
        for record in self:
            if not record.line_ids:
                record.compute_holiday()
            record.line_ids.write({'state': 'validated'})
        return obj
    def action_approve(self):
        #Validación adjunto
        for holiday in self:
            # Validacion compañia
            if self.env.company.id != holiday.employee_id.company_id.id:
                raise ValidationError(_('El empleado ' + holiday.employee_id.name + ' esta en la compañía ' + holiday.employee_id.company_id.name + ' por lo cual no se puede aprobar debido a que se encuentra ubicado en la compañía ' + self.env.company.name + ', seleccione la compañía del empleado para aprobar la ausencia.'))
            # Validación adjunto
            if holiday.holiday_status_id.obligatory_attachment:
                attachment = self.env['ir.attachment'].search([('res_model', '=', 'hr.leave'),('res_id','=',holiday.id)])    
                if not attachment:    
                    raise ValidationError(_('Es obligatorio agregar un adjunto para la ausencia '+holiday.display_name+'.'))
            holiday.line_ids.write({'state': 'validated'})
        #Ejecución metodo estandar
        
        obj = super(HolidaysRequest, self).action_approve()
        #Creación registro en el historico de vacaciones cuando es una ausencia no remunerada
        for record in self:
            if not record.line_ids:
                record.compute_holiday()
            if record.unpaid_absences:
                days_unpaid_absences = record.number_of_days
                days_vacation_represent = round((days_unpaid_absences * 15) / 365,0)
                if days_vacation_represent > 0:
                    # Obtener contrato y ultimo historico de vacaciones
                    obj_contract = self.env['hr.contract'].search([('employee_id','=',record.employee_id.id),('state','=','open')])
                    date_vacation = obj_contract.date_start
                    obj_vacation = self.env['hr.vacation'].search(
                        [('employee_id', '=', record.employee_id.id), ('contract_id', '=', obj_contract.id)])
                    if obj_vacation:
                        for history in sorted(obj_vacation, key=lambda x: x.final_accrual_date):
                            date_vacation = history.final_accrual_date + timedelta(
                                days=1) if history.final_accrual_date > date_vacation else date_vacation
                    #Fechas de causación
                    initial_accrual_date = date_vacation
                    final_accrual_date = date_vacation + timedelta(days=days_vacation_represent)

                    info_vacation = {
                        'employee_id': record.employee_id.id,
                        'contract_id': obj_contract.id,
                        'initial_accrual_date': initial_accrual_date,
                        'final_accrual_date': final_accrual_date,
                        'departure_date': record.request_date_from,
                        'return_date': record.request_date_to,
                        'business_units': days_vacation_represent,
                        'leave_id': record.id
                    }
                    self.env['hr.vacation'].create(info_vacation)

        return obj

    def action_refuse(self):
        obj = super(HolidaysRequest, self).action_refuse()
        for record in self:
            self.env['hr.vacation'].search([('leave_id','=',record.id)]).unlink()
        return obj

    def action_validate(self):
        # Validación adjunto
        for holiday in self:
            if holiday.holiday_status_id.obligatory_attachment:
                attachment = self.env['ir.attachment'].search([('res_model', '=', 'hr.leave'), ('res_id', '=', holiday.id)])
                if not attachment:
                    raise ValidationError(_('Es obligatorio agregar un adjunto para la ausencia ' + holiday.display_name + '.'))
            holiday.line_ids.write({'state': 'validated'})
        # Ejecución metodo estandar
        obj = super(HolidaysRequest, self).action_validate()
        return obj

    @api.model
    def create(self, vals):
        vals['sequence'] = self.env['ir.sequence'].next_by_code('seq.hr.leave') or ''
        if vals.get('employee_identification'):
            obj_employee = self.env['hr.employee'].search([('identification_id', '=', vals.get('employee_identification'))])            
            vals['employee_id'] = obj_employee.id
        if vals.get('employee_id'):
            obj_employee = self.env['hr.employee'].search([('id', '=', vals.get('employee_id'))])            
            vals['employee_identification'] = obj_employee.identification_id            
        
        res = super(HolidaysRequest, self).create(vals)
        return res

    def add_extension(self):
        return {
            'context': {'default_leave_id': self.id,
                        'default_date_end': self.request_date_to if self.request_date_to else False,
                        'default_diagnostic_original_id': self.diagnostic.id if self.diagnostic else False,
                        'default_diagnostic_id':self.diagnostic.id if self.diagnostic else False},
            'view_type': 'form',
            'view_mode': 'form',
            'res_model': 'lavish.hr.leave.extension.wizard',
            'type': 'ir.actions.act_window',
            'target': 'new',
        }

    @api.depends('leave_extension_ids','payroll_value','eps_value')
    def get_values_with_extension(self):
        for record in self:
            if len(record.leave_extension_ids) > 0:
                record.payroll_value_with_extension = record.payroll_value + sum([i.payroll_value for i in record.leave_extension_ids])
                record.eps_value_with_extension = record.eps_value + sum([i.eps_value for i in record.leave_extension_ids])
            else:
                record.payroll_value_with_extension = record.payroll_value
                record.eps_value_with_extension = record.eps_value


    def _cancel_work_entry_conflict(self):
        """
        Creates a leave work entry for each hr.leave in self.
        Check overlapping work entries with self.
        Work entries completely included in a leave are archived.
        e.g.:
            |----- work entry ----|---- work entry ----|
                |------------------- hr.leave ---------------|
                                    ||
                                    vv
            |----* work entry ****|
                |************ work entry leave --------------|
        """
        if not self:
            return

        if self.holiday_status_id.novelty in ("vco","sln"):
            return
        # 1. Create a work entry for each leave
        work_entries_vals_list = []
        for leave in self:
            contracts = leave.employee_id.sudo()._get_contracts(leave.date_from, leave.date_to, states=['open', 'close'])
            for contract in contracts:
                # Generate only if it has aleady been generated
                if leave.date_to >= contract.date_generated_from and leave.date_from <= contract.date_generated_to:
                    work_entries_vals_list += contracts._get_work_entries_values(leave.date_from, leave.date_to)

        new_leave_work_entries = self.env['hr.work.entry'].create(work_entries_vals_list)

        if new_leave_work_entries:
            # 2. Fetch overlapping work entries, grouped by employees
            start = min(self.mapped('date_from'), default=False)
            stop = max(self.mapped('date_to'), default=False)
            work_entry_groups = self.env['hr.work.entry'].read_group([
                ('date_start', '<', stop),
                ('date_stop', '>', start),
                ('employee_id', 'in', self.employee_id.ids),
            ], ['work_entry_ids:array_agg(id)', 'employee_id'], ['employee_id', 'date_start', 'date_stop'], lazy=False)
            work_entries_by_employee = defaultdict(lambda: self.env['hr.work.entry'])
            for group in work_entry_groups:
                employee_id = group.get('employee_id')[0]
                work_entries_by_employee[employee_id] |= self.env['hr.work.entry'].browse(group.get('work_entry_ids'))

            # 3. Archive work entries included in leaves
            included = self.env['hr.work.entry']
            overlappping = self.env['hr.work.entry']
            for work_entries in work_entries_by_employee.values():
                # Work entries for this employee
                new_employee_work_entries = work_entries & new_leave_work_entries
                previous_employee_work_entries = work_entries - new_leave_work_entries

                # Build intervals from work entries
                leave_intervals = new_employee_work_entries._to_intervals()
                conflicts_intervals = previous_employee_work_entries._to_intervals()

                # Compute intervals completely outside any leave
                # Intervals are outside, but associated records are overlapping.
                outside_intervals = conflicts_intervals - leave_intervals

                overlappping |= self.env['hr.work.entry']._from_intervals(outside_intervals)
                included |= previous_employee_work_entries - overlappping
            overlappping.write({'leave_id': False})
            included.write({'active': False})

    #############################################################################################
    #GET HR_LEAVE_LINE
    #############################################################################################
    def get_sequence_and_date(self):
        category_type = self.holiday_status_id.novelty
        if category_type in ['ige', 'irl']:
            start = self.date_from
            blacklist = [self.id]
            extension_id = self.extension_id
            while extension_id:
                if extension_id.id in blacklist:
                    raise ValidationError(f'Error de prórroga de si misma, validar extension ausencia {self.name}')
                blacklist.append(extension_id.id)
                start = extension_id.date_from
                extension_id = extension_id.extension_id
            return max([x.sequence for x in self.extension_id.line_ids] + [0]) + 1, start
        else:
            return 1, self.date_from

    def compute_line(self):
        self.compute_holiday()


    def _prepare_leave_line(self):
        if self.date_to and self.date_from:
            
            self.line_ids.unlink()
            annual_parameters = self.env['hr.annual.parameters'].search([('year', '=', self.date_to.year)])
            smmlv = annual_parameters.smmlv_monthly
            owd = annual_parameters.hours_daily
            horas_leave = self.number_of_hours_display
            new_leave_line = []
            date_tmp = self.date_from
            sequence, date_origin = self.get_sequence_and_date()
            type_id = self.holiday_status_id
            unit = type_id.request_unit
            #if not type_id.holiday_status_id:
            #    raise ValidationError('La categoría de la ausencia no tiene tipo')
            amount = self.ibc
            day_count = (self.date_to.date() - self.date_from.date()).days + 1
            smmlv_daily = self.env['hr.annual.parameters'].search([('year', '=', self.date_from.year)]).smmlv_daily
            #self.date_to and self.date_from:
            for day in range(day_count):
                if not (date_tmp.day == 31 and type_id.novelty != 'vco' and not type_id.apply_day_31):
                    if type_id.code == 'EGA' and sequence <= type_id.num_days_no_assume:
                        amount_real = amount / 30
                    elif type_id.novelty == 'irl' and sequence == 1:
                        amount_real = amount / 30
                    else:
                        amount_real = amount * type_id.get_rate_concept_id(sequence)[0] / 30
                    rule = type_id.get_rate_concept_id(sequence)[1] or type_id.eps_arl_input_id.id
                    if 1 <= sequence <= type_id.num_days_no_assume:
                        rule = type_id.company_input_id.id
                    if self.force_porc != 0:
                        amount_real = (amount / 30) * self.force_porc / 100
                    amount_real = max(amount_real,(smmlv/30) )
                    new_leave_line.append((0, 0, {
                        'sequence': sequence,
                        'date': date_tmp,
                        'state': 'validated',
                        'leave_id': self.id,
                        'rule_id': rule,
                        'amount': amount_real,
                        'days_payslip': 1,
                        'hours': owd,
                        
                    }))
                    sequence += 1
                date_tmp += timedelta(days=1)  # Move to the next day

            self.line_ids = new_leave_line
            self.payroll_value = sum(x.amount for x in self.line_ids)

    def _apply_leave_line(self, date_tmp):
        eval_days_off = self.holiday_status_id.evaluates_day_off
        is_day_off = eval_days_off and self.env['lavish.holidays'].search([('date', '=', date_tmp)]) #days_off.is_day_off(date_tmp)
        return not is_day_off and self.contract_id.is_working_day(date_tmp)


    def _clean_leave(self):
        if self.state == 'validated':
            self.line_ids.unlink()

    def _prepare_leave_line_value(self):
        if self.date_to and self.date_from:
            annual_parameters = self.env['hr.annual.parameters'].search([('year', '=', self.date_to.year)])
            smmlv = annual_parameters.smmlv_monthly
            owd = annual_parameters.hours_daily
            horas_leave = self.number_of_hours_display
            
            date_tmp = self.date_from
            type_id = self.holiday_status_id
            unit = type_id.request_unit
            amount = self.ibc
            day_count = (self.date_to.date() - self.date_from.date()).days + 1
            
            for leave_line in self.line_ids.sorted(key=lambda l: l.date):
                if not (leave_line.date.day == 31 and type_id.novelty != 'vco' and not type_id.apply_day_31):
                    sequence = leave_line.sequence
                    
                    if type_id.code == 'EGA' and sequence <= type_id.num_days_no_assume:
                        amount_real = amount / 30
                    elif type_id.novelty == 'irl' and sequence == 1:
                        amount_real = amount / 30
                    else:
                        amount_real = amount * type_id.get_rate_concept_id(sequence)[0] / 30
                    
                    rule = type_id.get_rate_concept_id(sequence)[1] or type_id.eps_arl_input_id.id
                    if 1 <= sequence <= type_id.num_days_no_assume:
                        rule = type_id.company_input_id.id
                    
                    if self.force_porc != 0:
                        amount_real = (amount / 30) * self.force_porc / 100
                    amount_real = max(amount_real,(smmlv/30) )
                    leave_line.write({
                        'amount': amount_real,
                        'rule_id': rule,
                    })
            
            self.payroll_value = sum(x.amount for x in self.line_ids)
            
    #######################
    def compute_holiday(self):
        for holiday in self:
            if not holiday.contract_id:
                raise UserError(_('Error! The leave has no contract assigned.'))
            if not holiday.contract_id.resource_calendar_id:
                raise UserError(_('Error! The contract has no working schedule defined.'))
            aband_type = holiday.holiday_status_id
            employee_id = holiday.employee_id
            calendar = employee_id.resource_calendar_id
            date_from = holiday.date_from
            date_to = holiday.date_to
            annual_parameters = self.env['hr.annual.parameters'].search([('year', '=', self.date_to.year)])
            smmlv = annual_parameters.smmlv_monthly
            working_hours = calendar.get_working_hours_payroll(calendar,date_from,date_to)
            l_lines = []
            lines = {}
            for work in working_hours:
                date_str = work['date']  
                work_date = datetime.strptime(date_str, '%Y-%m-%d').date()
                hours_assigned = work['hours']  
                days_assigned = work['days']  
                if work_date.day == 31 and not aband_type.apply_day_31:
                    continue
                add = {
                    'name': date_str,
                    'date':  date_str,
                    'hours_assigned': hours_assigned,  
                    'days_assigned': 1, 
                    'hours': hours_assigned,  
                    'days_payslip': 1,
                    'day': work['week_day'] 
                }
                lines[date_str] = add
                l_lines.append(add)

            if aband_type.apply_publicholiday:
                for festivo in calendar.leave_ids:
                    date_str = festivo.date_from.strftime('%Y-%m-%d')
                    if date_str in l_lines:
                        lines[date_str]['hours_assigned'] = 0
                        lines[date_str]['days_assigned'] = 0
                        

            l_lines = sorted(l_lines, key=itemgetter('name'))

            if aband_type.discount_rest_day:
                l_day = datetime.strptime(l_lines[-1]['name'], '%Y-%m-%d').date()
                l_kw_day = int(calendar.attendance_ids[-1].dayofweek)
                l_day = l_day + timedelta(days=abs(l_day.weekday() - l_kw_day))
                if len(set([x.dayofweek for x in calendar.attendance_ids])) == 5:
                    for x in range(1, 3):
                        name = l_day + timedelta(days=x)
                        add = {
                            'name': name.strftime('%Y-%m-%d'),
                            'hours_assigned': calendar.hours_per_day,
                            'days_assigned': 1,
                            'hours': calendar.hours_per_day,
                            'days_payslip': 1,
                            'day': str(name.weekday())
                        }
                        l_lines.append(add)
                else:  # 6 days of week
                    name = l_day + timedelta(days=1)
                    add = {
                        'name': name.strftime('%Y-%m-%d'),
                        'hours_assigned': calendar.hours_per_day,
                        'days_assigned': 1,
                        'hours': calendar.hours_per_day,
                        'days_payslip': 1,
                        'day': str(name.weekday())
                    }
                    l_lines.append(add)

            holiday.line_ids.unlink()

            sequence = 0
            if holiday.extension_id:
                last_sequence = holiday.extension_id.line_ids.mapped('sequence')
                if last_sequence:
                    sequence = max(last_sequence)

            for vals in l_lines:
                sequence += 1
                vals.update({'leave_id': holiday.id, 'sequence': sequence})
                self.env['hr.leave.line'].create(vals)
        self._prepare_leave_line_value()

        return True

class hr_leave_diagnostic(models.Model):
    _name = "hr.leave.diagnostic"
    _description = "Diagnosticos Ausencias"

    name = fields.Char('Nombre', required=True)
    code = fields.Char('Código', required=True)

    _sql_constraints = [('leave_diagnostic_code_uniq', 'unique(code)',
                         'Ya existe un diagnóstico con este código, por favor verificar.')]

    def name_get(self):
        result = []
        for record in self:
            result.append((record.id, "{} | {}".format(record.code,record.name)))
        return result

    @api.model
    def _name_search(self, name, args=None, operator='ilike', limit=100, name_get_uid=None):
        args = args or []
        domain = []
        if name:
            domain = ['|', ('name', operator, name), ('code', operator, name)]
        diagnostic_interface = self._search(expression.AND([domain, args]), limit=limit, access_rights_uid=name_get_uid)
        return diagnostic_interface

class lavish_hr_leave_extension_wizard(models.Model):
    _name = 'lavish.hr.leave.extension.wizard'
    _description = 'Agregar prorroga en ausencias'

    leave_id = fields.Many2one('hr.leave',string='Ausencia',required=True)
    date_end = fields.Date(string='Fecha final original', required=True)
    new_date_end = fields.Date(string='Nueva fecha final',required=True)
    diagnostic_original_id = fields.Many2one('hr.leave.diagnostic', 'Diagnóstico Original')
    diagnostic_id = fields.Many2one('hr.leave.diagnostic', 'Nuevo Diagnóstico')
    radicado = fields.Char('Recobro radicado #')
    payroll_value = fields.Float('Valor pagado en nómina')
    eps_value = fields.Float('Valor pagado por la EPS')
    payment_date = fields.Date('Fecha de pago')

    def authorized_extension(self):
        self.leave_id.action_refuse()
        self.leave_id.action_draft()
        self.leave_id.write({'request_date_to':self.new_date_end,
                               'qty_extension':self.leave_id.qty_extension+1,
                               'diagnostic':self.diagnostic_id.id})
        self.leave_id.action_confirm()
        if self.leave_id.state != 'validate':
            self.leave_id.action_approve()

class HrLeaveLine(models.Model):
    _name = 'hr.leave.line'
    _description = 'Lineas de Ausencia'
    _order = 'date desc'

    leave_id = fields.Many2one(comodel_name='hr.leave', string='Ausencia', required=True,ondelete='cascade')
    payslip_id = fields.Many2one(comodel_name='hr.payslip', string='Nónima')
    contract_id = fields.Many2one(string='Contrato', related='leave_id.contract_id')
    rule_id = fields.Many2one('hr.salary.rule', 'Reglas Salarial')
    date = fields.Date(string='Fecha')
    state = fields.Selection(string='Estado', selection=STATE)
    amount = fields.Float(string='Valor')
    days_payslip = fields.Float(string='Dias en nomina')
    hours = fields.Float(string='Hora')
    days_assigned = fields.Float('Dias de asignacion')
    hours_assigned = fields.Float('Horas de asignacion')
    sequence = fields.Integer(string='Secuencia')
    name = fields.Char('Reason', size=128, help='Reason for holiday')
    day = fields.Selection([('0', 'Lunes'),
                            ('1', 'Martes'),
                            ('2', 'Miercoles'),
                            ('3', 'Jueves'),
                            ('4', 'Viernes'),
                            ('5', 'Sabado'),
                            ('6', 'Domingo'),
                            ], 'Dia Semana')
    def create_payslip_line(self, payslip_id):
        leave_type_id = self.leave_id.leave_type_id
        rate, concept_id = leave_type_id.get_rate_concept_id(self.sequence)
        payslip_line = {
            'name': leave_type_id.name,
            'payslip_id': payslip_id,
            'category': leave_type_id.category,
            'value': self.amount,
            'qty': 1 if leave_type_id.category_type != 'VAC_MONEY' else self.leave_id.days_vac_money,
            'rate': rate,
            'total': self.amount,
            'origin': 'local',
            'concept_id': concept_id,
            'leave_id': self.leave_id.id,
            'novelty_id': None,
            'overtime_id': None,
        }
        for unique_key in ['rate', 'concept_id', 'leave_id', 'novelty_id', 'overtime_id']:
            if 'unique_key' in payslip_line:
                payslip_line['unique_key'] += str(payslip_line[unique_key])
            else:
                payslip_line['unique_key'] = str(payslip_line[unique_key])
        return payslip_line

    def belongs_category(self, categories):
        return self.leave_id.leave_type_id.id in categories

    def get_info_from_leave_type(self, cr, data):
        """
        Obtiene el numero de dias de un tipo de ausencia y de un contrato
        @params:
        cr: cursor con el que se va a ejecutar la consulta
        data: diccionario con la siguiente estructura.
            {'contract':int, 'start':datetime, 'end':datetime,'type':tuple(string)}
        """
        query = """
        SELECT COUNT(*), SUM(HLL.amount)
        FROM hr_leave_line AS  HLL
        INNER JOIN hr_leave AS HL ON HL.id = HLL.leave_id
        INNER JOIN hr_leave_type AS HLT ON HLT.id = HL.leave_type_id
        WHERE
            HL.contract_id = %(contract)s AND
            HLL.date BETWEEN %(start)s AND %(end)s AND
            HLT.category_type in %(type)s
        """
        res = orm._fetchall(cr, query, data)
        return sum([x[0] for x in res if x[0]]), sum([x[1] for x in res if x[1]])
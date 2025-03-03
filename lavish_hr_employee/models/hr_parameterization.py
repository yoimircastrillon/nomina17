# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from datetime import datetime, timedelta, date
from dateutil.relativedelta import relativedelta
import calendar
from odoo.exceptions import UserError, ValidationError
import time
from odoo.tools.safe_eval import safe_eval
import json
import math
import logging
_logger = logging.getLogger(__name__)

def monthrange(year=None, month=None):
    today = datetime.today()
    y = year or today.year
    m = month or today.month
    return y, m, calendar.monthrange(y, m)[1]

def get_days_in_months():
    """
    Genera una lista con el número de días en cada mes, considerando los años bisiestos.
    
    Returns:
        list: Lista con el número de días en cada mes.
    """
    days_in_months = [0, 31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
    
    # Ajustar el número de días en febrero para años bisiestos
    days_in_months[2] = 29 if calendar.isleap(datetime.now().year) else 28
    
    return days_in_months

def format_currency(value):
    """
    Formatea un número como una cadena de texto con formato de moneda.
    """
    return "${:,.2f}".format(value)

def days360(start_date, end_date, method_eu=True):
    """Compute number of days between two dates regarding all months
    as 30-day months"""

    start_day = start_date.day
    start_month = start_date.month
    start_year = start_date.year
    end_day = end_date.day
    end_month = end_date.month
    end_year = end_date.year

    if (
            start_day == 31 or
            (
                method_eu is False and
                start_month == 2 and (
                    start_day == 29 or (
                        start_day == 28 and
                        calendar.isleap(start_year) is False
                    )
                )
            )
    ):
        start_day = 30

    if end_day == 31:
        if method_eu is False and start_day != 30:
            end_day = 1

            if end_month == 12:
                end_year += 1
                end_month = 1
            else:
                end_month += 1
        else:
            end_day = 30
    if end_month == 2 and end_day in (28, 29):
        end_day = 30

    return (
        end_day + end_month * 30 + end_year * 360 -
        start_day - start_month * 30 - start_year * 360 + 1
    )

#Tabla de tipos de empleados
class hr_types_employee(models.Model):
    _name = 'hr.types.employee'
    _description = 'Tipos de empleado'

    code = fields.Char('Código',required=True)
    name = fields.Char('Nombre',required=True)

    _sql_constraints = [('change_code_uniq', 'unique(code)', 'Ya existe un tipo de empleado con este código, por favor verificar')]

#Tabla de tiesgos profesionales
class hr_contract_risk(models.Model):
    _name = 'hr.contract.risk'
    _description = 'Riesgos profesionales'

    code = fields.Char('Codigo', size=10, required=True)
    name = fields.Char('Nombre', size=100, required=True)
    percent = fields.Float('Porcentaje', digits=(12,3), required=True, help='porcentaje del riesgo profesional')
    date = fields.Date('Fecha vigencia')

    _sql_constraints = [('change_code_uniq', 'unique(code)', 'Ya existe un riesgo con este código, por favor verificar')]  

class lavish_economic_activity_level_risk(models.Model):
    _name = 'lavish.economic.activity.level.risk'
    _description = 'Actividad económica por nivel de riesgo'

    risk_class_id = fields.Many2one('hr.contract.risk','Clase de riesgo', required=True)
    code_ciiu_id = fields.Many2one('lavish.ciiu','CIIU', required=True)
    code = fields.Char('Código', required=True)
    name = fields.Char('Descripción', required=True)

    _sql_constraints = [('economic_activity_level_risk_uniq', 'unique(risk_class_id,code_ciiu_id,code)', 'Ya existe un riesgo con este código, por favor verificar')]

    def name_get(self):
        result = []
        for record in self:
            result.append((record.id, "{}{}{} | {}".format(record.risk_class_id.code, record.code_ciiu_id.code, record.code, record.code_ciiu_id.name)))
        return result

#Tabla tipos de entidades
class hr_contrib_register(models.Model):
    _name = 'hr.contribution.register'
    _description = 'Tipo de Entidades'
    
    name = fields.Char('Nombre', required=True)
    type_entities = fields.Selection([('none', 'No aplica'),
                             ('eps', 'Entidad promotora de salud'),
                             ('pension', 'Fondo de pensiones'),
                             ('cesantias', 'Fondo de cesantias'),
                             ('caja', 'Caja de compensación'),
                             ('riesgo', 'Aseguradora de riesgos profesionales'),
                             ('sena', 'SENA'),
                             ('icbf', 'ICBF'),
                             ('solidaridad', 'Fondo de solidaridad'),
                             ('subsistencia', 'Fondo de subsistencia')], 'Tipo', required=True)
    note = fields.Text('Description')

    _sql_constraints = [('change_name_uniq', 'unique(name)', 'Ya existe un tipo de entidad con este nombre, por favor verificar')]         

#Tabla de entidades
class hr_employee_entities(models.Model):
    _name = 'hr.employee.entities'
    _description = 'Entidades empleados'

    partner_id = fields.Many2one('res.partner', 'Entidad', help='Entidad relacionada')
    name = fields.Char(related="partner_id.name", readonly=True,string="Nombre")
    business_name = fields.Char(related="partner_id.business_name", readonly=True,string="Nombre de negocio")
    types_entities = fields.Many2many('hr.contribution.register',string='Tipo de entidad')
    code_pila_eps = fields.Char('Código PILA')
    code_pila_ccf = fields.Char('Código PILA para CCF')
    code_pila_regimen = fields.Char('Código PILA Regimen de excepción')
    code_pila_exterior = fields.Char('Código PILA Reside en el exterior')
    order = fields.Selection([('territorial', 'Orden Terrritorial'),
                             ('nacional', 'Orden Nacional')], 'Orden de la entidad')
    debit_account = fields.Many2one('account.account', string='Cuenta débito', company_dependent=True)
    credit_account = fields.Many2one('account.account', string='Cuenta crédito', company_dependent=True)
    _sql_constraints = [('change_partner_uniq', 'unique(partner_id)', 'Ya existe una entidad asociada a este tercero, por favor verificar')]         

    def name_get(self):
        result = []
        for record in self:
            if record.partner_id.business_name: 
                result.append((record.id, "{}".format(record.partner_id.business_name)))
            else: 
                result.append((record.id, "{}".format(record.partner_id.name)))
        return result

#Categorias reglas salariales herencia

class hr_categories_salary_rules(models.Model):
    _inherit = 'hr.salary.rule.category'
    
    group_payroll_voucher = fields.Boolean('Agrupar comprobante de nómina')
    sequence = fields.Integer(tracking=True)
#Contabilización reglas salariales
class hr_salary_rule_accounting(models.Model):
    _name ='hr.salary.rule.accounting'
    _description = 'Contabilización reglas salariales'    

    salary_rule = fields.Many2one('hr.salary.rule', string = 'Regla salarial')
    department = fields.Many2one('hr.department', string = 'Departamento')
    company = fields.Many2one('res.company', string = 'Compañía')
    work_location = fields.Many2one('res.partner', string = 'Ubicación de trabajo')
    third_debit = fields.Selection([('entidad', 'Entidad'),
                                    ('compañia', 'Compañia'),
                                    ('empleado', 'Empleado')], string='Tercero débito') 
    third_credit = fields.Selection([('entidad', 'Entidad'),
                                    ('compañia', 'Compañia'),
                                    ('empleado', 'Empleado')], string='Tercero crédito')
    debit_account = fields.Many2one('account.account', string = 'Cuenta débito', company_dependent=True)
    credit_account = fields.Many2one('account.account', string = 'Cuenta crédito', company_dependent=True)

#Estructura Salariales - Herencia
class hr_payroll_structure(models.Model):
    _inherit = 'hr.payroll.structure'

    @api.model
    def _get_default_rule_ids(self):
        default_rules = []
        if self.country_id.code == 'CO':
            if self.process == 'prima':
                # Añade las reglas para 'primas'
                default_rules.append((0, 0, {
                    # Detalles de la regla para 'primas'
                }))
            elif self.process == 'vacaciones':
                # Añade las reglas para 'nomina base'
                default_rules.append((0, 0, {
                    # Detalles de la regla para 'nomina base'
                }))
            elif self.process == 'cesantias':
                # Añade la regla para 'cesantias'
                default_rules.append((0, 0, {
                    'name': _('Cesantias'),
                    'sequence': 1,
                    'code': 'CESANTIAS',
                    'category_id': self.env.ref('lavish_hr_employee.PRESTACIONES_SOCIALES').id,
                    'condition_select': 'python',
                    'condition_python': 'result = payslip.get_salary_rule(\'CESANTIAS\',employee.type_employee.id)',
                    'amount_select': 'code',
                    'amount_python_compute': """
                        result = 0.0
                        obj_salary_rule = result
                        if obj_salary_rule:
                            date_start = payslip.date_from
                            date_end = payslip.date_to
                            if inherit_contrato != 0:
                                date_start = payslip.date_cesantias
                                date_end = payslip.date_liquidacion
                            accumulated = payslip.get_accumulated_cesantias(date_start,date_end) + values_base_cesantias
                            result = accumulated""",
                }))
        return default_rules

    process = fields.Selection([('nomina', 'Nónima'),
                                ('vacaciones', 'Vacaciones'),
                                ('prima', 'Prima'),
                                ('cesantias', 'Cesantías'),
                                ('intereses_cesantias', 'Intereses de cesantías'),
                                ('contrato', 'Liq. de Contrato'),
                                ('otro', 'Otro')], string='Proceso')
    regular_pay = fields.Boolean('Pago standar')
    rule_ids = fields.One2many(
        'hr.salary.rule', 'struct_id',
        string='Salary Rules', default=_get_default_rule_ids)

    @api.onchange('regular_pay')
    def onchange_regular_pay(self):
        for record in self:
            record.process = 'nomina' if record.regular_pay == True else False  
  
    @api.onchange('process')
    def _onchange_process(self):
        # Solo cambia las reglas si el registro no ha sido guardado todavía
        if not self._origin:
            self.rule_ids = self._get_default_rule_ids()
#Tipos entradas de trabajo - Herencia
class hr_work_entry_type(models.Model):
    _name = 'hr.work.entry.type'
    _inherit = ['hr.work.entry.type','mail.thread', 'mail.activity.mixin']

    code = fields.Char(tracking=True)
    sequence = fields.Integer(tracking=True)
    round_days = fields.Selection(tracking=True)
    round_days_type = fields.Selection(tracking=True)
    is_leave = fields.Boolean(tracking=True)
    is_unforeseen = fields.Boolean(tracking=True)

#Reglas Salariales - Herencia

lr = [0, 1, 100]
class hr_salary_rule(models.Model):
    _name = 'hr.salary.rule'
    _inherit = ['hr.salary.rule','mail.thread', 'mail.activity.mixin']

    #Trazabilidad
    struct_id = fields.Many2one(tracking=True)
    active = fields.Boolean(tracking=True)
    sequence = fields.Integer(tracking=True)
    condition_select = fields.Selection(tracking=True)
    amount_select = fields.Selection(tracking=True)
    amount_python_compute = fields.Text(tracking=True)
    appears_on_payslip = fields.Boolean(tracking=True)
    proyectar_nom = fields.Boolean('Proyectar en nomina')
    proyectar_ret = fields.Boolean('Proyectar en Retencion')
    #Campos lavish
    types_employee = fields.Many2many('hr.types.employee',string='Tipos de Empleado', tracking=True)
    dev_or_ded = fields.Selection([('devengo', 'Devengo'),
                                     ('deduccion', 'Deducción')],'Naturaleza', tracking=True)
    type_concepts = fields.Selection([('contrato', 'Fijo Contrato'),
                                     ('ley', 'Por Ley'),
                                     ('novedad', 'Novedad Variable'),
                                     ('prestacion', 'Prestación Social'),
                                     ('tributaria', 'Deducción Tributaria')],'Tipo', required=True, default='contrato', tracking=True)
    aplicar_cobro = fields.Selection([('15','Primera quincena'),
                                        ('30','Segunda quincena'),
                                        ('0','Siempre')],'Aplicar cobro', tracking=True)
    modality_value = fields.Selection([('fijo', 'Valor fijo'),
                                       ('diario', 'Valor diario'),
                                       ('diario_efectivo', 'Valor diario del día efectivamente laborado')],'Modalidad de valor', tracking=True)
    deduction_applies_bonus = fields.Boolean('Aplicar deducción en Prima', tracking=True)
    account_tax_id = fields.Many2one("account.tax", "Impuesto de Retefuente Laboral")
    #Es incapacidad / deducciones
    amount_select = fields.Selection([
        ('percentage', 'Percentage (%)'),
        ('fix', 'Fixed Amount'),
        ('code', 'Python Code'),
        ('concept', 'concept Code'),
    ], string='Amount Type', index=True, required=True, default='fix', help="The computation method for the rule amount.")
    is_leave = fields.Boolean('Es Ausencia', tracking=True)
    is_recargo = fields.Boolean('Es Recargos', tracking=True)
    deduct_deductions = fields.Selection([('all', 'Todas las deducciones'),
                                          ('law', 'Solo las deducciones de ley')],'Tener en cuenta al descontar', default='all', tracking=True)    #Vacaciones
    restart_one_month_prima = fields.Boolean('Restar 1 mes al promedio de los acumulados en prima', tracking=True)
    #Base de prestaciones
    base_prima = fields.Boolean('Para prima', tracking=True)
    base_cesantias = fields.Boolean('Para cesantías', tracking=True)
    base_vacaciones = fields.Boolean('Para vacaciones tomadas', tracking=True)
    base_vacaciones_dinero = fields.Boolean('Para vacaciones dinero', tracking=True)
    base_intereses_cesantias = fields.Boolean('Para intereses de cesantías', tracking=True)
    base_auxtransporte_tope = fields.Boolean('Para tope de auxilio de transporte', tracking=True)
    base_compensation = fields.Boolean('Para liquidación de indemnización', tracking=True)
    #Base de Seguridad Social
    base_seguridad_social = fields.Boolean('Para seguridad social', tracking=True)
    base_arl = fields.Boolean('Para seguridad social', tracking=True)
    base_parafiscales = fields.Boolean('Para parafiscales', tracking=True)
    excluir_ret = fields.Boolean('excluir de Calculo retefuente', tracking=True)
    #Contabilización
    salary_rule_accounting = fields.One2many('hr.salary.rule.accounting', 'salary_rule', string="Contabilización", tracking=True)
    #Reportes
    display_days_worked = fields.Boolean(string='Mostrar la cantidad de días trabajados en los formatos de impresión', tracking=True)
    short_name = fields.Char(string='Nombre corto/reportes')
    process = fields.Selection([('nomina', 'Nónima'),
                                ('vacaciones', 'Vacaciones'),
                                ('prima', 'Prima'),
                                ('cesantias', 'Cesantías'),
                                ('intereses_cesantias', 'Intereses de cesantías'),
                                ('contrato', 'Liq. de Contrato'),
                                ('otro', 'Otro')], string='Proceso')
    novedad_ded = fields.Selection([('cont', 'Contrato'),
                                    ('Noved', 'Novedad'),
                                    ('0', 'No'),],'Opcion de Novedad', tracking=True)
    not_include_flat_payment_file = fields.Boolean(string='No incluir en archivo plano de pagos')
    #Empleados publicos
    account_id_cxp = fields.Many2one('account.account',string='Cuenta CXP', company_dependent=True)
    state_budget_item = fields.Char(string='Rubro')
    state_budget_resource = fields.Char(string='Recurso')



    def _compute_rule(self, localdict):

        """
        :param localdict: dictionary containing the current computation environment
        :return: returns a tuple (amount, qty, rate)
        :rtype: (float, float, float)
        """
        self.ensure_one()
        res = 0,0,0,0,0,[]
        if self.amount_select == 'fix':
            try:
                return self.amount_fix or 0.0, float(safe_eval(self.quantity, localdict)), 100.0, self.name,False,False
            except Exception as e:
                self._raise_error(localdict, _("Wrong quantity defined for:"), e)
        if self.amount_select == 'percentage':
            try:
                return (float(safe_eval(self.amount_percentage_base, localdict)),
                        float(safe_eval(self.quantity, localdict)),
                        self.amount_percentage or 0.0, self.name,False,False)
            except Exception as e:
                self._raise_error(localdict, _("Wrong percentage base or quantity defined for:"), e)
        if self.amount_select == 'code':
            try:
                safe_eval(self.amount_python_compute or 0.0, localdict, mode='exec', nocopy=True)
                return float(localdict['result']), localdict.get('result_qty', 1.0), localdict.get('result_rate', 100.0), self.name,False,False
            except Exception as e:
                self._raise_error(localdict, _("Wrong python code defined for:"), e)
        if self.amount_select == 'concept':
            try:
                method = getattr(self, '_' + str(self.code).lower(), None)
                if method:
                    res = method(localdict)
                    return float(res[0]), res[1], res[2], res[3],res[4],res[5]
                return float(res[0]), res[1], res[2] , res[3],res[4],res[5]
            except Exception as e:
                self._raise_error(localdict, _("Wrong python code defined for:"), e)



    def _compute_rule_lavish(self, localdict):

        """
        :param localdict: dictionary containing the current computation environment
        :return: returns a tuple (amount, qty, rate)
        :rtype: (float, float, float)
        """
        self.ensure_one()
        res = 0,0,0,0,0,[]
        if self.amount_select == 'fix':
            try:
                return self.amount_fix or 0.0, float(safe_eval(self.quantity, localdict)), 100.0,False,False,False
            except Exception as e:
                self._raise_error(localdict, _("Wrong quantity defined for:"), e)
        if self.amount_select == 'percentage':
            try:
                return (float(safe_eval(self.amount_percentage_base, localdict)),
                        float(safe_eval(self.quantity, localdict)),
                        self.amount_percentage or 0.0,False,False,False)
            except Exception as e:
                self._raise_error(localdict, _("Wrong percentage base or quantity defined for:"), e)
        if self.amount_select == 'code':
            try:
                safe_eval(self.amount_python_compute or 0.0, localdict, mode='exec', nocopy=True)
                return float(localdict['result']), localdict.get('result_qty', 1.0), localdict.get('result_rate', 100.0),False,False,False
            except Exception as e:
                self._raise_error(localdict, _("Wrong python code defined for:"), e)
        if self.amount_select == 'concept':
            try:
                method = getattr(self, '_' + str(self.code).lower(), None)
                if method:
                    res = method(localdict)
                    return float(res[0]), res[1], res[2], res[3],res[4],res[5]
                return float(res[0]), res[1], res[2], res[3],res[4],res[5] #float(localdict['result']), localdict.get('result_qty', 1.0), localdict.get('result_rate', 100.0)
            except Exception as e:
               self._raise_error(localdict, _("Wrong python code defined for:"), e)

    def _basic(self, ld): #BASIC
        """
        Sueldo basico
        :param ld:
        :return: Valor de salario asignado en el contrato y depende de los dias trabajados en el periodo
        Varia el nombre del concepto dependiendo del tipo de contrato y el rate cambia unicamente cuando es tipo
        aprendiz lectivo
        """
        if not ld['contract'].subcontract_type:
            wage = ld['wage']
            result = math.fsum([wage / 30])
            wage = math.trunc(result * 100) / 100
            work100 = ld['worked_days'].WORK100.number_of_days
            name = ''
            log = ''
            rate = 100.0
            if ld['contract'].modality_salary in ('basico','especie','variable'):
                name = 'SUELDO BASICO'
            else:
                return 0,0,0,False,False,False
            return wage, work100, rate, name, log,False
        else:
            return 0,0,0,False,False,False

    def _basic002(self, ld): #BASIC
        """
        Sueldo basico
        :param ld:
        :return: Valor de salario asignado en el contrato y depende de los dias trabajados en el periodo
        Varia el nombre del concepto dependiendo del tipo de contrato y el rate cambia unicamente cuando es tipo
        aprendiz lectivo
        """
        if not ld['contract'].subcontract_type:
            wage = ld['wage'] / 30
            work100 = ld['worked_days'].WORK100.number_of_days
            name = ''
            log = ''
            rate = 100.0
            if ld['contract'].modality_salary == 'integral':
                name = 'SUELDO BASICO INTEGRAL'
            else:
                return 0,0,0,False,False,False
            return wage, work100, rate, name, log,False
        else:
            return 0,0,0,False,False,False


    def _basic003(self, ld): #BASIC
        """
        Sueldo basico
        :param ld:
        :return: Valor de salario asignado en el contrato y depende de los dias trabajados en el periodo
        Varia el nombre del concepto dependiendo del tipo de contrato y el rate cambia unicamente cuando es tipo
        aprendiz lectivo
        """
        if not ld['contract'].subcontract_type:
            wage = ld['wage'] / 30
            work100 = ld['worked_days'].WORK100.number_of_days
            name = ''
            log = ''
            rate = 100.0
            if ld['contract'].modality_salary == 'sostenimiento':
                if ld['employee'].tipo_coti_id.code == '12':
                    name = 'CUOTA DE SOSTENIMIENTO LECTIVO'
                elif ld['employee'].tipo_coti_id.code == '19':
                    start_period = ld['payslip'].date_from
                    end_period = ld['payslip'].date_to
                    name = 'CUOTA DE SOSTENIMIENTO PRODUCTIVO'
                    if ld['contract'].apr_prod_date:
                        if start_period < ld['contract'].apr_prod_date <= end_period:
                            diff = days360(ld['contract'].apr_prod_date, end_period)
                            if diff:
                                lec_wd = ld['worked_days'].WORK100.number_of_days - diff
                                lect_amount = ld['contract'].wage_old * lec_wd / 30
                                prod_amount = ld['wage'] *  diff / 30
                                amount = lect_amount + prod_amount
                                wage = amount
            else:
                return 0,0,0,False,False,False,False
            return wage, work100, rate, name, log,False
        else:
            return 0,0,0,False,False,False







    def _aux000(self, ld):
        """ Subsidio de transporte
        :param ld:
        :return: Valor de auxilio de transporte definido en variables economicas por los dias trabajados en el mes o periodo.
        Tambien omite el calculo si en el contrato está marcada la opcion skip_aux_trans
        Si el valor de la categoria de devengados supera el valor de dos salarios minimos se omite el pago
        """
        aux_trans_monthly = ld['annual_parameters'].transportation_assistance_monthly
        contract = ld['contract']
        worked_days = ld['worked_days']
        payslip = ld['payslip']
        categories = ld['categories']
        employee = ld['employee']
        annual_parameters = ld['annual_parameters']
        # Condiciones iniciales rápidas para retornos directos
        if contract.skip_commute_allowance or contract.remote_work_allowance:
            return 0, 0, 0, 0, 0, 0
        if contract.not_validate_top_auxtransportation and worked_days.WORK100.number_of_days != 0.0:
            return aux_trans_monthly / 30, worked_days.WORK100.number_of_days, 100, False, False
        if (contract.pay_auxtransportation and payslip.date_from < 15) or contract.modality_salary == 'integral' or employee.tipo_coti_id.code == '12':
            return 0, 0, 0, 0, 0, 0
        # Cálculo de los devengados
        earnings = categories.DEV_SALARIAL + sum(p.get_payslip_category('DEV_SALARIAL') - p.get_payslip_concept_total('AUX000') for p in ld['payslips_month'])
        smmlv_twice = 2 * annual_parameters.smmlv_monthly
        if earnings >= smmlv_twice or contract.wage > smmlv_twice:
            return 0, 0, 0, 0, 0, 0
        # Política de aplicación de auxilio
        policy_applies = contract.modality_salary in ['basico','especie','variable','sostenimiento'] and not contract.subcontract_type
        if not policy_applies:
            return 0, 0, 0, 0, 0, 0

        base = aux_trans_monthly / 30
        paid_days = sum(p.get_payslip_concept('AUX000').quantity for p in ld['payslips_month'])
        qty = worked_days.WORK_D.number_of_days - paid_days
        work100 = ld['worked_days'].WORK100.number_of_days

        # Ajuste para trabajadores con código '19'
        if employee.tipo_coti_id.code == '19' and contract.apr_prod_date:
            start_period, end_period = payslip.date_from, payslip.date_to
            if start_period < contract.apr_prod_date <= end_period:
                qty = days360(contract.apr_prod_date, end_period)

        return base, work100, 100, False, False,False
    def need_compute_salary_average(self, contract, date_from, date_to):
        date_3_months_before = date_to - relativedelta(months=3)
        if date_from > date_3_months_before:
            date_3_months_before = date_from
        return contract.has_change_salary(date_3_months_before, date_to)

    def sum_mount_x_rule(self,code, contract, date_from,date_to):
        self.env.cr.execute("""
            SELECT COALESCE(sum(pl.total), 0) as suma 
            FROM hr_payslip as hp
            INNER JOIN hr_payslip_line as pl ON hp.id = pl.slip_id
            INNER JOIN hr_salary_rule hc ON pl.salary_rule_id = hc.id
            WHERE hp.state IN ('done','paid') 
                AND hp.contract_id = %s 
                AND hp.date_from >= %s 
                AND hp.date_to <= %s
                AND hc.code = %s
        """, (contract.id, date_from, date_to, code))
        res = self.env.cr.fetchone()
        return res[0] if res else 0.0

    def sum_mount(self,code, contract, date_from,date_to):
        self.env.cr.execute("""
            SELECT COALESCE(sum(pl.total), 0) AS suma
            FROM hr_payslip AS hp
            INNER JOIN hr_payslip_line AS pl ON hp.id = pl.slip_id
            INNER JOIN hr_salary_rule_category hc ON pl.category_id = hc.id
            LEFT JOIN hr_salary_rule_category hc_parent ON hc.parent_id = hc_parent.id
            WHERE hp.state IN ('done', 'paid')
                AND hp.contract_id = %s
                AND hp.date_from >= %s
                AND hp.date_to <= %s
                AND (hc.code = %s OR hc_parent.code = %s)
        """, (contract.id, date_from, date_to, code, code))
        res = self.env.cr.fetchone()
        return res[0] if res else 0.0

    def sum_days_works(self, code_work_entry_type, contract, from_date, to_date):
        """
        Calculate the days effectively worked within the given date range.
        :param code_work_entry_type: Code of the work entry type
        :param from_date: Start date of the range
        :param to_date: End date of the range
        :return: Number of days worked
        """
        from_date_str = from_date
        to_date_str = to_date

        query = """
            SELECT COALESCE(SUM(hd.number_of_days), 0) AS dias
            FROM hr_payslip_worked_days hd
            INNER JOIN hr_payslip hp ON hp.id = hd.payslip_id AND hp.state IN ('done', 'paid')
            INNER JOIN hr_work_entry_type wt ON hd.work_entry_type_id = wt.id
            WHERE wt.code = %s
            AND hp.contract_id = %s
            AND hp.date_from >= %s
            AND hp.date_to <= %s
        """
        
        self.env.cr.execute(query, (code_work_entry_type, contract.id, from_date_str, to_date_str))
        res = self.env.cr.fetchone()

        return res[0] if res else 0.0


    def _ibd(self, payslip_data):
        """
        Calculate Ingreso Base de Deducciones (IBD)
        :param payslip_data: Dictionary containing payslip and contract information
        :return: Tuple containing:
            - IBD amount
            - Multiplier (always 1)
            - Percentage (always 100)
            - Boolean flag (always False)
            - Calculation log
            - Boolean flag (always False)
        """
        contract = payslip_data['contract']
        payslip = payslip_data['payslip']
        result_rules = payslip_data['result_rules_co']
        result_rules = payslip_data['result_rules_co']
        worked_days = payslip_data['worked_days']
        annual_parameters = payslip_data['annual_parameters']
        if contract.contract_type == 'aprendizaje':
            return 0, 0, 0, 0, 0, False
        date_from = payslip.date_from.replace(day=1)
        date_to = payslip.date_to
        # Calculate base salary
        work100 = worked_days.WORK100.number_of_days + self.sum_days_works('WORK100', contract, date_from, date_to)
        
        wage_total = payslip_data['categories'].BASIC #result_rules['BASIC']['total'] + result_rules['BASIC002']['total']  + result_rules['BASIC003']['total'] # sum(result_rules[code]['total'] for code in ['BASIC', 'BASIC002', 'BASIC003'])
        wage_total += self.sum_mount('BASIC', contract, date_from, date_to)
        
        force_min = 'No'
        if contract.minimum_wage and work100 != 0:
            wage_total = max((wage_total / work100), annual_parameters.smmlv_daily) * work100
            force_min = 'SI'
        base_salary = wage_total
        # Calculate total earnings
        base_seguridad_social_total = 0
        for rule_code, rule_data in result_rules.dict.items():
            total = rule_data.get('total', 0)
            if rule_code != 'BASIC' and rule_code != 'AUX000' and rule_data.get('base_seguridad_social', False):
                base_seguridad_social_total += total
        self.env.cr.execute("""
            SELECT code
            FROM hr_salary_rule
            WHERE base_seguridad_social = True
            AND code NOT IN ('BASIC', 'BASIC003', 'AUX000')
        """)
        base_seguridad_social_codes = [row[0] for row in self.env.cr.fetchall()]
        prev_earn = sum(self.sum_mount_x_rule(code, contract, date_from, date_to) for code in base_seguridad_social_codes)
        total_earnings = base_salary + base_seguridad_social_total + prev_earn
        # Calculate other earnings
        other_earnings = self.sum_mount('DEV_NO_SALARIAL', contract, date_from, date_to)
        ibd_amount = total_earnings

        top40 = (total_earnings + other_earnings) * 0.4
        if other_earnings > top40:
            ibd_amount = total_earnings + other_earnings - top40
            apply_40_percent = 'SI'
            added_amount = other_earnings - top40
        else:
            apply_40_percent = 'No'
            added_amount = 0.0

        # Apply integral salary adjustment
        if contract.modality_salary == 'integral':
            ibd_amount *= 0.7

        # Apply 25 SMMLV cap
        max_ibd = 25 * annual_parameters.smmlv_monthly
        ibd_amount = min(ibd_amount, max_ibd)
        # Generate calculation log
        log = [
            ('BASICO', base_salary),
            ('FORZAR MINIMO', force_min),
            ('INGRESOS SALARIALES', total_earnings),
            ('INGRESOS SALARIALES PREVIOS', total_earnings - base_salary),
            ('OTROS INGRESOS', other_earnings),
            ('VALOR TOPE 40%', added_amount),
            ('APLICA 40%', apply_40_percent),
            ('IBC TOTAL', ibd_amount),
        ]
        return ibd_amount, 1, 100, False, log, False

    # SEGURIDAD SOCIAL
    def _ssocial001(self, ld):
        """
        Deduccion de salud
        :param ld:
        :return: Valor a deducir al empleado correspondiente a salud, debe contemplear lo que ya se haya descontado
        en quincenas anteriores y se descuenta tambien de la base el valor de las incapacidades mayores a 180 dias
        El valor es el 4% del ibc
        """
        base = 0
        rate = 0
        name = ''
        log = ''
        cobro = self.aplicar_cobro
        if ld['contract'].contract_type != 'aprendizaje':
            if ld['payslip'].date_from.day < 15 and cobro=='15':
                prev_ded = sum([p.get_payslip_concept_total('SSOCIAL001') for p in ld['payslips_month']])
                rate = ld['annual_parameters'].value_porc_health_employee / 100
                if prev_ded != 0:
                    prev_ded = prev_ded / rate
                ibd = ld['rules_computed'].IBD
                base = ibd - abs(prev_ded)
                rate = ld['annual_parameters'].value_porc_health_employee
            elif ld['payslip'].date_from.day > 15 and cobro=='30':
                prev_ded = sum([p.get_payslip_concept_total('SSOCIAL001') for p in ld['payslips_month']])
                rate = ld['annual_parameters'].value_porc_health_employee / 100
                if prev_ded != 0:
                    prev_ded = prev_ded / rate
                ibd = ld['rules_computed'].IBD
                base = ibd - abs(prev_ded)
                rate = ld['annual_parameters'].value_porc_health_employee
            elif cobro not in ['30','15']:
                prev_ded = sum([p.get_payslip_concept_total('SSOCIAL001') for p in ld['payslips_month']])
                rate = ld['annual_parameters'].value_porc_health_employee / 100
                if prev_ded != 0:
                    prev_ded = prev_ded / rate
                ibd = ld['rules_computed'].IBD
                base = ibd - abs(prev_ded)
                rate = ld['annual_parameters'].value_porc_health_employee
        return base, -1,rate,name,log,False

    def _ssocial002(self, ld):
        """
        Deduccion de pension
        :param ld:
        :return: Valor a deducir al empleado correspondiente a pension, debe contemplear lo que ya se haya descontado
        en quincenas anteriores y se descuenta tambien de la base el valor de las incapacidades mayores a 180 dias
        El valor es el 4% del ibc, con el cambio del decreto 558 de 2020 se consulta en politicas de nomina
        """
        base = 0
        rate = 0
        name = ''
        log = ''
        cobro = self.aplicar_cobro
        employee = ld['employee']
        if employee.subtipo_coti_id.not_contribute_pension:
            return 0, 0, 0, 0, 0, 0
        if ld['contract'].contract_type != 'aprendizaje':
            if ld['payslip'].date_from.day < 15 and cobro=='15':
                prev_ded = sum([p.get_payslip_concept_total('SSOCIAL002') for p in ld['payslips_month']])
                rate = ld['annual_parameters'].value_porc_pension_employee / 100
                if prev_ded != 0:
                    prev_ded = prev_ded / rate
                ibd = ld['rules_computed'].IBD
                base = ibd - abs(prev_ded)
                rate = ld['annual_parameters'].value_porc_pension_employee
            elif ld['payslip'].date_from.day > 15 and cobro=='30':
                prev_ded = sum([p.get_payslip_concept_total('SSOCIAL002') for p in ld['payslips_month']])
                rate = ld['annual_parameters'].value_porc_pension_employee / 100
                if prev_ded != 0:
                    prev_ded = prev_ded / rate
                ibd = ld['rules_computed'].IBD
                base = ibd - abs(prev_ded)
                rate = ld['annual_parameters'].value_porc_pension_employee
            elif cobro not in ['30','15']:
                prev_ded = sum([p.get_payslip_concept_total('SSOCIAL002') for p in ld['payslips_month']])
                rate = ld['annual_parameters'].value_porc_pension_employee / 100
                if prev_ded != 0:
                    prev_ded = prev_ded / rate
                ibd = ld['rules_computed'].IBD
                base = ibd - abs(prev_ded)
                rate = ld['annual_parameters'].value_porc_pension_employee
        return base, -1,rate,name,log,False

    def _ssocial003(self, ld):
        """
        Deduccion de fondo de solidaridad
        :param ld:
        :return: Valor correspondiente al 0.5% del ibc si el ibc supera los 4 salarios minimos, debe contemplear si se
        ha realizado esta deduccion en otras nominas del mismo mes
        """

        base = 0.0
        base2 = ld['rules_computed'].IBD
        rate = 0.5
        qty = 1
        name = ''
        log = ''
        cobro = self.aplicar_cobro
        if base2 > ld['annual_parameters'].top_four_fsp_smmlv and ld['contract'].contract_type != 'aprendizaje':
            base = ld['rules_computed'].IBD
            if ld['payslip'].date_from.day < 15 and cobro=='15':
                retired = True if ld['employee'].subtipo_coti_id.code not in ['00', False] else False
                if not retired:
                    prev_ded = sum([p.get_payslip_concept_total('SSOCIAL003') for p in ld['payslips_month']])
                    if prev_ded != 0:
                        prev_ded = prev_ded / (rate /100)
                    base = base - abs(prev_ded)
            elif ld['payslip'].date_from.day > 15 and cobro=='30':
                retired = True if ld['employee'].subtipo_coti_id.code not in ['00', False] else False
                if not retired:
                    prev_ded = sum([p.get_payslip_concept_total('SSOCI9AL003') for p in ld['payslips_month']])
                    if prev_ded != 0:
                        prev_ded = prev_ded / (rate /100)
                    base = base - abs(prev_ded)
            elif cobro not in ['30','15']:
                retired = True if ld['employee'].subtipo_coti_id.code not in ['00', False] else False
                if not retired:
                    prev_ded = sum([p.get_payslip_concept_total('SSOCIAL003') for p in ld['payslips_month']])
                    if prev_ded != 0:
                        prev_ded = prev_ded / (rate /100)
                    base = base - abs(prev_ded)
        return base,-1,rate,name,log,False

    def _ssocial004(self, ld):
        """ Deducción del Fondo de Subsistencia
        :param ld: Datos del empleado y nómina
        :return: Valor correspondiente a la deducción del Fondo de Subsistencia
        """
        def get_subsistence_rate(ibd, sal_min):
            if ibd <= 4 * sal_min:
                return 0.0
            elif ibd <= 16 * sal_min:
                return 0.5
            elif ibd <= 17 * sal_min:
                return 0.7
            elif ibd <= 18 * sal_min:
                return 0.9
            elif ibd <= 19 * sal_min:
                return 1.1
            elif ibd <= 20 * sal_min:
                return 1.3
            else:
                return 1.5

        def get_subsistence_log(ibd, sal_min):
            log = []
            log.append(('<= 4 SMMLV = 0.5', 'Si' if ibd > 4 * sal_min else 'No'))
            log.append(('16 SMMLV <= 17 SMMLV = 0.2', 'Si' if 16 * sal_min <= ibd <= 17 * sal_min else 'No'))
            log.append(('> 17 SMMLV <= 18 SMMLV = 0.4', 'Si' if 17 * sal_min < ibd <= 18 * sal_min else 'No'))
            log.append(('> 18 SMMLV <= 19 SMMLV = 0.6', 'Si' if 18 * sal_min < ibd <= 19 * sal_min else 'No'))
            log.append(('> 19 SMMLV = 20 SMMLV = 0.8', 'Si' if 19 * sal_min < ibd <= 20 * sal_min else 'No'))
            log.append(('> 20 SMMLV = 1', 'Si' if ibd > 20 * sal_min else 'No'))
            return log
        ibd = ld['rules_computed'].IBD
        sal_min = ld['annual_parameters'].smmlv_monthly
        retired = ld['employee'].subtipo_coti_id.code not in ['00', False]
        cobro = self.aplicar_cobro
        rate = 0
        base = 0
        name = ''

        if retired or ld['contract'].contract_type == 'aprendizaje' or ibd <= ld['annual_parameters'].top_four_fsp_smmlv:
            return 0.0, 1, 0.0, name, [], []
        
        if ld['payslip'].date_from.day < 15 and cobro=='15':
            rate = get_subsistence_rate(ibd, sal_min)
        elif ld['payslip'].date_from.day > 15 and cobro=='30':
            rate = get_subsistence_rate(ibd, sal_min)
        elif cobro not in ['30','15']:
            rate = get_subsistence_rate(ibd, sal_min)
        if rate != 0.0:    
            prev_ded = sum(p.get_payslip_concept_total('SSOCIAL004') for p in ld['payslips_month'])
            rate = rate
            amount = ibd * rate / 100
            base = (amount - prev_ded) / (rate / 100)
            log = get_subsistence_log(ibd, sal_min)

        return base, -1, rate, name, log,False


    def _prv_prim(self, ld):
        contract = ld['contract']
        date_from = ld['payslip'].date_from.replace(day=1)  # Siempre al inicio del mes
        date_to = ld['payslip'].date_to
        annual_parameters = ld['annual_parameters']
        def sum_mount_x_rule(code):
            self.env.cr.execute("""
                SELECT COALESCE(sum(pl.total), 0) as suma 
                FROM hr_payslip as hp
                INNER JOIN hr_payslip_line as pl ON hp.id = pl.slip_id
                INNER JOIN hr_salary_rule hc ON pl.salary_rule_id = hc.id
                WHERE hp.state IN ('done','paid') 
                    AND hp.contract_id = %s 
                    AND hp.date_from >= %s 
                    AND hp.date_to <= %s
                    AND hc.code = %s
            """, (contract.id, date_from, date_to, code))
            return self.env.cr.fetchone()[0] or 0.0
        def sum_mount(code):
            self.env.cr.execute("""
                SELECT COALESCE(sum(pl.total), 0) AS suma
                FROM hr_payslip AS hp
                INNER JOIN hr_payslip_line AS pl ON hp.id = pl.slip_id
                INNER JOIN hr_salary_rule_category hc ON pl.category_id = hc.id
                LEFT JOIN hr_salary_rule_category hc_parent ON hc.parent_id = hc_parent.id
                WHERE hp.state IN ('done', 'paid')
                    AND hp.contract_id = %s
                    AND hp.date_from >= %s
                    AND hp.date_to <= %s
                    AND (hc.code = %s OR hc_parent.code = %s)
            """, (contract.id, date_from, date_to, code, code))
            return self.env.cr.fetchone()[0] or 0.0
        base = 0
        rate = 0
        name = ''
        log = ''
        skip = ld['employee'].tipo_coti_id.code in ['12', '19']
        skip |= ld['contract'].modality_salary == 'integral'
        if skip:
            return 0,0,0,0,0,False
        item = ld['result_rules_co']
        if self.env.company.simple_provisions:
            base_prima_total = 0
            base_primas_items = []
            base_prima_total = ld['categories'].BASIC
            base_prima_total += ld['rules_computed'].AUX000
       
            for rule_code, rule_data in item.dict.items():
                total = rule_data.get('total', 0)
                if rule_code != 'BASIC' and rule_code != 'AUX000' and rule_data.get('base_prima', False):
                    base_prima_total += total
                    base_primas_items.append(rule_code)
            total_earn = base_prima_total
            self.env.cr.execute("""
                SELECT code
                FROM hr_salary_rule
                WHERE base_prima = True
                AND code NOT IN ('BASIC', 'BASIC003', 'AUX000')
                """)
            base_primas_items = [row[0] for row in self.env.cr.fetchall()]
            total_earn += sum(sum_mount_x_rule(code) for code in base_primas_items)
            prv_prev =  sum_mount_x_rule('PRV_PRIM') #sum([p.get_payslip_concept_total('PRV_PRIM') for p in ld['payslips_month']]) * 100/4.17
            base = total_earn - prv_prev
            rate = 4.17
            rate = 8.33
            return base,1,rate,name,log,False
        else:
            # Calculo de fechas de referencia para calculos
            k_dt_start = ld['contract'].date_start
            ref_month = ref_month = '01' if ld['payslip'].date_from.month <= 6 else '07'
            ref_date = (str(ld['payslip'].date_from.year) + '-' + str(ref_month) + '-01')
            ref_date = datetime.strptime(ref_date, '%Y-%m-%d').date()
            if ref_date < k_dt_start:
                ref_date = k_dt_start
            ref_to_date = ld['payslip'].date_to
            #day_to = monthrange(ref_to_date.year, ref_to_date.month)[2]
            #ref_to_date = datetime.strptime(str(str(ref_to_date.year) + '-' + str(ref_to_date.month) + '-' + str(day_to)),'%Y-%m-%d').date()
            if ld['contract'].date_end and ld['contract'].date_end < ref_to_date:
                ref_to_date = ld['contract'].date_end

            prima_data = self.get_prst(ref_date, ref_to_date, ld, include=True, prst='prima')

            provs = self.get_interval_concept('PRV_PRIM', ref_date, ref_to_date,ld['contract'].id)
            t_provs = sum([x[1] for x in provs])

            log = [
                ('FECHA DESDE', str(ref_date)),
                ('FECHA HASTA', str(ref_to_date)),
                ('DIAS LABORADOS', prima_data['days']),
                ('DIAS DE LICENCIA', prima_data['days_mat']),
                ('DIAS DE SUSPENSION', prima_data['susp']),
               # ('CAMBIO DE SALARIO', prima_data['wc']),
                ('TOTAL SALARIO', prima_data['twage']),
                ('TOTAL VARIABLE', prima_data['total_variable']),
                ('BASE', prima_data['base']),
                ('NETO PRIMA A LA FECHA', prima_data['pres']),
                ('PARCIALES', prima_data['partials']),
                ('PROVISIONES REALIZADAS', t_provs)
            ]
            base = prima_data['pres'] - t_provs
            log = log
            rate = 100
            name = 'PROV. PRIMAS' + ' ' + str(ref_date) + ' - ' + str(ref_to_date)

        return base,1,rate,name,log,False

    def _prv_ces(self, ld): #PRV_CES
        contract = ld['contract']
        date_from = ld['payslip'].date_from.replace(day=1)  # Siempre al inicio del mes
        date_to = ld['payslip'].date_to
        annual_parameters = ld['annual_parameters']
        def sum_mount_x_rule(code):
            self.env.cr.execute("""
                SELECT COALESCE(sum(pl.total), 0) as suma 
                FROM hr_payslip as hp
                INNER JOIN hr_payslip_line as pl ON hp.id = pl.slip_id
                INNER JOIN hr_salary_rule hc ON pl.salary_rule_id = hc.id
                WHERE hp.state IN ('done','paid') 
                    AND hp.contract_id = %s 
                    AND hp.date_from >= %s 
                    AND hp.date_to <= %s
                    AND hc.code = %s
            """, (contract.id, date_from, date_to, code))
            return self.env.cr.fetchone()[0] or 0.0
        def sum_mount(code):
            self.env.cr.execute("""
                SELECT COALESCE(sum(pl.total), 0) AS suma
                FROM hr_payslip AS hp
                INNER JOIN hr_payslip_line AS pl ON hp.id = pl.slip_id
                INNER JOIN hr_salary_rule_category hc ON pl.category_id = hc.id
                LEFT JOIN hr_salary_rule_category hc_parent ON hc.parent_id = hc_parent.id
                WHERE hp.state IN ('done', 'paid')
                    AND hp.contract_id = %s
                    AND hp.date_from >= %s
                    AND hp.date_to <= %s
                    AND (hc.code = %s OR hc_parent.code = %s)
            """, (contract.id, date_from, date_to, code, code))
            return self.env.cr.fetchone()[0] or 0.0
        base = 0
        rate = 0
        name = ''
        log = ''
        skip = ld['employee'].tipo_coti_id.code in ['12', '19']
        skip |= ld['contract'].modality_salary == 'integral'
        if skip:
            return 0,0,0,0,0,False
        item = ld['result_rules_co']
        if self.env.company.simple_provisions:
            base_prima_total = 0
            base_primas_items = []
            base_prima_total = ld['categories'].BASIC
            base_prima_total += ld['rules_computed'].AUX000
       
            for rule_code, rule_data in item.dict.items():
                total = rule_data.get('total', 0)
                if rule_code != 'BASIC' and rule_code != 'AUX000' and rule_data.get('base_cesantias', False):
                    base_prima_total += total
                    base_primas_items.append(rule_code)
            total_earn = base_prima_total
            self.env.cr.execute("""
                SELECT code
                FROM hr_salary_rule
                WHERE base_cesantias = True
                AND code NOT IN ('BASIC', 'BASIC003', 'AUX000')
                """)
            base_primas_items = [row[0] for row in self.env.cr.fetchall()]
            total_earn += sum(sum_mount_x_rule(code) for code in base_primas_items)
            prv_prev =  sum_mount_x_rule('PRV_CES') #sum([p.get_payslip_concept_total('PRV_PRIM') for p in ld['payslips_month']]) * 100/4.17
            base = total_earn - prv_prev
            rate = 8.33
            return base,1,rate,name,log,False
        else:
            k_dt_start = ld['contract'].date_start
            ref_month = '01'
            ref_date = (str(ld['payslip'].date_from.year) + '-' + str(ref_month) + '-01')
            ref_date = datetime.strptime(ref_date, '%Y-%m-%d').date()
            if ref_date < k_dt_start:
                ref_date = k_dt_start
            ref_to_date = ld['payslip'].date_to
            if ld['contract'].date_end and ld['contract'].date_end < ref_to_date:
                ref_to_date = ld['contract'].date_end

            ces_data = self.get_prst(ref_date, ref_to_date, ld, include=True, prst='ces')

            provs = self.get_interval_concept('PRV_CES', ref_date, ref_to_date,ld['contract'].id)
            t_provs = sum([x[1] for x in provs])

            log = [
                ('FECHA DESDE', str(ref_date)),
                ('FECHA HASTA', str(ref_to_date)),
                ('DIAS LABORADOS', ces_data['days']),
                ('DIAS DE LICENCIA', ces_data['days_mat']),
                ('DIAS DE SUSPENSION', ces_data['susp']),
                ('TOTAL SALARIO', ces_data['twage']),
                ('TOTAL VARIABLE', ces_data['total_variable']),
                ('BASE', ces_data['base']),
                ('NETO CESANTIAS A LA FECHA', ces_data['pres']),
                ('PARCIALES', ces_data['partials']),
                ('PROVISIONES REALIZADAS', t_provs)
            ]
            base = ces_data['pres'] - t_provs
            log = log
            rate = 100
            name = 'PROV. CESANTIAS' + ' ' + str(ref_date) + ' - ' + str(ref_to_date)
        return base,1,rate,name,log,False

    def _prv_ices(self, ld):
        base = 0
        rate = 0
        name = ''
        log = ''
        skip = ld['employee'].tipo_coti_id.code in ['12', '19']
        skip |= ld['contract'].modality_salary == 'integral'
        if skip:
            return 0,0,0,0,0,0
        if self.env.company.simple_provisions:
            prv_ces = ld['rules_computed'].PRV_CES
            base = prv_ces
            rate = 12
            return base,1,rate,name,log,False
        else:
            k_dt_start = ld['contract'].date_start
            ref_month = '01'
            ref_date = (str(ld['payslip'].date_from.year) + '-' + str(ref_month) + '-01')
            ref_date = datetime.strptime(ref_date, '%Y-%m-%d').date()
            if ref_date < k_dt_start:
                ref_date = k_dt_start
            ref_to_date = ld['payslip'].date_to
            if ld['contract'].date_end and ld['contract'].date_end < ref_to_date:
                ref_to_date = ld['contract'].date_end
            ces_data = self.get_prst(ref_date, ref_to_date, ld, include=True, prst='ces')
            provs = self.get_interval_concept('PRV_ICES', ref_date, ref_to_date,ld['contract'].id)
            t_provs = sum([x[1] for x in provs])
            prev_ices_itv = self.get_interval_concept('ICES_PART', ref_date, ref_to_date,ld['contract'].id)
            prev_ices = sum([x[1] for x in prev_ices_itv])
            if prev_ices_itv:
                date_max = max([ices_part[0] for ices_part in prev_ices_itv])
                date_max = datetime.strptime(date_max,"%Y-%m") + relativedelta(months=1)
                date_max = datetime.strptime((str(datetime.strftime(date_max,"%Y-%m")) + '-01'),'%Y-%m-%d').date()
                if date_max > ref_date:
                    ref_date = date_max
            days = days360(ref_date, ref_to_date)
            net_ices = (ces_data['pres'] - ces_data['partials']) * 0.12
            i_fecha = net_ices
            base = net_ices - t_provs + prev_ices
            log = [
                ('FECHA DESDE', str(ref_date)),
                ('FECHA HASTA', str(ref_to_date)),
                ('DIAS LABORADOS', days),
                ('DIAS DE LICENCIA', ces_data['days_mat']),
                ('DIAS DE SUSPENSION', ces_data['susp']),
                ('TOTAL SALARIO', ces_data['twage']),
                ('TOTAL VARIABLE', ces_data['total_variable']),
                ('BASE', ces_data['base']),
                ('NETO CESANTIAS', ces_data['pres'] - ces_data['partials']),
                ('INTERESES A LA FECHA', i_fecha ),
                ('PROVISIONES PREVIAS', t_provs)
            ]
            log = log
            rate = 100
            name = 'PROV. INTERESES DE CESANTIAS' + ' ' + str(ref_date) + ' - ' + str(ref_to_date)
        return base,1,rate,name,log,False
    def _prim_liq(self, ld):
        base = 0
        rate = 100
        name = ''
        log = ''
        skip = ld['employee'].tipo_coti_id.code in ['12', '19']
        skip |= ld['contract'].modality_salary == 'integral'
        if skip:
            return 0,0,0,0,0,False

        date_to = ld['payslip'].date_liquidacion or ld['payslip'].date_to
        from_month = 1 if ld['payslip'].date_from.month <= 6 else 7
        date_from = ld['payslip'].date_from.replace(
            month=from_month, day=1)
        if date_from < ld['contract'].date_start:
            date_from = ld['contract'].date_start

        prima_data = self.get_prst(date_from, date_to, ld, include=True, prst='prima')

        log = [
            ('FECHA DESDE', str(from_month)),
            ('FECHA HASTA', str(date_to)),
            ('DIAS LABORADOS', prima_data['days']),
            ('DIAS DE LICENCIA', prima_data['days_mat']),
            ('DIAS DE SUSPENSION', prima_data['susp']),
            ('CAMBIO DE SALARIO', prima_data['wc']),
            ('TOTAL SALARIO', prima_data['twage']),
            ('TOTAL VARIABLE', prima_data['total_variable']),
            ('TOTAL FIJO', prima_data['total_fix']),
            ('BASE', prima_data['base']),
            ('NETO PRIMA A LA FECHA', prima_data['pres']),
            ('PARCIALES', prima_data['partials']),
        ]

        base = prima_data['net_pres']
        log = log
        prev_prim_liq = """
            SELECT SUM(HPC.total)
            FROM hr_payslip_line as HPC
            INNER JOIN hr_payslip as HP ON HP.id = HPC.slip_id
            WHERE HPC.code = %s
                AND HP.state = 'done'
                AND HP.contract_id = %s
                AND HP.slip_id != %s
                AND HP.date_from <= %s
                AND HP.date_to >= %s
        """
        # Ejecutar la consulta con parámetros vinculados
        self._cr.execute(prev_prim_liq, ('PRIM_LIQ', ld['contract'].id, self.id, date_to, from_month))

        prev_prim_liq_total = self._cr.fetchone()[0]

        if prev_prim_liq_total:
            prev_prim_liq = prev_prim_liq_total
            base = base - prev_prim_liq
            log.append(('PRIMA LIQUIDADA EN OTRAS LIQUIDACIONES',prev_prim_liq))

        return base,1,rate,name,log,False
    def _prv_vac(self, ld):
        skip = ld['employee'].tipo_coti_id.code in ['12', '19']
        if skip:
            return 0,0,0,0,0,0
        base = 0
        rate = 100
        name = ''
        log = ''
        item = ld['result_rules_co']
        if self.env.company.simple_provisions:
            base_prima_total = 0
            base_primas_items = []
            base_prima_total = ld['categories'].BASIC
            for rule_code, rule_data in item.dict.items():
                total = rule_data.get('total', 0)
                if rule_code != 'BASIC' and rule_code != 'AUX000' and rule_data.get('base_vacaciones', False):
                    base_prima_total += total
                    base_primas_items.append(rule_code)
            total_earn = base_prima_total
            for code in  base_primas_items:
                total_earn += sum(p.get_payslip_concept_total(code) for p in ld['payslips_month'])
            prv_prev = sum([p.get_payslip_concept_total('PRV_VAC') for p in ld['payslips_month']]) * 100/4.17
            base = total_earn - prv_prev
            rate = 4.17
            return base,1,rate,name,log,False
        else:
            init_date = self.env.company.init_vac_date
            k_dt_start = ld['contract'].date_start
            if init_date and  k_dt_start < init_date:
                k_dt_start = self.env.company.init_vac_date
            ref_date = ld['payslip'].date_to
            if ld['contract'].date_end:
                ref_date = min(ld['contract'].date_end,ld['payslip'].date_to)
            
            ref_date = ref_date - relativedelta(years=1) + relativedelta(days=1)
            if ref_date < k_dt_start:
                ref_date = k_dt_start
            ref_to_date = ld['contract'].date_end or ld['payslip'].date_liquidacion or ld['payslip'].date_to
            days_itval = days360(ref_date, ref_to_date)
            # Calculo de acumulados
            basic = ld['rules_computed'].BASIC
            basic += sum([p.get_payslip_concept_total('BASIC') for p in ld['payslips_month']])
            # Informacion de propia nomina
            base_prima_total = 0
            base_primas_items = []
            for rule_code, rule_data in item.dict.items():
                total = rule_data.get('total', 0)
                if rule_code != 'BASIC' and rule_code != 'AUX000' and rule_data.get('base_vacaciones', False):
                    base_prima_total += total
                    base_primas_items.append(rule_code)
            total_earn = base_prima_total + basic
            earnings = 0
            for code in  base_primas_items:
                total_earn += sum(p.get_payslip_concept_total(code) for p in ld['payslips_month'])
                earnings += sum(x[1] for x in self.get_interval_concept(code, ref_date, ref_to_date, ld['contract'].id) if x[1] is not None)
            if days_itval > 360:
                days_itval = 360
            # Promedios del periodo
            if days_itval >= 30:
                t_earnings = (earnings + total_earn) * 30 / days_itval
            else:
                t_earnings = total_earn
            avr =  t_earnings
            sus_lic = ld['slip'].leave_days_ids.filtered(lambda x: x.state == 'validated' and x.leave_id.holiday_status_id.no_payable)
            qty_sus = sum([aus.days_payslip for aus in sus_lic ])
            #sus_vac_book = ld['contract'].get_sus_per()
            accounts = tuple(self.salary_rule_accounting.credit_account.ids)

            if accounts:  # Verificar si la lista de cuentas no está vacía
                provs_q = """
                    SELECT SUM(AML.credit) - SUM(AML.debit)
                    FROM account_move_line AS AML
                    INNER JOIN res_partner AS RP ON RP.id = AML.partner_id
                    INNER JOIN hr_employee AS HC ON HC.address_home_id = RP.employee_id
                    WHERE HC.id = %s 
                        AND AML.state = 'posted'
                        AND AML.account_id IN %s
                        AND AML.date <= %s
                """
                self._cr.execute(provs_q, (ld['employee'].id, accounts, ld['payslip'].date_to))
                provs = self._cr.fetchone()
            else:
                # Aquí puedes decidir cómo manejar el caso cuando no hay cuentas
                # Por ejemplo, podrías asignar un valor predeterminado a provs o simplemente omitir la ejecución de la consulta.
                provs = []  

            t_provs = provs[0] if provs and provs[0] else 0
            log = [
                ('SALARIO', ld['wage']),
                ('FECHA INICIO', str(ref_date)),
                ('FECHA FIN', str(ref_to_date)),
                ('PROMEDIO DEVENGOS', t_earnings),
                ('PROMEDIO DEVENGOS !!!', avr),
                ('DIAS REFERENCIA SIN LICENCIAS', days_itval),
                ('LICENCIAS/SUSPENSIONES NOMINA', qty_sus),
                #('LICENCIAS/SUSPENSIONES LIBRO VACACIONES', sus_vac_book),
                ('PROVISIONES REALIZADAS PREVIAMENTE', t_provs)
            ]
            log = log

            prev_vac_liq = False
            if ld['payslips_month']:
                payslips_month = [p.id for p in ld['payslips_month']]
                payslips_month = tuple(payslips_month if len(payslips_month) > 1 else [payslips_month[0], 0])
                prev_vac_liq_q = """
                    SELECT total, quantity 
                    FROM hr_payslip_line
                    WHERE slip_id IN %s AND code = 'VAC_LIQ'
                """
                self._cr.execute(prev_vac_liq_q, (payslips_month,))
                prev_vac_liq = self._cr.fetchall()
            qty = ld['contract'].get_pend_vac(date_calc=ref_to_date, sus=qty_sus)
            if prev_vac_liq:
                qty = prev_vac_liq[0][1]
                prev_vac_liq = sum([x[0] for x in prev_vac_liq])
                reg_prov = avr * qty / 15
                base = (reg_prov - prev_vac_liq)
                log.append(('TOTAL PROVISIONADO A LA FECHA', reg_prov))
                log.append(('DIAS DE VACACIONES PROVISIONADOS', 0))
            elif qty:
                payslip_vac = ld['slip'].leave_days_ids.filtered(lambda x: x.state == 'validated' and x.leave_id.holiday_status_id.is_vacation)
                qty_disf = sum([aus.days_payslip for aus in payslip_vac])
                payed_per = ld['result_rules_co']['VAC_PAG']['quantity']
                qty -= (qty_disf + payed_per)
                reg_prov = avr * qty / 30
                base = reg_prov - t_provs
                log.append(('TOTAL PROVISIONADO A LA FECHA', reg_prov))
                log.append(('DIAS DE VACACIONES PROVISIONADOS', qty))
        return base,1,rate,name,log,False

    def get_prst(self, date_start, date_end, ld, include=False, prst='False', nocesly=False):
        # Definiendo los dias de salario a calcular
        e_v = ld['annual_parameters']
        item = ld['result_rules_co']
        plain_days = days360(date_start, date_end)
        days = plain_days

        # Restando dias de licencia de maternidad que es tenido en cuenta como un ingreso separado
        mat_lic = self.get_interval_concept_qty('MAT', ld, date_start, date_end, ld['contract'].id)
        a_mat_lic_qty = sum(p.get_payslip_concept('MAT').quantity if p.get_payslip_concept('MAT') else 0 for p in ld['payslips_month'] if p)

        if mat_lic is not None:
            days_mat = sum([x[2] for x in mat_lic]) + a_mat_lic_qty
        else:
            days_mat = a_mat_lic_qty 
        days -= days_mat

        if self.env.company.prst_wo_susp and prst == 'prima':
            susp = 0
        else:
            susp = sum([i.number_of_days for i in self.env['hr.leave'].search([
                ('date_from', '>=', date_start), 
                ('date_to', '<=', date_end), 
                ('state', '=', 'validate'), 
                ('employee_id', '=', ld['contract'].employee_id.id), 
                ('unpaid_absences', '=', True)])])
        
        days -= susp

        # Asegurar que los días no sean negativos
        days = max(days, 0)
        
        # Determinar el punto de referencia para cambios de salario
        dt_wc = date_end - relativedelta(months=3) if date_end.month >= 3 else date(date_end.year, 1, 1)
        
        # Usar parámetros en la consulta SQL para evitar problemas de tipo
        wage_change_q = """
            SELECT id FROM hr_contract_change_wage
            WHERE contract_id = %s AND date_start > %s AND date_start <= %s
        """
        params = (ld['contract'].id, dt_wc.strftime('%Y-%m-%d'), date_end.strftime('%Y-%m-%d'))
        self._cr.execute(wage_change_q, params)
        wage_changes = self._cr.fetchall()

        # En prima siempre se toma el devengado promedio
        if prst == 'prima':
            wage_changes = True

        # Calculo de salario
        a_basic = ld['rules_computed'].BASIC
        if not wage_changes:
            lwq = """
                SELECT wage FROM hr_contract_change_wage
                WHERE contract_id = %s AND date_start <= %s
                ORDER BY date_start DESC LIMIT 1
            """
            params = (ld['contract'].id, date_end.strftime('%Y-%m-%d'))
            self._cr.execute(lwq, params)
            lw = self._cr.fetchone()
            wage = lw[0] if lw else ld['wage']
            twage = wage * days / 30
        else:
            wage_q = """
                SELECT date_start, wage FROM hr_contract_change_wage
                WHERE contract_id = %s AND date_start BETWEEN %s AND %s
                ORDER BY date_start ASC
            """
            params = (ld['contract'].id, date_start.strftime('%Y-%m-%d'), date_end.strftime('%Y-%m-%d'))
            self._cr.execute(wage_q, params)
            segments = self._cr.fetchall()
            date_step = date_start
            wag_seg = []
            for count, seg in enumerate(segments):
                next_dt = segments[count + 1][0] - relativedelta(days=1) if count + 1 < len(segments) else date_end
                ds_e = seg[0]
                if date_step == date_start and count == 0:
                    rwq = """
                        SELECT wage FROM hr_contract_change_wage
                        WHERE contract_id = %s AND date_start <= %s
                        ORDER BY date_start DESC LIMIT 1
                    """
                    params = (ld['contract'].id, date_step.strftime('%Y-%m-%d'))
                    self._cr.execute(rwq, params)
                    rw = self._cr.fetchone()
                    ref_wag = rw[0] if rw else ld['wage']
                    if date_step != ds_e:
                        dt_dum = ds_e - relativedelta(days=1)
                        wag_seg.append((date_step, dt_dum, ref_wag))
                    wag_seg.append((ds_e, next_dt, seg[1]))
                    date_step = ds_e
                else:
                    wag_seg.append((ds_e, next_dt, seg[1]))
                    date_step = ds_e

            twage = sum([(sgmt[2] * days360(sgmt[0], sgmt[1], method_eu=True) - susp - days_mat) / 30 for sgmt in wag_seg])
            if not twage:
                lwq = """
                    SELECT wage FROM hr_contract_change_wage
                    WHERE contract_id = %s AND date_start <= %s 
                    ORDER BY date_start DESC LIMIT 1
                """
                params = (ld['contract'].id, date_end.strftime('%Y-%m-%d'))
                self._cr.execute(lwq, params)
                lw = self._cr.fetchone()
                wage = lw[0] if lw else e_v.smmlv_monthly or 0.0 if ld['contract'].minimum_wage else ld['wage']
                twage = wage * days / 30

        if ld['contract'].subcontract_type:
            twage = 0
        a_mat_lic = ld['rules_computed'].MAT
        if mat_lic is not None:
            ml_amount = sum([x[1] for x in mat_lic]) + a_mat_lic
        else:
            ml_amount = a_mat_lic 

        # Aux de transporte
        if ld['contract'].modality_aux == 'basico' and ld['rules_computed'].AUX000 == 0:
            aux_ev  = ld['annual_parameters'].transportation_assistance_monthly
            aux = aux_ev * (days + days_mat) / 30
            days_aux = days + days_mat
        else:
            a_aux = ld['rules_computed'].AUX000
            days_aux_a = 0
            if ld['worked_days'].WORK100: #.number_of_days
                days_aux_a = ld['worked_days'].WORK100.number_of_days
            days_aux_o = self.get_interval_concept_qty('AUX000', ld, date_start, date_end, ld['contract'].id)
            if days_aux_o is not None:
                days_aux = sum(x[2] for x in days_aux_o if len(x) > 2 and x[2] is not None) + days_aux_a
            else:
                days_aux = days_aux_a
            aux_itv = self.get_interval_concept('AUX000', date_start, date_end, ld['contract'].id)
            aux = sum([x[1] for x in aux_itv]) + (a_aux if include else 0)
        
        base_prima_total = 0
        base_primas_items = []
        for rule_code, rule_data in item.dict.items():
            total = rule_data.get('total', 0)
            if rule_code != 'BASIC' and rule_code != 'AUX000' and rule_data.get('base_prima', False):
                base_prima_total += total
                base_primas_items.append(rule_code)
        total_variable = base_prima_total
        extra = 0
        for code in base_primas_items:
            extras = (self.get_interval_concept(code, date_start, date_end, ld['contract'].id) for p in ld['payslips_month'])
            extra += sum([x[1] for x in extras if len(x) > 1 and x[1] is not None])
        # Definir los campos base según el tipo de acumulado
        if prst == 'ces':
            base_field = 'base_cesantias'
        elif prst == 'prima':
            base_field = 'base_prima'
        else:
            raise ValueError("Tipo debe ser 'cesantias' o 'prima'")
        # Definir la condición adicional para base_auxtransporte_tope
        str_base_auxtransporte_tope = f'and hc.{base_field} = true'
        # Ejecutar la consulta SQL
        self.env.cr.execute(f"""
            Select Sum(accumulated) as accumulated
            From
            (
                Select COALESCE(sum(pl.total),0) as accumulated 
                    From hr_payslip as hp 
                    Inner Join hr_payslip_line as pl on  hp.id = pl.slip_id 
                    Inner Join hr_salary_rule hc on pl.salary_rule_id = hc.id {str_base_auxtransporte_tope} and hc.code != 'AUX000'
                    Inner Join hr_salary_rule_category hsc on hc.category_id = hsc.id and hsc.code != 'BASIC' 
                    WHERE hp.state in ('done','paid') and hp.contract_id = %s
                    AND (hp.date_from between %s and %s
                        or
                        hp.date_to between %s and %s )
                Union 
                Select COALESCE(sum(pl.amount),0) as accumulated
                    From hr_accumulated_payroll as pl
                    Inner Join hr_salary_rule hc on pl.salary_rule_id = hc.id {str_base_auxtransporte_tope} and hc.code != 'AUX000'
                    Inner Join hr_salary_rule_category hsc on hc.category_id = hsc.id and hsc.code != 'BASIC' 
                    WHERE pl.employee_id = %s and pl.date between %s and %s
            ) As A
        """, (ld['contract'].id, date_start, date_end, date_start, date_end, ld['employee'].id, date_start, date_end))
        
        res = self.env.cr.fetchone()

        extra += res and res[0] or 0.0
        total_variable = ml_amount + extra + total_variable
        total_fix = aux
        salmin = e_v.smmlv_monthly
        if ld['contract'].modality_aux == 'basico':
            if days and (twage + total_variable) * 30 / days > 2 * salmin:
                total_fix = 0
            else:
                total_fix = aux
        # Base de ingresos
        if (days + days_mat) < 30:
            total = twage
            if days + days_mat > 0 and total / (days + days_mat) <= salmin * 2:
                total += total_fix
        else:
            total = twage + total_variable
            if days + days_mat > 0 and (total / (days + days_mat)) <= salmin * 2:
                total += total_fix

        # Base de calculo
        if days + days_mat:
            if days == days_aux or (days + days_mat) >= 30:
                base = total * 360 / (days + days_mat) / 360 * 30 if (days + days_mat) else 0
            else:
                base = (total - total_fix) * 360 / (days + days_mat) / 360 * 30 if (days + days_mat) else 0
                base += total_fix * 360 / days / 360 * (days) if days else 0
            if (days + days_mat) < 30:
                base += total_variable
        else:
            base = 0

        # Prestacion
        pres = base * (days + days_mat) / 360

        # Prest parciales
        # Prest parciales en intervalo de referencia
        t_part = 0
        if prst == 'ces':
            part = self.get_interval_concept('CES_PART', date_start, date_end, ld['contract'].id)
            cesly = self.get_interval_concept('CESLY', date_start, date_end, ld['contract'].id) if not nocesly else []
            t_part = sum([x[1] for x in part]) + sum([x[1] for x in cesly])
        elif prst == 'prima':
            if ld['payslip'].struct_process == 'contract':
                part_date_end = ld['payslip'].date_to
            else:
                part_date_end = date_end
            part = self.get_interval_concept('PRIMA', date_start, part_date_end, ld['contract'].id)
            t_part = sum([x[1] for x in part])

        net_pres = pres - t_part

        res = {
            'pres': pres,
            'days': days,
            'plain_days': plain_days,
            'net_pres': net_pres,
            'base': base,
            'twage': twage,
            'total_variable': total_variable,
            'total_fix': total_fix,
            'days_mat': days_mat,
            'wc': 1 if wage_changes else 0,
            'partials': t_part,
            'susp': susp,
        }

        return res

    def _prima(self, data_payslip):
        skip = data_payslip['employee'].tipo_coti_id.code in ['12', '19']
        skip |= data_payslip['contract'].modality_salary == 'integral'
        if skip:
            return 0,0,0,0,0,0
        
        from_month = 1 if data_payslip['slip'].date_from.month <= 6 else 7
        to_month = 6 if data_payslip['slip'].date_from.month <= 6 else 12
        to_day = 30 if data_payslip['slip'].date_from.month <= 6 else 31
        date_from = data_payslip['slip'].date_from.replace(month=from_month, day=1)
        date_to = data_payslip['slip'].date_from.replace(month=to_month, day=to_day)
        if data_payslip['slip'].reason_retiro:
            date_to = data_payslip['slip'].date_liquidacion
        if date_from < data_payslip['contract'].date_start:
            date_from = data_payslip['contract'].date_start
        prima_data = self.get_prst(date_from, date_to, data_payslip, include=True, prst='prima')
        name = 'PRIMAS DEl' + ' ' + str(date_from) + ' - ' + str(date_to)
        log = [
            ('FECHA DESDE', date_from),
            ('FECHA HASTA', date_to),
            ('DIAS LABORADOS', prima_data['days']),
            ('DIAS DE LICENCIA', prima_data['days_mat']),
            ('DIAS DE SUSPENSION', prima_data['susp']),
            ('CAMBIO DE SALARIO', prima_data['wc']),
            ('TOTAL SALARIO', prima_data['twage']),
            ('TOTAL VARIABLE', prima_data['total_variable']),
            ('TOTAL FIJO', prima_data['total_fix']),
            ('BASE', prima_data['base']),
            ('NETO PRIMA A LA FECHA', prima_data['pres']),
            ('PARCIALES', prima_data['partials']),
        ]
        _logger.info(log)    
        return  prima_data['pres'],1,100,name,log,prima_data

    def _cesantias(self, data_payslip): #CESANTIAS
        skip = data_payslip['employee'].tipo_coti_id.code in ['12', '19']
        skip |= data_payslip['contract'].modality_salary == 'integral'
        if skip:
            return 0,0,0,0,0,0
        
        date_ref = data_payslip['slip'].date_to - relativedelta(years=1)
        date_from = date_ref.replace(month=1, day=1)
        date_to = date_ref.replace(month=12, day=31)
        if date_from < data_payslip['contract'].date_start:
            date_from = data_payslip['contract'].date_start
        if data_payslip['slip'].reason_retiro:
            date_to = data_payslip['slip'].date_liquidacion
            date_from = data_payslip['slip'].date_liquidacion.replace(month=1, day=1)
        prima_data = self.get_prst(date_from, date_to, data_payslip, include=False, prst='ces')
        name = 'CESANTIAS DEl' + ' ' + str(date_from) + ' - ' + str(date_to)
        log = [
            ('FECHA DESDE', date_from),
            ('FECHA HASTA', date_to),
            ('DIAS LABORADOS', prima_data['days']),
            ('DIAS DE LICENCIA', prima_data['days_mat']),
            ('DIAS DE SUSPENSION', prima_data['susp']),
            ('CAMBIO DE SALARIO', prima_data['wc']),
            ('TOTAL SALARIO', prima_data['twage']),
            ('TOTAL VARIABLE', prima_data['total_variable']),
            ('TOTAL FIJO', prima_data['total_fix']),
            ('BASE', prima_data['base']),
            ('NETO PRIMA A LA FECHA', prima_data['pres']),
            ('PARCIALES', prima_data['partials']),
        ]
        #_logger.info(log)    
        return  prima_data['pres'],1,100,name,log,prima_data

    def _intcesantias(self, data_payslip): #INTCESANTIAS
        skip = data_payslip['employee'].tipo_coti_id.code in ['12', '19']
        skip |= data_payslip['contract'].modality_salary == 'integral'
        if skip:
            return 0,0,0,0,0,0
        date_ref = data_payslip['slip'].date_to - relativedelta(years=1)
        date_from = date_ref.replace(month=1, day=1)
        date_to = date_ref.replace(month=12, day=31)
        if date_from < data_payslip['contract'].date_start:
            date_from = data_payslip['contract'].date_start
        if data_payslip['slip'].reason_retiro:
            date_to = data_payslip['slip'].date_liquidacion
        prima_data = self.get_prst(date_from, date_to, data_payslip, include=False, prst='ces')
        name = 'INT. CESANTIAS DEl' + ' ' + str(date_from) + ' - ' + str(date_to)
        log = ''
        rate = 0.12
        total = prima_data['pres'] * rate

        return  total,1,12,name,log,prima_data    

    def _totaldev(self, ld): #	TOTALDEV
        base = 0
        rate = 100
        name = ''
        log = ''
        total_earnings = ld['categories'].DEV_SALARIAL + ld['categories'].DEV_NO_SALARIAL + ld['categories'].PRESTACIONES_SOCIALES  + ld['categories'].AUX
        base = total_earnings
        return base,1,rate,name,log,False

    def _totalded(self, ld): # 	TOTALDED
        base = 0
        rate = 100
        name = ''
        log = ''
        total_deductions = ld['categories'].DEDUCCIONES
        if ld['contract'].limit_deductions and total_deductions > 0.5 * ld['concepts'].TOTALDEV:
            if ld['slip'].struct_process == 'Nomina':
                raise UserError(u"La nomina de {emp} presenta un total de deducciones "
                              u"superior al 50% de los devengos y el contrato esta configurado para limitarlo.".format(
                                emp=ld['employee'].name))
        base = total_deductions
        return base,1,rate,name,log,False

    def _net(self, ld):
        """
        Neto a pagar
        :param ld:
        :return: Valor a pagar al empleado
        """
        base = 0
        rate = 100
        name = ''
        log = ''
        total_earnings = ld['categories'].TOTALDEV 
        total_deductions = ld['categories'].TOTALDED
        neto = total_earnings + total_deductions 
        # neto = 0 if neto < 0 else neto
        base = neto
        return base,1,rate,name,log,False

    def get_interval_concept_qty(self, concept, ld, start, end, contract=False):
        contract_id = contract

        query = """
            SELECT SUBSTRING(hp.date_from::VARCHAR, 1, 7), SUM(hpc.total), SUM(hpc.quantity)
            FROM hr_payslip_line hpc
            INNER JOIN hr_payslip hp ON hpc.slip_id = hp.id
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

        return res
    def get_interval_concept(self, concept, start, end, contract):
        """
        Fetches and summarizes concept totals from payroll data within a specified date range.

        Parameters:
        - concept (str): The concept code to summarize.
        - start (str): Start date in 'YYYY-MM-DD' format.
        - end (str): End date in 'YYYY-MM-DD' format.
        - contract (int or False): Contract ID to filter by, if any. If False, uses the instance's contract ID.

        Returns:
        A list of tuples, each containing a month in 'YYYY-MM' format and the sum of the concept totals for that month.
        """
        contract_id = contract
        query = """
            SELECT SUBSTRING(hp.date_to::VARCHAR, 1, 7), SUM(hpc.total)
            FROM hr_payslip_line hpc
            INNER JOIN hr_payslip hp ON hpc.slip_id = hp.id
            WHERE hpc.code = %s
            AND hp.date_to >= %s
            AND hp.date_from <= %s
            AND hp.contract_id = %s
            GROUP BY SUBSTRING(hp.date_to::VARCHAR, 1, 7)
        """
        # Using parameterized query execution for safety
        self._cr.execute(query, (concept, start, end, contract_id))
        res = self._cr.fetchall()
        return res



    def get_interval_category(self, category, start, end, exclude=(), contract=False):
        """
        Fetches and summarizes category totals from payroll data within a specified date range,
        optionally excluding specific codes.

        Parameters:
        - category (str): The payroll concept category to summarize.
        - start (str): Start date in 'YYYY-MM-DD' format.
        - end (str): End date in 'YYYY-MM-DD' format.
        - exclude (tuple): Optional tuple of concept codes to exclude from the summary.
        - contract (int or False): Optional contract ID to filter by. Uses the instance's contract ID if False.

        Returns:
        A list of tuples, each containing a month in 'YYYY-MM' format and the sum of category totals for that month.
        """
        contract_id = contract.id
        prefetch_q = """
            SELECT pl.id FROM hr_payslip_line AS pl 
            INNER JOIN hr_salary_rule_category hc ON pl.category_id = hc.id 
            LEFT JOIN hr_salary_rule_category hc_parent ON hc.parent_id = hc_parent.id 
            WHERE (hc.code = %s OR hc_parent.code = %s) AND contract_id = %s
        """
        self._cr.execute(prefetch_q, (category, category, contract_id))
        prefetch = self._cr.fetchall()

        if prefetch:
            # Construct a tuple of ids for the SQL IN clause
            pre_ids = tuple(x[0] for x in prefetch) + (0,)

            exception = ''.join(" AND hpc.code != %s" for _ in exclude)
            parameters = [start, end] + list(exclude) + [pre_ids]
            
            catq = """
                SELECT SUBSTRING(hp.date_from::VARCHAR, 1, 7), SUM(hpc.total)
                FROM hr_payslip_line hpc
                INNER JOIN hr_payslip hp ON hpc.slip_id = hp.id
                WHERE hp.date_to >= %s
                AND hp.date_from <= %s
                {} 
                AND hpc.id IN %s
                GROUP BY SUBSTRING(hp.date_from::VARCHAR, 1, 7)
            """.format(exception)

            self._cr.execute(catq, parameters)
            res = self._cr.fetchall()
        else:
            res = []
        return res


class hr_types_faults(models.Model):
    _name = 'hr.types.faults'
    _description = 'Tipos de faltas'

    name = fields.Char('Nombre', required=True)
    description = fields.Text('Descripción')

class Hr_payslip_line(models.Model):
    _inherit = 'hr.payslip.line'

    amount = fields.Float(digits='Payroll')
    quantity = fields.Float(digits='Payroll', default=1.0)
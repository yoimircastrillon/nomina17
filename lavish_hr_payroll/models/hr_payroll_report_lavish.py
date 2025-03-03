# -*- coding: utf-8 -*-
from odoo import tools
from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError
from datetime import datetime
from pytz import timezone
import json
import pandas as pd
import numpy as np 
import base64
import io
import xlsxwriter
import logging
from odoo.tools import get_lang
_logger = logging.getLogger(__name__)
class HrPayrollReportlavishFilter(models.TransientModel):
    _name = "hr.payroll.report.lavish.filter"
    _description = "Filtros - Informe Liquidación"
    
    payslip_ids = fields.Many2many('hr.payslip.run',string='Lotes de nómina', domain=[('state', '!=', 'draft')])    
    liquidations_ids= fields.Many2many('hr.payslip', string='Liquidaciones individuales', domain=[('payslip_run_id', '=', False)])
    show_date_of_entry = fields.Boolean(string="Fecha de Ingreso", default= True)
    show_job_placement = fields.Boolean(string="Ubicación Laboral", default= True)
    show_sectional = fields.Boolean(string="Seccional", default= True)
    show_department = fields.Boolean(string="Departamento", default= True)
    show_analytical_account = fields.Boolean(string="Cuenta Analítica", default= True)
    show_job = fields.Boolean(string="Cargo", default= True)
    show_sena_code = fields.Boolean(string="Código SENA", default= True)
    show_basic_salary = fields.Boolean(string="Salario Base", default= True)
    show_dispersing_account = fields.Boolean(string="Cuenta Dispersora", default=True)
    show_bank_officer = fields.Boolean(string="Banco del Funcionario", default=True)
    show_bank_account_officer = fields.Boolean(string="Cuenta Bancaria del Funcionario", default=True)
    not_show_rule_entity = fields.Boolean(string="No mostrar las reglas + entidad", default=False)
    not_show_quantity = fields.Boolean(string="No mostrar cantidades horas extra y prestaciones", default=False)
    excel_file = fields.Binary('Excel file')
    excel_file_name = fields.Char('Excel name')
    pdf_report_payroll = fields.Html('Reporte en PDF')

    def name_get(self):
        result = []
        for record in self:            
            result.append((record.id, "Informe de nómina"))
        return result

    def show_all_fields(self):
        self.show_date_of_entry = True
        self.show_job_placement = True
        self.show_sectional = True
        self.show_department = True
        self.show_analytical_account = True
        self.show_job = True
        self.show_sena_code = True
        self.show_basic_salary = True
        self.show_dispersing_account = True
        self.show_bank_officer = True
        self.show_bank_account_officer = True
        return {
            'context': self.env.context,
            'view_type': 'form',
            'view_mode': 'form',
            'res_model': 'hr.payroll.report.lavish.filter',
            'res_id': self.id,
            'type': 'ir.actions.act_window',
            'target': 'new',
        }

    def not_show_all_fields(self):
        self.show_date_of_entry = False
        self.show_job_placement = False
        self.show_sectional = False
        self.show_department = False
        self.show_analytical_account = False
        self.show_job = False
        self.show_sena_code = False
        self.show_basic_salary = False
        self.show_dispersing_account = False
        self.show_bank_officer = False
        self.show_bank_account_officer = False
        return {
            'context': self.env.context,
            'view_type': 'form',
            'view_mode': 'form',
            'res_model': 'hr.payroll.report.lavish.filter',
            'res_id': self.id,
            'type': 'ir.actions.act_window',
            'target': 'new',
        }

    def get_hr_payslip_template_signature(self):
        obj_company = self.env['res.company']
        for lote in self.payslip_ids:
            obj_company = lote.company_id

        for liq in self.liquidations_ids:
            obj_company = liq.company_id

        obj = self.env['hr.payslip.reports.template'].search([('company_id','=',obj_company.id),('type_report','=','nomina')])
        return obj

    def generate_excel(self):
        obj_payslips = self.env['hr.payslip']
        min_date = ''
        max_date = ''

        if len(self.payslip_ids) == 0 and len(self.liquidations_ids) == 0:
            raise ValidationError(_('Debe seleccionar algún filtro.'))

        #Obtener las liquidaciones de los lotes seleccionados
        if len(self.payslip_ids) > 0:            
            ids = self.payslip_ids.ids
            for payslip in self.payslip_ids:
                if min_date == '' and max_date == '':
                    min_date = payslip.date_start
                    max_date = payslip.date_end                
                else: 
                    if payslip.date_start < min_date:
                        min_date = payslip.date_start
                    if payslip.date_end > max_date:
                        max_date = payslip.date_end

            obj_payslips += self.env['hr.payslip'].search([('payslip_run_id','in',ids)])
        
        #Obtener las liquidaciones seleccionadas
        if len(self.liquidations_ids) > 0:
            obj_payslips += self.liquidations_ids

            for payslip in self.liquidations_ids:
                if min_date == '' and max_date == '':
                    min_date = payslip.date_from
                    max_date = payslip.date_to               
                else: 
                    if payslip.date_from < min_date:
                        min_date = payslip.date_from
                    if payslip.date_to > max_date:
                        max_date = payslip.date_to
        lang = self.env.user.lang or get_lang(self.env).code
        #Obtener ids a filtrar
        str_ids = ''
        for i in obj_payslips:
            if str_ids == '':
                str_ids = str(i.id)
            else:
                str_ids = str_ids+','+str(i.id)

        min_date = min_date.strftime('%Y-%m-%d')
        max_date = max_date.strftime('%Y-%m-%d')

        query_novedades = '''
            Select c.identification_id as "Identificación", c.name as "Empleado", COALESCE(a.private_name,b.name::jsonb ->> '%s', b.name::jsonb ->> 'en_US','') as "Novedad",
                    Case When row_number() over(partition by c.identification_id) = max_item Then 1 else 0 end as "EsUltimo"
            From hr_leave as a
            Inner Join hr_leave_type as b on a.holiday_status_id = b.id
            Inner Join hr_employee as c on a.employee_id = c.id
            Inner Join (Select max(item) as max_item,identification_id
                        From (
                            Select row_number() over(partition by c.identification_id) as item,
                                c.identification_id, COALESCE(a.private_name,b.name::jsonb ->> '%s', b.name::jsonb ->> 'en_US','') as novedad
                            From hr_leave as a
                            Inner Join hr_leave_type as b on a.holiday_status_id = b.id
                            Inner Join hr_employee as c on a.employee_id = c.id
                            Where a.state='validate' 
                                    and ((a.request_date_from >= '%s' and a.request_date_from <= '%s') or (a.request_date_to >= '%s' and a.request_date_to <= '%s'))
                        )as A
                        group by identification_id
                    ) as max_nov on c.identification_id = max_nov.identification_id
            Where a.state='validate' 
                  and ((a.request_date_from >= '%s' and a.request_date_from <= '%s') or (a.request_date_to >= '%s' and a.request_date_to <= '%s'))
        ''' % (lang,lang,min_date,max_date,min_date,max_date,min_date,max_date,min_date,max_date)

        query_days = '''
                    Select  c.item as "Item",
                    COALESCE(c.identification_id,'') as "Identificación",
                    COALESCE(c.name,'') as "Empleado",
                    COALESCE(d.date_start,'1900-01-01') as "Fecha Ingreso",
                    COALESCE(e.name,'') as "Seccional",
                    COALESCE(f.name,'') as "Cuenta Analítica",
                    COALESCE(g.name::jsonb ->> '%s', g.name::jsonb ->> 'en_US', NULL) as "Cargo",
                    COALESCE(rb.name,'') as "Banco",
                    COALESCE(bank.acc_number,'') as "Cuenta Bancaria",
                    COALESCE(ajb.name,'') as "Cuenta Dispersora",
                    COALESCE(d.code_sena,'') as "Código SENA",
                    COALESCE(rp.name,'') as "Ubicación Laboral",
                    COALESCE(dt.name,'') as "Departamento",
                    COALESCE(d.wage,0) as "Salario Base",'' as "Novedades",
                    COALESCE(wt.short_name,COALESCE(wt.name::jsonb ->> '%s', wt.name::jsonb ->> 'en_US','')) as "Regla Salarial",
                    COALESCE(wt.short_name,COALESCE(wt.name::jsonb ->> '%s', wt.name::jsonb ->> 'en_US','')) as "Reglas Salariales + Entidad",
                    'Días' as "Categoría",0 as "Secuencia",COALESCE(Sum(b.number_of_days),0) as "Monto"
            From hr_payslip as a 
            --Info Empleado
            Inner Join (Select distinct row_number() over(order by a.name) as item,
                        a.id,identification_id,a.name,a.branch_id,a.job_id,
                        address_id,work_contact_id,a.department_id
                        From hr_employee as a
                        inner join hr_payslip as p on a.id = p.employee_id and p.id in (%s)
                        group by a.id,identification_id,a.name,a.branch_id,a.job_id,address_id,work_contact_id,a.department_id) as c on a.employee_id = c.id
            Inner Join hr_contract as d on a.contract_id = d.id
            Inner Join hr_payslip_worked_days as b on a.id = b.payslip_id
            inner join hr_work_entry_type as wt on b.work_entry_type_id = wt.id
            Left join lavish_res_branch as e on c.branch_id = e.id
            Left join account_analytic_account as f on d.analytic_account_id = f.id
            Left join hr_job g on c.job_id = g.id
            Left Join hr_department dt on c.department_id = dt.id
            Left Join res_partner rp on c.address_id = rp.id
            --Info Bancaria
            Left join res_partner_bank bank on c.work_contact_id = bank.partner_id and bank.company_id = a.company_id and bank.is_main = True
            Left join res_bank rb on bank.bank_id = rb.id 
            Left join account_journal ajb on bank.payroll_dispersion_account = ajb.id 
            Where a.id in (%s)     
            Group By c.item,c.identification_id,c.name,d.date_start,e.name,
                        f.name,g.name,rb.name,bank.acc_number,ajb.name,
                        d.code_sena,rp.name,dt.name,d.wage,wt.name,wt.short_name
        ''' % (lang,lang,lang,str_ids,str_ids)

        query_amount_rules ='''
            Select  c.item as "Item",
                    COALESCE(c.identification_id,'') as "Identificación",
                    COALESCE(c.name,'') as "Empleado",
                    COALESCE(d.date_start,'1900-01-01') as "Fecha Ingreso",
                    COALESCE(e.name,'') as "Seccional",
                    COALESCE(f.name,'') as "Cuenta Analítica",
                    COALESCE(g.name::jsonb ->>  '%s', g.name::jsonb ->> 'en_US','') as "Cargo",
                    COALESCE(rb.name,'') as "Banco",
                    COALESCE(bank.acc_number,'') as "Cuenta Bancaria",
                    COALESCE(ajb.name,'') as "Cuenta Dispersora",
                    COALESCE(d.code_sena,'') as "Código SENA",
                    COALESCE(rp.name,'') as "Ubicación Laboral",COALESCE(dt.name,'') as "Departamento",
                    COALESCE(d.wage,0) as "Salario Base",'' as "Novedades",
                    COALESCE(hr.short_name,COALESCE(hr.name::jsonb ->>  '%s', hr.name::jsonb ->> 'en_US', '')) as "Regla Salarial",
                    COALESCE(hr.short_name,COALESCE(hr.name::jsonb ->>  '%s', hr.name::jsonb ->> 'en_US', '')) ||' '|| case when hc.code = 'SSOCIAL' then '' else COALESCE(COALESCE(rp_et.business_name,rp_et.name),'') end as "Reglas Salariales + Entidad",
                    COALESCE(hc.name::jsonb ->>  '%s', hc.name::jsonb ->> 'en_US','') as "Categoría",COALESCE(b.sequence,0) as "Secuencia",COALESCE(Sum(b.total),0) as "Monto"
            From hr_payslip as a 
            --Info Empleado
            Inner Join (Select distinct row_number() over(order by a.name) as item,
                        a.id,identification_id,a.name,a.branch_id,a.job_id,
                        address_id,work_contact_id,a.department_id
                        From hr_employee as a
                        inner join hr_payslip as p on a.id = p.employee_id and p.id in (%s)
                        group by a.id,identification_id,a.name,a.branch_id,a.job_id,address_id,work_contact_id,a.department_id) as c on a.employee_id = c.id
            Inner Join hr_contract as d on a.contract_id = d.id
            Left Join hr_payslip_line as b on a.id = b.slip_id
            Left Join hr_salary_rule as hr on b.salary_rule_id = hr.id
            Left Join hr_salary_rule_category as hc on b.category_id = hc.id
            Left join lavish_res_branch as e on c.branch_id = e.id
            Left join account_analytic_account as f on d.analytic_account_id = f.id
            Left join hr_job g on c.job_id = g.id
            Left Join hr_department dt on c.department_id = dt.id
            Left Join res_partner rp on c.address_id = rp.id
            --Entidad
            Left Join hr_employee_entities et on b.entity_id = et.id
            Left Join res_partner rp_et on et.partner_id = rp_et.id
            --Info Bancaria
            Left join res_partner_bank bank on c.work_contact_id = bank.partner_id and bank.company_id = a.company_id and bank.is_main = True
            Left join res_bank rb on bank.bank_id = rb.id 
            Left join account_journal ajb on bank.payroll_dispersion_account = ajb.id             
            Where a.id in (%s)     
            Group By c.item,c.identification_id,c.name,d.date_start,e.name,
                        f.name,g.name,rb.name,bank.acc_number,ajb.name,
                        d.code_sena,rp.name,dt.name,d.wage,hr.short_name,hr.name,hc.code,
                        rp_et.business_name,rp_et.name,hc.name,b.sequence
        ''' % (lang,lang,lang,lang,str_ids,str_ids)

        query_quantity_bases_days = '''
            Select c.item as "Item",
                COALESCE(c.identification_id,'') as "Identificación",COALESCE(c.name,'') as "Empleado",COALESCE(d.date_start,'1900-01-01') as "Fecha Ingreso",
                COALESCE(e.name,'') as "Seccional",COALESCE(f.name,'') as "Cuenta Analítica",
                COALESCE(g.name::jsonb ->> '%s', g.name::jsonb ->> 'en_US','') as "Cargo",
                COALESCE(rb.name,'') as "Banco",
                COALESCE(bank.acc_number,'') as "Cuenta Bancaria",
                COALESCE(ajb.name,'') as "Cuenta Dispersora",
                COALESCE(d.code_sena,'') as "Código SENA",COALESCE(rp.name,'') as "Ubicación Laboral",COALESCE(dt.name,'') as "Departamento",
                COALESCE(d.wage,0) as "Salario Base",'' as "Novedades",
                COALESCE(hr.short_name,COALESCE(hr.name::jsonb ->>  '%s', hr.name::jsonb ->> 'en_US','')) as "Regla Salarial",REPLACE_TITULO,
                COALESCE(hc.name::jsonb ->>  '%s', hc.name::jsonb ->> 'en_US','') as "Categoría",b.sequence as "Secuencia",REPLACE_VALUE
            From hr_payslip as a 
            Inner Join hr_payslip_line as b on a.id = b.slip_id   
            Inner Join hr_salary_rule as hr on b.salary_rule_id = hr.id             
            Inner Join hr_salary_rule_category as hc on b.category_id = hc.id REPLACE_FILTER_RULE_CATEGORY
            --Info Empleado
            Inner Join (Select distinct row_number() over(order by a.name) as item,
                        a.id,identification_id,a.name,a.branch_id,a.job_id,
                        address_id,work_contact_id,a.department_id
                        From hr_employee as a
                        inner join hr_payslip as p on a.id = p.employee_id and p.id in (%s)
                        group by a.id,identification_id,a.name,a.branch_id,a.job_id,address_id,work_contact_id,a.department_id) as c on a.employee_id = c.id
            Inner Join hr_contract as d on a.contract_id = d.id
            Left join lavish_res_branch as e on c.branch_id = e.id
            Left join account_analytic_account as f on d.analytic_account_id = f.id
            Left join hr_job g on c.job_id = g.id
            Left Join hr_department dt on c.department_id = dt.id
            Left Join res_partner rp on c.address_id = rp.id
            --Entidad
            Left Join hr_employee_entities et on b.entity_id = et.id
            Left Join res_partner rp_et on et.partner_id = rp_et.id
            --Info Bancaria
            Left join res_partner_bank bank on c.work_contact_id = bank.partner_id and bank.company_id = a.company_id and bank.is_main = True
            Left join res_bank rb on bank.bank_id = rb.id 
            Left join account_journal ajb on bank.payroll_dispersion_account = ajb.id             
            Where a.id in (%s)
            Group By c.item,c.identification_id,c.name,d.date_start,e.name,
                        f.name,g.name,rb.name,bank.acc_number,ajb.name,
                        d.code_sena,rp.name,dt.name,d.wage,hr.short_name,hr.name,hc.code,
                        rp_et.business_name,rp_et.name,hc.name,b.sequence
        ''' % (lang,lang,lang,str_ids,str_ids)

        query = f"""
                    Select * from
                    (
                        --DIAS INVOLUCRADOS EN LA LIQUIDACIÓN
                        {query_days}
                        Union
                        --VALORES LIQUIDADOS
                        {query_amount_rules}
                        Union 
                        -- CANTIDAD SOLO PARA HORAS EXTRAS Y PRESTACIONES SOCIALES (CESANTIAS & PRIMA)
                        {query_quantity_bases_days.replace('REPLACE_TITULO', ''' 'Cantidad de ' || COALESCE(hr.short_name,COALESCE(hr.name::jsonb ->>  '%s', hr.name::jsonb ->> 'en_US','')) as "Reglas Salariales + Entidad" ''').replace('REPLACE_VALUE', 'COALESCE(Sum(b.quantity),0) as "Cantidad"').replace('REPLACE_FILTER_RULE_CATEGORY',''' and hc.code in ('HEYREC','PRESTACIONES_SOCIALES') ''')}
        				Union 
        				-- BASE SOLO PARA PRESTACIONES SOCIALES (CESANTIAS & PRIMA)
        				{query_quantity_bases_days.replace('REPLACE_TITULO', ''' 'Base de ' || COALESCE(hr.short_name,COALESCE(hr.name::jsonb ->>  '%s', hr.name::jsonb ->> 'en_US','')) as "Reglas Salariales + Entidad" ''').replace('REPLACE_VALUE', 'COALESCE(Sum(b.amount_base),0) as "Base"').replace('REPLACE_FILTER_RULE_CATEGORY',''' and hc.code in ('PRESTACIONES_SOCIALES') ''')}
        				Union
        				-- DIAS AUSENCIAS NO REMUNERADOS		
        				{query_quantity_bases_days.replace('REPLACE_TITULO', ''' 'Días Ausencias no remuneradas de ' || COALESCE(hr.short_name,COALESCE(hr.name::jsonb ->>  '%s', hr.name::jsonb ->> 'en_US','')) as "Reglas Salariales + Entidad" ''').replace('REPLACE_VALUE', 'COALESCE(Sum(b.days_unpaid_absences),0) as "Dias Ausencias no remuneradas"').replace('REPLACE_FILTER_RULE_CATEGORY',''' and b.days_unpaid_absences > 0 ''')}
                    ) as a 
                """
        
        query_totales = '''
            Select 500000 as "Item",'' as "Identificación", '' as "Empleado", '1900-01-01' as "Fecha Ingreso",
                    '' as "Seccional", '' as "Cuenta Analítica",'' as "Cargo",'' as "Banco",'' as "Cuenta Bancaria",'' as "Cuenta Dispersora",
                    '' as "Código SENA",'' as "Ubicación Laboral",'' as "Departamento",
                    0 as "Salario Base",'' as "Novedades",
                    "Regla Salarial","Reglas Salariales + Entidad","Categoría","Secuencia",Sum("Monto") as "Monto"
            From(
                Select  c.name,COALESCE(wt.short_name,COALESCE(wt.name::jsonb ->> '%s', wt.name::jsonb ->> 'en_US','')) as "Regla Salarial",
                COALESCE(wt.short_name,COALESCE(wt.name::jsonb ->> '%s', wt.name::jsonb ->> 'en_US','')) as "Reglas Salariales + Entidad",
                        'Días' as "Categoría",0 as "Secuencia",COALESCE(Sum(b.number_of_days),0) as "Monto"
                From hr_payslip as a 
                Inner Join hr_payslip_worked_days as b on a.id = b.payslip_id 
                Inner Join hr_work_entry_type as wt on b.work_entry_type_id = wt.id
                --Info Empleado
                Inner Join hr_employee  as c on a.employee_id = c.id                
                Inner Join hr_contract as d on a.contract_id = d.id
                Where a.id in (%s)
                Group By c.name,wt.name,wt.short_name
                Union
                Select  c.name,COALESCE(hr.short_name,COALESCE(hr.name::jsonb ->>  '%s', hr.name::jsonb ->> 'en_US','')) as "Regla Salarial",COALESCE(hr.short_name,COALESCE(hr.name::jsonb ->>  '%s', hr.name::jsonb ->> 'en_US','')) ||' '|| case when hc.code = 'SSOCIAL' then '' else COALESCE(COALESCE(rp_et.business_name,rp_et.name),'') end as "Reglas Salariales + Entidad",
                        COALESCE(hc.name::jsonb ->>  '%s', hc.name::jsonb ->> 'en_US','') as "Categoría",b.sequence as "Secuencia",COALESCE(Sum(b.total),0) as "Monto"
                From hr_payslip as a 
                Inner Join hr_payslip_line as b on a.id = b.slip_id
                Inner Join hr_salary_rule as hr on b.salary_rule_id = hr.id
                Inner Join hr_salary_rule_category as hc on b.category_id = hc.id
                --Info Empleado
                Inner Join hr_employee  as c on a.employee_id = c.id                
                Inner Join hr_contract as d on a.contract_id = d.id
                --Entidad
                Left Join hr_employee_entities et on b.entity_id = et.id
                Left Join res_partner rp_et on et.partner_id = rp_et.id
                Where a.id in (%s)
                Group By c.name,hr.short_name,hr.name,hc.code,rp_et.business_name,rp_et.name,hc.name,b.sequence
                Union
                Select c.name,COALESCE(hr.short_name,COALESCE(hr.name::jsonb ->>  '%s', hr.name::jsonb ->> 'en_US','')) as "Regla Salarial",'Cantidad de ' || COALESCE(hr.short_name,COALESCE(hr.name::jsonb ->>  '%s', hr.name::jsonb ->> 'en_US','')) as "Reglas Salariales + Entidad",
                       COALESCE(hc.name::jsonb ->>  '%s', hc.name::jsonb ->> 'en_US','') as "Categoría",b.sequence as "Secuencia",COALESCE(Sum(b.quantity),0) as "Cantidad"
                From hr_payslip as a 
                Inner Join hr_payslip_line as b on a.id = b.slip_id         
                Inner Join hr_salary_rule as hr on b.salary_rule_id = hr.id       
                Inner Join hr_salary_rule_category as hc on b.category_id = hc.id and hc.code = 'HEYREC'
                --Info Empleado
                Inner Join hr_employee  as c on a.employee_id = c.id
                Inner Join hr_contract as d on c.id = d.employee_id and d.state = 'open'
                --Entidad
                Left Join hr_employee_entities et on b.entity_id = et.id
                Left Join res_partner rp_et on et.partner_id = rp_et.id 
                Where a.id in (%s)
                Group By c.name,hr.short_name,hr.name,hc.code,rp_et.business_name,rp_et.name,hc.name,b.sequence
            ) as a 
            Group By "Regla Salarial","Reglas Salariales + Entidad","Categoría","Secuencia"
            order by "Item","Empleado","Secuencia"
        ''' % (lang,lang,str_ids,lang,lang,lang,str_ids,lang,lang,lang,str_ids)

        #Finalizar query principal
        query = '''
            %s
            union
            %s
        ''' % (query,query_totales)

        #Ejecutar query principal
        self.env.cr.execute(query)
        result_query = self.env.cr.dictfetchall()

        df_report = pd.DataFrame(result_query)
        
        if len(df_report) == 0:
            raise ValidationError(_('No se ha encontrado información con el lote seleccionado, por favor verificar.'))

        #Ejecutar query de novedades
        self.env.cr.execute(query_novedades)
        result_query_novedades = self.env.cr.dictfetchall()

        df_novedades = pd.DataFrame(result_query_novedades)
        identification = ''
        novedades = ''
        for i,j in df_novedades.iterrows():
            if identification == df_novedades.loc[i,'Identificación']:
                novedades = novedades +' -\r\n '+ df_novedades.loc[i,'Novedad']                
            else:                
                identification = df_novedades.loc[i,'Identificación']
                novedades = df_novedades.loc[i,'Novedad']

            if df_novedades.loc[i,'EsUltimo'] == 1:
                df_report.loc[df_report['Identificación'] == identification, 'Novedades'] = novedades

        columns_index = ['Item', 'Identificación', 'Empleado']
        if self.show_date_of_entry == True:
            columns_index.append('Fecha Ingreso')
        if self.show_job_placement == True:
            columns_index.append('Ubicación Laboral')
        if self.show_sectional == True:
            columns_index.append('Seccional')
        if self.show_department == True:
            columns_index.append('Departamento')
        if self.show_analytical_account == True:
            columns_index.append('Cuenta Analítica')
        if self.show_job == True:
            columns_index.append('Cargo')
        if self.show_bank_officer == True:
            columns_index.append('Banco')
        if self.show_bank_account_officer == True:
            columns_index.append('Cuenta Bancaria')
        if self.show_dispersing_account == True:
            columns_index.append('Cuenta Dispersora')
        if self.show_sena_code == True:
            columns_index.append('Código SENA')
        if self.show_basic_salary == True:
            columns_index.append('Salario Base')
        columns_index.append('Novedades')

        # Obtener tamaño de las columnas fijas
        column_len = []
        position_initial = 0
        for column_i in columns_index:
            max_len = max([len(str(df_report.loc[i, column_i])) for i,j in df_report.iterrows()])
            if column_i == 'Novedades':
                max_len = 50 if max_len > 50 else max_len
            column_len.append({'position': position_initial,'name_column': column_i,'len_column': max_len})
            position_initial += 1

        #Pivotear consulta final
        if self.not_show_rule_entity:
            columns_pivot_final = ['Secuencia', 'Categoría', 'Regla Salarial']
        else:
            columns_pivot_final = ['Secuencia', 'Categoría', 'Reglas Salariales + Entidad']
        # Traducir las columnas antes de construir el pivot_table
        pivot_report = pd.pivot_table(df_report, values='Monto', index=columns_index,
                                      columns=columns_pivot_final, aggfunc=np.sum)
        _logger.info(df_report)
        #Obtener titulo y fechas de liquidación
        text_title = 'Informe de Liquidación'
        text_dates = 'Fechas Liquidación: %s a %s' % (min_date,max_date)
        text_generate = 'Informe generado el %s' % (datetime.now(timezone(self.env.user.tz)))
        text_liquidation = ''
        for lote in self.payslip_ids:
            text_liquidation += lote.name if text_liquidation == '' else ', ' + lote.name

        for liq in self.liquidations_ids:
            text_liquidation += liq.name if text_liquidation == '' else ', ' + liq.name

        text_liquidation += ' | ' + text_generate
        #Obtener info
        cant_filas = pivot_report.shape[0]+3 # + 3 de los registros pertenencientes al encabezado
        cant_columnas = pivot_report.shape[1]+len(columns_index) # + las columnas fijas
        #Obtener tamaño de las columnas que se crearon con el pivot



        for idx, column_name in enumerate(pivot_report.columns):
            column_len.append({
                'position': position_initial,
                'name_column': column_name,
                'len_column': len(column_name)
            })
            position_initial += 1

        #Crear Excel
        filename = 'Informe Liquidación.xlsx'
        stream = io.BytesIO()
        writer = pd.ExcelWriter(stream, engine='xlsxwriter')
        writer.book.filename = stream
        pivot_report.to_excel(writer, sheet_name='Liquidación')
        worksheet = writer.sheets['Liquidación']
        #Agregar formatos al excel
        cell_format_title = writer.book.add_format({'bold': True, 'align': 'left'})
        cell_format_title.set_font_name('Calibri')
        cell_format_title.set_font_size(15)
        cell_format_title.set_font_color('#1F497D')
        cell_format_text_generate = writer.book.add_format({'bold': False, 'align': 'left'})
        cell_format_text_generate.set_font_name('Calibri')
        cell_format_text_generate.set_font_size(10)
        cell_format_text_generate.set_font_color('#1F497D')
        if len(columns_index)-2 != 2:
            worksheet.merge_range(0,2,0,len(columns_index)-2, text_title, cell_format_title)
            worksheet.merge_range(1,2,1,len(columns_index)-2, text_dates, cell_format_title)
            worksheet.merge_range(2,2,2,len(columns_index)-2, text_generate, cell_format_text_generate)
        else:
            worksheet.write(0, 2, text_title, cell_format_title)
            worksheet.write(1, 2, text_dates, cell_format_title)
            worksheet.write(2, 2, text_generate, cell_format_text_generate)
        if self.env.company.logo:
            logo_company = io.BytesIO(base64.b64decode(self.env.company.logo))
            worksheet.insert_image('A1', "logo_company.png", {'image_data': logo_company,'x_scale': 0.1, 'y_scale': 0.1})
        #Dar tamaño a las columnas
        # cell_format_left = writer.book.add_format({'align': 'left'})
        for size_column in column_len:
            worksheet.set_column(size_column['position'], size_column['position'], size_column['len_column'] + 5)
        #Campos númericos
        number_format = writer.book.add_format({'num_format': '#,##', 'border': 1})
        # https://xlsxwriter.readthedocs.io/worksheet.html#conditional_format
        worksheet.conditional_format(3, len(columns_index), cant_filas, cant_columnas-1,
                                     {'type': 'no_errors',
                                      'format': number_format})
        #Campo de novedades
        cell_format_novedades = writer.book.add_format({'text_wrap': True, 'border': 1, 'align': 'left'})
        cell_format_novedades.set_font_name('Calibri')
        cell_format_novedades.set_font_size(11)
        worksheet.conditional_format(3,len(columns_index)-1,cant_filas-1,len(columns_index)-1,
                                        {'type': 'no_errors',
                                        'format': cell_format_novedades})  
        #Titulo totales
        cell_format_total = writer.book.add_format({'bold': True,'align':'right','border':1})
        cell_format_total.set_font_name('Calibri')
        cell_format_total.set_font_size(11)
        worksheet.merge_range(cant_filas,0,cant_filas,len(columns_index)-1,'TOTALES',cell_format_total)
        worksheet.set_zoom(80)
        #worksheet.set_column('M:M', 0, None, {'hidden': 1})
        #Firmas
        obj_signature = self.get_hr_payslip_template_signature()
        cell_format_firma = writer.book.add_format({'bold': True, 'align': 'center', 'top': 1})
        cell_format_txt_firma = writer.book.add_format({'bold': True, 'align': 'center'})
        if len(obj_signature) == 1:
            if obj_signature.signature_prepared:
                worksheet.merge_range(cant_filas + 5, 1, cant_filas + 5, 2, 'ELABORO', cell_format_firma)
                if obj_signature.txt_signature_prepared:
                    worksheet.merge_range(cant_filas + 6, 1, cant_filas + 6, 2, obj_signature.txt_signature_prepared, cell_format_txt_firma)
            if obj_signature.signature_reviewed:
                worksheet.merge_range(cant_filas + 5, 4, cant_filas + 5, 5, 'REVISO', cell_format_firma)
                if obj_signature.txt_signature_reviewed:
                    worksheet.merge_range(cant_filas + 6, 4, cant_filas + 6, 5, obj_signature.txt_signature_reviewed, cell_format_txt_firma)
            if obj_signature.signature_approved:
                worksheet.merge_range(cant_filas + 5, 7, cant_filas + 5, 8, 'APROBO', cell_format_firma)
                if obj_signature.txt_signature_approved:
                    worksheet.merge_range(cant_filas + 6, 7, cant_filas + 6, 8, obj_signature.txt_signature_approved, cell_format_txt_firma)
        else:
            worksheet.merge_range(cant_filas + 5, 1, cant_filas + 5, 2, 'ELABORO', cell_format_firma)
            worksheet.merge_range(cant_filas + 5, 4, cant_filas + 5, 5, 'REVISO', cell_format_firma)
            worksheet.merge_range(cant_filas + 5, 7, cant_filas + 5, 8, 'APROBO', cell_format_firma)
        # Guardar excel
        writer.save()

        self.write({
            'excel_file': base64.encodebytes(stream.getvalue()),
            'excel_file_name': filename,
        })
        
        action = {
                    'name': filename,
                    'type': 'ir.actions.act_url',
                    'url': "web/content/?model=hr.payroll.report.lavish.filter&id=" + str(self.id) + "&filename_field=excel_file_name&field=excel_file&download=true&filename=" + self.excel_file_name,
                    'target': 'self',
                }
        return action

    def generate_pdf(self):
        #Crear información
        obj_payslips = self.env['hr.payslip']
        min_date = ''
        max_date = ''

        if len(self.payslip_ids) == 0 and len(self.liquidations_ids) == 0:
            raise ValidationError(_('Debe seleccionar algún filtro.'))

        # Obtener las liquidaciones de los lotes seleccionados
        if len(self.payslip_ids) > 0:
            ids = self.payslip_ids.ids
            for payslip in self.payslip_ids:
                if min_date == '' and max_date == '':
                    min_date = payslip.date_start
                    max_date = payslip.date_end
                else:
                    if payslip.date_start < min_date:
                        min_date = payslip.date_start
                    if payslip.date_end > max_date:
                        max_date = payslip.date_end

            obj_payslips += self.env['hr.payslip'].search([('payslip_run_id', 'in', ids)])

        # Obtener las liquidaciones seleccionadas
        if len(self.liquidations_ids) > 0:
            obj_payslips += self.liquidations_ids

            for payslip in self.liquidations_ids:
                if min_date == '' and max_date == '':
                    min_date = payslip.date_from
                    max_date = payslip.date_to
                else:
                    if payslip.date_from < min_date:
                        min_date = payslip.date_from
                    if payslip.date_to > max_date:
                        max_date = payslip.date_to

        # Obtener ids a filtrar
        str_ids = ''
        for i in obj_payslips:
            if str_ids == '':
                str_ids = str(i.id)
            else:
                str_ids = str_ids + ',' + str(i.id)

        min_date = min_date.strftime('%Y-%m-%d')
        max_date = max_date.strftime('%Y-%m-%d')

        query_days = '''
                    Select  c.item as "Item",
                            COALESCE(c.identification_id,'') as "Identificación",COALESCE(c.name,'') as "Empleado",                            
                            COALESCE(wt.short_name,COALESCE(wt.name,'')) as "Regla Salarial",0 as "Secuencia",COALESCE(Sum(b.number_of_days),0) as "Monto"
                    From hr_payslip as a 
                    --Info Empleado
                    Inner Join (Select distinct row_number() over(order by a.name) as item,
                                a.id,identification_id,a.name,a.branch_id,a.job_id,
                                address_id,a.department_id
                                From hr_employee as a
                                inner join hr_payslip as p on a.id = p.employee_id and p.id in (%s)
                                group by a.id,identification_id,a.name,a.branch_id,a.job_id,address_id,a.department_id) as c on a.employee_id = c.id
                    Inner Join hr_contract as d on a.contract_id = d.id
                    Inner Join hr_payslip_worked_days as b on a.id = b.payslip_id
                    inner join hr_work_entry_type as wt on b.work_entry_type_id = wt.id
                    Left join lavish_res_branch as e on c.branch_id = e.id
                    Left join account_analytic_account as f on d.analytic_account_id = f.id
                    Left join hr_job g on c.job_id = g.id
                    Left Join hr_department dt on c.department_id = dt.id
                    Left Join res_partner rp on c.address_id = rp.id
                    Where a.id in (%s)     
                    Group By c.item,c.identification_id,c.name,d.date_start,e.name,
                                f.name,g.name,d.code_sena,rp.name,dt.name,d.wage,wt.name,wt.short_name
                ''' % (str_ids, str_ids)

        query_amount_rules = '''
                    Select  c.item as "Item",
                            COALESCE(c.identification_id,'') as "Identificación",COALESCE(c.name,'') as "Empleado",
                            COALESCE(hr.short_name,COALESCE(hr.name,'')) as "Regla Salarial",
                            COALESCE(b.sequence,0) as "Secuencia",COALESCE(Sum(b.total),0) as "Monto"
                    From hr_payslip as a 
                    --Info Empleado
                    Inner Join (Select distinct row_number() over(order by a.name) as item,
                                a.id,identification_id,a.name,a.branch_id,a.job_id,
                                address_id,a.department_id
                                From hr_employee as a
                                inner join hr_payslip as p on a.id = p.employee_id and p.id in (%s)
                                group by a.id,identification_id,a.name,a.branch_id,a.job_id,address_id,a.department_id) as c on a.employee_id = c.id
                    Inner Join hr_contract as d on a.contract_id = d.id
                    Left Join hr_payslip_line as b on a.id = b.slip_id
                    Left Join hr_salary_rule as hr on b.salary_rule_id = hr.id and hr.code in ('TOTALDEV','TOTALDED','NET')
                    Left Join hr_salary_rule_category as hc on b.category_id = hc.id
                    Left join lavish_res_branch as e on c.branch_id = e.id
                    Left join account_analytic_account as f on d.analytic_account_id = f.id
                    Left join hr_job g on c.job_id = g.id
                    Left Join hr_department dt on c.department_id = dt.id
                    Left Join res_partner rp on c.address_id = rp.id
                    --Entidad
                    Left Join hr_employee_entities et on b.entity_id = et.id
                    Left Join res_partner rp_et on et.partner_id = rp_et.id            
                    Where a.id in (%s) and hr.code in ('TOTALDEV','TOTALDED','NET')      
                    Group By c.item,c.identification_id,c.name,d.date_start,e.name,
                                f.name,g.name,d.code_sena,rp.name,dt.name,d.wage,hr.short_name,hr.name,hc.code,
                                rp_et.business_name,rp_et.name,hc.name,b.sequence
                ''' % (str_ids, str_ids)

        query = f"""
                            Select * from
                            (
                                --DIAS INVOLUCRADOS EN LA LIQUIDACIÓN
                                {query_days}
                                Union
                                --VALORES LIQUIDADOS
                                {query_amount_rules}                                
                            ) as a 
                        """

        query_totales = '''
                    Select 500000 as "Item",'' as "Identificación", '' as "Empleado", 
                            "Regla Salarial","Secuencia",Sum("Monto") as "Monto"
                    From(
                        Select  c.name,COALESCE(wt.short_name,COALESCE(wt.name,'')) as "Regla Salarial",0 as "Secuencia",
                                COALESCE(Sum(b.number_of_days),0) as "Monto"
                        From hr_payslip as a 
                        Inner Join hr_payslip_worked_days as b on a.id = b.payslip_id 
                        Inner Join hr_work_entry_type as wt on b.work_entry_type_id = wt.id
                        --Info Empleado
                        Inner Join hr_employee  as c on a.employee_id = c.id                
                        Inner Join hr_contract as d on a.contract_id = d.id
                        Where a.id in (%s)
                        Group By c.name,wt.name,wt.short_name
                        Union
                        Select  c.name,COALESCE(hr.short_name,COALESCE(hr.name,'')) as "Regla Salarial",
                                b.sequence as "Secuencia",COALESCE(Sum(b.total),0) as "Monto"
                        From hr_payslip as a 
                        Inner Join hr_payslip_line as b on a.id = b.slip_id
                        Inner Join hr_salary_rule as hr on b.salary_rule_id = hr.id and hr.code in ('TOTALDEV','TOTALDED','NET')
                        Inner Join hr_salary_rule_category as hc on b.category_id = hc.id
                        --Info Empleados
                        Inner Join hr_employee  as c on a.employee_id = c.id                
                        Inner Join hr_contract as d on a.contract_id = d.id
                        --Entidad
                        Left Join hr_employee_entities et on b.entity_id = et.id
                        Left Join res_partner rp_et on et.partner_id = rp_et.id
                        Where a.id in (%s) and hr.code in ('TOTALDEV','TOTALDED','NET')
                        Group By c.name,hr.short_name,hc.code,hc.code,rp_et.name,rp_et.name,hc.id,b.sequence,wt.code                        
                    ) as a 
                    Group By "Regla Salarial","Secuencia"
                    order by "Item","Secuencia"
                ''' % (str_ids, str_ids)

        # Finalizar query principal
        query = '''
                    %s
                    union
                    %s
                ''' % (query, query_totales)

        # Ejecutar query principal
        self.env.cr.execute(query)
        result_query = self.env.cr.dictfetchall()

        df_report = pd.DataFrame(result_query)

        if len(df_report) == 0:
            raise ValidationError(_('No se ha encontrado información con el lote seleccionado, por favor verificar.'))

        columns_index = ['Item', 'Identificación', 'Empleado']
        # Pivotear consulta final
        columns_pivot_final = ['Secuencia','Regla Salarial']

        pivot_report = pd.pivot_table(df_report, values='Monto', index=columns_index,
                                      columns=columns_pivot_final, aggfunc=np.sum)

        # Obtener titulo y fechas de liquidación
        text_title = 'Informe de Liquidación'
        text_dates = 'Fechas Liquidación: %s a %s' % (min_date, max_date)
        #'Informe generado el %s' % (datetime.now(timezone(self.env.user.tz)))
        text_generate = ''
        obj_company = self.env['res.company']
        for lote in self.payslip_ids:
            text_generate += lote.name if text_generate == '' else ', '+lote.name
            obj_company = lote.company_id

        for liq in self.liquidations_ids:
            text_generate += liq.name if text_generate == '' else ', ' + liq.name
            obj_company = liq.company_id
        #Crear HTML reporte
        html = '''  
            <table class="table table-borderless table-sm" style="margin:0px;padding:0px;">
                <tr>
                    <td>  
                        <img src="data:image/jpg;base64,'''+obj_company.logo.decode("utf-8") +'''" 
                            style="height: 50px; width:100px">       
                    </td>
                    <td colspan="6" style="text-align:center;padding-right:260px;">                             
                        <p style="font-size: small;margin:0px;padding:0px;">%s</p>
                        <p style="font-size: x-small;margin:0px;padding:0px;">%s</p>
                        <p style="font-size: x-small;margin:0px;padding:0px;">%s</p>                        
                    </td>
                </tr>
            </table>
        ''' % (text_title,text_dates,text_generate)

        html += pivot_report.to_html(float_format='{:,.0f}'.format, na_rep='0', classes=['table','table-bordered','table-sm'], table_id='table-report')

        html = html.replace('''<th></th>
      <th></th>
      <th>Regla Salarial</th>''', '''<th>Item</th>
      <th>Identificación</th>
      <th>Empleado</th>''')

        qty_type_days = str(len(pivot_report.columns)-3) # Todas las columnas menos Total devengo, Total deducción y Neto
        sequence_total_dev = str(self.env['hr.salary.rule'].search([('code','=','TOTALDEV')],limit=1).sequence)
        sequence_total_ded = str(self.env['hr.salary.rule'].search([('code','=','TOTALDED')],limit=1).sequence)
        sequence_total_net = str(self.env['hr.salary.rule'].search([('code','=','NET')],limit=1).sequence)

        html = html.replace('''<tr>
      <th></th>
      <th></th>
      <th>Secuencia</th>
      <th colspan="'''+qty_type_days+'''" halign="left">0</th>
      <th>'''+sequence_total_dev+'''</th>
      <th>'''+sequence_total_ded+'''</th>
      <th>'''+sequence_total_net+'''</th>
    </tr>''', '')

        html = html.replace('''<th>500000</th>
      <th></th>
      <th></th>''', '''<th colspan='3' halign="right">TOTALES</th>''')

        html = html.replace('      <th></th>', '')
        html = html.replace('\n'*len(pivot_report.columns), '')

        html = html.replace('''<tr>
      <th>Item</th>
      <th>Identificación</th>
      <th>Empleado</th>
    </tr>''', '')

        html = html.replace('nan', '0')

        obj_signature = self.get_hr_payslip_template_signature()
        if len(obj_signature) == 1:
            signatures = ''
            if obj_signature.signature_prepared:
                if signatures != '':
                    signatures += '<td style="width: 5%;background-color:white;border:none;"/>'
                txt_signature_prepared = obj_signature.txt_signature_prepared if obj_signature.txt_signature_prepared else ''
                signatures += '''
                    <td style="width: 30%;font-size: x-small;">
                        ELABORÓ <br/>
                        '''+txt_signature_prepared+'''
                    </td>
                '''
            else:
                signatures += '<td style="width: 30%;background-color:white;border:none;"/>'

            if obj_signature.signature_reviewed:
                if signatures != '':
                    signatures += '<td style="width: 5%;background-color:white;border:none;"/>'
                txt_signature_reviewed = obj_signature.txt_signature_reviewed if obj_signature.txt_signature_reviewed else ''
                signatures += '''
                    <td style="width: 30%;font-size: x-small;">
                        REVISÓ <br/>
                        '''+txt_signature_reviewed+'''
                    </td>
                '''
            else:
                signatures += '<td style="width: 30%;background-color:white;border:none;"/>'

            if obj_signature.signature_approved:
                if signatures != '':
                    signatures += '<td style="width: 5%;background-color:white;border:none;"/>'
                txt_signature_approved = obj_signature.txt_signature_approved if obj_signature.txt_signature_approved else ''
                signatures += '''
                    <td style="width: 30%;font-size: x-small;">
                        APROBÓ <br/>
                        '''+txt_signature_approved+'''
                    </td>
                '''
            else:
                signatures += '<td style="width: 30%;background-color:white;border:none;"/>'

            html += '''
            <br/>
            <table class="table table-striped table-sm">
                <tr class="text-center">
                    '''+signatures+'''
                </tr>
            </table>        
            '''
        else:
            html += '''
            <br/>
            <table class="table table-striped table-sm">
                <tr class="text-center">
                    <td style="width: 30%;font-size: x-small;">
                        ELABORÓ
                    </td>
                    <td style="width: 5%;background-color:white;border:none;"/>
                    <td style="width: 30%;font-size: x-small;">
                        REVISÓ
                    </td>
                    <td style="width: 5%;background-color:white;border:none;"/>
                    <td style="width: 30%;font-size: x-small;">
                        APROBÓ
                    </td>
                </tr>
            </table>        
            '''

        self.pdf_report_payroll = html

        # Descargar PDF
        datas = {
            'id': self.id,
            'model': 'hr.payroll.report.lavish.filter'
        }

        return {
            'type': 'ir.actions.report',
            'report_name': 'lavish_hr_payroll.report_payroll_lavish',
            'report_type': 'qweb-pdf',
            'datas': datas
        }

    def generate_excel(self):
        if not self.payslip_ids and not self.liquidations_ids:
            raise ValidationError(_('You must select at least one filter.'))
        payslips = self.env['hr.payslip'].search([
            '|',
            ('payslip_run_id', 'in', self.payslip_ids.ids),
            ('id', 'in', self.liquidations_ids.ids)
        ])
        data = self._prepare_data(payslips)
        df_report = pd.DataFrame(data)

        if df_report.empty:
            raise ValidationError(_('No information found for the selected batch, please verify.'))
        self._process_novedades(df_report, payslips)
            # Calculate totals

        columns_index = self._prepare_columns_index()
        pivot_report = self._pivot_dataframe(df_report, columns_index)
        totals = self._calculate_totals(pivot_report)
        output = io.BytesIO()
        writer = pd.ExcelWriter(output, engine='xlsxwriter')
        pivot_report.to_excel(writer, sheet_name='Liquidación')
        worksheet = writer.sheets['Liquidación']

        # Apply Excel formatting
        self._apply_excel_formatting(writer, worksheet, pivot_report, totals, payslips)

        writer.save()
        excel_data = output.getvalue()

        # Save the Excel file
        self.write({
            'excel_file': base64.encodebytes(excel_data),
            'excel_file_name': 'Informe Liquidación.xlsx',
        })

        return {
            'name': 'Informe Liquidación.xlsx',
            'type': 'ir.actions.act_url',
            'url': f"/web/content/?model=hr.payroll.report.lavish.filter&id={self.id}&filename_field=excel_file_name&field=excel_file&download=true&filename={self.excel_file_name}",
            'target': 'self',
        }

    def _calculate_totals(self, pivot_report):
        totals = pivot_report.sum().to_frame().T
        totals.index = ['TOTALES']
        return totals


    def _prepare_data(self, payslips):
        data = []
        for payslip in payslips:
            employee = payslip.employee_id
            contract = payslip.contract_id
            for line in payslip.line_ids:
                base_dict = {
                    'Item': employee.id,
                    'Identificación': employee.identification_id,
                    'Empleado': employee.name,
                    'Fecha Ingreso': contract.date_start,
                    'Seccional': employee.branch_id.name,
                    'Cuenta Analítica': contract.analytic_account_id.name,
                    'Cargo': employee.job_id.name,
                    'Banco': employee.bank_account_id.bank_id.name,
                    'Cuenta Bancaria': employee.bank_account_id.acc_number,
                    'Cuenta Dispersora': employee.bank_account_id.journal_id.name,
                    'Código SENA': contract.code_sena,
                    'Ubicación Laboral': employee.address_id.name,
                    'Departamento': employee.department_id.name,
                    'Salario Base': contract.wage,
                    'Novedades': '',
                    'Regla Salarial': line.salary_rule_id.name,
                    'Reglas Salariales + Entidad': f"{line.salary_rule_id.name} {line.entity_id.name or ''}",
                    'Categoría': line.category_id.name,
                    'Secuencia': line.sequence,
                    'Monto': line.total,
                }
                data.append(base_dict)

                # Horas extras y prestaciones sociales
                if line.category_id.code in ['HEYREC', 'PRESTACIONES_SOCIALES']:
                    quantity_dict = base_dict.copy()
                    quantity_dict['Reglas Salariales + Entidad'] = f"Cantidad de {line.salary_rule_id.name}"
                    quantity_dict['Monto'] = line.quantity
                    data.append(quantity_dict)

                # Base para prestaciones sociales
                if line.category_id.code == 'PRESTACIONES_SOCIALES':
                    base_amount_dict = base_dict.copy()
                    base_amount_dict['Reglas Salariales + Entidad'] = f"Base de {line.salary_rule_id.name}"
                    base_amount_dict['Monto'] = line.amount_base
                    data.append(base_amount_dict)

            # Días trabajados
            for worked_days in payslip.worked_days_line_ids:
                worked_dict = base_dict.copy()
                worked_dict.update({
                    'Regla Salarial': worked_days.work_entry_type_id.name,
                    'Reglas Salariales + Entidad': worked_days.work_entry_type_id.name,
                    'Categoría': 'Días',
                    'Secuencia': 0,
                    'Monto': worked_days.number_of_days,
                })
                data.append(worked_dict)

                # # Días de ausencias no remuneradas
                # if worked_days.amount == 0:  # Asumiendo que las ausencias no remuneradas tienen amount = 0
                #     unpaid_dict = worked_dict.copy()
                #     unpaid_dict['Reglas Salariales + Entidad'] = f"Días Ausencias no remuneradas de {worked_days.work_entry_type_id.name}"
                #     unpaid_dict['Monto'] = worked_days.number_of_days
                #     data.append(unpaid_dict)

        return data

    def _process_novedades(self, df_report, payslips):
        for payslip in payslips:
            novedades = []
            for leave in payslip.leave_ids.filtered(lambda l: l.leave_id.state == 'validate' and 
                                                                (l.leave_id.request_date_from >= payslip.date_from and l.leave_id.request_date_from <= payslip.date_to) or
                                                                (l.leave_id.request_date_to >= payslip.date_from and l.leave_id.request_date_to <= payslip.date_to)):
                novedades.append(leave.leave_id.holiday_status_id.name)
            df_report.loc[df_report['Identificación'] == payslip.employee_id.identification_id, 'Novedades'] = ' -\r\n '.join(novedades)

    def _prepare_columns_index(self):
        columns_index = ['Item', 'Identificación', 'Empleado']
        if self.show_date_of_entry:
            columns_index.append('Fecha Ingreso')
        if self.show_job_placement:
            columns_index.append('Ubicación Laboral')
        if self.show_sectional:
            columns_index.append('Seccional')
        if self.show_department:
            columns_index.append('Departamento')
        if self.show_analytical_account:
            columns_index.append('Cuenta Analítica')
        if self.show_job:
            columns_index.append('Cargo')
        if self.show_bank_officer:
            columns_index.append('Banco')
        if self.show_bank_account_officer:
            columns_index.append('Cuenta Bancaria')
        if self.show_dispersing_account:
            columns_index.append('Cuenta Dispersora')
        if self.show_sena_code:
            columns_index.append('Código SENA')
        if self.show_basic_salary:
            columns_index.append('Salario Base')
        columns_index.append('Novedades')
        return columns_index

    def _pivot_dataframe(self, df_report, columns_index):
        if self.not_show_rule_entity:
            columns_pivot = ['Secuencia', 'Categoría', 'Regla Salarial']
        else:
            columns_pivot = ['Secuencia', 'Categoría', 'Reglas Salariales + Entidad']
        
        pivot_report = pd.pivot_table(df_report, values='Monto', index=columns_index,
                                    columns=columns_pivot, aggfunc=np.sum, fill_value=0)
        pivot_report = pivot_report.sort_index(axis=1, level=['Secuencia', 'Categoría'])
        category_totals = pivot_report.groupby(axis=1, level='Categoría').sum()
        for category in category_totals.columns:
            pivot_report[('', 'Total', f'Total {category}')] = category_totals[category]
        pivot_report = pivot_report.sort_index(axis=1, level=['Secuencia', 'Categoría'])
        return pivot_report

    def _apply_excel_formatting(self, writer, worksheet, pivot_report, totals, payslips):
        workbook = writer.book

        # Formats
        title_format = workbook.add_format({
            'bold': True, 'font_name': 'Calibri', 'font_size': 15, 'font_color': '#1F497D', 'align': 'left'
        })
        date_format = workbook.add_format({
            'bold': True, 'font_name': 'Calibri', 'font_size': 10, 'font_color': '#1F497D', 'align': 'left'
        })
        number_format = workbook.add_format({'num_format': '#,##', 'border': 1})
        total_format = workbook.add_format({'bold': True, 'num_format': '#,##', 'border': 1, 'top': 2})

        # Title and date
        worksheet.write('A1', 'Informe de Liquidación', title_format)
        worksheet.write('A2', f'Fechas Liquidación: {min(payslips.mapped("date_from"))} a {max(payslips.mapped("date_to"))}', date_format)

        # Column widths
        for i, column in enumerate(pivot_report.columns):
            worksheet.set_column(i, i, 20)

        # Apply number format
        data_start_row = 4
        worksheet.conditional_format(data_start_row, 0, 
                                    len(pivot_report) + data_start_row, 
                                    len(pivot_report.columns) + len(pivot_report.index.names) - 1,
                                    {'type': 'no_errors', 'format': number_format})

        # Format totals
        totals_start_row = len(pivot_report) + data_start_row + 2
        worksheet.conditional_format(totals_start_row, 0,
                                    totals_start_row, len(totals.columns) + len(totals.index.names) - 1,
                                    {'type': 'no_errors', 'format': total_format})

        # Add company logo
        if self.env.company.logo:
            image_data = io.BytesIO(base64.b64decode(self.env.company.logo))
            worksheet.insert_image('A1', 'logo.png', {'image_data': image_data, 'x_scale': 0.5, 'y_scale': 0.5, 'x_offset': 10, 'y_offset': 10})

        # Adjust first row height to accommodate logo
        worksheet.set_row(0, 45)
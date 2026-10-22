from datetime import datetime
import requests
from requests.auth import HTTPBasicAuth
import urllib3
import json
from modules.email_module.db import *
from ERP.db import *
from modules.email_module.content import generate_voucher_approval_body
from modules.email_module.service import send_email

def push_to_jde(src_id):
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    session = requests.Session()
    session.auth = HTTPBasicAuth("SVCAI01", "aiagent")

    headers = {
        "Content-Type": "application/json"
    }

    try:
        # ---------------- STEP 0: GET DATA ----------------
        print("----------Step 1: Checking PO number")
        header_info, line_info = extract_inv_data(src_id)
        print("Header info, line info", header_info, line_info)

        if not line_info:
            insert_log(src_id, "Failed", "JDE", "No line data")
            return {"status": "error", "message": "No line data"}

        order_number = line_info[0].get('order_number')
        # order_number = '84921' 
        # order_number = '02369188' 

        print("----order num-----", order_number)

        if not order_number:
            insert_log(src_id, "Failed", "JDE", "Missing order number")
            return {"status": "error", "message": "Missing order number"}

        # ---------------- STEP 1: CHECK PO ----------------
        payload = {
            "OrderNumber": order_number
        }

        url = "https://10.0.4.216:8041/jderest/v3/orchestrator/JDE_ORCH_AI_CheckPO"

        response = session.post(url, json=payload, headers=headers, verify=False)
        print("CheckPO Status:", response.status_code)
        print("CheckPO Response:", response.text)

        response = json.loads(response.text)

        error_code = response.get('ErrorCode', '').strip()
        error_desc = response.get('ErrorDescription')

        print("Parsed ErrorCode:", error_code)

        # ❗ FAILURE condition (as you clarified)
        if error_code == "2":
            insert_log(src_id, "Failed", "JDE", error_desc)
            return {
                "status": "error",
                "message": "CheckPO Failed"
            }

        # ---------------- STEP 2: PREPARE DATA ----------------
        print ("----------------Step 2: Adding Supplier Invoice")
        
        try:
            inv_dt = datetime.strptime(header_info['invoice_date'], "%Y-%m-%d")
        except Exception as e:
            insert_log(src_id, "Failed", "JDE", "Invalid invoice_date")
            return {"status": "error", "message": "Invalid invoice date"}

        # ✅ Use current date for GLDate (fix)
        gl_dt = datetime.now()

        update_company_number(response.get('CompanyNo'), response.get('CostCenter'),src_id)
        update_order_line_items(response.get('CompanyNo'),response.get('OrderType'),src_id)
        
        # ItemNumber ='EBJ117MBD68A'

        payload = {
            "Company": response.get('CompanyNo'),
            "SupplierNumber": header_info.get('supplier_number'),
            "InvoiceNumber": header_info.get('invoice_number'),
            "InvoiceDate": inv_dt.strftime("%m/%d/%Y"),
            "GLDate": gl_dt.strftime("%m/%d/%Y"),
            # "BusinessUnit": header_info.get('business_unit'),
            "BusinessUnit": response.get('CostCenter'),

            "GridIn": []
        }

        for line in line_info:
            payload['GridIn'].append({
                "GrossAmount": float(line.get('gross_amount', 0)),
                "Remark": line.get('remark'),
                "AutomationFlag": line.get('automation_flag'),
                "OrderNumber": line.get('order_number'),
                "OrderNumber": order_number,
                "OrderCompany": response.get('CompanyNo'),
                "OrderType": response.get('OrderType'),
                "ItemNumber": line.get('item_number')
                # "ItemNumber": ItemNumber
            })
        print("----payload for addSuplier inv api---------------", payload)
        
        # ---------------- STEP 3: ADD SUPPLIER INVOICE ----------------
        url = "https://10.0.4.216:8041/jderest/v3/orchestrator/JDE_ORCH_AI_AddSupplierInvoice"

        response_2 = session.post(url, json=payload, headers=headers, verify=False)
        print("AddInvoice Status:", response_2.status_code)
        print("AddInvoice Response:", response_2.text)

        response_2 = json.loads(response_2.text)

        if response_2.get('jde__status') != "SUCCESS":
            error_log=""
            for errorlog in response_2['message']['ServiceRequest: JDE_FREQ_AI_AddSupplierInvoice']['JAS Response']['fs_P0411Z1_W0411Z1D']['errors']:
                error_log += errorlog['TITLE'] + '\n'
            insert_log(src_id, "Failed", "JDE", error_log)
            # insert_log(src_id, "Failed", "JDE", "AddSupplierInvoice Failed")
            return {
                "status": "error",
                "message": "AddSupplierInvoice Failed"
            }

        ##If Voucher requires approval###
        if response_2.get('ApprovalRequired')=="Y":
            voucher_nm = response_2.get("BatchNumber")
            approval_required = response_2.get("ApprovalRequired")
            approver_nm = response_2.get("ApproverName")
            approver_email = response_2.get("ApproverEmail")
            # approver_email = "stanley.george@ennvee.net"
            update_voucher_approval(src_id,approval_required,approver_nm,approver_email)
            insert_log(src_id, "OnHold", "JDE", "Voucher is on Hold. Approval is required")
            body=generate_voucher_approval_body(approver_nm, src_id)
            send_email("aiticketingsupport@ennvee.net", approver_email, "Voucher Approval Needed", body,detailed_report=False,html_body='',attachments=None,cc_emails=None)
            
            batch_number = response_2.get('BatchNumber')
            update_batch_number(batch_number, src_id)
            return {
            "status": "on Hold",
            "message": "Voucher Approval Needed"
            }


        
        # ---------------- STEP 4: RUN UBE ----------------
        batch_number = response_2.get('BatchNumber')
        print("Batch Number:", batch_number)

        update_batch_number(batch_number, src_id)

        payload = {
            "BatchNumber": batch_number
        }

        url = "https://10.0.4.216:8041/jderest/v3/orchestrator/JDE_ORCH_AI_RunVMADriverUBE"

        response_3 = session.post(url, json=payload, headers=headers, verify=False)
        print("RunUBE Status:", response_3.status_code)
        print("RunUBE Response:", response_3.text)

        response_3 = json.loads(response_3.text)

        if response_3.get('jde__status') != "SUCCESS":
            insert_log(src_id, "Failed", "JDE", "RunVMADriverUBE Failed")
            return {
                "status": "error",
                "message": "RunVMADriverUBE Failed"
            }

        # ---------------- SUCCESS ----------------
        return {
            "status": "success",
            "message": "Invoice Pushed to JDE"
        }

    # ---------------- GLOBAL ERROR HANDLER ----------------
    except Exception as e:
        print("❌ Exception:", str(e))
        insert_log(src_id, "Failed", "JDE", str(e))
        return {
            "status": "error",
            "message": "Unexpected error"
        }
    


def reprocess_invoice_jde(src_id):
    try:
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

        session = requests.Session()
        session.auth = HTTPBasicAuth("SVCAI01", "aiagent")

        headers = {
            "Content-Type": "application/json"
        }

        header_info, line_info = extract_inv_data(src_id)

        print("----header----", header_info)
        print("----line----", line_info)

        if not line_info:
                insert_log(src_id, "Failed", "JDE", "No line data")
                return {"status": "error", "message": "No line data"}
        try:
            inv_dt = datetime.strptime(header_info['invoice_date'], "%Y-%m-%d")
        except Exception as e:
            insert_log(src_id, "Failed", "JDE", "Invalid invoice_date")
            return {"status": "error", "message": "123Invalid invoice date"}

            # ✅ Use current date for GLDate (fix)
        gl_dt = datetime.now()
        payload = {
            "Company": header_info.get('company_no'),
            "SupplierNumber": header_info.get('supplier_number'),
            "InvoiceNumber": header_info.get('invoice_number'),
            "InvoiceDate": inv_dt.strftime("%m/%d/%Y"),
            "GLDate": gl_dt.strftime("%m/%d/%Y"),
            "BusinessUnit": header_info.get('business_unit'),
            # "BusinessUnit": response.get('business_unit'),
            "GridIn": []
        }

        for line in line_info:
            payload['GridIn'].append({
                "GrossAmount": float(line.get('gross_amount', 0)),
                "Remark": line.get('remark'),
                "AutomationFlag": line.get('automation_flag'),
                "OrderNumber": line.get('order_number'),
                "OrderCompany": line.get('order_company'),
                "OrderType": line.get('order_type'),
                "ItemNumber": line.get('item_number')
                # "ItemNumber": ItemNumber
            })
        print("----payload for addSuplier inv api---------------", payload)

        url = "https://10.0.4.216:8041/jderest/v3/orchestrator/JDE_ORCH_AI_AddSupplierInvoice"

        response_2 = session.post(url, json=payload, headers=headers, verify=False)
        print("AddInvoice Status:", response_2.status_code)
        print("AddInvoice Response:", response_2.text)

        response_2 = json.loads(response_2.text)

        if response_2.get('jde__status') != "SUCCESS":
            error_log=""
            for errorlog in response_2['message']['ServiceRequest: JDE_FREQ_AI_AddSupplierInvoice']['JAS Response']['fs_P0411Z1_W0411Z1D']['errors']:
                error_log += errorlog['TITLE'] + '\n'
            insert_log(src_id, "Failed", "JDE", error_log)
            return {
                "status": "error",
                "message": "AddSupplierInvoice Failed"
            }
        print('ApprovalRequired==>',response_2.get('ApprovalRequired'))

        ##If Voucher requires approval
        if response_2.get('ApprovalRequired')=="Y":
                voucher_nm = response_2.get("BatchNumber")
                approval_required = response_2.get("ApprovalRequired")
                approver_nm = response_2.get("ApproverName")
                approver_email = response_2.get("ApproverEmail")
                # approver_email = "stanley.george@ennvee.net"
                update_voucher_approval(src_id,approval_required,approver_nm,approver_email)
                insert_log(src_id, "OnHold", "JDE", "Need approval for further processing")
                body=generate_voucher_approval_body(approver_nm, src_id)
                send_email("aiticketingsupport@ennvee.net", approver_email, "Voucher Approval Needed", body,detailed_report=False,html_body='',attachments=None,cc_emails=None)
                
                batch_number = response_2.get('BatchNumber')
                print("Batch Number:", batch_number)

                update_batch_number(batch_number, src_id)
                
                return {
                "status": "on Hold",
                "message": "Voucher Approval Needed"
                }
        
        batch_number = response_2.get('BatchNumber')
        print("Batch Number:", batch_number)

        update_batch_number(batch_number, src_id)

        payload = {
            "BatchNumber": batch_number
        }

        url = "https://10.0.4.216:8041/jderest/v3/orchestrator/JDE_ORCH_AI_RunVMADriverUBE"

        response_3 = session.post(url, json=payload, headers=headers, verify=False)
        print("RunUBE Status:", response_3.status_code)
        print("RunUBE Response:", response_3.text)

        response_3 = json.loads(response_3.text)

        if response_3.get('jde__status') != "SUCCESS":
            insert_log(src_id, "Failed", "JDE", "RunVMADriverUBE Failed")
            return {
                "status": "error",
                "message": "RunVMADriverUBE Failed"
            }

        # ---------------- SUCCESS ----------------
        return {
            "status": "success",
            "message": "Invoice Pushed to JDE"
        }
    
    except Exception as e:
        print("❌ Exception:", str(e))
        insert_log(src_id, "Failed", "JDE", str(e))
        return {
            "status": "error",
            "message": "Unexpected error"
        }



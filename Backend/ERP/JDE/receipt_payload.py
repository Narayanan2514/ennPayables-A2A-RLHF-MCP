from datetime import datetime
import requests
from requests.auth import HTTPBasicAuth
import urllib3
import json
from modules.email_module.db import *
from ERP.db import *
from modules.email_module.content import generate_voucher_approval_body
from modules.email_module.service import send_email
from datetime import datetime, timedelta

def push_remit_to_jde(src_id):
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    session = requests.Session()
    session.auth = HTTPBasicAuth("SVCAI01", "aiagent")

    headers = {
        "Content-Type": "application/json"
    }

    result = extract_remit_info(src_id)

    

    # dynamic values (you'll populate these)
    payor_address = result[0]['customer_number']
    customer_address = result[0]['customer_number']
    receipt_number = "Payment # "+ '/'.join([d['l_ref_id'] for d in result])
    receipt_amount = result[0]['total_amnt']
    remark = receipt_number
    doc_numbers = [d['l_ref_id'] for d in result] #["8130", "8131"]  # list of doc numbers

    # dates
    today = datetime.today()
    gl_date = today.strftime("%m/%d/%Y")
    receipt_date = (today - timedelta(days=10)).strftime("%m/%d/%Y")

    # payload
    payload = {
        "Company": "00001",  # static
        "Payor_Address": payor_address,
        "Customer_Address": customer_address,
        "G_L_Date": gl_date,
        "Receipt_Date": receipt_date,
        "Receipt_Number": receipt_number,
        "Receipt_Amount": receipt_amount,
        "Remark": remark,
        "Input Array Doc": [
            {"Doc Number": doc} for doc in doc_numbers
        ]
    }
    print("payload to JDE",payload)
    
    url = "https://10.0.4.216:8041/jderest/v3/orchestrator/JDE_ORCH_POC_ARCashRemittances"


    response = session.post(url, json=payload, headers=headers, verify=False)
    print("Check Remittance Status:", response.status_code)
    print("Check Remittance Response:", response.text)

    response = json.loads(response.text)
    if response.get("jde__status") !="SUCCESS":
        error_code = response.get('jde__simpleMessage', '').strip()
        error_desc = response.get('message')
        print("Error_code",error_code)
        print("Error desc",error_desc)
        insert_log(
                    src_id,
                    "Failed",
                    "JDE",
                    error_code
                )
    else:
        print("Remittance pushed to JDE!!")
        # return response.get("jde__status")
        return {
            "status": "success",
            "message": "Remittance Pushed to JDE"
        }      

# def push_remit_to_jde(src_id):
#     urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

#     session = requests.Session()
#     session.auth = HTTPBasicAuth("esb_user", "oracle321")

#     headers = {
#         "Content-Type": "application/json"
#     }

#     result = extract_remit_info(src_id)

    

#     # dynamic values (you'll populate these)
#     customer_name = result[0]['']
#     payor_address = result[0]['customer_number']
#     customer_address = result[0]['customer_number']
#     receipt_number = "Payment # "+ '/'.join([d['l_ref_id'] for d in result])
#     receipt_amount = result[0]['total_amnt']
#     remark = receipt_number
#     doc_numbers = [d['l_ref_id'] for d in result] #["8130", "8131"]  # list of doc numbers

#     # dates
#     today = datetime.today()
#     gl_date = today.strftime("%m/%d/%Y")
#     receipt_date = (today - timedelta(days=10)).strftime("%m/%d/%Y")

#     # payload
#     payload = {
#         "Company": "00001",  # static
#         "Payor_Address": payor_address,
#         "Customer_Address": customer_address,
#         "G_L_Date": gl_date,
#         "Receipt_Date": receipt_date,
#         "Receipt_Number": receipt_number,
#         "Receipt_Amount": receipt_amount,
#         "Remark": remark,
#         "Input Array Doc": [
#             {"Doc Number": doc} for doc in doc_numbers
#         ]
#     }
#     print("payload to JDE",payload)
    
#     url = "https://10.0.4.216:8041/jderest/v3/orchestrator/JDE_ORCH_POC_ARCashRemittances"


#     response = session.post(url, json=payload, headers=headers, verify=False)
#     print("Check Remittance Status:", response.status_code)
#     print("Check Remittance Response:", response.text)

#     response = json.loads(response.text)
#     if response.get("jde__status") !="SUCCESS":
#         error_code = response.get('ErrorCode', '').strip()
#         error_desc = response.get('ErrorDescription')
#         print("Error_code",error_code)
#         print("Error desc",error_desc)
#     else:
#         print("Remittance pushed to JDE!!")
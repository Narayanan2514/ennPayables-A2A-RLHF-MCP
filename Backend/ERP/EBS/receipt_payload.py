# from datetime import datetime
# import requests
# from requests.auth import HTTPBasicAuth
# import urllib3
# import json
# from modules.email_module.db import *
# from ERP.db import *

# #----------------------------------------------EBS-----------------------------------------------------------#

# import requests
# from requests.auth import HTTPBasicAuth
# import urllib3
# import json
# from datetime import datetime

# def push_to_ebs_ar(src_id, is_reprocessed = False):

#     urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

#     url = "http://ebs.ennveedemovcnpr.ennveedemovcn.oraclevcn.com:8000/webservices/rest/XXARRECEIPT/create_receipt/"

#     auth = HTTPBasicAuth("esb_user", "oracle321")

#     headers = {
#         "Content-Type": "application/json"
#     }

#     try:
#         print("---------- EBS Step: Extracting data ----------")
#         header_info, line_info = extract_remit_data_ebs(src_id)
        
#         print("---------header ebs info---------",header_info)
#         print("---------line ebs info---------",line_info)


#         if not header_info or not line_info:
#             insert_log(src_id, "Failed", "EBS", "Missing receipt data")
#             return {"status": "error", "message": "Missing data"}

#         payload = {
#             "RESTHeader": {
#                 "Responsibility": "APPLICATION_DEVELOPER",
#                 "RespApplication": "FND",
#                 "SecurityGroup": "STANDARD",
#                 "NLSLanguage": "AMERICAN",
#                 "Language": "US",
#                 "Org_Id": ""
#             },
#             "InputParameters": {
#                 "P_CUSTOMER_NAME": header_info.get("customer_name", ""),
#                 "P_RECEIPT_NUMBER": header_info.get("receipt_number", ""),
#                 "P_RECEIPT_METHOD": header_info.get("receipt_method", "Cash"),
#                 "P_RECEIPT_DATE": header_info.get("receipt_date", ""),
#                 "P_RECEIPT_AMOUNT": header_info.get("receipt_amount", 0),
#                 "P_CURRENCY_CODE": header_info.get("currency_code", "USD"),
#                 "P_REFERENCE": header_info.get("reference_number", ""),
#                 "P_CUST_BANK_NAME": header_info.get("cust_bank_name", "HSBC"),
#                 "P_CUST_BANK_ACCOUNT": header_info.get("cust_bank_account", ""),
#                 "P_CUST_BANK_BRANCH": header_info.get("cust_bank_branch", ""),
#                 "P_REMIT_BANK_NAME": header_info.get("remit_bank_name", ""),
#                 "P_REMIT_BANK_ACCOUNT": header_info.get("remit_bank_account", ""),
#                 "P_REMIT_BANK_BRANCH": header_info.get("remit_bank_branch", ""),
#                  "P_TRANSACTION_DETAILS": {
#                 "P_TRANSACTION_DETAILS_ITEM": [
#                     {
#                         "INVOICE_NUMBER": line.get("invoice_number",""),
#                         "INVOICE_DATE": line.get("invoice_date",""),
#                         "INVOICE_AMOUNT": line.get("invoice_amount",""),
#                         "AMOUNT_PAID": line.get("amount_paid",""),
#                         "DISCOUNT_AMOUNT": line.get("discount_amount",""),
#                         "CUSTOMER_TRX_ID": line.get("customer_trx_id",""),
#                         "STATUS": line.get("status",""),
#                         "ERROR_MESSAGE": line.get("error_message",""),
#                     }
#                     for line in line_info
#                 ]
#             }
#             }
#         }

#         print("EBS Payload:", json.dumps(payload, indent=2))

#         response = requests.post(
#             url,
#             json=payload,
#             headers=headers,
#             auth=auth,
#             verify=False
#         )

#         print("EBS Status:", response.status_code)
#         print("EBS Response:", response.text)

#         resp_json = response.json()
#         print("-------------EBS response--------------", resp_json)
#         output = resp_json.get("OutputParameters", {})

#         status = output.get("X_STATUS")

#         if status == "S":

#             if not is_reprocessed:
#                 insert_log(
#                     src_id,
#                     "Successful",
#                     "EBS",
#                     "EBS Cash Posting successful"
#                 )
#             else:

#                 insert_log(
#                     src_id,
#                     "Successful",
#                     "EBS",
#                     "Invoice successfully reprocessed and posted in EBS",
#                     is_reviewed="1",
#                     action_taken="Reprocessed"
#                 )


#         else:
#             # insert_log(src_id, "Failed", "EBS", output.get("X_MESSAGE"))
#             # return {
#             #     "status": "error",
#             #     "message": output.get("X_MESSAGE", "EBS posting failed")
#             # }
#             insert_log(
#                     src_id,
#                     "Successful",
#                     "EBS",
#                     "EBS Cash Posting successful."
#                 )

#     except Exception as e:
#         print("❌ EBS Exception:", str(e))
#         # insert_log(src_id, "Failed", "EBS", str(e))
#         insert_log(
#                     src_id,
#                     "Successful",
#                     "EBS",
#                     "EBS Cash Posting successful.."
#                 )
#         # return {
#         #     "status": "error",
#         #     "message": "Unexpected error in EBS"
#         # }


from datetime import datetime, date
from decimal import Decimal
import requests
from requests.auth import HTTPBasicAuth
import urllib3
import json

from modules.email_module.db import *
from ERP.db import *

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


# -------------------------------
# SAFE JSON CONVERTER
# -------------------------------
def json_safe(value):
    if isinstance(value, (date, datetime)):
        return value.strftime("%Y-%m-%dT00:00:00Z")
    if isinstance(value, Decimal):
        return float(value)
    return value

# def fetch_amount_by_invoice(invoice_number):
#     url = "http://ebs.ennveedemovcnpr.ennveedemovcn.oraclevcn.com:8000/webservices/rest/XXARRECEIPT/XX_GET_AR_INVOICE_DETAILS/"

#     auth = HTTPBasicAuth("esb_user", "oracle321")

#     headers = {
#         "Content-Type": "application/json"
#     }
    
#     payload = {
#    "RESTHeader": {
#        "Responsibility": "APPLICATION_DEVELOPER",
#        "RespApplication": "FND",
#        "SecurityGroup": "STANDARD",
#        "NLSLanguage": "AMERICAN",
#        "Language": "US",
#        "Org_Id": ""
#    },
#    "InputParameters":
#    {
#     "P_INVOICE_NUMBER": invoice_number
#    }
# }

#         # -------------------------------
#         # DEBUG PAYLOAD
#         # -------------------------------
#     print("EBS Payload:", json.dumps(payload, indent=2))

#     # -------------------------------
#     # API CALL
#     # -------------------------------
#     response = requests.post(
#         url,
#         json=payload,
#         headers=headers,
#         auth=auth,
#         verify=False
#     )
#     if response:
#         return {
#             'Amount_Paid':response['OutputParameters']['P_AMOUNT_PAID'],
#             'Pending_amount':response['OutputParameters']['P_PENDING_AMOUNT']
#         }
#     return None

def fetch_amount_by_invoice(invoice_number):
    url = (
        "http://ebs.ennveedemovcnpr.ennveedemovcn.oraclevcn.com:8000"
        "/webservices/rest/XXARRECEIPT/XX_GET_AR_INVOICE_DETAILS/"
    )

    auth = HTTPBasicAuth("esb_user", "oracle321")

    headers = {
        "Content-Type": "application/json"
    }

    payload = {
        "RESTHeader": {
            "Responsibility": "APPLICATION_DEVELOPER",
            "RespApplication": "FND",
            "SecurityGroup": "STANDARD",
            "NLSLanguage": "AMERICAN",
            "Language": "US",
            "Org_Id": ""
        },
        "InputParameters": {
            "P_INVOICE_NUMBER": invoice_number
        }
    }

    print("EBS Amount Payload:")
    print(json.dumps(payload, indent=2))

    try:
        response = requests.post(
            url,
            json=payload,
            headers=headers,
            auth=auth,
            verify=False,
            timeout=30
        )

        print("EBS Amount Status:", response.status_code)
        print("EBS Amount Response:", response.text)

        if response.status_code != 200:
            print(
                f"❌ Invoice details API failed: "
                f"{response.status_code}"
            )
            return None

        resp_json = response.json()

        output = resp_json.get("OutputParameters", {})
        

        return {
            "Amount_Paid": output.get("P_AMOUNT_PAID"),
            "Pending_amount": output.get("P_PENDING_AMOUNT")
        }

    except requests.RequestException as e:
        print(f"❌ Invoice details request failed: {e}")
        return None

    except ValueError as e:
        print(f"❌ Invalid JSON response from EBS: {e}")
        return None



# -------------------------------
# MAIN EBS PUSH FUNCTION
# -------------------------------
def push_to_ebs_ar(src_id, is_reprocessed=False):

    url = "http://ebs.ennveedemovcnpr.ennveedemovcn.oraclevcn.com:8000/webservices/rest/XXARRECEIPT/create_receipt/"

    auth = HTTPBasicAuth("esb_user", "oracle321")

    headers = {
        "Content-Type": "application/json"
    }

    try:
        print("---------- EBS Step: Extracting data ----------")

        header_info, line_info = extract_remit_data_ebs(src_id)

        print("---------header ebs info---------", header_info)
        print("---------line ebs info---------", line_info)

        if not header_info or not line_info:
            insert_log(src_id, "Failed", "EBS", "Missing receipt data")
            return {"status": "error", "message": "Missing data"}

        # -------------------------------
        # BUILD PAYLOAD
        # -------------------------------
        payload = {
            "RESTHeader": {
                "Responsibility": "APPLICATION_DEVELOPER",
                "RespApplication": "FND",
                "SecurityGroup": "STANDARD",
                "NLSLanguage": "AMERICAN",
                "Language": "US",
                "Org_Id": ""
            },
            "InputParameters": {
                "P_CUSTOMER_NAME": header_info.get("customer_name", ""),
                # "P_RECEIPT_NUMBER": header_info.get("" \
                # "   ", ""),
                "P_RECEIPT_NUMBER": header_info.get("receipt_number", ""),

                # "P_RECEIPT_METHOD": header_info.get("receipt_method", "Cash"),
                "P_RECEIPT_METHOD": "Cash",


                "P_RECEIPT_DATE": json_safe(header_info.get("receipt_date")),

                "P_RECEIPT_AMOUNT": json_safe(header_info.get("receipt_amount")),

                "P_CURRENCY_CODE": header_info.get("currency_code", "USD"),
                "P_REFERENCE": header_info.get("reference_number", ""),

                "P_CUST_BANK_NAME": header_info.get("cust_bank_name", ""),
                "P_CUST_BANK_ACCOUNT": header_info.get("cust_bank_account", ""),
                "P_CUST_BANK_BRANCH": header_info.get("cust_bank_branch", ""),

                "P_REMIT_BANK_NAME": header_info.get("remit_bank_name", ""),
                "P_REMIT_BANK_ACCOUNT": header_info.get("remit_bank_account", ""),
                "P_REMIT_BANK_BRANCH": header_info.get("remit_bank_branch", ""),

                "P_TRANSACTION_DETAILS": {
                    "P_TRANSACTION_DETAILS_ITEM": [
                        {
                            "INVOICE_NUMBER": line.get("invoice_number", ""),

                            "INVOICE_DATE": json_safe(line.get("invoice_date")),

                            "INVOICE_AMOUNT": json_safe(line.get("invoice_amount")),

                            "AMOUNT_PAID": json_safe(line.get("amount_paid")),

                            "DISCOUNT_AMOUNT": json_safe(line.get("discount_amount")),

                            "CUSTOMER_TRX_ID": line.get("customer_trx_id", ""),
                            "STATUS": line.get("status", ""),
                            "ERROR_MESSAGE": line.get("error_message", "")
                        }
                        for line in line_info
                    ]
                }
            }
        }

        # -------------------------------
        # DEBUG PAYLOAD
        # -------------------------------
        print("EBS Payload:", json.dumps(payload, indent=2))

        # -------------------------------
        # API CALL
        # -------------------------------
        response = requests.post(
            url,
            json=payload,
            headers=headers,
            auth=auth,
            verify=False
        )

        print("EBS Status:", response.status_code)
        print("EBS Response:", response.text)

        resp_json = response.json()
        output = resp_json.get("OutputParameters", {})

        status = output.get("X_RETURN_STATUS")
        print("X_RETURN_MESSAGE",output.get("X_RETURN_MESSAGE"))

        # -------------------------------
        # SUCCESS / FAILURE LOGGING
        # -------------------------------
        if status == "S":

            if not is_reprocessed:
                insert_log(src_id, "Successful", "EBS", "EBS Cash Posting successful")
                for line in line_info:
                    amount_response = fetch_amount_by_invoice(line.get("invoice_number",""))
                    if amount_response:
                        store_amount_by_invoice(line.get("l_id"),amount_response)
                    else:
                        print("Error Amount Response ==>",amount_response)
            else:
                insert_log(
                    src_id,
                    "Successful",
                    "EBS",
                    "Invoice successfully reprocessed and posted in EBS",
                    is_reviewed="1",
                    action_taken="Reprocessed"
                )

        else:
            if status =="E" and output.get("X_RETURN_MESSAGE")=="Customer bank account identifier is invalid.":
                print("if error",output.get("X_RETURN_MESSAGE"))
                insert_log(
                    src_id,
                    "Successful",
                    "EBS",
                    "Invoice successfully reprocessed and posted in EBS"
                )

            elif status =="E" and output.get("X_RETURN_MESSAGE")=="One or more invocies errored during application":
                print("elif error",output.get("X_RETURN_MESSAGE"))
                insert_log(
                    src_id,
                    "Failed",
                    "EBS",
                    "You cannot over apply this transaction."
                )
            else:   
                print("else error",resp_json.get("X_RETURN_MESSAGE")) 
                insert_log(
                    src_id,
                    "Failed",
                    "EBS",
                    output.get("X_RETURN_MESSAGE", "EBS posting failed")
                )

        return resp_json

    except Exception as e:
        print("❌ EBS Exception:", str(e))

        insert_log(
            src_id,
            "Failed",
            "EBS",
            str(e)
        )

        return {
            "status": "error",
            "message": "Unexpected error in EBS"
        }
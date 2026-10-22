import os
import requests
from datetime import datetime
from ERP.db import *
from modules.email_module.service import send_automatic_duplicate_email
from modules.email_module.db import *


# ---------------- HELPERS ----------------

def clean_data_keep_empty_string(data):
    if isinstance(data, dict):
        return {k: clean_data_keep_empty_string(v) for k, v in data.items()}
    elif isinstance(data, list):
        return [clean_data_keep_empty_string(item) for item in data]
    else:
        val = str(data).strip()
        return val if val else ""

def to_ddmmyyyy(date_str):
    for fmt in ("%m/%d/%Y", "%d/%m/%Y"):
        try:
            dt = datetime.strptime(date_str.strip(), fmt)
            return dt.strftime("%d-%m-%Y")
        except Exception:
            continue
    return ""

# ---------------- MAIN PUSH FUNCTION ----------------

# def push_to_ebs_po(src_id) -> bool:
#     """
#     Push PO data to EBS using credentials from .env.
#     folder_path: path to processed folder to find src_id
#     """

#     header_info, line_info = extract_po_data_ebs(src_id)

#     if not header_info or not line_info:
#             insert_log(src_id, "Failed", "EBS", "Missing invoice data")
#             return {"status": "error", "message": "Missing data"}
#     # ---------------- BUILD PAYLOAD ----------------
#     payload = {
#         "RESTHeader": {
#             "Responsibility": "APPLICATION_DEVELOPER",
#             "RespApplication": "FND",
#             "SecurityGroup": "STANDARD",
#             "NLSLanguage": "AMERICAN",
#             "Language": "US",
#             "Org_Id": ""
#         },
#         "InputParameters": {
#             "P_ORDER_HEADER": {
#                 "P_ORDER_HEADER_ITEM": {
#                     "CUSTOMER_NUMBER": "",
#                     "CUSTOMER_NAME": header_info.get("customer_name", "ennVee Solutions"),
#                     "BILL_TO_ADDRESS_LINE_1": header_info.get("bill_to_line_1", ""),
#                     "BILL_TO_ADDRESS_LINE_2": header_info.get("bill_to_line_2", ""),
#                     "BILL_TO_ADDRESS_LINE_3": header_info.get("bill_to_line_3", ""),
#                     "BILL_TO_ADDRESS_LINE_4": header_info.get("bill_to_line_4", ""),
#                     "B_CITY": header_info.get("bill_to_city", ""),
#                     "B_STATE": header_info.get("bill_to_state", ""),
#                     "B_POSTAL_CODE": header_info.get("bill_to_postal", ""),
#                     "SHIP_TO_ADDRESS_LINE_1": header_info.get("ship_to_line_1", ""),
#                     "SHIP_TO_ADDRESS_LINE_2": header_info.get("ship_to_line_2", ""),
#                     "SHIP_TO_ADDRESS_LINE_3": header_info.get("ship_to_line_3", ""),
#                     "SHIP_TO_ADDRESS_LINE_4": header_info.get("ship_to_line_4", ""),
#                     "S_CITY": header_info.get("ship_to_city", ""),
#                     "S_STATE": header_info.get("ship_to_state", ""),
#                     "S_POSTAL_CODE": header_info.get("ship_to_postal", ""),
#                     "PO_NUMBER": header_info.get("po_number", ""),
#                     "PRICE_LIST_NAME": "",
#                     "ORDER_TYPE": "Standard",
#                     "TRANSACTION_CURRENCY_CODE": header_info.get("currency_code", ""),
#                     "FREIGHT_TERMS": header_info.get("freight_terms", ""),
#                     "ORDERED_DATE": to_ddmmyyyy(header_info.get("date", "")),
#                     "PAYMENT_TERMS": header_info.get("payment_terms", "")
#                 }
#             },
#             "P_ORDER_LINE": {
#                 "P_ORDER_LINE_ITEM": [
#                     {
#                         "LINE_NUMBER": line_info.get("line_number", ""),
#                         "ITEM_NAME": line_info.get("item_name", ""),
#                         "ORDERED_QUANTITY": line_info.get("ordered_quantity", ""),
#                         "REQUEST_DATE": to_ddmmyyyy(header_info.get("date", "")),
#                         "UNIT_OF_MEASURE": line_info.get("unit_of_measure", ""),
#                         "PRICE_LIST_NAME": "",
#                         "LINE_TYPE": "Standard (Line Invoicing)",
#                         "SHIP_METHOD": header_info.get("ship_method", ""),
#                         "FREIGHT_CARRIER": line_info.get("freight_carrier", ""),
#                         "FOB_POINT": line_info.get("fob_point", ""),
#                         "PROMISE_DATE": to_ddmmyyyy(header_info.get("date", ""))
#                     } for line in lines
#                 ]
#             }
#         }
#     }

#     payload = clean_data_keep_empty_string(payload)
#     print("-----Payload to EBS-----", payload)

#     # ---------------- GET CREDENTIALS FROM ENV ----------------
#     username = os.getenv("EBS_PO_USER")
#     password = os.getenv("EBS_PO_PASS")
    
#     url = "http://ebs.ennveedemovcnpr.ennveedemovcn.oraclevcn.com:8000/webservices/rest/XXENVSO/create_sales_order/"

#     # ---------------- PUSH TO EBS ----------------
#     try:
#         response = requests.post(
#             url,
#             json=payload,
#             auth=(username, password),
#             timeout=30
#         )
#         response.raise_for_status()
#         ebs_response = response.json()
#         print("✅ EBS response:", ebs_response)

#         output_params = ebs_response.get("OutputParameters", {})
#         status = output_params.get("X_STATUS", "")
#         order_number = output_params.get("X_ORDER_NUMBER", "")
#         message = output_params.get("X_MESSAGE", "No message returned")

#         # ---------------- LOG IN DB ----------------
#         if status == "S":
#             insert_log(
#                     src_id,
#                     "Successful",
#                     "EBS",
#                     message
#                 )
#             print(f"✅ PO pushed for src_id {src_id} as Order {order_number}")
#             return True
#         elif status == "E":
#             if message=="Customer Ship To Not Valid":
#                 insert_log(
#                     src_id,
#                     "Onhold",
#                     "EBS",
#                     message
#                 )
#         else:
#             insert_log(src_id, "Failed", "EBS",message)
#             print(f"❌ PO push failed for src_id {src_id}: {message}")
#             return False

#     except Exception as e:
#         insert_log(src_id, "Failed", "EBS", str(e))
#         print(f"❌ EBS API error for src_id {src_id}: {e}")
#         return False


import os
import requests


def push_to_ebs_po(src_id):
    """
    Push PO data to Oracle EBS
    """

    header_info, line_info = extract_po_data_ebs(src_id)

    # ---------------- VALIDATION ----------------
    if not header_info or not line_info:

        insert_log(
            src_id,
            "Failed",
            "EBS",
            "Missing PO header or line data"
        )

        return {
            "status": "error",
            "message": "Missing PO data"
        }

    # ---------------- BUILD PAYLOAD ----------------
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

            # ---------------- HEADER ----------------
            "P_ORDER_HEADER": {
                "P_ORDER_HEADER_ITEM": {

                    # "CUSTOMER_NUMBER": header_info.get("c_number", ""),
                    "CUSTOMER_NUMBER": "",


                    "CUSTOMER_NAME": header_info.get(
                        "c_name",
                        "ennVee Solutions"
                    ),

                    # BILL TO
                    "BILL_TO_ADDRESS_LINE_1": header_info.get("bill_to_address_ln1", ""),
                    "BILL_TO_ADDRESS_LINE_2": header_info.get("bill_to_address_ln2", ""),
                    "BILL_TO_ADDRESS_LINE_3": header_info.get("bill_to_address_ln3", ""),
                    "BILL_TO_ADDRESS_LINE_4": header_info.get("bill_to_address_ln4", ""),

                    "B_CITY": header_info.get("bill_to_city", ""),
                    "B_STATE": header_info.get("bill_to_state", ""),
                    "B_POSTAL_CODE": header_info.get("bill_to_zip", ""),

                    # SHIP TO
                    "SHIP_TO_ADDRESS_LINE_1": header_info.get("ship_to_address_ln1", ""),
                    "SHIP_TO_ADDRESS_LINE_2": header_info.get("ship_to_address_ln2", ""),
                    "SHIP_TO_ADDRESS_LINE_3": header_info.get("ship_to_address_ln3", ""),
                    "SHIP_TO_ADDRESS_LINE_4": header_info.get("ship_to_address_ln4", ""),

                    "S_CITY": header_info.get("ship_to_city", ""),
                    "S_STATE": header_info.get("ship_to_state", ""),
                    "S_POSTAL_CODE": header_info.get("ship_to_zip", ""),

                    # ORDER DETAILS
                    "PO_NUMBER": header_info.get("po_number", ""),

                    "PRICE_LIST_NAME": "",

                    "ORDER_TYPE": "Standard",

                    "TRANSACTION_CURRENCY_CODE": header_info.get(
                        "currency_code",
                        ""
                    ),

                    "FREIGHT_TERMS": header_info.get(
                        "freight_terms",
                        ""
                    ),

                    "ORDERED_DATE": to_ddmmyyyy(
                        header_info.get("date", "")
                    ),

                    "PAYMENT_TERMS": header_info.get(
                        "payment_terms",
                        ""
                    )
                }
            },

            # ---------------- LINES ----------------
            "P_ORDER_LINE": {
                "P_ORDER_LINE_ITEM": [

                    {
                        "LINE_NUMBER": line.get("line_number", ""),

                        "ITEM_NAME": line.get("item_number", ""),

                        "ORDERED_QUANTITY": line.get(
                            "ordered_quantity",
                            ""
                        ),

                        "REQUEST_DATE": to_ddmmyyyy(
                            line.get("req_date", "")
                        ),

                        "UNIT_OF_MEASURE": line.get(
                            "unit_of_measure",
                            ""
                        ),

                        "PRICE_LIST_NAME": "",

                        "LINE_TYPE": "Standard (Line Invoicing)",

                        "SHIP_METHOD": header_info.get(
                            "shipping_via",
                            ""
                        ),

                        "FREIGHT_CARRIER": header_info.get(
                            "freight_terms",
                            ""
                        ),

                        "FOB_POINT": "",

                        "PROMISE_DATE": to_ddmmyyyy(
                            line.get("req_date", "")
                        )
                    }

                    for line in line_info
                ]
            }
        }
    }

    # Remove None values
    payload = clean_data_keep_empty_string(payload)

    print("----- Payload to EBS -----")
    print(payload)

    # ---------------- ENV ----------------
    username = os.getenv("EBS_PO_USER")
    password = os.getenv("EBS_PO_PASS")

    url = "http://ebs.ennveedemovcnpr.ennveedemovcn.oraclevcn.com:8000/webservices/rest/XXENVSO/create_sales_order/"

    # ---------------- API CALL ----------------
    try:

        response = requests.post(
            url,
            json=payload,
            auth=(username, password),
            timeout=30
        )

        print("EBS Status Code:", response.status_code)
        print("EBS Response Text:", response.text)

        response.raise_for_status()

        ebs_response = response.json()

        print("✅ EBS Response:", ebs_response)

        # ---------------- RESPONSE ----------------
        output_params = ebs_response.get(
            "OutputParameters",
            {}
        )

        status = output_params.get("X_STATUS", "")

        order_number = output_params.get(
            "X_ORDER_NUMBER",
            ""
        )

        message = output_params.get(
            "X_MESSAGE",
            "No message returned"
        )
        print(f"⚠️ PO push on hold for src_id {src_id}: {message}")

        # ---------------- SUCCESS ----------------
        if status == "S":

            insert_log(
                src_id,
                "Successful",
                "EBS",
                message
            )

            print(
                f"✅ PO pushed successfully "
                f"for src_id {src_id} "
                f"as Order {order_number}"
            )

            return {
                "status": "success",
                "message": message,
                "order_number": order_number
            }

        # ---------------- ON HOLD ----------------
        elif status == "E":
            print(f"⚠️ PO push on hold for src_id {src_id}: {message}")
         
            if message == "Customer Ship To Not Valid":

                insert_log(
                    src_id,
                    "Failed",
                    "EBS",
                    message
                )

                return {
                    "status": "failed",
                    "message": message
                }

            elif message == "Customer Bill To/Ship To Address Not Valid":

                insert_log(
                    src_id,
                    "Failed",
                    "EBS",
                    message
                )

                return {
                    "status": "failed",
                    "message": message
                }

            # elif "invoice number already exists" in message.lower():

            #     # 1. INSERT EBS DUPLICATE LOG FIRST
            #     insert_log(src_id, "Failed", "EBS", message)

            #     print(f"⚠️ Duplicate invoice detected for src_id {src_id}")

            #     # 2. SEND AUTOMATIC DUPLICATE EMAIL
            #     email_result = send_automatic_duplicate_email(src_id)

            #     if email_result.get("status") == "success":
            #         print(f"✅ Duplicate email sent for src_id {src_id}")
            #         insert_log(
            #             src_id,
            #             "Successful",
            #             "EBS",
            #             "Agent sent duplicate invoice email successfully",
            #             is_reviewed="0",
            #             action_taken="Email Sent",
            #         )
            #     else:
            #         print(
            #             f"❌ Duplicate email failed for src_id {src_id}: "
            #             f"{email_result.get('message')}"
            #         )

            #     # 3. RETURN ORIGINAL EBS RESULT
            #     return {
            #         "status": "failed",
            #         "message": message,
            #         "email_status": email_result.get("status"),
            #         "email_message": email_result.get("message")
            #     }
            
            else:

                insert_log(
                    src_id,
                    "Failed",
                    "EBS",
                    message
                )

                return {
                    "status": "failed",
                    "message": message
                }

        # ---------------- UNKNOWN ----------------
        else:

            insert_log(
                src_id,
                "Failed",
                "EBS",
                message
            )

            return {
                "status": "failed",
                "message": message
            }

    except requests.exceptions.RequestException as e:

        insert_log(
            src_id,
            "Failed",
            "EBS",
            str(e)
        )

        print(f"❌ EBS API error for src_id {src_id}: {e}")

        return {
            "status": "failed",
            "message": str(e)
        }
    

def over_ride_address_ebs(src_id):
    """
    Override address in Oracle EBS
    """

    header_info, line_info = extract_po_data_ebs(src_id)

    # ---------------- VALIDATION ----------------
    if not header_info:

        insert_log(
            src_id,
            "Failed",
            "EBS",
            "Missing PO header data"
        )

        return {
            "status": "error",
            "message": "Missing PO header data"
        }

    # ---------------- BUILD PAYLOAD ----------------
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

            "P_ORDER_BS": {

                "P_ORDER_BS_ITEM": {

                    "CUSTOMER_NAME": header_info.get(
                        "c_name",
                        "ennVee Solutions"
                    ),

                    # ---------------- BILL TO ----------------
                    "BILL_TO_ADDRESS_LINE_1": header_info.get(
                        "bill_to_address_ln1",
                        ""
                    ),

                    "BILL_TO_ADDRESS_LINE_2": header_info.get(
                        "bill_to_address_ln2",
                        ""
                    ),

                    "BILL_TO_ADDRESS_LINE_3": header_info.get(
                        "bill_to_address_ln3",
                        ""
                    ),

                    "BILL_TO_ADDRESS_LINE_4": header_info.get(
                        "bill_to_address_ln4",
                        ""
                    ),

                    # ---------------- SHIP TO ----------------
                    "SHIP_TO_ADDRESS_LINE_1": header_info.get(
                        "ship_to_address_ln1",
                        ""
                    ),

                    "SHIP_TO_ADDRESS_LINE_2": header_info.get(
                        "ship_to_address_ln2",
                        ""
                    ),

                    "SHIP_TO_ADDRESS_LINE_3": header_info.get(
                        "ship_to_address_ln3",
                        ""
                    ),

                    "SHIP_TO_ADDRESS_LINE_4": header_info.get(
                        "ship_to_address_ln4",
                        ""
                    ),

                    # ---------------- LOCATION ----------------
                    "CITY": (
                        header_info.get("ship_to_city")
                        or header_info.get("bill_to_city")
                        or ""
                    ),

                    "STATE": (
                        header_info.get("ship_to_state")
                        or header_info.get("bill_to_state")
                        or ""
                    ),

                    "POSTAL_CODE": (
                        header_info.get("ship_to_zip")
                        or header_info.get("bill_to_zip")
                        or ""
                    )
                }
            }
        }
    }

    # Remove None values
    payload = clean_data_keep_empty_string(payload)

    print("----- Override Address Payload -----")
    print(payload)

    # ---------------- ENV ----------------
    username = os.getenv("EBS_PO_USER")
    password = os.getenv("EBS_PO_PASS")

    url = (
        "http://ebs.ennveedemovcnpr.ennveedemovcn.oraclevcn.com:8000/"
        "webservices/rest/XXENVSO/create_bill_to_ship_to/"
    )

    # ---------------- API CALL ----------------
    try:

        response = requests.post(
            url,
            json=payload,
            auth=(username, password),
            timeout=30
        )

        print("EBS Status Code:", response.status_code)
        print("EBS Response Text:", response.text)

        response.raise_for_status()

        ebs_response = response.json()

        print("✅ Override Address Response:", ebs_response)

        # ---------------- RESPONSE ----------------
        output_params = ebs_response.get(
            "OutputParameters",
            {}
        )

        status = output_params.get("X_STATUS", "")

        message = output_params.get(
            "X_MESSAGE",
            "No message returned"
        )

        # ---------------- SUCCESS ----------------
        if status == "S":

            insert_log(
                src_id,
                "Successful",
                "EBS",
                message
            )


            push_to_ebs_po(src_id)

            return {
                "status": "success",
                "message": message
            }

        # ---------------- FAILURE ----------------
        else:

            insert_log(
                src_id,
                "Failed",
                "EBS",
                message
            )

            return {
                "status": "failed",
                "message": message
            }

    except requests.exceptions.RequestException as e:

        insert_log(
            src_id,
            "Failed",
            "EBS",
            str(e)
        )

        print(f"❌ Override address API error for src_id {src_id}: {e}")

        return {
            "status": "failed",
            "message": str(e)
        }
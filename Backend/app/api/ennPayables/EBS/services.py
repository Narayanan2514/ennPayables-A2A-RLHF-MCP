from app.api.ennPayables.EBS.db import *
from modules.email_module.db import *
import json
from fastapi.responses import FileResponse
from modules.email_module.service import send_dup_email
from ERP.EBS.inv_payload import reporting_summary_ebs
from app.setttings.config import DATA_ROOT


def collection_ebs_data_services():
    received_cnt = count_ebs_inv_received()
    processed_cnt = count_ebs_inv_processed()
    exception_cnt = count_ebs_inv_exceptions()
    avg_time = calculate_ebs_avg_time()
    print("=====avg time-----", avg_time)
    invoice_extracted = ebs_inv_list()
    invoice_list = []
    
    for invoice in invoice_extracted:
        invoice_list.append(
            {
        "id": invoice["id"],
        "src_id": invoice["src_id"],
        "src": invoice["channel"],
        "doc_type": invoice["doc_type"],
        "atch_nm": invoice["atch_nm"],
        "archive": invoice["archive"],
        "channel": invoice["channel"],
        "folder_path": invoice["folder_path"],
        "timestamp": invoice["timestamp"].isoformat(),
        "from_email": invoice["from_email"],
        "subject": invoice["subject"],
        "body": invoice["body"]
        # "body":" "
        }
        )

    return {
        "erp": "EBS",
        "InvoiceReceived":received_cnt,
        "Processed":processed_cnt,
        "Exception":exception_cnt,
        "Avgtime":avg_time,
        "invoice_list":invoice_list
    }

def fetch_ebs_invoice_services(src_id):
    fp = fetch_invoice_fp_ebs(src_id)

    if not DATA_ROOT:
        raise FileNotFoundError("ENNVAULT_DATA_ROOT is not configured")

    # source.archive is stored relative to DATA_ROOT (see
    # ENNVAULT_DATA_ROOT in Backend/.env) -- every reader joins it back on
    # the same way, rather than each deriving its own base path.
    full_fp = os.path.normpath(os.path.join(DATA_ROOT, os.path.normpath(fp)))

    if not os.path.exists(full_fp):
        raise FileNotFoundError(f"Folder not found: {full_fp}")

    # Get files
    files = [
        f for f in os.listdir(full_fp)
        if os.path.isfile(os.path.join(full_fp, f))
    ]

    if not files:
        raise FileNotFoundError("No files found")

    # Pick PDF
    pdf_files = [f for f in files if f.lower().endswith(".pdf")]
    selected_file = pdf_files[0] if pdf_files else files[0]

    full_file_path = os.path.join(full_fp, selected_file)

    # print("Final File:", full_file_path)

    # ✅ Display in browser instead of download
    return FileResponse(
        full_file_path,
        media_type='application/pdf',   
        filename=selected_file,
        headers={
            "Content-Disposition": f'inline; filename="{selected_file}"'
        }
    )

def fetch_processed_ebs_info():
    received_cnt = count_ebs_inv_received()
    processed_cnt = count_ebs_inv_processed()
    exception_cnt = count_ebs_inv_exceptions()
    avg_time = '40s'
    processed_invoice = fetch_ebs_processed_header_line_items()
    return {
        "erp": "EBS",
        "InvoiceReceived":received_cnt,
        "Processed":processed_cnt,
        "Exception":exception_cnt,
        "Avgtime":avg_time,
        "invoice_list":processed_invoice
    }

def fetch_ebs_exception_records(role):
    # exception_cnt = count_ebs_inv_exceptions()
    # open_exception_cnt = count_ebs_inv_exceptions()
    # manual_review = 0
    # avg_time = '40s'
    if role.lower()=="user":
        stage_mapping = {
            "Collection": 1,
            "Preprocessing": 2,
            "LLM Extraction": 3,
            "EBS": 4
        }
        result = fetch_exception_records_db()
        # print("----exception records-------",exception_records)
        exception_records =[]
        for records in result:
            records['stage'] = stage_mapping.get(records['stage'])
            records['log_time'] = str(records['log_time'])
            # ✅ Add hold flag
            if records['status'] == 'OnHold' and records['is_reviewed'] == '1':
                continue
            # if records['status'] == 'OnHold' and records['is_reviewed'] !='1':
            #     records['is_hold'] = 1
            else:
                records['is_hold'] = 0
            exception_records.append(records)
            # print("Records",records['stage'])
        
        return  {
            "erp": "EBS",
            # "exception_cnt":exception_cnt,
            # "open_exception_cnt":open_exception_cnt,
            # "manual_review":manual_review,
            # "avg_time":avg_time,
            "invoice_list":exception_records,
            "my_approvals":[]
            
        }
    else:
        stage_mapping = {
        "Collection": 1,
        "Preprocessing": 2,
        "LLM Extraction": 3,
        "EBS": 4
        }
        result = fetch_exception_records_db()
        print("----exception records-----------------",result)
        exception_records =[]
        my_approval=[]
        for records in result:
            records['stage'] = stage_mapping.get(records['stage'])
            records['log_time'] = str(records['log_time'])
            # ✅ Add hold flag
            if records['status'] == 'OnHold' and records['is_reviewed'] == '1':
                my_approval.append(records)
                continue
            # if records['status'] == 'OnHold' and records['is_reviewed'] !='1':
            #     records['is_hold'] = 1
            else:
                records['is_hold'] = 0
            exception_records.append(records)
            # print("Records",records['stage'])
        
        return  {
            "erp": "EBS",
            # "exception_cnt":exception_cnt,
            # "open_exception_cnt":open_exception_cnt,
            # "manual_review":manual_review,
            # "avg_time":avg_time,
            "invoice_list":exception_records,
            "my_approval":my_approval

        }

def dashboard_ebs_service():
    kpi=ebs_dashboard_db_kpi()
    process_chart=ebs_process_chart_db()
    recent_act=ebs_recent_act_db()
    return {
        "erp": "EBS",
        "kpi": kpi,
        "process_chart": process_chart,
        "recent_act": recent_act
    }

def except_hlink_ebs_service(src_id):
    doc_link =fetch_ebs_invoice_services(src_id)
    header_line =fetch_ebs_header_line_items(src_id)
    # print("----------header line--------------", header_line)
    result =fetch_exception_records_db(src_id)
    # print("------------------exception result------------", result)
    error_desc = [row.get("description") for row in result]
    # modified_list =[row.get("what_modified") for row in result]
    try:
        temp_modified=[row.get("what_modified") for row in result]
        modified_list=[]
        for i in temp_modified:
            modified_list.extend((list(set(list(e.lower().strip() for e in i.split(","))))))
    except:
        modified_list =[row.get("what_modified") for row in result]


    action_button = None

    for row in result:
        desc = row.get("description", "")

        # if "item" in desc.lower():
        if "item not found" in desc.lower():
            action_button = "Request Approval"
            break

        if "exists" in desc.lower():
            action_button = "Duplicate"
            break

        if "exceeds"in desc.lower():
            action_button = "Request Approval & Email"
        
        if "po" in desc.lower():
            action_button = "Invalid PO"

    return {
        "erp": "EBS",
        "doc_link":doc_link ,
        "header_line_items":header_line ,
        "error_desc": error_desc,
        "modified_list": modified_list,
        "action_button": action_button
    }

# def update_reprocess_ebs_service(
#     src_id,
#     invoice_number,
#     invoice_date,
#     supplier_number,
#     line_items
# ):
#     data = {
#         "src_id": src_id,
#         "invoice_number": invoice_number,
#         "invoice_date": invoice_date,
#         "supplier_number": supplier_number,
#         "line_items": line_items
#     }

#     print("-----data for reprocess update----", data)

#     result = reprocess_ebs_invoice_db(data)

#     print("----print result reporcess---", result)
#     return result

# def update_duplicate_ebs_log_service (src_id):
#     update_duplicate_ebs_log_service_db(src_id)
#     return

def get_reviewed_ebs_data_service():
    reviewed_records = get_ebs_reviewed_data_db()
    # print("----reviewd records----", reviewed_records)
    return reviewed_records



def request_approval_ebs_service(src_id, field_list):
    field_list = json.loads(field_list)
    result = request_approval_ebs_db(src_id, field_list)
    if result["status"] == "success":
       m_fields = result["modified_fields"]
       print("---------------modified fields----------------", m_fields)
       what_modified= f"{', '.join(m_fields)}"
    else:
        print("------errror updating the fields----------------")
        what_modified =""
    
    insert_log(src_id, "OnHold", "EBS", "Requested approval for reprocessing",
                is_reviewed="1" if result["status"] == "success" else "0",
                action_taken ="Requested Approval",
                what_modified=what_modified)
    # print("----reviewd records----", reviewed_records)
    return result["status"]

def archive_exceptions_services( src_id: str):
    try:
        result = archive_exceptions_db(src_id)
        return result

    except Exception as e:
        return {
            "status": "error",
            "message": str(e)
        }

def email_exceptions_services(src_id: str, email_to, subject, body, attachments=None):
    result = email_exceptions_db( src_id)
    send_result = send_dup_email(
        src_id=src_id,
        email_to=email_to,
        subject=subject,
        body=body,
        attachments=attachments
    )
    return result

def reporting_list_services():
    return reporting_summary_ebs()
from fastapi import APIRouter,Depends,Form,UploadFile,File,HTTPException,Request
from fastapi.responses import JSONResponse,FileResponse,StreamingResponse
from app.api.ennPayables.EBS.services import *
import json
from modules.email_module.service import *
from typing import Optional
from ERP.EBS.inv_payload import *
from typing import Optional, List


router  = APIRouter()

@router.post('/collections_ebs')
def ebs_collection_data():
    # try:
    collection_list = collection_ebs_data_services()
    return JSONResponse(collection_list,status_code=200)
    # except Exception as e:
    #     return JSONResponse(status_code=500, content={"error in /collections": str(e)})

@router.post("/fetch-invoice-file-ebs")
def fetch_invoice_ebs(src_id:str = Form(...)):
    try:
        result = fetch_ebs_invoice_services(src_id)
        if isinstance(result, FileResponse):
            return result
        raise HTTPException(status_code=404, detail=result.get("error", "File not found"))
    except HTTPException:
        raise
    except Exception as e:
        print("/download_file error : ",e)

@router.post("/processed_ebs")
def processed_invoice_ebs():
    # try:
    collection_list = fetch_processed_ebs_info()
    return JSONResponse(collection_list,status_code=200)
    # except Exception as e:
        # return JSONResponse(status_code=500, content={"error in /processed": str(e)})


# @router.post('/exceptions_ebs')
# def exception_invoice_ebs():
#     try:
#         exception_records = fetch_ebs_exception_records()
#         return JSONResponse(exception_records,status_code=200)
#     except Exception as e:
#         return JSONResponse(status_code=500, content={"error in /exceptions": str(e)})

@router.post('/exceptions_ebs')
def exception_invoice_ebs(role: Optional[str] = Form("Admin")):
    try:
        exception_records = fetch_ebs_exception_records(role)
        return JSONResponse(exception_records,status_code=200)
    except Exception as e:
        return JSONResponse(status_code=500, content={"error in /exceptions": str(e)})

@router.post('/dashboard_ebs')
def dashboard_ebs():
    records = dashboard_ebs_service()
    return records

@router.post('/except_hlink_ebs')
def except_hlink_ebs(src_id:str = Form(...)):
    print("-----ip src for hlink----------------", src_id)
    record = except_hlink_ebs_service(src_id)
    print("-------------record result-----------")
    return record

@router.post('/reprocess_ebs')
def reprocess_ebs(
    src_id: str = Form(...),
):
    insert_log(src_id, "Successful", "EBS", "Approved successfully for reprocessing",
                is_reviewed="1",
                action_taken ="Approved",
                )
    print("-----ip src for reprocess----------------", src_id)
    is_reprocessed = True
    result = push_to_ebs_inv(src_id,is_reprocessed)
    return result

# @router.post('/duplicate_email_ebs')
# def send_duplicate_email(
#     src_id: str = Form(...),
#     to: str = Form(...),
#     subject: str = Form(...),
#     body: str = Form(...),
#     attachment: str = Form(...)
# ):
#     print(src_id, to, subject, body, attachment)
#     send_duplicate_email_service(src_id, to, subject, body, attachment)

#     update_duplicate_ebs_log_service(src_id)

#     return {"erp": "EBS","status": "success", "message": "Email sent successfully"}

@router.post('/reviewed_ebs')
def get_reviewed_data():
    records= get_reviewed_ebs_data_service()
    return records

@router.post('/request_approval_ebs')
def request_approva(
    src_id: str = Form(...),
    field_list: str = Form(...)
):
    result =request_approval_ebs_service(src_id, field_list)

    return result

@router.post("/archive_exception_ebs")
def archive_exceptions_route(src_id: str = Form(...)):
    result = archive_exceptions_services(src_id)

    status_code = 200 if result.get("status") == "success" else 400

    return JSONResponse(content=result, status_code=status_code)

@router.post("/email_exception_duplicate")
def email_exceptions_route(
    src_id: str = Form(...),
    email_to: str = Form(...),
    subject: str = Form(...),
    body: str = Form(...),
    attachments: Optional[List[UploadFile]] = File(None),
   
):
    print("src_id:", src_id)
    print("email_to:", email_to)
    print("subject:", subject)
    print("body:", body)

    if attachments:
        for f in attachments:
            print("attachment:", f.filename)

    result = email_exceptions_services( 
    src_id,
    email_to,
    subject,
    body,
    attachments)

    status_code = 200 if result.get("status") == "success" else 400

    return JSONResponse(content=result, status_code=status_code)



@router.post("/reporting_list_ebs")
def reporting_list_route():
    result = reporting_list_services()

    status_code = 200 if result.get("status") == "success" else 400

    return JSONResponse(
        content=result,
        status_code=status_code
    )
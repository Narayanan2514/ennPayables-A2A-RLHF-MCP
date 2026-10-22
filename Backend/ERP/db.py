
from dotenv import load_dotenv
from pathlib import Path
import os
load_dotenv(Path(__file__).resolve().parents[1] / ".env", override=True)
from app.setttings.config import get_db_connection

    

def extract_inv_data(src_id):
    """Fetches invoice data from db"""
    connection = get_db_connection()
    if connection is None:
        raise ValueError("[extract_inv_data] Database connection is not initialized")
    
    cursor = None
    try:
        cursor = connection.cursor()  
        cursor.execute("SELECT * FROM jde_inv_header WHERE src_id = %s", (src_id,))
        header_dtls = cursor.fetchone()  
        
        line_dtls = []
        if header_dtls:
            cursor.execute("SELECT * FROM jde_inv_lines WHERE header_id = %s", (header_dtls['id'],))
            line_dtls = cursor.fetchall()  
            
        
        return header_dtls, line_dtls
    
    except Exception as e:
        print(f"[extract_inv_data] Error fetching invoice details: {e}")
        return None, None
     
    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()

def extract_inv_data_ebs(src_id):
    """Fetches invoice data from db"""
    connection = get_db_connection()
    if connection is None:
        raise ValueError("[extract_inv_data] Database connection is not initialized")
    
    cursor = None
    try:
        cursor = connection.cursor()  
        cursor.execute("SELECT * FROM inv_header WHERE src_id = %s", (src_id,))
        header_dtls = cursor.fetchone()  
        
        line_dtls = []
        if header_dtls:
            cursor.execute("SELECT * FROM inv_line WHERE header_id = %s", (header_dtls['id'],))
            line_dtls = cursor.fetchall()  
            
        
        return header_dtls, line_dtls
    
    except Exception as e:
        print(f"[extract_inv_data] Error fetching invoice details: {e}")
        return None, None
     
    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()


def extract_po_data_ebs(src_id):
    """Fetches invoice data from db"""
    connection = get_db_connection()
    if connection is None:
        raise ValueError("[extract_inv_data] Database connection is not initialized")
    
    cursor = None
    try:
        cursor = connection.cursor()  
        cursor.execute("SELECT * FROM inv_header WHERE src_id = %s", (src_id,))
        header_dtls = cursor.fetchone()  
        
        line_dtls = []
        if header_dtls:
            cursor.execute("SELECT * FROM inv_line WHERE header_id = %s", (header_dtls['id'],))
            line_dtls = cursor.fetchall()  
            
        
        return header_dtls, line_dtls
    
    except Exception as e:
        print(f"[extract_inv_data] Error fetching invoice details: {e}")
        return None, None
     
    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()
    
def update_batch_number(batch_number, src_id):
    connection = get_db_connection()
    if connection is None:
        raise ValueError("[update_batch_number] Database connection is not initialized")
    
    cursor = None
    try:
        cursor = connection.cursor()  
        cursor.execute(
            "UPDATE jde_inv_header SET batch_number = %s WHERE src_id = %s",
            (batch_number, src_id)
        )
        connection.commit()
    except Exception as e:
        print(f"[update_batch_number] Error updating batch number: {e}")
    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()

def update_company_number(companyNo,CostCenter,srcid):
    connection = get_db_connection()
    if connection is None:
        raise ValueError("[extract_inv_data] Database connection is not initialized")
    cursor = None
    
    try:
        cursor = connection.cursor()  
        cursor.execute(
            '''
            UPDATE jde_inv_header 
            SET company_no = %s, business_unit = %s 
            WHERE src_id = %s
            ''',
            (companyNo, CostCenter, srcid)
        )
        connection.commit()
    finally:
        cursor.close()  
        connection.close()

def update_order_line_items(order_company, order_type, src_id):
    connection = get_db_connection()
    if connection is None:
        raise ValueError("[update_order_line_items] Database connection is not initialized")

    cursor = None
    try:
        cursor = connection.cursor()

        query = """
        UPDATE jde_inv_lines l
        JOIN jde_inv_header h ON l.header_id = h.id
        SET l.order_company = %s,
            l.order_type = %s
        WHERE h.src_id = %s
        """

        cursor.execute(query, (order_company, order_type, src_id))
        connection.commit()

        # Optional: check how many rows were updated
        rows_updated = cursor.rowcount
        if rows_updated == 0:
            print(f"[update_order_line_items] No records found for src_id: {src_id}")
        else:
            print(f"[update_order_line_items] Successfully updated {rows_updated} rows for src_id: {src_id}")

    except Exception as e:
        print(f"[update_order_line_items] Error: {e}")
        connection.rollback()

    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()

def update_voucher_approval(src_id,approval_required,approver_nm,approver_email):
    connection = get_db_connection()
    if connection is None:
        raise ValueError("[update_voucher_approval] Database connection is not initialized")
 
    cursor = None
    try:
        cursor = connection.cursor()
        cursor.execute(""" update jde_inv_header set approval_required = %s , approver_name = %s , approver_email = %s  where src_id = %s""",
                    (approval_required,approver_nm,approver_email,src_id))
 
        connection.commit()
    except Exception as e:
            print(f"[update_voucher_approval] Error updating approval info: {e}")
    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()


def extract_remit_info(src_id):
    connection = get_db_connection()
    if connection is None:
        raise ValueError("[extract_remit_info] Database connection is not initialized")
 
    cursor = None
    try:
        cursor = connection.cursor()
        
        cursor.execute("""SELECT a.h_id,b.l_id,a.customer_number,b.l_ref_id,a.total_amnt
                        FROM ennvault.remit_header a left join ennvault.remit_line b on a.h_id = b.h_id 
                        where a.src_id = %s""", (src_id,))
        line_dtls = cursor.fetchall()  
        

        return line_dtls
    except Exception as e:
            print(f"[update_voucher_approval] Error updating approval info: {e}")
    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()


def extract_remit_data_ebs(src_id):
    """Fetches invoice data from db"""
    connection = get_db_connection()
    if connection is None:
        raise ValueError("[extract_inv_data] Database connection is not initialized")
    
    cursor = None
    try:
        cursor = connection.cursor()  
        cursor.execute("SELECT * FROM remit_header_ebs WHERE src_id = %s", (src_id,))
        header_dtls = cursor.fetchone()  
        
        line_dtls = []
        if header_dtls:
            cursor.execute("SELECT * FROM remit_line_ebs WHERE h_id = %s", (header_dtls['h_id'],))
            line_dtls = cursor.fetchall()  
            
        
        return header_dtls, line_dtls
    
    except Exception as e:
        print(f"[extract_remit_data_ebs] Error fetching invoice details: {e}")
        return None, None
     
    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()

# def store_amount_by_invoice(l_id,amount_response):
#     try:
#         connection = get_db_connection()
#         if connection is None:
#             raise ValueError("[extract_inv_data] Database connection is not initialized")
#         cursor = None
#         cursor = connection.cursor()
        
#         total_amt = amount_response['Pending_amount'] + amount_response['Amount_Paid']
#         cursor.execute(""" update remit_line_ebs set outstanding = %s , org_invoice_amount = %s where l_id = %s""",
#                     (amount_response['Pending_amount'],total_amt,l_id))
 
#         connection.commit()
#     except Exception as e:
#         print(f"[extract_remit_data_ebs] Error fetching invoice details: {e}")
#         return None, None
     
#     finally:
#         if cursor:
#             cursor.close()
#         if connection:
#             connection.close()

from decimal import Decimal

def store_amount_by_invoice(l_id, amount_response):
    connection = None
    cursor = None

    try:
        connection = get_db_connection()

        if connection is None:
            raise ValueError(
                "[store_amount_by_invoice] Database connection is not initialized"
            )

        cursor = connection.cursor()

        pending_amount = amount_response.get("Pending_amount")
        amount_paid = amount_response.get("Amount_Paid")

        # None / empty value => 0
        pending_amount = Decimal(str(pending_amount or "0"))
        amount_paid = Decimal(str(amount_paid or "0"))

        total_amt = pending_amount + amount_paid

        print("Pending Amount:", pending_amount)
        print("Amount Paid:", amount_paid)
        print("Original Invoice Amount:", total_amt)

        cursor.execute(
            """
            UPDATE remit_line_ebs
            SET outstanding = %s,
                org_invoice_amount = %s
            WHERE l_id = %s
            """,
            (
                pending_amount,
                total_amt,
                l_id
            )
        )

        connection.commit()

        print(
            f"✅ Updated l_id={l_id}: "
            f"outstanding={pending_amount}, "
            f"org_invoice_amount={total_amt}"
        )

        return {
            "outstanding": pending_amount,
            "org_invoice_amount": total_amt
        }

    except Exception as e:
        print(
            f"[store_amount_by_invoice] Error updating invoice amount: {e}"
        )

        if connection:
            connection.rollback()

        return None

    finally:
        if cursor:
            cursor.close()

        if connection:
            connection.close()

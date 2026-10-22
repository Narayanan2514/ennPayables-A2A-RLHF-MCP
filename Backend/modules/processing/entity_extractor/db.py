import os
from datetime import datetime
from app.setttings.config import get_db_connection

def extract_po_number(order_number: str) -> str:
    if not order_number:
        return ""
    return order_number.split("OP")[0]

def get_last_n_path_parts(path, n=4):
    """
    Returns a string of the last `n` parts of a path, joined with os.sep.
    """
    parts = path.replace("\\", "/").split("/")  
    last_parts = parts[-n:]  
    return os.sep.join(last_parts)


def normalize_date_dmY(date_str):
   
    if not date_str or str(date_str).lower() in ("none", "null", ""):
        return None

    formats = [
        "%d/%m/%Y",
        "%d/%m/%y",
        "%m/%d/%Y",
        "%m/%d/%y"
    ]

    for fmt in formats:
        try:
            return datetime.strptime(date_str, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue

    print(f"⚠️ Could not parse date: {date_str}")
    return None



def get_src_id(folder_path: str) -> int:
    """
    Fetch the src_id for a folder_path from the 'source' table.
    Uses its own DB connection.
    """
    last_4 = get_last_n_path_parts(folder_path, 4)
    print("folder name----", last_4)

    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT src_id FROM source WHERE folder_path = %s",
                (last_4,)
            )
            row = cursor.fetchone()
            if not row:
                raise Exception(f"Source ID not found for {last_4}")
            return row["src_id"]
    finally:
        conn.close()

#---- remmitance----------------------
def insert_remit_header(data: dict, folder_path: str) -> int:
    """
    Inserts a remit_header record and returns its ID.
    Uses internal DB connections for both getting src_id and inserting.
    """
    conn = get_db_connection()
    print("data dict....", data)

    try:
        with conn.cursor() as cursor:
            # Use new get_src_id that manages its own connection
            src_id = get_src_id(folder_path)
            print("source id in action----", src_id)

            sql = """
                INSERT INTO remit_header (
                    src_id,
                    customer,
                    customer_number,
                    ref_number,
                    total_amnt,
                    currency,
                    date
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s)
            """
            # date_val = "2025-09-25"
            date_val = normalize_date_dmY(data.get("date"))

            cursor.execute(sql, (
                src_id,
                data.get("customer", ""),
                data.get("customer_number", ""),
                data.get("ref_number", ""),
                data.get("total_amnt", ""),
                data.get("currency", ""),
                date_val
            ))

            conn.commit()
            return cursor.lastrowid

    finally:
        conn.close()


def insert_remit_lines(h_id: int, lines: list[dict]):
    
    if not lines:
        return
    conn = get_db_connection()
    print("got lines i/p....", lines)

    try:
        with conn.cursor() as cursor:
            sql = """
                INSERT INTO remit_line (
                    h_id,
                    l_ref_id,
                    date,
                    org_amnt,
                    disc_amnt
                )
                VALUES (%s, %s, %s, %s, %s)
            """

            for line in lines:
                line_date = normalize_date_dmY(line.get("date"))
                cursor.execute(sql, (
                    h_id,
                    line.get("l_ref_id", ""),
                    line_date,
                    line.get("org_amnt", ""),
                    line.get("disc_amnt", "")
                ))

            conn.commit()
    finally:
        conn.close()


# def insert_remit_header_ebs(data: dict, folder_path: str) -> int:
#     """
#     Inserts a remit_header_ebs record and returns its ID.
#     Uses internal DB connections for both getting src_id and inserting.
#     """
#     conn = get_db_connection()
#     print("EBS header data....", data)

#     try:
#         with conn.cursor() as cursor:
#             src_id = get_src_id(folder_path)
#             print("source id ----", src_id)

#             sql = """
#                 INSERT INTO remit_header_ebs (
#                     src_id,
#                     customer_name,
#                     customer_number,
#                     receipt_number,
#                     receipt_method,
#                     receipt_date,
#                     receipt_amount,
#                     currency_code,
#                     reference_number,
#                     cust_bank_name,
#                     cust_bank_account,
#                     cust_bank_branch,
#                     remit_bank_name,
#                     remit_bank_account,
#                     remit_bank_branch,
#                     org_id
#                 )
#                 VALUES (
#                     %s, %s, %s, %s, %s, %s, %s, %s,
#                     %s, %s, %s, %s, %s, %s, %s, %s
#                 )
#             """

#             receipt_date = normalize_date_dmY(data.get("receipt_date"))

#             cursor.execute(sql, (
#                 src_id,
#                 data.get("customer_name", ""),
#                 data.get("customer_number", ""),
#                 data.get("receipt_number", ""),
#                 data.get("receipt_method", ""),
#                 receipt_date,
#                 data.get("receipt_amount", 0),
#                 data.get("currency_code", ""),
#                 data.get("reference_number", ""),
#                 data.get("cust_bank_name", ""),
#                 data.get("cust_bank_account", ""),
#                 data.get("cust_bank_branch", ""),
#                 data.get("remit_bank_name", ""),
#                 data.get("remit_bank_account", ""),
#                 data.get("remit_bank_branch", ""),
#                 data.get("org_id", "")
#             ))

#             conn.commit()
#             return cursor.lastrowid, src_id

#     finally:
#         conn.close()




def insert_remit_header_ebs(data: dict, folder_path: str):
    """
    Inserts a remit_header_ebs record and returns (h_id, src_id).

    Expected LLM Header:
    {
        "customer": "",
        "customer_number": "",
        "ref_number": "",
        "total_amnt": "",
        "currency": "",
        "date": ""
    }
    """

    conn = get_db_connection()
    print("EBS header data....", data)

    try:
        with conn.cursor() as cursor:

            src_id = get_src_id(folder_path)
            print("source id ----", src_id)

            receipt_date = normalize_date_dmY(data.get("date"))

            currency = data.get("currency", "").strip()
            if currency == "$":
                currency = "USD"

            sql = """
                INSERT INTO remit_header_ebs (
                    src_id,
                    customer_name,
                    customer_number,
                    receipt_number,
                    receipt_method,
                    receipt_date,
                    receipt_amount,
                    currency_code,
                    reference_number,
                    cust_bank_name,
                    cust_bank_account,
                    cust_bank_branch,
                    remit_bank_name,
                    remit_bank_account,
                    remit_bank_branch,
                    org_id
                )
                VALUES (
                    %s,%s,%s,%s,%s,%s,%s,%s,
                    %s,%s,%s,%s,%s,%s,%s,%s
                )
            """

            cursor.execute(
                sql,
                (
                    src_id,

                    # customer_name
                    data.get("customer", ""),

                    # customer_number
                    data.get("customer_number", ""),

                    # receipt_number (same as check/reference number)
                    data.get("ref_number", ""),

                    # receipt_method (filled later if required)
                    "",

                    # receipt_date
                    receipt_date,

                    # receipt_amount
                    clean_amount(data.get("total_amnt")),

                    # currency_code
                    currency,

                    # reference_number (same value)
                    data.get("ref_number", ""),

                    # Customer Bank Details
                    "HSBC",
                    "",
                    "",

                    # Remittance Bank Details
                    "",
                    "",
                    "",

                    # Org ID
                    ""
                )
            )

            conn.commit()

            return cursor.lastrowid, src_id

    finally:
        conn.close()

# def insert_remit_lines_ebs(h_id: int, lines: list[dict]):
#     """
#     Inserts remit_line_ebs records.
#     """
#     if not lines:
#         return

#     conn = get_db_connection()
#     print("EBS line data....", lines)

#     try:
#         with conn.cursor() as cursor:

#             sql = """
#                 INSERT INTO remit_line_ebs (
#                     h_id,
#                     invoice_number,
#                     invoice_date,
#                     invoice_amount,
#                     amount_paid,
#                     discount_amount,
#                     customer_trx_id,
#                     status,
#                     error_message
#                 )
#                 VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
#             """

#             for line in lines:

#                 invoice_date = normalize_date_dmY(line.get("invoice_date"))

#                 cursor.execute(sql, (
#                     h_id,
#                     line.get("invoice_number", ""),
#                     invoice_date,
#                     line.get("invoice_amount", 0),
#                     line.get("amount_paid", 0),
#                     line.get("discount_amount", 0),
#                     line.get("customer_trx_id", ""),
#                     line.get("status", ""),
#                     line.get("error_message", "")
#                 ))

#             conn.commit()

#     finally:
#         conn.close()


def insert_remit_lines_ebs(h_id: int, lines: list[dict]):
    """
    Inserts remit_line_ebs records.

    Expected LLM Line Format:
    {
        "l_ref_id": "",
        "date": "",
        "org_amnt": "",
        "disc_amnt": ""
    }
    """

    if not lines:
        return

    conn = get_db_connection()
    print("EBS line data....", lines)

    try:
        with conn.cursor() as cursor:

            sql = """
                INSERT INTO remit_line_ebs (
                    h_id,
                    invoice_number,
                    invoice_date,
                    invoice_amount,
                    amount_paid,
                    discount_amount,
                    customer_trx_id,
                    status,
                    error_message
                )
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
            """

            for line in lines:

                invoice_date = normalize_date_dmY(line.get("date"))

                invoice_amount = clean_amount(line.get("org_amnt"))
                discount_amount = clean_amount(line.get("disc_amnt"))

                cursor.execute(
                    sql,
                    (
                        h_id,

                        # Invoice Number
                        line.get("l_ref_id", ""),

                        # Invoice Date
                        invoice_date,

                        # Original Invoice Amount
                        invoice_amount,

                        # Amount Paid
                        invoice_amount,

                        # Discount Amount
                        discount_amount,

                        # Customer Transaction ID
                        "",

                        # Status
                        "",

                        # Error Message
                        ""
                    )
                )

            conn.commit()

    finally:
        conn.close()

#------bank doc--------------------------
import re

def clean_amount(value):
    if value is None:
        return 0

    if isinstance(value, (int, float)):
        return value

    # remove currency symbols, commas, spaces
    cleaned = re.sub(r"[^\d\.\-]", "", str(value))

    return float(cleaned) if cleaned else 0

def insert_bank_doc(data: dict, folder_path: str):
    """
    Insert a bank document record linked to src_id.
    """
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            # ✅ Get src_id using folder_path directly
            src_id = get_src_id(folder_path)
            print("source id in action----", src_id)

            sql = """
                INSERT INTO bank_doc (
                    src_id,
                    ref_num,
                    bank_nm,
                    amnt
                )
                VALUES (%s, %s, %s, %s)
            """

            cursor.execute(sql, (
                src_id,
                data.get("ref_num", ""),
                data.get("bank_nm", ""),
                clean_amount(data.get("amnt", 0))              ))

            conn.commit()

    except Exception as e:
        print(f"❌ Failed to insert bank document: {e}")

    finally:
        conn.close()


def find_remit_by_ref(ref_number: str):
    """
    Find Remittance header by ref number
    """
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            sql = """
                SELECT h_id, src_id, ref_number, total_amnt, currency
                FROM remit_header
                WHERE ref_number = %s
            """
            cursor.execute(sql, (ref_number,))
            return cursor.fetchone()
    finally:
        conn.close()

def find_bank_doc_by_ref(ref_number: str):
    """
    Fetch bank document by reference number
    """
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            sql = """
                SELECT 
                    b_id,
                    src_id,
                    ref_num,
                    bank_nm,
                    amnt
                FROM bank_doc
                WHERE ref_num = %s
            """
            cursor.execute(sql, (ref_number,))
            return cursor.fetchone()
    except Exception as e:
        print(f"❌ Failed to lookup bank_doc by ref: {e}")
        return None
    finally:
        conn.close()

#------------------PO EBS--------------------------------



def insert_po_header(header, folder_path):
    conn = get_db_connection()

    try:
        with conn.cursor() as cursor:

            
            src_id = get_src_id(folder_path)

            # check duplicate
            cursor.execute(
                "SELECT id FROM po_header WHERE src_id = %s",
                (src_id,)
            )
            existing = cursor.fetchone()

            if existing:
                return existing["id"]

            sql = """
                INSERT INTO po_header (
                    src_id,

                    bill_to, ship_to,
                    po_number, date,
                    currency_code, c_name, c_number,
                    freight_terms, payment_terms, ship_method,

                    ship_to_name, ship_to_address_ln1, ship_to_address_ln2,
                    ship_to_address_ln3, ship_to_address_ln4,
                    ship_to_city, ship_to_state, ship_to_zip, ship_to_country,

                    bill_to_name, bill_to_address_ln1, bill_to_address_ln2,
                    bill_to_address_ln3, bill_to_address_ln4,
                    bill_to_city, bill_to_state, bill_to_zip, bill_to_country,

                    shipping_via, so_number
                )
                VALUES (
                    %s,
                    %s,%s,%s,%s,
                    %s,%s,%s,
                    %s,%s,%s,

                    %s,%s,%s,%s,%s,
                    %s,%s,%s,%s,

                    %s,%s,%s,%s,%s,
                    %s,%s,%s,%s,

                    %s,%s
                )
            """

            cursor.execute(sql, (
                src_id,

                header.get("bill_to", ""),
                header.get("ship_to", ""),

                header.get("po_number", ""),
                header.get("date", ""),

                header.get("currency_code", ""),
                header.get("c_name", header.get("customer_name", "ennVee Solutions")),
                header.get("c_number", header.get("customer_number", "")),

                header.get("freight_terms", ""),
                header.get("payment_terms", ""),
                header.get("ship_method", ""),

                header.get("ship_to_name", ""),
                header.get("ship_to_address_ln1", "123, Innovation Drive"),
                header.get("ship_to_address_ln2", "Tech City"),
                header.get("ship_to_address_ln3", ""),
                header.get("ship_to_address_ln4", ""),
                header.get("ship_to_city", ""),
                header.get("ship_to_state", "CA"),
                header.get("ship_to_zip", "90210"),
                header.get("ship_to_country", ""),

                header.get("bill_to_name", ""),
                header.get("bill_to_address_ln1", "123, Innovation Drive"),
                header.get("bill_to_address_ln2", "Tech City"),
                header.get("bill_to_address_ln3", ""),
                header.get("bill_to_address_ln4", ""),
                header.get("bill_to_city", ""),
                header.get("bill_to_state", "CA"),
                header.get("bill_to_zip", "90210"),
                header.get("bill_to_country", ""),

                header.get("shipping_via", ""),
                header.get("so_number", "")
            ))

            conn.commit()
            return cursor.lastrowid

    finally:
        conn.close()



def insert_po_line(header_id, line):
    conn = get_db_connection()

    try:
        with conn.cursor() as cursor:

            sql = """
                INSERT INTO po_line (
                    header_id,
                    line_number,
                    item_number,
                    item_description,
                    ordered_quantity,
                    unit_of_measure,
                    total,
                    req_date
                )
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
            """

            cursor.execute(sql, (
                header_id,

                line.get("line_number", ""),
                line.get("item_number", ""),
                line.get("item_description", ""),
                line.get("quantity", ""),
                line.get("unit_of_measure", ""),

                line.get("net_amount", line.get("total", "")),
                normalize_date_dmY(line.get("requested_date"))          
                    ))

            conn.commit()

    finally:
        conn.close()


def update_processed_folder(old_path: str, new_path: str):
    """
    Update folder_path in DB after _p → _c rename
    Paths must be RELATIVE (doc_transition\\...)
    """

    conn = get_db_connection()

    try:
        with conn.cursor() as cursor:

            sql = """
                UPDATE source
                SET folder_path = %s
                WHERE folder_path = %s
            """

            cursor.execute(sql, (new_path, old_path))
            conn.commit()

            if cursor.rowcount == 0:
                print(f"⚠️ No match in DB for: {old_path}")
            else:
                print(f"✅ Updated: {old_path} → {new_path}")

    except Exception as e:
        print(f"❌ DB update error: {e}")

    finally:
        conn.close()


#---------------------invoice line-------------------------------
def parse_date_safe(date_str):
    """Convert string to date safely"""
    for fmt in ("%d.%m.%Y", "%m/%d/%Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(date_str.strip(), fmt).date()
        except Exception:
            pass
    return None

def parse_float_safe(value):
    """Convert string to float safely"""
    try:
        if not value or value.strip() == "":
            return None
        return float(value.replace(",", "").strip())
    except:
        return None
    
def insert_inv_header(decoded_header, folder_path):
    """Insert invoice header and return the header_id"""
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:

            # Lookup email_id by folder
            # folder_name = f"processed\\{folder_path}"
            # cursor.execute("SELECT email_id FROM emails WHERE folder = %s", (folder_name,))
            # result = cursor.fetchone()
            # if not result:
            #     print(f"❌ Email ID not found for folder: {folder_name}")
            #     return None
            # email_id = result['email_id']

            src_id = get_src_id(folder_path)
            print("source id in action----", src_id)

            # Insert header
            sql = """
                INSERT INTO inv_header (
                    src_id, bill_to, ship_to, supplier_name, invoice_number,
                    invoice_date, payment_terms, customer_number, invoice_duedate,
                    customer_po_number, so_number, shipping_point, currency_code, invoice_amount
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """
            invoice_amount = parse_float_safe(decoded_header.get("total", ""))
            cursor.execute(sql, (
                src_id,
                decoded_header.get("bill_to", ""),
                decoded_header.get("ship_to", ""),
                decoded_header.get("supplier_name", ""),
                decoded_header.get("invoice_number", ""),
                parse_date_safe(decoded_header.get("invoice_date", "")),
                decoded_header.get("payment_terms", "Immediate"),
                decoded_header.get("customer_number", ""),
                parse_date_safe(decoded_header.get("invoice_duedate", "")),
                decoded_header.get("customer_po_number", ""),
                decoded_header.get("sales_order_number", ""),
                decoded_header.get("shipping_point", ""),
                decoded_header.get("currency_code", "$"),
                invoice_amount
            ))
            conn.commit()
            return cursor.lastrowid
    except Exception as e:
        print(f"❌ Failed to insert invoice header: {e}")
        return None
    finally:
        conn.close()


def insert_inv_line(header_id, line_item):
    """Insert a single invoice line"""
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            sql = """
                INSERT INTO inv_line (
                    header_id, line_number, item_name, item_desc, ordered_quantity,
                    unit_of_measure, total, fob_point, freight_carrier
                ) VALUES (%s, %s, %s,  %s, %s, %s, %s, %s, %s)
            """
            cursor.execute(sql, (
                header_id,
                line_item.get("line_number", ""),
                line_item.get("item_name", ""),
                line_item.get("item_description", ""),
                line_item.get("ordered_quantity", ""),
                line_item.get("unit_of_measure", ""),
                # parse_float_safe(line_item.get("price", "")),
                parse_float_safe(line_item.get("total", "")),
                line_item.get("fob_point", ""),
                line_item.get("freight_carrier", "")
            ))
            conn.commit()
    except Exception as e:
        print(f"❌ Failed to insert invoice line: {e}")
    finally:
        conn.close()

# --------------------- JDE INVOICE -------------------------------

def insert_jde_inv_header(data: dict, folder_path: str) -> int:
    """
    Insert JDE invoice header and return header_id.
    Uses internal DB connection for both getting src_id and inserting.
    """
    conn = get_db_connection()

    try:
        with conn.cursor() as cursor:

            # ✅ Get src_id using folder_path directly
            src_id = get_src_id(folder_path)
            print("source id in action----", src_id)

            sql = """
                INSERT INTO jde_inv_header (
                    src_id,
                    company,
                    supplier_number,
                    invoice_number,
                    invoice_date,
                    gl_date,
                    business_unit,
                    batch_number
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """
            gl_date =datetime.now().strftime("%m/%d/%Y")
            cursor.execute(sql, (
                src_id,
                data.get("company", ""),
                data.get("supplier_number", ""),
                data.get("invoice_number", ""),
                parse_date_safe(data.get("invoice_date", "")),
                gl_date,
                data.get("business_unit", ""),
                data.get("batch_number", "")
            ))

            conn.commit()
            return cursor.lastrowid

    except Exception as e:
        print(f"❌ Failed to insert JDE invoice header: {e}")
        return None

    finally:
        conn.close()

def insert_jde_inv_lines(header_id: int, lines: list[dict]):
    """
    Insert JDE invoice lines
    """
    if not lines:
        return

    conn = get_db_connection()

    try:
        with conn.cursor() as cursor:

            sql = """
                INSERT INTO jde_inv_lines (
                    header_id,
                    gross_amount,
                    remark,
                    automation_flag,
                    order_number,
                    order_company,
                    order_type,
                    item_number
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """
            
            for line in lines:
                # Normalize order_number key
                order_number_raw = line.get("order_number") or line.get("Purchase order number") or ""
                order_number = extract_po_number(order_number_raw)
                gross_amount = (line.get("gross_amount") or "").replace("$", "").strip()
                remark = line.get("remark", "Test JDE Inv") or line.get("description", "")
                
                cursor.execute(sql, (
                    header_id,
                    gross_amount,
                    remark,
                    line.get("automation_flag", 1),  
                    order_number,
                    line.get("order_company", ""),
                    line.get("order_type", ""),
                    line.get("item_number", "")
                ))

            conn.commit()

    except Exception as e:
        print(f"❌ Failed to insert JDE invoice lines: {e}")

    finally:
        conn.close()


def insert_case(remit_src_id, bank_src_id):
    """
    Insert a new case with the grouped source IDs.
    case_id is generated by the DB trigger.
    """
    conn = get_db_connection()

    try:
        with conn.cursor() as cursor:

            src_grp = f"{remit_src_id},{bank_src_id}"

            cursor.execute("""
                INSERT INTO case_table (src_grp)
                VALUES (%s)
            """, (src_grp,))

        conn.commit()

    except Exception as e:
        print(f"❌ Failed to insert case: {e}")

    finally:
        conn.close()
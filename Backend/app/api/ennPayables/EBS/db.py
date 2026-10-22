import os
from mysql.connector import Error
import mysql.connector
from datetime import datetime
from modules.email_module.db import *
from app.setttings.config import DATA_ROOT


def db_connection():
    """Establish a connection to the MySQL database using environment variables."""
    try:
        host = os.getenv('HOST')
        user = os.getenv('DB_USER')
        password = os.getenv('PASSWORD')
        database = os.getenv('DATABASE_NAME')
    


        connection = mysql.connector.connect(
            host=host,
            user=user,
            password=password,
            database=database
        )
        return connection
    except Error as e:
        print(f"Database connection error: {e}")
        return None
    except ValueError as ve:
        print(f"Configuration error: {ve}")
        return None

def count_ebs_inv_received():
    connection = db_connection()
    if connection is None:
        raise ValueError("[extract_inv_data] Database connection is not initialized")

    try:
        cursor = connection.cursor(dictionary=True)
        cursor.execute("SELECT count(*) as Invoice_Received FROM source WHERE LOWER(doc_type) = LOWER(%s) AND target = 'EBS'", ('Invoice',))
        invoice_dtls = cursor.fetchall() 
        print(invoice_dtls)
        inv_received  = invoice_dtls[0]['Invoice_Received'] 
        print("Inv received",inv_received)
        return inv_received
    except Exception as e:
        print(f"[extract_inv_data] Error fetching employee details: {e}")
    

    finally:
        cursor.close()  
        connection.close() 

def count_ebs_inv_processed():
    connection = db_connection()
    cursor = connection.cursor(dictionary=True)

    try:
        valid_src_ids = get_valid_src_ids(cursor)
        return len(valid_src_ids)
    finally:
        cursor.close()
        connection.close() 

def get_valid_src_ids(cursor):
    # cursor.execute("""
    #     SELECT entity_id
    #     FROM log_table
    #     WHERE status = 'Successful'
    #     AND LOWER(doc_type) = LOWER('Invoice')
    #     GROUP BY entity_id
    #     HAVING COUNT(*) = 4
    # """)
    
    cursor.execute("""
        SELECT l.entity_id
        FROM log_table l
        JOIN source s 
            ON l.entity_id = s.src_id
        WHERE l.status = 'Successful'
        AND LOWER(s.doc_type) = LOWER('Invoice')
        AND s.target = 'EBS'
        AND (
                   l.action_taken IS NULL
                   OR l.action_taken NOT IN ("Email sent", "Archived","Approved")

                )
        GROUP BY l.entity_id
        HAVING COUNT(*) >= 2   
                    """)
    
    rows = cursor.fetchall()
    return {row["entity_id"] for row in rows}  

def count_ebs_inv_exceptions():
    try:
        data = fetch_exception_records_db()

        # get unique src_ids
        unique_src_ids = {row["entity_id"] for row in data}

        return len(unique_src_ids)

    except Exception as e:
        print(f"Error in count_inv_exceptions: {e}")
        return 0

def fetch_exception_records_db(src_id=None):
    connection = db_connection()
    cursor = connection.cursor(dictionary=True)

    try:
        query = """
            SELECT 
                l.*,
                s.doc_type,
                s.channel,
                e.from_email,
                j.invoice_number

            FROM ennvault.log_table l

            -- Join source (only invoice docs)
            INNER JOIN ennvault.source s 
                ON l.entity_id = s.src_id
                AND s.doc_type = 'invoice'
                AND s.target = 'EBS'

            -- Optional email
            LEFT JOIN ennvault.email e 
                ON l.entity_id = e.src_id
                AND s.channel = 'email'

            -- Invoice number
            LEFT JOIN ennvault.inv_header j
                ON l.entity_id = j.src_id

            -- ✅ ONLY FAILED LOGS
            WHERE l.status IN ('Failed', 'OnHold','ON_HOLD')
            AND l.stage IN('EBS','JDE','LLM Extraction')
            AND (l.is_active IS NULL OR l.is_active = 0)
        """

        params = ()

        # ✅ Apply src_id filter if provided
        if src_id:
            query += " AND l.entity_id = %s"
            params = (src_id,)

        query += " ORDER BY l.log_time DESC"

        cursor.execute(query, params)
        exception_rec = cursor.fetchall()
        return exception_rec

    except Exception as e:
        print(f"[fetch_exception_records_db] Error: {e}")
        return []

    finally:
        cursor.close()
        connection.close()

def calculate_ebs_avg_time():
    connection = db_connection()
    if not connection:
        return "0s"

    try:
        cursor = connection.cursor()

        query = """
        SELECT 
            AVG(duration) AS avg_time
        FROM (
            SELECT 
                entity_id,
                TIMESTAMPDIFF(SECOND, MIN(log_time), MAX(log_time)) AS duration
            FROM (
                SELECT
                    entity_id,
                    log_time,
                    ROW_NUMBER() OVER(PARTITION BY entity_id ORDER BY log_time) AS rn
                FROM log_table
            ) t
            WHERE rn <= 4
            GROUP BY entity_id
        ) t2;
        """

        cursor.execute(query)
        result = cursor.fetchone()
        avg_seconds = result[0] if result and result[0] else 0

        return f"{int(avg_seconds)}s"

    except Exception as e:
        print(f"Error calculating avg time: {e}")
        return "0s"

    finally:
        cursor.close()
        connection.close()

def ebs_inv_list():
    connection = db_connection()

    if connection is None:
        raise ValueError("[extract_inv_data] Database connection is not initialized")

    try:
        cursor = connection.cursor(dictionary=True)
        # cursor.execute(""" select * from ennvault.source a left join ennvault.email b on a.src_id = b.src_id""")
        cursor.execute("""
            SELECT * 
            FROM ennvault.source a 
            LEFT JOIN ennvault.email b 
            ON a.src_id = b.src_id
            WHERE LOWER(a.doc_type) = LOWER('Invoice')
            AND a.target = 'EBS'
            ORDER BY a.timestamp DESC
        """)
        inv_list = cursor.fetchall()
        return inv_list
    except Exception as e:
        print(f"[extract_inv_data] Error fetching employee details: {e}")


    finally:
        cursor.close()  
        connection.close() 

def fetch_invoice_fp_ebs(src_id):
    connection = db_connection()

    try:
        cursor = connection.cursor(dictionary=True)
        cursor.execute("""
            SELECT archive 
            FROM ennvault.source 
            WHERE src_id = %s
            AND target = 'EBS'
        """, (src_id,))
        
        result = cursor.fetchone()

        if not result or not result.get("archive"):
            raise ValueError("No archive path found for given src_id")

        return result["archive"]

    finally:
        cursor.close()
        connection.close()

def fetch_ebs_processed_header_line_items(src_id=None):
    connection = db_connection()
    cursor = connection.cursor(dictionary=True)

    # ✅ Step 1: Get valid src_ids
    if src_id:
        valid_src_ids = {src_id}
    else:
        valid_src_ids = get_valid_src_ids(cursor)

    # ✅ Step 2: Fetch invoice data
        cursor.execute("""
    SELECT 
        a.*,
        b.id AS line_id,
        b.line_number,
        b.item_name,
        b.ordered_quantity,
        b.unit_of_measure,
        b.total,
        b.fob_point,
        b.freight_carrier,
        b.item_desc,
        c.log_time
                
        FROM ennvault.inv_header a
        LEFT JOIN ennvault.inv_line b 

        ON a.id = b.header_id
        left join ennvault.log_table c on a.src_id=c.entity_id

        where c.status="Successful" and c.stage="EBS"
        AND c.action_taken NOT IN ("Email sent", "Archived", "Approved")
        ORDER BY a.id DESC

        """)
    # print("Into execution",valid_src_ids)


    rows = cursor.fetchall()

    # ✅ Step 3: Build filtered JSON
    return build_invoice_processed_json(rows, valid_src_ids)

def fetch_ebs_header_line_items(src_id=None):
    connection = db_connection()
    cursor = connection.cursor(dictionary=True)

    # ✅ Step 1: Get valid src_ids
    if src_id:
        valid_src_ids = {src_id}
    else:
        valid_src_ids = get_valid_src_ids(cursor)

    # ✅ Step 2: Fetch invoice data
    cursor.execute("""
        SELECT 
            '' as log_time,
            a.*,
            b.id AS line_id,
            b.line_number,
            b.item_name,
            b.ordered_quantity,
            b.unit_of_measure,
            b.total,
            b.fob_point,
            b.freight_carrier,
            b.item_desc
                    
        FROM ennvault.inv_header a
        LEFT JOIN ennvault.inv_line b 
        ON a.id = b.header_id
        ORDER BY a.id DESC
    """)
    print("Into execution",valid_src_ids)


    rows = cursor.fetchall()

    # ✅ Step 3: Build filtered JSON
    return build_invoice_json(rows, valid_src_ids)

def build_invoice_processed_json(rows, valid_src_ids):
    result = []
    header_map = {}
    # print("rows", rows)
    # print("src_id", valid_src_ids)

    for row in rows:
        header_id = row["id"]
        src_id = row["src_id"]

        # Skip invalid src_ids
        if src_id not in valid_src_ids:
            # print("Continuing",src_id)
            continue

        # Create header object once
        print("header_id",header_id)
        if header_id not in header_map:
            header_obj = {
                "id": header_id,
                "src_id": row["src_id"],
                "bill_to": row["bill_to"],
                "ship_to": row["ship_to"],
                "supplier_name": row["supplier_name"],
                "invoice_number": row["invoice_number"],
                "invoice_date": str(row["log_time"]) if row["log_time"] else None,#str(row["invoice_date"]) if row["invoice_date"] else None,
                "payment_terms": row["payment_terms"],
                "customer_number": row["customer_number"],
                "invoice_duedate": str(row["invoice_duedate"]) if row["invoice_duedate"] else None,
                "customer_po_number": row["customer_po_number"],
                "so_number": row["so_number"],
                "shipping_point": row["shipping_point"],
                "currency_code": row["currency_code"],
                "invoice_amount": float(row["invoice_amount"])
                                    if row["invoice_amount"] not in (None, "")
                                    else 0.0,
                "supplier_site": row["supplier_site"],
                "line_items": []
            }

            header_map[header_id] = header_obj
            result.append(header_obj)
            # print("header_obj",header_obj)

        # Add line item
        if row["line_id"] is not None:
            header_map[header_id]["line_items"].append({
                "id": row["line_id"],
                "line_number": row["line_number"],
                "item_name": row["item_name"],
                "ordered_quantity": row["ordered_quantity"],
                "unit_of_measure": row["unit_of_measure"],

                "total": float(str(row["total"]).replace(",", ""))
                            if row["total"] not in (None, "")
                            else 0.0,

                "fob_point": row["fob_point"],
                "freight_carrier": row["freight_carrier"],
                "item_desc": row["item_desc"]
            })
    # print("result of header and line", result)
    return result



def build_invoice_json(rows, valid_src_ids):
    result = []
    header_map = {}
    # print("rows", rows)
    # print("src_id", valid_src_ids)

    for row in rows:
        header_id = row["id"]
        src_id = row["src_id"]

        # Skip invalid src_ids
        if src_id not in valid_src_ids:
            # print("Continuing",src_id)
            continue

        # Create header object once
        print("header_id",header_id)
        if header_id not in header_map:
            header_obj = {
                "id": header_id,
                "src_id": row["src_id"],
                "bill_to": row["bill_to"],
                "ship_to": row["ship_to"],
                "supplier_name": row["supplier_name"],
                "invoice_number": row["invoice_number"],
                "invoice_date": str(row["invoice_date"]) if row["invoice_date"] else None,
                "payment_terms": row["payment_terms"],
                "customer_number": row["customer_number"],
                "invoice_duedate": str(row["invoice_duedate"]) if row["invoice_duedate"] else None,
                "customer_po_number": row["customer_po_number"],
                "so_number": row["so_number"],
                "shipping_point": row["shipping_point"],
                "currency_code": row["currency_code"],
                "invoice_amount": float(row["invoice_amount"])
                                    if row["invoice_amount"] not in (None, "")
                                    else 0.0,
                "supplier_site": row["supplier_site"],
                "line_items": []
            }

            header_map[header_id] = header_obj
            result.append(header_obj)
            print("header_obj",header_obj)

        # Add line item
        if row["line_id"] is not None:
            header_map[header_id]["line_items"].append({
                "id": row["line_id"],
                "line_number": row["line_number"],
                "item_name": row["item_name"],
                "ordered_quantity": row["ordered_quantity"],
                "unit_of_measure": row["unit_of_measure"],

                "total": float(str(row["total"]).replace(",", ""))
                            if row["total"] not in (None, "")
                            else 0.0,

                "fob_point": row["fob_point"],
                "freight_carrier": row["freight_carrier"],
                "item_desc": row["item_desc"]
            })
    # print("result of header and line", result)
    return result

def ebs_dashboard_db_kpi():
    return {
        "received_30": count_ebs_inv_received_dboard(),
        "processed_30": count_ebs_inv_processed_dboard(),
        "failed_30": count_ebs_inv_exceptions_dboard()
    }

def count_ebs_inv_received_dboard():
    connection = db_connection()
    if connection is None:
        raise ValueError("[extract_inv_data] Database connection is not initialized")

    try:
        cursor = connection.cursor(dictionary=True)
        cursor.execute("SELECT count(*) as Invoice_Received FROM source WHERE LOWER(doc_type) = LOWER(%s) AND target = 'EBS'", ('Invoice',))
        invoice_dtls = cursor.fetchall() 
        inv_received  = invoice_dtls[0]['Invoice_Received'] 
        print("Inv received",inv_received)
        return inv_received
    except Exception as e:
        print(f"[extract_inv_data] Error fetching employee details: {e}")
    

    finally:
        cursor.close()  
        connection.close() 

def count_ebs_inv_exceptions_dboard():
    try:
        data = fetch_exception_records_db()

        # get unique src_ids
        unique_src_ids = {row["entity_id"] for row in data}

        return len(unique_src_ids)

    except Exception as e:
        print(f"Error in count_inv_exceptions: {e}")
        return 0

def count_ebs_inv_processed_dboard():
    connection = db_connection()
    cursor = connection.cursor(dictionary=True)

    try:
        valid_src_ids = get_valid_src_ids(cursor)
        return len(valid_src_ids)
    finally:
        cursor.close()
        connection.close() 

# def ebs_process_chart_db():
#     connection = db_connection()
#     cursor = connection.cursor(dictionary=True)

#     try:
#         # Day order (Mon → Sun)
#         days_order = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]

#         # Initialize result
#         received_map = {day: 0 for day in days_order}
#         processed_map = {day: 0 for day in days_order}
#         failed_map = {day: 0 for day in days_order}

#         # ✅ 1. RECEIVED
#         cursor.execute("""
#             SELECT DAYNAME(timestamp) as day, COUNT(*) as cnt
#             FROM source
#             WHERE timestamp >= NOW() - INTERVAL 7 DAY
#             AND LOWER(doc_type) = 'invoice'
#             AND target = 'EBS' 
#             GROUP BY DAYNAME(timestamp)
#         """)

#         for row in cursor.fetchall():
#             received_map[row["day"]] = row["cnt"]

#         # ✅ 2. PROCESSED
#         valid_src_ids = get_valid_src_ids(cursor)

#         if valid_src_ids:
#             format_strings = ','.join(['%s'] * len(valid_src_ids))

#             cursor.execute(f"""
#                 SELECT DAYNAME(timestamp) as day, COUNT(*) as cnt
#                 FROM source
#                 WHERE src_id IN ({format_strings})
#                 AND timestamp >= NOW() - INTERVAL 7 DAY
#                 AND target = 'EBS'
#                 GROUP BY DAYNAME(timestamp)
#             """, tuple(valid_src_ids))

#             for row in cursor.fetchall():
#                 processed_map[row["day"]] = row["cnt"]

#         # ✅ 3. FAILED
#         cursor.execute("""
#             SELECT DAYNAME(s.timestamp) as day, COUNT(DISTINCT l.entity_id) as cnt
#             FROM log_table l
#             JOIN source s ON l.entity_id = s.src_id
#             WHERE l.status = 'Failed'
#             AND s.doc_type = 'invoice'
#             AND s.timestamp >= NOW() - INTERVAL 7 DAY
#             AND s.target = 'EBS'
#             GROUP BY DAYNAME(s.timestamp)
#         """)

#         for row in cursor.fetchall():
#             failed_map[row["day"]] = row["cnt"]

#         # ✅ Final format (Mon → Sun)
#         return {
#             "x": ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"],
#             "received": [received_map[d] for d in days_order],
#             "processed": [processed_map[d] for d in days_order],
#             "failed": [failed_map[d] for d in days_order]
#         }

#     finally:
#         cursor.close()
#         connection.close()


def ebs_process_chart_db():
    connection = db_connection()
    cursor = connection.cursor(dictionary=True)

    try:
        days_order = [
            "Monday",
            "Tuesday",
            "Wednesday",
            "Thursday",
            "Friday",
            "Saturday",
            "Sunday"
        ]

        received_map = {day: 0 for day in days_order}
        processed_map = {day: 0 for day in days_order}
        failed_map = {day: 0 for day in days_order}

        # Current week starts on Monday
        week_start_condition = """
            CURDATE() - INTERVAL WEEKDAY(CURDATE()) DAY
        """

        # 1. RECEIVED
        cursor.execute("""
            SELECT DAYNAME(timestamp) AS day, COUNT(*) AS cnt
            FROM source
            WHERE timestamp >= CURDATE() - INTERVAL WEEKDAY(CURDATE()) DAY
              AND timestamp <= NOW()
              AND LOWER(doc_type) = 'invoice'
              AND target = 'EBS'
            GROUP BY DAYNAME(timestamp)
        """)

        for row in cursor.fetchall():
            received_map[row["day"]] = row["cnt"]

        # 2. PROCESSED
        valid_src_ids = get_valid_src_ids(cursor)

        if valid_src_ids:
            format_strings = ','.join(['%s'] * len(valid_src_ids))

            cursor.execute(f"""
                SELECT DAYNAME(timestamp) AS day, COUNT(*) AS cnt
                FROM source
                WHERE src_id IN ({format_strings})
                  AND timestamp >= CURDATE() - INTERVAL WEEKDAY(CURDATE()) DAY
                  AND timestamp <= NOW()
                  AND target = 'EBS'
                GROUP BY DAYNAME(timestamp)
            """, tuple(valid_src_ids))

            for row in cursor.fetchall():
                processed_map[row["day"]] = row["cnt"]

        # 3. FAILED
        cursor.execute("""
            SELECT DAYNAME(s.timestamp) AS day,
                   COUNT(DISTINCT l.entity_id) AS cnt
            FROM log_table l
            JOIN source s ON l.entity_id = s.src_id
            WHERE l.status = 'Failed'
              AND s.doc_type = 'invoice'
              AND s.timestamp >= CURDATE() - INTERVAL WEEKDAY(CURDATE()) DAY
              AND s.timestamp <= NOW()
              AND s.target = 'EBS'
            GROUP BY DAYNAME(s.timestamp)
        """)

        for row in cursor.fetchall():
            failed_map[row["day"]] = row["cnt"]

        return {
            "x": ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"],
            "received": [received_map[d] for d in days_order],
            "processed": [processed_map[d] for d in days_order],
            "failed": [failed_map[d] for d in days_order]
        }

    finally:
        cursor.close()
        connection.close()

def format_time_ago(dt):
    now = datetime.now()
    diff = now - dt

    seconds = int(diff.total_seconds())

    if seconds < 10:
        return "just now"

    if seconds < 60:
        return f"{seconds} sec ago"
    
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes} min ago"
    
    hours = minutes // 60
    if hours < 24:
        return f"{hours} hr ago"
    
    days = hours // 24
    if days == 1:
        return "1 day ago"
    
    return f"{days} days ago"

def ebs_recent_act_db():
    connection = db_connection()
    cursor = connection.cursor(dictionary=True)

    try:
        cursor.execute("""
            SELECT 
                l.entity_id,
                l.stage,
                l.status,
                l.log_time,
                l.action_taken, 
                s.channel,
                j.invoice_number,
                SUM(CAST(li.total AS DECIMAL(10,2))) as total_amount

            FROM log_table l

            LEFT JOIN source s 
                ON l.entity_id = s.src_id

            LEFT JOIN inv_header j 
                ON l.entity_id = j.src_id

            LEFT JOIN inv_line li 
                ON j.id = li.header_id

            WHERE l.stage IN ('collection', 'ebs')
                AND LOWER(s.doc_type) = LOWER('Invoice')
                AND s.target = 'EBS'
                AND (
                    l.action_taken = 'reprocessed'
                    OR lower(l.action_taken) = 'archived'
                    OR lower(l.action_taken) = 'email sent'
                    OR lower(l.action_taken) = 'requested approval'
                    OR lower(l.action_taken) = 'reprocessed'
                    OR lower(l.action_taken) = 'approved'

                    OR l.action_taken IS NULL
                    OR TRIM(l.action_taken) = ''
                )

            GROUP BY 
                l.id, l.entity_id, l.stage, l.status, l.log_time, 
                s.channel, j.invoice_number

            ORDER BY l.log_time DESC
            LIMIT 5
        """)

        rows = cursor.fetchall()

        activities = []

        for row in rows:
            stage = (row["stage"] or "").lower()
            status = (row["status"] or "").lower()

            invoice_no = row["invoice_number"] or "N/A"
            amount = row["total_amount"] or 0
            channel = row["channel"] or "unknown"

            # 🔹 COLLECTION STAGE
            if stage == "collection":
                activities.append({
                    "title": "New Invoice Received",
                    "subtitle": f"Ref: {row['entity_id']}, received via {channel}",
                    "time": format_time_ago(row["log_time"])
                })

            # 🔹 EBS STAGE
            elif stage == "ebs":
                action_taken = (row.get("action_taken") or "").strip().lower()                
                print("-------------action taken---------------", action_taken)
                
                if status == "successful" and action_taken == "archived":
                    activities.append({
                        "title": "Duplicate Invoice Archived",
                        "subtitle": f"Invoice number-{invoice_no} has been archived successfully.",
                        "time": format_time_ago(row["log_time"])
                    }) 
                elif status == "successful"and action_taken == "":
                    activities.append({
                        "title": "Invoice Posted",
                        "subtitle": f"Invoice number-{invoice_no}, of ${amount} posted to Oracle EBS.",
                        "time": format_time_ago(row["log_time"])
                    })
                
                elif status == "successful"and action_taken == "reprocessed":
                    activities.append({
                        "title": "Invoice Posted",
                        "subtitle": f"Invoice number-{invoice_no}, of ${amount} has been reprocessed and posted to Oracle EBS.",
                        "time": format_time_ago(row["log_time"])
                    })

                elif status == "successful"and action_taken == "approved":
                    activities.append({
                        "title": "Admin Approved",
                        "subtitle": f"Invoice number-{invoice_no}, of ${amount} has been approved for reprocessing.",
                        "time": format_time_ago(row["log_time"])
                    })

                elif status == "successful" and action_taken == "email sent":
                    activities.append({
                        "title": "Email Notified",
                        "subtitle": f"Email has been sent for Invoice number-{invoice_no}.",
                        "time": format_time_ago(row["log_time"])
                    }) 
                elif status == "onhold" and action_taken == "requested approval":
                    activities.append({
                        "title": "Invoice OnHold",
                        "subtitle": f"Ref: {row['entity_id']} is awaiting admin approval for reprocessing",
                        "time": format_time_ago(row["log_time"])
                    })
                else:
                    activities.append({
                        "title": "Invoice Failed",
                        "subtitle": f"Invoice number-{invoice_no}, failed Oracle EBS posting.",
                        "time": format_time_ago(row["log_time"])
                    })

        return activities

    finally:
        cursor.close()
        connection.close()

# def reprocess_ebs_invoice_db(data):
#     connection = db_connection()
#     cursor = connection.cursor(dictionary=True)

#     try:
#         src_id = data["src_id"]
#         invoice_number = data["invoice_number"]
#         invoice_date = data["invoice_date"]
#         supplier_number = data["supplier_number"]
#         line_items = data["line_items"]

#         # ---------------------------
#         # 1. Get header_id
#         # ---------------------------
#         cursor.execute("""
#             SELECT id FROM inv_header
#             WHERE src_id = %s
#         """, (src_id,))
#         header = cursor.fetchone()

#         if not header:
#             raise Exception(f"No header found for src_id: {src_id}")

#         header_id = header["id"]

#         # ---------------------------
#         # 2. Update header
#         # ---------------------------
#         cursor.execute("""
#             UPDATE inv_header
#             SET invoice_number = %s,
#                 invoice_date = %s,
#                 supplier_number = %s
#             WHERE src_id = %s
#         """, (invoice_number, invoice_date, supplier_number, src_id))

#         # ---------------------------
#         # 3. Update line items
#         # ---------------------------
#         for item in line_items:
#             cursor.execute("""
#                 UPDATE jde_inv_line
#                 SET item_number = %s,
#                     gross_amount = %s
#                 WHERE header_id = %s 
#             """, (
#                 item["item_number"],
#                 item["gross_amount"],
#                 header_id
#             ))

#         # ---------------------------
#         # 4. Get latest active log
#         # ---------------------------
#         cursor.execute("""
#             SELECT id FROM log_table
#             WHERE entity_id = %s 
#             ORDER BY log_time DESC
#             LIMIT 1
#         """, (src_id,))
#         latest_log = cursor.fetchone()

#         # ---------------------------
#         # 5. Deactivate old log
#         # ---------------------------
#         if latest_log:
#             cursor.execute("""
#                 UPDATE log_table
#                 SET is_active = '0'
#                 WHERE id = %s
#             """, (latest_log["id"],))

#         # ---------------------------
#         # 6. Insert new log
#         # ---------------------------
#         cursor.execute("""
#             INSERT INTO log_table (
#                 entity_id,
#                 status,
#                 stage,
#                 description,
#                 is_active,
#                 is_reviewed,
#                 action_taken,
#                 log_time
#             )
#             VALUES (%s, %s, %s, %s, %s, %s, %s, NOW())
#         """, (
#             src_id,
#             "Successful",
#             "Reprocess",
#             "Invoice reprocessed successfully",
#             '0',
#             '1',
#             'Reprocessed'
#         ))

#         connection.commit()

#         return {
#             "status": "success",
#             "message": "Invoice reprocessed successfully"
#         }

#     except Exception as e:
#         connection.rollback()
#         return {
#             "status": "error",
#             "message": str(e)
#         }

#     finally:
#         cursor.close()
#         connection.close()

# def update_duplicate_ebs_log_service_db(src_id: str):
#     connection = db_connection()  
#     cursor = connection.cursor(dictionary=True)

#     # 1️⃣ Deactivate last FAILED log for this src_id
#     cursor.execute("""
#         SELECT id
#         FROM log_table
#         WHERE entity_id = %s AND status = 'Failed' 
#         ORDER BY log_time DESC
#         LIMIT 1
#     """, (src_id,))
#     row = cursor.fetchone()

#     if row:
#         last_log_id = row['id']
#         cursor.execute("""
#             UPDATE log_table
#             SET is_active = '0'
#             WHERE id = %s
#         """, (last_log_id,))
#         print(f"Deactivated last failed log id {last_log_id} for src_id {src_id}")
#     else:
#         print(f"No failed active log found for src_id {src_id}")

#     # 2️⃣ Insert new log entry for this email action
#     cursor.execute("""
#         INSERT INTO log_table (entity_id, status, stage, description, is_active, is_reviewed, action_taken, log_time)
#         VALUES (%s, %s, %s, %s, '0', '1', 'Email', %s)
#     """, (
#         src_id,
#         'Successful',              
#         'EBS',       
#         'Email sent for duplicate invoice',  
#         datetime.now()           
#     ))
#     print(f"Inserted new email log for src_id {src_id}")

#     connection.commit()
#     cursor.close()
#     connection.close()

def get_ebs_reviewed_data_db():
    records = fetch_ebs_reviewed_records_db()
    
    return records

# def fetch_ebs_reviewed_records_db(src_id=None):
#     connection = db_connection()
#     cursor = connection.cursor(dictionary=True)

#     try:
#         query = """
#             SELECT 
#             l.entity_id,
#             l.description,
#             l.action_taken,
#             e.from_email,
#             j.invoice_number,
#             l.log_time
#         FROM ennvault.log_table l

#         JOIN ennvault.source s
#             ON s.src_id = l.entity_id
#         AND s.doc_type = 'invoice'
#         AND s.target = 'EBS'

#         LEFT JOIN ennvault.email e
#             ON e.src_id = l.entity_id

#         LEFT JOIN ennvault.inv_header j
#             ON j.src_id = l.entity_id

#         WHERE l.is_reviewed = 1

#         ORDER BY l.entity_id, l.log_time;
#         """

#         params = ()

#         if src_id:
#             query += " AND l.entity_id = %s"
#             params = (src_id,)

#         query += " ORDER BY l.log_time DESC"

#         cursor.execute(query, params)
#         records = cursor.fetchall()
#         reviewed_data = {}
#         for rec in records:
#             reviewed_data[rec['entity_id']] = {
#                 "entity_id": rec['entity_id'],
#                 "description": rec['description'],
#                 "action_taken": rec['action_taken'],
#                 "from_email": rec['from_email'],
#                 "invoice_number": rec['invoice_number'],
#                 "log_time": rec['log_time']
#             }

#         return reviewed_data

#     except Exception as e:
#         print(f"[fetch_reviewed_records_db] Error: {e}")
#         return {}

#     finally:
#         cursor.close()
#         connection.close()

def fetch_ebs_reviewed_records_db(src_id=None):
    connection = db_connection()
    cursor = connection.cursor(dictionary=True)

    try:
        query = """
            SELECT 
                l.entity_id,
                l.description,
                l.action_taken,
                e.from_email,
                j.invoice_number,
                l.log_time
            FROM ennvault.log_table l

            JOIN ennvault.source s
                ON s.src_id = l.entity_id
               AND s.doc_type = 'invoice'
               AND s.target = 'EBS'

            LEFT JOIN ennvault.email e
                ON e.src_id = l.entity_id

            LEFT JOIN ennvault.inv_header j
                ON j.src_id = l.entity_id

            WHERE l.is_reviewed = 1
        """

        params = []

        if src_id:
            query += " AND l.entity_id = %s"
            params.append(src_id)

        query += " ORDER BY l.log_time DESC"

        cursor.execute(query, tuple(params))
        records = cursor.fetchall()

        reviewed_data = []

        for rec in records:
            reviewed_data.append({
                "entity_id": rec['entity_id'],
                "description": rec['description'],
                "action_taken": rec['action_taken'],
                "from_email": rec['from_email'],
                "invoice_number": rec['invoice_number'],
                "log_time": rec['log_time']
            })

        return reviewed_data

    except Exception as e:
        print(f"[fetch_reviewed_records_db] Error: {e}")
        return []

    finally:
        cursor.close()
        connection.close()



# def request_approval_ebs_db(src_id, field_list):

#     connection = db_connection()

#     if not connection:
#         return {
#             "status": "failed",
#             "message": "Database connection failed"
#         }

#     cursor = connection.cursor(dictionary=True)

#     try:

#         header_columns = {
#             "bill_to",
#             "ship_to",
#             "supplier_name",
#             "invoice_number",
#             "invoice_date",
#             "payment_terms",
#             "customer_number",
#             "invoice_duedate",
#             "customer_po_number",
#             "so_number",
#             "shipping_point",
#             "currency_code",
#             "invoice_amount",
#             "supplier_site"
#         }

#         line_columns = {
#             "item_name",
#             "ordered_quantity",
#             "unit_of_measure",
#             "total",
#             "fob_point",
#             "freight_carrier",
#             "item_desc"
#         }

#         modified_fields = []

#         # get header id
#         cursor.execute(
#             """
#             SELECT id
#             FROM inv_header
#             WHERE src_id = %s
#             """,
#             (src_id,)
#         )

#         header_record = cursor.fetchone()

#         if not header_record:
#             return {
#                 "status": "failed",
#                 "message": "Header record not found"
#             }

#         header_id = header_record["id"]

#         # update fields
#         for key, value in field_list.items():

#             # HEADER TABLE
#             if key in header_columns:

#                 query = f"""
#                     UPDATE inv_header
#                     SET {key} = %s
#                     WHERE src_id = %s
#                 """

#                 cursor.execute(query, (value, src_id))

#                 modified_fields.append(key)

#             # LINE TABLE
#             elif key in line_columns:

#                 query = f"""
#                     UPDATE inv_line
#                     SET {key} = %s
#                     WHERE header_id = %s
#                 """

#                 cursor.execute(query, (value, header_id))

#                 modified_fields.append(key)

#         connection.commit()

#         return {
#             "status": "success",
#             "modified_fields": modified_fields
#         }

#     except Exception as e:

#         connection.rollback()

#         return {
#             "status": "failed",
#             "message": str(e)
#         }

#     finally:
#         cursor.close()
#         connection.close()


def request_approval_ebs_db(src_id, field_list):

    connection = db_connection()

    if not connection:
        return {
            "status": "failed",
            "message": "Database connection failed"
        }

    cursor = connection.cursor(dictionary=True)

    try:

        header_columns = {
            "bill_to",
            "ship_to",
            "supplier_name",
            "invoice_number",
            "invoice_date",
            "payment_terms",
            "customer_number",
            "invoice_duedate",
            "customer_po_number",
            "so_number",
            "shipping_point",
            "currency_code",
            "invoice_amount",
            "supplier_site"
        }

        line_columns = {
            "item_name",
            "ordered_quantity",
            "unit_of_measure",
            "total",
            "fob_point",
            "freight_carrier",
            "item_desc",
            "line_number"
        }

        modified_fields = []

        cursor.execute(
            """
            SELECT id
            FROM inv_header
            WHERE src_id = %s
            """,
            (src_id,)
        )

        header_record = cursor.fetchone()

        if not header_record:
            return {
                "status": "failed",
                "message": "Header record not found"
            }

        header_id = header_record["id"]

        header_changes = field_list.get("header", {}) if isinstance(field_list, dict) else {}
        line_changes = field_list.get("lines", []) if isinstance(field_list, dict) else []

        for key, value in header_changes.items():
            if key in header_columns:
                query = f"""
                    UPDATE inv_header
                    SET {key} = %s
                    WHERE src_id = %s
                """
                cursor.execute(query, (value, src_id))
                modified_fields.append(key)

        for line_change in line_changes:
            if not isinstance(line_change, dict):
                continue

            line_id = line_change.get("line_id")
            line_fields = line_change.get("fields", {})
            if not line_id or not isinstance(line_fields, dict):
                continue

            for key, value in line_fields.items():
                if key in line_columns:
                    query = f"""
                        UPDATE inv_line
                        SET {key} = %s
                        WHERE header_id = %s AND id = %s
                    """
                    cursor.execute(query, (value, header_id, line_id))
                    modified_fields.append(key)

        if any(field == "total" for field in modified_fields):
            cursor.execute(
                """
                SELECT COALESCE(SUM(total), 0) AS grand_total
                FROM inv_line
                WHERE header_id = %s
                """,
                (header_id,)
            )

            total_record = cursor.fetchone()
            grand_total = total_record["grand_total"] if total_record else 0

            cursor.execute(
                """
                UPDATE inv_header
                SET invoice_amount = %s
                WHERE id = %s
                """,
                (grand_total, header_id)
            )

        connection.commit()

        return {
            "status": "success",
            "modified_fields": modified_fields
        }

    except Exception as e:

        connection.rollback()

        return {
            "status": "failed",
            "message": str(e)
        }

    finally:
        cursor.close()
        connection.close()

def archive_exceptions_db(src_id):
    insert_log(src_id, "Successful", "EBS", "Duplicate invoice has been archived successfully",
                is_reviewed="1",
                action_taken ="Archived",
                )
    return {
        "status": "success",
        "message": "Exception archived successfully"
    }


def email_exceptions_db(src_id):
    insert_log(src_id, "Successful", "EBS", "Email has been sent successfully",
                is_reviewed="1",
                action_taken ="Email Sent",
                )
    return {
        "status": "success",
        "message": "Email sent successfully"
    }

def fetch_duplicate_email_recipient_db(src_id: str):
    connection = db_connection()
    cursor = connection.cursor(dictionary=True)

    try:
        query = """
            SELECT from_email
            FROM ennvault.email
            WHERE src_id = %s
            LIMIT 1
        """

        cursor.execute(query, (src_id,))
        record = cursor.fetchone()

        if record:
            return record.get("from_email")

        return None

    except Exception as e:
        print(f"[fetch_duplicate_email_recipient_db] Error: {e}")
        return None

    finally:
        cursor.close()
        connection.close()

def get_source_attachments_db(src_id: str):
    connection = db_connection()
    cursor = connection.cursor(dictionary=True)

    try:
        query = """
            SELECT archive
            FROM ennvault.source
            WHERE src_id = %s
            LIMIT 1
        """

        cursor.execute(query, (src_id,))
        record = cursor.fetchone()

        if not record:
            print(f"[get_source_attachments_db] No source found for src_id: {src_id}")
            return []

        archive = record.get("archive")

        if not archive:
            print(f"[get_source_attachments_db] No archive path for src_id: {src_id}")
            return []

        # source.archive is stored relative to DATA_ROOT -- same join
        # fetch_ebs_invoice_services (services.py) uses, so both readers of
        # this column agree on where it actually points.
        folder_path = os.path.normpath(os.path.join(DATA_ROOT, os.path.normpath(archive))) if DATA_ROOT else archive

        if not os.path.isdir(folder_path):
            print(
                f"[get_source_attachments_db] Folder does not exist: "
                f"{folder_path}"
            )
            return []

        attachments = []

        for filename in os.listdir(folder_path):
            file_path = os.path.join(folder_path, filename)

            if os.path.isfile(file_path):
                attachments.append(file_path)

        return attachments

    except Exception as e:
        print(f"[get_source_attachments_db] Error: {e}")
        return []

    finally:
        cursor.close()
        connection.close()


def get_customer_po_number(src_id):
    connection = db_connection()

    try:
        cursor = connection.cursor(dictionary=True)

        cursor.execute("""
            SELECT customer_po_number
            FROM inv_header
            WHERE src_id = %s
            LIMIT 1
        """, (src_id,))

        result = cursor.fetchone()

        if not result or not result.get("customer_po_number"):
            raise ValueError(
                f"No customer PO number found for src_id: {src_id}"
            )

        return result["customer_po_number"]

    finally:
        cursor.close()
        connection.close()

def get_previous_src_id_by_customer_po(customer_po_number, current_src_id):
    connection = db_connection()

    try:
        cursor = connection.cursor(dictionary=True)

        cursor.execute("""
            SELECT src_id
            FROM inv_header
            WHERE customer_po_number = %s
              AND src_id <> %s
            ORDER BY id DESC
            LIMIT 1
        """, (
            customer_po_number,
            current_src_id
        ))

        result = cursor.fetchone()

        if not result or not result.get("src_id"):
            raise ValueError(
                f"No previous invoice found for customer PO: "
                f"{customer_po_number}"
            )

        return result["src_id"]

    finally:
        cursor.close()
        connection.close()

def get_conversation_id_by_src_id(src_id):
    connection = db_connection()

    try:
        cursor = connection.cursor(dictionary=True)

        cursor.execute("""
            SELECT coversationId
            FROM email
            WHERE src_id = %s
            LIMIT 1
        """, (src_id,))

        result = cursor.fetchone()

        if not result or not result.get("coversationId"):
            raise ValueError(
                f"No conversation ID found for src_id: {src_id}"
            )

        return result["coversationId"]

    finally:
        cursor.close()
        connection.close()


import pymysql, os

DB_HOST = os.getenv("DB_HOST", "localhost")
DB_USER = os.getenv("DB_USER", "root")
DB_PASSWORD = os.getenv("DB_PASSWORD", "")
DB_NAME = os.getenv("DB_NAME", "ennvault")

def get_db_connection():
    return pymysql.connect(
        host=DB_HOST,
        user=DB_USER,
        password=DB_PASSWORD,
        database=DB_NAME,
        charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor,
        autocommit=True
    )

def insert_source(channel,target, doc_type, atch_nm, archive, folder_path):
    conn = get_db_connection()
    cursor = conn.cursor()

    sql = """
    INSERT INTO source (channel, target,doc_type, atch_nm, archive, folder_path)
    VALUES (%s, %s, %s, %s, %s,%s)
    """
    cursor.execute(sql, (channel, target, doc_type, atch_nm, archive, folder_path))
    conn.commit()

    new_id = cursor.lastrowid

    cursor.execute("SELECT src_id FROM source WHERE id = %s", (new_id,))
    result = cursor.fetchone()

    conn.close()

    if result:
        return result["src_id"]
    else:
        raise Exception("src_id not found after insert")

# def insert_email(src_id, from_email, subject, body, convo_id):
#     conn = get_db_connection()
#     cursor = conn.cursor()

#     sql = """
#     INSERT INTO email (src_id, from_email, subject, body,coversationId )
#     VALUES (%s, %s, %s, %s, %s)
#     """
#     cursor.execute(sql, (src_id, from_email, subject, body, convo_id))
#     conn.commit()
#     conn.close()

def insert_email(src_id, from_email, subject, body, convo_id, message_id):
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
        INSERT INTO email (src_id, from_email, subject, body, coversationId, messageId)
        VALUES (%s, %s, %s, %s, %s, %s)
        ON DUPLICATE KEY UPDATE
            from_email = VALUES(from_email),
            subject = VALUES(subject)
    """, (src_id, from_email, subject, body, convo_id, message_id))

    conn.commit()
    conn.close()


# def insert_log(entity_id, status, stage, description):
#     conn = get_db_connection()
#     cursor = conn.cursor()

#     sql = """
#     INSERT INTO log_table (entity_id, status, stage, description)
#     VALUES (%s, %s, %s, %s)
#     """
#     cursor.execute(sql, (entity_id, status, stage, description))
#     conn.commit()
#     conn.close()

def get_attachment_path(src_id):
    conn = get_db_connection()
    cursor = conn.cursor()  # or dictionary=True
    
    sql = """
    SELECT archive
    FROM source
    WHERE src_id = %s
    LIMIT 1
    """
    cursor.execute(sql, (src_id,))
    row = cursor.fetchone()
    conn.close()
    
    if row:
        archive_path = row["archive"]  
        return archive_path if archive_path else None
    
    return None



def insert_log(entity_id, status, stage, description,is_reviewed='0',action_taken='',what_modified =''):
    conn = get_db_connection()
    cursor = conn.cursor()
    sql = """ UPDATE log_table set is_active  = '0' where entity_id = %s """
    cursor.execute(sql,(entity_id,))
 
    sql = """
    INSERT INTO log_table (entity_id, status, stage, description,is_active,is_reviewed,action_taken, what_modified)
    VALUES (%s, %s, %s, %s,%s,%s,%s,%s)
    """
    cursor.execute(sql, (entity_id, status, stage, description,'1',is_reviewed,action_taken, what_modified))
    conn.commit()
    conn.close()



def extract_po_data_ebs(src_id):
    """Fetches invoice data from db"""
    connection = get_db_connection()
    if connection is None:
        raise ValueError("[extract_po_data_ebs] Database connection is not initialized")
    
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

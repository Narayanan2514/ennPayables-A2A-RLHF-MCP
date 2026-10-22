from app.setttings.config import get_db_connection

def update_archive_path_by_folder(folder_path, archive_path):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute(
        "UPDATE source SET archive=%s WHERE folder_path=%s",
        (archive_path, folder_path)
    )
    print("archive_path,folder_path",archive_path, folder_path)
    cur.execute("select archive from source where folder_path=%s",(folder_path,))
    archive = {row['archive'] for row in cur.fetchall()}
    print('archive',archive)
    conn.commit()
    conn.close()
    return archive

def extract_remit_refs():
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT ref_number FROM remit_header WHERE ref_number IS NOT NULL")
    refs = {row["ref_number"] for row in cur.fetchall()}
    cur.close()
    conn.close()
    return refs


def extract_bdoc_refs():
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT ref_num FROM bank_doc WHERE ref_num IS NOT NULL")
    refs = {row["ref_num"] for row in cur.fetchall()}
    cur.close()
    conn.close()
    return refs

def detect_doc_type(folder_path):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute(
        "SELECT doc_type FROM source WHERE folder_path=%s",
        (folder_path,)
    )

    row = cur.fetchone()
    cur.close()
    conn.close()

    if row and row["doc_type"]:
        return row["doc_type"]

    return "UNKNOWN"
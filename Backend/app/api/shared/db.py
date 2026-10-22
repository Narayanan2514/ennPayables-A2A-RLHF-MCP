import os
import mysql.connector
from mysql.connector import Error

def db_connection():
    """Establish MySQL database connection"""
    
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
        print(f"[db_connection] Database connection error: {e}")
        return None

    except ValueError as ve:
        print(f"[db_connection] Configuration error: {ve}")
        return None

def get_user_by_email(email: str):

    connection = db_connection()

    if connection is None:
        raise ValueError("[get_user_by_email] Database connection is not initialized")

    try:
        cursor = connection.cursor(dictionary=True)

        query = """SELECT email, hashed_pswd, name, erp, role, reporting_to FROM users WHERE email = %s"""

        cursor.execute(query, (email,))
        user = cursor.fetchone()

        return user

    except Exception as e:
        print(f"[get_user_by_email] Error fetching user: {e}")
        return None

    finally:
        cursor.close()
        connection.close()
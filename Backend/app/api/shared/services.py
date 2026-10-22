from fastapi import HTTPException
from passlib.context import CryptContext
from jose import jwt
from datetime import datetime, timedelta

from app.api.shared.db import *

SECRET_KEY = "your-secret-key-change-this-in-production"
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 8

pwd_context = CryptContext(
    schemes=["bcrypt"],
    deprecated="auto"
)

def create_access_token(data: dict):

    payload = data.copy()

    payload["exp"] = (
        datetime.utcnow() +
        timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    )

    return jwt.encode(
        payload,
        SECRET_KEY,
        algorithm=ALGORITHM
    )

def login_service(email: str, password: str):

    # Fetch user from DB
    user = get_user_by_email(email)

    # User not found
    if not user:
        raise HTTPException(
            status_code=401,
            detail="Invalid credentials"
        )

    # Verify password
    if not pwd_context.verify(password, user["hashed_pswd"]):
        raise HTTPException(
            status_code=401,
            detail="Invalid credentials"
        )

    # Generate token
    token = create_access_token({
        "sub": email,
        "name": user["name"],
        "role": user["role"],
        "erp": user["erp"]
    })

    return {
        "message": "Login successful",
        "token": token,
        "email": user["email"],
        "name": user["name"],
        "erp": user["erp"],
        "role": user["role"],
        "reporting_to": user["reporting_to"]
    }
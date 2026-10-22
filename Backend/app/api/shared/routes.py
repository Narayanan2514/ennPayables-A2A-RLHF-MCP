from fastapi import APIRouter, Request
from app.api.shared.services import *

router  = APIRouter()

@router.post("/login")
async def login(request: Request):

    body = await request.json()

    email = body.get("email")
    password = body.get("password")

    return login_service(
        email=email,
        password=password
    )
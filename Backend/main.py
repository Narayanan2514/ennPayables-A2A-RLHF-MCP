import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.api.ennPayables.EBS.routes import router as ebs_router
from app.api.shared.routes import router as login_router
from app.api.internal.routes import router as internal_router
import uvicorn

app = FastAPI(title="ennPayables EBS")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(ebs_router, prefix="/ebs")
app.include_router(login_router, prefix="/api")
app.include_router(internal_router, prefix="/internal")

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=int(os.getenv("APP_PORT", 8011)), reload=True)

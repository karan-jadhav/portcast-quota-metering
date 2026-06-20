from fastapi import FastAPI
from app.api.admin_routes import router as admin_router
from app.api.consumer_routes import router as consumer_router
from app.api.quota_routes import router as quota_router

app = FastAPI()

app.include_router(admin_router)
app.include_router(consumer_router)
app.include_router(quota_router)

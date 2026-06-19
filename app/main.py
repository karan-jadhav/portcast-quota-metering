from fastapi import Depends, FastAPI
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from app.api.admin_routes import router as admin_router
from app.api.consumer_routes import router as consumer_router
from app.api.quota_routes import router as quota_router
from app.db import get_db

app = FastAPI()

app.include_router(admin_router)
app.include_router(consumer_router)
app.include_router(quota_router)


@app.get("/")
async def root(db: AsyncSession = Depends(get_db)):

    sql = text("SELECT 1")
    result = await db.execute(sql)

    return {"message": "Hello World", "db_result": result.scalar()}

from fastapi import Depends, FastAPI
from sqlalchemy.ext.asyncio import  AsyncSession
from sqlalchemy import text
from db import get_db

app = FastAPI()

@app.get("/")
async def root(db: AsyncSession = Depends(get_db)):

    sql = text("SELECT 1")
    result = await db.execute(sql)

    return {"message": "Hello World", "db_result": result.scalar()}
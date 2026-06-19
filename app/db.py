from typing import AsyncGenerator
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from app.config import settings

engine = create_async_engine(
    settings.SQLALCHEMY_DATABASE_URL,
    pool_size=10,
    max_overflow=20,
    pool_recycle=1800,
    pool_pre_ping=True,
)

# Async session factory creation
AsyncSessionLocal = async_sessionmaker(
    bind=engine, class_=AsyncSession, expire_on_commit=False
)


# FastAPI dependency engine
async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()

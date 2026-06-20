from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.quota import service

router = APIRouter(prefix="/admin", tags=["admin"])


class QuotaLimitRequest(BaseModel):
    limit_units: int = Field(ge=0)


class QuotaLimitResponse(BaseModel):
    org_id: UUID
    feature: str
    limit_units: int


@router.put(
    "/orgs/{org_id}/features/{feature}/quota",
    response_model=QuotaLimitResponse,
)
async def configure_quota(
    org_id: UUID,
    feature: str,
    request: QuotaLimitRequest,
    db: AsyncSession = Depends(get_db),
) -> QuotaLimitResponse:
    quota = await service.configure_quota(db, org_id, feature, request.limit_units)
    return QuotaLimitResponse(
        org_id=quota["org_id"],
        feature=quota["feature"],
        limit_units=quota["limit_units"],
    )

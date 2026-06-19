from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.quota import service

router = APIRouter(prefix="/quota", tags=["quota"])


class QuotaUsageResponse(BaseModel):
    used_units: int
    next_reset_at: datetime


@router.get(
    "/orgs/{org_id}/features/{feature}",
    response_model=QuotaUsageResponse,
)
async def get_feature_usage(
    org_id: UUID,
    feature: str,
    db: AsyncSession = Depends(get_db),
) -> QuotaUsageResponse:
    try:
        usage = await service.get_feature_usage(db, org_id, feature)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc

    return QuotaUsageResponse(
        used_units=usage["used_units"],
        next_reset_at=usage["next_reset_at"],
    )

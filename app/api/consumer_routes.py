from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.quota import service

router = APIRouter(prefix="/user", tags=["user"])


class ProcessItemsRequest(BaseModel):
    items: list[str] = Field(min_length=1)
    simulate_failure: bool = False


class ProcessItemsResponse(BaseModel):
    reservation_id: UUID
    processed_items: int
    status: str


def process_items(items: list[str], simulate_failure: bool) -> int:
    if simulate_failure:
        raise RuntimeError("simulated downstream failure")

    return len(items)


@router.post(
    "/orgs/{org_id}/features/{feature}/items",
    response_model=ProcessItemsResponse,
)
async def consume_items(
    org_id: UUID,
    feature: str,
    request: ProcessItemsRequest,
    idempotency_key: str = Header(alias="Idempotency-Key", min_length=1),
    db: AsyncSession = Depends(get_db),
) -> ProcessItemsResponse:
    units = len(request.items)

    try:
        reservation = await service.reserve_quota(
            db,
            org_id,
            feature,
            units,
            idempotency_key,
            datetime.now(UTC),
        )
    except service.QuotaExceededError as exc:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=str(exc)
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc

    reservation_id = reservation["reservation_id"]
    reservation_status = reservation["status"]

    if reservation_status == "committed":
        return ProcessItemsResponse(
            reservation_id=reservation_id,
            processed_items=reservation["units"],
            status=reservation_status,
        )

    if reservation_status != "reserved":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"reservation is already {reservation_status}",
        )

    try:
        processed_items = process_items(request.items, request.simulate_failure)
    except Exception as exc:
        await service.release_reservation(db, reservation_id)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="downstream operation failed",
        ) from exc

    reservation = await service.commit_reservation(db, reservation_id)

    return ProcessItemsResponse(
        reservation_id=reservation_id,
        processed_items=processed_items,
        status=reservation["status"],
    )

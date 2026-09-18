from fastapi import APIRouter, HTTPException

from app.schemas.billing import ReadingCreate, SettleRequest
from app.services.billing_service import BillingService
from app.services.errors import DomainError, NotFoundError

router = APIRouter(tags=["readings"])


def _map_errors(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except NotFoundError as e:
        raise HTTPException(404, str(e))
    except DomainError as e:
        raise HTTPException(409, str(e))


@router.get("/readings")
def list_readings():
    with BillingService() as svc:
        return {"items": svc.list_readings()}


@router.post("/readings", status_code=201)
def create_reading(body: ReadingCreate):
    """写入抄表（estimate/actual）；同户同账期双有效冲突返回 409 可读信息。"""
    with BillingService() as svc:
        return _map_errors(
            svc.create_reading, body.account_id, body.period, body.kwh, body.peak, body.source
        )


@router.post("/readings/{reading_id}/preview")
def preview_reading(reading_id: int):
    """试算：只读，不写 calc_runs。"""
    with BillingService() as svc:
        return _map_errors(svc.preview_reading, reading_id)


@router.post("/readings/{reading_id}/settle")
def settle_reading(reading_id: int, body: SettleRequest):
    """结算：生成差值记录并关闭估计有效态，单事务提交。"""
    with BillingService() as svc:
        return _map_errors(svc.settle_estimate, reading_id, body.actual_kwh, body.peak)

from fastapi import APIRouter

from app.schemas.readings import ReadingCreate, SettleCreate
from app.services.billing_service import BillingService

router = APIRouter(tags=["readings"])


@router.get("/readings")
def list_readings():
    with BillingService() as svc:
        return {"items": svc.list_readings()}


@router.post("/readings")
def create_reading(body: ReadingCreate):
    """写入带 estimate 标记的估计抄表，或 confirmed 正式抄表。冲突返回 409。"""
    with BillingService() as svc:
        return svc.create_reading(
            body.account_id, body.period, body.kind, body.kwh, body.peak
        )


@router.get("/readings/{reading_id}/trial")
def trial_reading(reading_id: int):
    """试算：只读不写运行记录，返回分段明细。"""
    with BillingService() as svc:
        return svc.trial_reading(reading_id)


@router.post("/readings/{reading_id}/settle")
def settle_reading(reading_id: int, body: SettleCreate):
    """结算估计：录入实抄电量，生成差值记录并关闭估计有效态（单事务）。"""
    with BillingService() as svc:
        return svc.settle_reading(reading_id, body.actual_kwh, body.peak)

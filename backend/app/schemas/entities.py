from pydantic import BaseModel


class AccountOut(BaseModel):
    id: int
    name: str
    meter_no: str
    note: str | None = None


class TierOut(BaseModel):
    id: int
    up_to: float | None
    price: float
    sort_order: int


class ReadingOut(BaseModel):
    id: int
    account_id: int
    period: str | None = None
    kwh: float
    peak: int
    source: str = "actual"
    status: str = "confirmed"


class SettlementOut(BaseModel):
    id: int
    account_id: int
    period: str
    estimate_reading_id: int
    actual_reading_id: int
    estimate_kwh: float
    actual_kwh: float
    delta_kwh: float
    estimate_amount: float
    actual_amount: float
    delta_amount: float
    created_at: str

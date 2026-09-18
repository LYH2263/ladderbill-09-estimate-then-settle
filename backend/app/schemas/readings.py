from typing import Literal

from pydantic import BaseModel, Field


class ReadingCreate(BaseModel):
    account_id: int
    period: str = Field(min_length=1, description="账期，如 2026-09")
    kind: Literal["estimate", "confirmed"]
    kwh: float = Field(ge=0)
    peak: bool = False


class SettleCreate(BaseModel):
    actual_kwh: float = Field(ge=0)
    peak: bool | None = None  # 默认沿用估计抄表的尖峰标记


class ReadingOut(BaseModel):
    id: int
    account_id: int
    period: str
    kind: str
    status: str
    kwh: float
    peak: int
    settled_by_reading_id: int | None = None
    created_at: str | None = None


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
    created_at: str | None = None

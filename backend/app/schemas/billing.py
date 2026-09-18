from typing import Literal

from pydantic import BaseModel, Field


class BillRequest(BaseModel):
    account_id: int | None = None
    kwh: float = Field(ge=0)
    peak: bool = False
    persist: bool = True


class CompareRequest(BaseModel):
    kwh: float = Field(ge=0)
    persist: bool = False


class ReadingCreate(BaseModel):
    account_id: int
    period: str = Field(pattern=r"^\d{4}-(0[1-9]|1[0-2])$", description="账期 YYYY-MM")
    kwh: float = Field(ge=0)
    peak: bool = False
    source: Literal["estimate", "actual"] = "estimate"


class SettleRequest(BaseModel):
    actual_kwh: float = Field(ge=0)
    peak: bool | None = None  # None 时沿用估计抄表的尖峰标记


class CalcRunOut(BaseModel):
    id: int
    kind: str
    account_id: int | None
    input_json: str
    result_json: str
    created_at: str

import json
import sqlite3

from app.db import connect
from app.engines.peak_compare import compare_plain_vs_peak
from app.engines.tier_progressive import calc_bill
from app.errors import ApiError, ConflictError, NotFoundError
from app.repositories import accounts as accounts_repo
from app.repositories import readings as readings_repo
from app.repositories import runs as runs_repo
from app.repositories import settlements as settlements_repo
from app.repositories import settings as settings_repo
from app.repositories import tiers as tiers_repo

KIND_LABEL = {"estimate": "估计", "confirmed": "正式", "actual": "实抄"}


class BillingService:
    def __init__(self):
        self._conn = connect()

    def close(self):
        self._conn.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    # ---- accounts / config ----
    def list_accounts(self):
        return accounts_repo.list_all(self._conn)

    def get_account(self, account_id: int):
        return accounts_repo.get(self._conn, account_id)

    def list_tiers(self):
        return tiers_repo.list_ordered(self._conn)

    def list_readings(self):
        return readings_repo.list_all(self._conn)

    def readings_for_account(self, account_id: int):
        return readings_repo.for_account(self._conn, account_id)

    def settlements_for_account(self, account_id: int):
        return settlements_repo.for_account(self._conn, account_id)

    def settings_map(self):
        return settings_repo.get_map(self._conn)

    # ---- estimate / confirmed readings ----
    def _require_account(self, account_id: int):
        account = accounts_repo.get(self._conn, account_id)
        if not account:
            raise NotFoundError(f"户号 {account_id} 不存在")
        return account

    def _calc(self, kwh: float, peak: bool) -> dict:
        tiers = tiers_repo.as_calc_rows(self._conn)
        pf = settings_repo.peak_factor(self._conn)
        factor = pf if peak else 1.0
        return calc_bill(kwh, tiers, factor)

    def create_reading(
        self, account_id: int, period: str, kind: str, kwh: float, peak: bool
    ) -> dict:
        """写入 estimate/confirmed 抄表。同户同账期已存在有效抄表则可读拒绝。"""
        self._require_account(account_id)
        period = period.strip()

        existing = readings_repo.find_active(self._conn, account_id, period)
        if existing:
            label = KIND_LABEL.get(existing["kind"], existing["kind"])
            raise ConflictError(
                f"账期 {period} 已存在{label}有效抄表（记录 #{existing['id']}），"
                "估计与正式抄表不能在同一户同一账期并存为双有效",
                extra={
                    "conflict_reading_id": existing["id"],
                    "conflict_kind": existing["kind"],
                    "conflict_status": existing["status"],
                    "period": period,
                },
            )
        try:
            reading_id = readings_repo.insert(self._conn, account_id, period, kind, kwh, peak)
            self._conn.commit()
        except sqlite3.IntegrityError:
            self._conn.rollback()
            raise ConflictError(
                f"账期 {period} 已存在有效抄表，禁止重复写入",
                extra={"period": period},
            )
        return readings_repo.get(self._conn, reading_id)

    def trial_reading(self, reading_id: int) -> dict:
        """只读试算：不写任何运行记录、不改变抄表状态。"""
        reading = readings_repo.get(self._conn, reading_id)
        if not reading:
            raise NotFoundError(f"抄表记录 #{reading_id} 不存在")
        calc = self._calc(reading["kwh"], bool(reading["peak"]))
        return {"reading": reading, "calc": calc}

    def settle_reading(self, reading_id: int, actual_kwh: float, peak: bool | None) -> dict:
        """
        结算估计抄表（单事务）：
        关闭估计有效态 → 写入实际抄表 → 生成差值记录 → 返回实抄测算。
        任一步失败整体回滚，不会留下“估计仍有效而实际半写入”的状态。
        """
        conn = self._conn
        try:
            est = readings_repo.get(conn, reading_id)
            if not est:
                raise NotFoundError(f"抄表记录 #{reading_id} 不存在")
            if est["kind"] != "estimate":
                raise ApiError(f"记录 #{reading_id} 不是估计抄表，无需结算")
            if est["status"] != "active":
                settled_by = est.get("settled_by_reading_id")
                raise ConflictError(
                    f"估计抄表 #{reading_id} 已关闭"
                    + (f"（已由实抄记录 #{settled_by} 结算）" if settled_by else ""),
                    extra={"reading_id": reading_id, "settled_by_reading_id": settled_by},
                )

            actual_peak = bool(est["peak"]) if peak is None else bool(peak)
            est_calc = self._calc(est["kwh"], bool(est["peak"]))
            actual_calc = self._calc(actual_kwh, actual_peak)

            # 顺序：关闭估计 → 写实抄 → 写差值（同一事务提交）
            readings_repo.mark_closed(conn, est["id"], None)
            actual_id = readings_repo.insert(
                conn, est["account_id"], est["period"], "actual", actual_kwh, actual_peak
            )
            conn.execute(
                "UPDATE readings SET settled_by_reading_id=? WHERE id=?",
                (actual_id, est["id"]),
            )
            delta_kwh = round(float(actual_kwh) - float(est["kwh"]), 3)
            delta_amount = round(actual_calc["total"] - est_calc["total"], 2)
            settlement_id = settlements_repo.insert(
                conn,
                est["account_id"],
                est["period"],
                est["id"],
                actual_id,
                est["kwh"],
                actual_kwh,
                delta_kwh,
                est_calc["total"],
                actual_calc["total"],
                delta_amount,
            )
            conn.commit()
        except Exception:
            conn.rollback()
            raise

        return {
            "settlement_id": settlement_id,
            "estimate_reading": readings_repo.get(conn, est["id"]),
            "actual_reading": readings_repo.get(conn, actual_id),
            "settlement": settlements_repo.get(conn, settlement_id),
            "estimate_calc": est_calc,
            "actual_calc": actual_calc,
        }

    # ---- generic calc ----
    def run_bill(self, kwh: float, peak: bool, account_id: int | None, persist: bool):
        tiers = tiers_repo.as_calc_rows(self._conn)
        pf = settings_repo.peak_factor(self._conn)
        factor = pf if peak else 1.0
        result = calc_bill(kwh, tiers, factor)
        run_id = None
        if persist:
            run_id = runs_repo.insert(
                self._conn,
                "bill",
                {"kwh": kwh, "peak": peak, "account_id": account_id},
                result,
                account_id,
            )
        return {"run_id": run_id, **result}

    def run_compare(self, kwh: float, persist: bool):
        tiers = tiers_repo.as_calc_rows(self._conn)
        pf = settings_repo.peak_factor(self._conn)
        result = compare_plain_vs_peak(kwh, tiers, pf)
        run_id = None
        if persist:
            run_id = runs_repo.insert(self._conn, "compare", {"kwh": kwh}, result, None)
        return {"run_id": run_id, **result}

    def list_history(self, limit: int = 50):
        return runs_repo.list_recent(self._conn, limit)

    def get_run(self, run_id: int):
        return runs_repo.get(self._conn, run_id)

    def dashboard_stats(self):
        accounts = accounts_repo.list_all(self._conn)
        readings = readings_repo.list_all(self._conn)
        clean = [a for a in accounts if "种子" not in a.get("name", "")]
        dirty = [a for a in accounts if "种子" in a.get("name", "")]
        return {
            "account_count": len(accounts),
            "reading_count": len(readings),
            "clean_accounts": len(clean),
            "dirty_accounts": len(dirty),
            "recent_runs": len(runs_repo.list_recent(self._conn, 5)),
        }

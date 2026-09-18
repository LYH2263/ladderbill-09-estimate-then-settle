import sqlite3

from app.db import connect
from app.engines.peak_compare import compare_plain_vs_peak
from app.engines.tier_progressive import calc_bill
from app.repositories import accounts as accounts_repo
from app.repositories import readings as readings_repo
from app.repositories import runs as runs_repo
from app.repositories import settings as settings_repo
from app.repositories import settlements as settlements_repo
from app.repositories import tiers as tiers_repo
from app.services.errors import DomainError, NotFoundError

READING_SOURCES = ("estimate", "actual")


class BillingService:
    def __init__(self):
        self._conn = connect()

    def close(self):
        self._conn.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

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

    def _calc(self, kwh: float, peak: bool) -> dict:
        tiers = tiers_repo.as_calc_rows(self._conn)
        pf = settings_repo.peak_factor(self._conn)
        return calc_bill(kwh, tiers, pf if peak else 1.0)

    def run_bill(self, kwh: float, peak: bool, account_id: int | None, persist: bool):
        result = self._calc(kwh, peak)
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

    # ---- 估计抄表与结算 ----

    def create_reading(self, account_id: int, period: str, kwh: float, peak: bool, source: str):
        """写入抄表（estimate/actual）。同户同账期不允许双有效，冲突可读拒绝。"""
        if source not in READING_SOURCES:
            raise DomainError(f"未知抄表来源：{source}（仅支持 estimate/actual）")
        if not accounts_repo.get(self._conn, account_id):
            raise NotFoundError(f"户号 #{account_id} 不存在")
        status = "estimated" if source == "estimate" else "confirmed"
        try:
            self._conn.execute("BEGIN IMMEDIATE")
            clash = readings_repo.active_for_period(self._conn, account_id, period)
            if clash:
                raise DomainError(self._conflict_message(clash, source))
            new_id = readings_repo.insert(self._conn, account_id, period, kwh, peak, source, status)
            self._conn.commit()
        except DomainError:
            self._conn.rollback()
            raise
        except sqlite3.IntegrityError:
            # 并发下撞部分唯一索引兜底，仍返回可读信息
            self._conn.rollback()
            raise DomainError(f"户号 #{account_id} 账期 {period} 已存在有效抄表，请刷新后重试")
        except Exception:
            self._conn.rollback()
            raise
        return readings_repo.get(self._conn, new_id)

    @staticmethod
    def _conflict_message(clash: dict, new_source: str) -> str:
        where = f"户号 #{clash['account_id']} 账期 {clash['period']}"
        if clash["status"] == "estimated":
            if new_source == "estimate":
                return f"{where}已存在有效估计抄表（#{clash['id']}），请先对其结算"
            return f"{where}存在未结算估计抄表（#{clash['id']}），请通过结算接口录入实际电量"
        if new_source == "estimate":
            return f"{where}已存在正式抄表（#{clash['id']}），不能再录入估计"
        return f"{where}已存在正式抄表（#{clash['id']}）"

    def preview_reading(self, reading_id: int):
        """试算：只读，绝不写 calc_runs。"""
        reading = readings_repo.get(self._conn, reading_id)
        if not reading:
            raise NotFoundError(f"抄表记录 #{reading_id} 不存在")
        result = self._calc(reading["kwh"], bool(reading["peak"]))
        return {"reading": reading, "run_id": None, **result}

    def settle_estimate(self, estimate_id: int, actual_kwh: float, peak: bool | None = None):
        """结算：录入实际电量 → 生成差值记录 + 关闭估计有效态。

        单事务提交；任一步失败整体回滚，不会留下“估计仍有效而实际半写入”。
        """
        if actual_kwh < 0:
            raise DomainError("实际抄表电量不能为负数")
        try:
            self._conn.execute("BEGIN IMMEDIATE")
            est = readings_repo.get(self._conn, estimate_id)
            if not est:
                raise NotFoundError(f"估计抄表 #{estimate_id} 不存在")
            if est["source"] != "estimate":
                raise DomainError(f"抄表 #{estimate_id} 不是估计记录，不能结算")
            if est["status"] != "estimated":
                raise DomainError(f"估计抄表 #{estimate_id} 已结算，不能重复结算")
            clash = readings_repo.active_for_period(
                self._conn, est["account_id"], est["period"], exclude_id=estimate_id
            )
            if clash:
                raise DomainError(self._conflict_message(clash, "actual"))
            actual_peak = bool(est["peak"]) if peak is None else peak
            est_bill = self._calc(est["kwh"], bool(est["peak"]))
            act_bill = self._calc(actual_kwh, actual_peak)
            # 先关闭估计有效态再写实际抄表：同户同账期任一时刻只有一条有效记录
            # （唯一索引在语句级生效）；同事务内失败会整体回滚，估计恢复有效。
            readings_repo.update_status(self._conn, estimate_id, "settled")
            actual_id = readings_repo.insert(
                self._conn, est["account_id"], est["period"], actual_kwh, actual_peak, "actual", "confirmed"
            )
            settlement_id = settlements_repo.insert(
                self._conn,
                est["account_id"],
                est["period"],
                estimate_id,
                actual_id,
                est["kwh"],
                actual_kwh,
                est_bill["total"],
                act_bill["total"],
            )
            self._conn.commit()
        except (DomainError, NotFoundError):
            self._conn.rollback()
            raise
        except Exception:
            self._conn.rollback()
            raise
        return {
            "settlement": settlements_repo.get(self._conn, settlement_id),
            "estimate": readings_repo.get(self._conn, estimate_id),
            "actual": readings_repo.get(self._conn, actual_id),
        }

    # ---- 历史与统计 ----

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

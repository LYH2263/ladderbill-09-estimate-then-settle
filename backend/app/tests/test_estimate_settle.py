"""估计抄表与结算：冲突拒绝、只读试算、事务结算、差值记录。"""

import os
import sqlite3
import tempfile

os.environ.setdefault("DATA_DIR", tempfile.mkdtemp(prefix="ladderbill-test-"))

import pytest

from app import seed
from app.db import connect
from app.services.billing_service import BillingService
from app.services.errors import DomainError, NotFoundError

TIERS = [(180, 0.52, 1), (260, 0.62, 2), (None, 0.82, 3)]


@pytest.fixture()
def svc():
    seed.init_db()
    conn = connect()
    for t in ("settlements", "readings", "calc_runs", "accounts", "tiers", "settings"):
        conn.execute(f"DELETE FROM {t}")
    conn.execute("INSERT INTO accounts(id, name, meter_no) VALUES (1, '测试户', 'M-T1')")
    conn.executemany("INSERT INTO tiers(up_to, price, sort_order) VALUES (?,?,?)", TIERS)
    conn.execute("INSERT INTO settings(key, value) VALUES ('peak_factor', '1.2')")
    conn.commit()
    conn.close()
    with BillingService() as s:
        yield s


def _rows(sql, params=()):
    conn = connect()
    try:
        return [dict(r) for r in conn.execute(sql, params).fetchall()]
    finally:
        conn.close()


def test_create_estimate_then_preview_is_readonly(svc):
    est = svc.create_reading(1, "2026-09", 150, False, "estimate")
    assert est["status"] == "estimated"
    assert est["source"] == "estimate"
    before = _rows("SELECT COUNT(*) c FROM calc_runs")[0]["c"]
    out = svc.preview_reading(est["id"])
    assert out["run_id"] is None
    assert out["kwh"] == 150
    assert len(out["segments"]) == 1  # 150 全在一档
    after = _rows("SELECT COUNT(*) c FROM calc_runs")[0]["c"]
    assert after == before  # 试算只读，不写运行记录


def test_double_active_estimate_rejected(svc):
    svc.create_reading(1, "2026-09", 150, False, "estimate")
    with pytest.raises(DomainError, match="已存在有效估计抄表"):
        svc.create_reading(1, "2026-09", 160, False, "estimate")


def test_estimate_blocks_direct_confirmed(svc):
    svc.create_reading(1, "2026-09", 150, False, "estimate")
    with pytest.raises(DomainError, match="结算接口"):
        svc.create_reading(1, "2026-09", 150, False, "actual")


def test_confirmed_blocks_estimate(svc):
    svc.create_reading(1, "2026-09", 150, False, "actual")
    with pytest.raises(DomainError, match="已存在正式抄表"):
        svc.create_reading(1, "2026-09", 150, False, "estimate")


def test_different_periods_coexist(svc):
    svc.create_reading(1, "2026-09", 150, False, "estimate")
    other = svc.create_reading(1, "2026-10", 200, False, "estimate")
    assert other["status"] == "estimated"


def test_settle_closes_estimate_and_writes_diff(svc):
    est = svc.create_reading(1, "2026-09", 150, False, "estimate")
    out = svc.settle_estimate(est["id"], 180)
    st = out["settlement"]
    assert st["estimate_kwh"] == 150 and st["actual_kwh"] == 180
    assert st["delta_kwh"] == 30
    assert st["estimate_amount"] == 78.0 and st["actual_amount"] == 93.6
    assert st["delta_amount"] == 15.6
    assert out["estimate"]["status"] == "settled"  # 估计有效态已关闭
    assert out["actual"]["status"] == "confirmed"
    diffs = svc.settlements_for_account(1)
    assert len(diffs) == 1 and diffs[0]["id"] == st["id"]


def test_settle_twice_rejected_without_side_effect(svc):
    est = svc.create_reading(1, "2026-09", 150, False, "estimate")
    svc.settle_estimate(est["id"], 180)
    with pytest.raises(DomainError, match="不能重复结算"):
        svc.settle_estimate(est["id"], 200)
    assert _rows("SELECT COUNT(*) c FROM readings")[0]["c"] == 2
    assert _rows("SELECT COUNT(*) c FROM settlements")[0]["c"] == 1


def test_settle_failure_rolls_back_atomically(svc, monkeypatch):
    est = svc.create_reading(1, "2026-09", 150, False, "estimate")
    from app.repositories import settlements as settlements_repo

    def boom(*args, **kwargs):
        raise RuntimeError("disk full")

    monkeypatch.setattr(settlements_repo, "insert", boom)
    with pytest.raises(RuntimeError):
        svc.settle_estimate(est["id"], 180)
    # 估计仍有效、实际未半写入、无差值记录
    readings = _rows("SELECT * FROM readings")
    assert len(readings) == 1 and readings[0]["status"] == "estimated"
    assert _rows("SELECT COUNT(*) c FROM settlements")[0]["c"] == 0


def test_settle_negative_actual_rejected_before_write(svc):
    est = svc.create_reading(1, "2026-09", 150, False, "estimate")
    with pytest.raises(DomainError, match="不能为负数"):
        svc.settle_estimate(est["id"], -5)
    assert _rows("SELECT COUNT(*) c FROM readings")[0]["c"] == 1


def test_settle_missing_estimate_404(svc):
    with pytest.raises(NotFoundError):
        svc.settle_estimate(999, 100)


def test_settle_uses_estimate_peak_by_default(svc):
    est = svc.create_reading(1, "2026-09", 100, True, "estimate")
    out = svc.settle_estimate(est["id"], 120)
    assert out["actual"]["peak"] == 1
    # 尖峰系数 1.2：120 * 0.52 * 1.2 = 74.88
    assert out["settlement"]["actual_amount"] == 74.88


def test_formal_bill_after_settle_persists_run(svc):
    est = svc.create_reading(1, "2026-09", 150, False, "estimate")
    out = svc.settle_estimate(est["id"], 180)
    bill = svc.run_bill(out["actual"]["kwh"], False, 1, True)
    assert bill["run_id"] is not None
    assert bill["total"] == 93.6


def test_migration_adds_columns_to_old_table(tmp_path):
    from app.seed import _migrate_readings

    conn = sqlite3.connect(tmp_path / "old.db")
    conn.row_factory = sqlite3.Row
    conn.execute("CREATE TABLE readings(id INTEGER PRIMARY KEY, account_id INTEGER, kwh REAL, peak INTEGER)")
    conn.execute("INSERT INTO readings(account_id, kwh, peak) VALUES (1, 100, 0)")
    _migrate_readings(conn)
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(readings)")}
    assert {"period", "source", "status"} <= cols
    conn.close()

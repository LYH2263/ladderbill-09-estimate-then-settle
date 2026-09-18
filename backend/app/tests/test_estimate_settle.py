import pytest

from app import seed
from app.errors import ApiError, ConflictError, NotFoundError
from app.repositories import readings as readings_repo
from app.repositories import settlements as settlements_repo
from app.services.billing_service import BillingService


@pytest.fixture()
def svc(tmp_path, monkeypatch):
    """临时 SQLite，不触碰开发库。"""
    import app.db as db

    db_path = tmp_path / "test.db"
    monkeypatch.setattr(db, "DB_PATH", db_path)
    seed.init_db()
    with BillingService() as service:
        yield service


def _create(svc, kind="estimate", period="2026-09", kwh=200, peak=False, account_id=1):
    return svc.create_reading(account_id, period, kind, kwh, peak)


# ---- estimate 写入与冲突拒绝 ----

def test_create_estimate_ok(svc):
    r = _create(svc)
    assert r["kind"] == "estimate"
    assert r["status"] == "active"
    assert r["period"] == "2026-09"


def test_estimate_and_confirmed_cannot_both_be_active(svc):
    _create(svc, kind="estimate")
    with pytest.raises(ConflictError) as ei:
        _create(svc, kind="confirmed")
    assert ei.value.status_code == 409
    assert "估计" in ei.value.message
    assert ei.value.extra["conflict_kind"] == "estimate"
    # 被拒绝后该账期仍只有一条有效
    rows = readings_repo.for_account(svc._conn, 1)
    active_09 = [r for r in rows if r["period"] == "2026-09" and r["status"] == "active"]
    assert len(active_09) == 1
    assert active_09[0]["kind"] == "estimate"


def test_confirmed_then_estimate_also_rejected(svc):
    _create(svc, kind="confirmed")
    with pytest.raises(ConflictError):
        _create(svc, kind="estimate")


def test_two_estimates_same_period_rejected(svc):
    _create(svc, kind="estimate", kwh=200)
    with pytest.raises(ConflictError):
        _create(svc, kind="estimate", kwh=210)


def test_unknown_account_rejected(svc):
    with pytest.raises(NotFoundError):
        svc.create_reading(999, "2026-09", "estimate", 100, False)


# ---- 只读试算 ----

def test_trial_returns_segments_without_writing(svc):
    r = _create(svc, kwh=400)
    runs_before = svc._conn.execute("SELECT COUNT(*) c FROM calc_runs").fetchone()["c"]
    out = svc.trial_reading(r["id"])
    assert out["calc"]["total"] > 0
    assert len(out["calc"]["segments"]) == 3
    runs_after = svc._conn.execute("SELECT COUNT(*) c FROM calc_runs").fetchone()["c"]
    assert runs_after == runs_before  # 试算不写运行记录
    again = readings_repo.get(svc._conn, r["id"])
    assert again["status"] == "active"  # 状态不变


def test_trial_missing_reading(svc):
    with pytest.raises(NotFoundError):
        svc.trial_reading(4242)


# ---- 结算链路 ----

def test_settle_closes_estimate_and_records_delta(svc):
    est = _create(svc, kwh=200)
    out = svc.settle_reading(est["id"], actual_kwh=240, peak=None)

    closed = readings_repo.get(svc._conn, est["id"])
    assert closed["status"] == "closed"
    assert closed["settled_by_reading_id"] == out["actual_reading"]["id"]

    actual = out["actual_reading"]
    assert actual["kind"] == "actual"
    assert actual["status"] == "active"
    assert actual["kwh"] == 240

    settlement = out["settlement"]
    assert settlement["delta_kwh"] == 40
    assert settlement["delta_amount"] == round(
        out["actual_calc"]["total"] - out["estimate_calc"]["total"], 2
    )

    # 同户同账期仍只有一条有效（实抄）
    active = readings_repo.find_active(svc._conn, 1, "2026-09")
    assert active["id"] == actual["id"]

    # 户详情可查差值记录
    assert any(s["id"] == settlement["id"] for s in svc.settlements_for_account(1))


def test_settled_estimate_cannot_settle_again(svc):
    est = _create(svc, kwh=200)
    svc.settle_reading(est["id"], 240, None)
    with pytest.raises(ConflictError):
        svc.settle_reading(est["id"], 250, None)


def test_settle_confirmed_reading_rejected(svc):
    r = _create(svc, kind="confirmed")
    with pytest.raises(ApiError):
        svc.settle_reading(r["id"], 240, None)


def test_formal_calc_after_settle(svc):
    est = _create(svc, kwh=200)
    out = svc.settle_reading(est["id"], actual_kwh=400, peak=True)
    # 对实抄正式测算（入库一条 calc_run）
    formal = svc.run_bill(
        out["actual_reading"]["kwh"], bool(out["actual_reading"]["peak"]), 1, persist=True
    )
    assert formal["run_id"] is not None
    assert formal["total"] == out["actual_calc"]["total"]


# ---- 原子性：结算失败不留半写入 ----

def test_settle_failure_rolls_back(svc, monkeypatch):
    est = _create(svc, kwh=200)

    def boom(*a, **k):
        raise RuntimeError("settlements insert failed")

    monkeypatch.setattr(settlements_repo, "insert", boom)

    with pytest.raises(RuntimeError):
        svc.settle_reading(est["id"], 240, None)

    # 估计仍有效
    still = readings_repo.get(svc._conn, est["id"])
    assert still["status"] == "active"
    assert still["settled_by_reading_id"] is None
    # 没有半写入的实抄与差值
    rows = readings_repo.for_account(svc._conn, 1)
    assert all(r["kind"] != "actual" for r in rows)
    assert svc.settlements_for_account(1) == []
    # 有效态唯一：find_active 仍指向估计
    assert readings_repo.find_active(svc._conn, 1, "2026-09")["id"] == est["id"]

    # 回滚后可正常结算（证明连接/事务仍可用）
    monkeypatch.undo()
    ok = svc.settle_reading(est["id"], 240, None)
    assert ok["actual_reading"]["status"] == "active"


def test_settle_failure_after_partial_write_rolls_back(svc, monkeypatch):
    est = _create(svc, kwh=200)

    # 中途已经写入一行 settlement 后再失败：验证部分写入也整体回滚
    def insert_then_boom(conn, *args, **kwargs):
        conn.execute(
            "INSERT INTO settlements(account_id, period) VALUES (?,?)",
            (1, "2026-09"),
        )
        raise RuntimeError("failed after partial write")

    monkeypatch.setattr(settlements_repo, "insert", insert_then_boom)

    with pytest.raises(RuntimeError):
        svc.settle_reading(est["id"], 240, None)

    still = readings_repo.get(svc._conn, est["id"])
    assert still["status"] == "active"
    assert svc.settlements_for_account(1) == []
    assert all(r["kind"] != "actual" for r in readings_repo.for_account(svc._conn, 1))
    assert readings_repo.find_active(svc._conn, 1, "2026-09")["id"] == est["id"]

import sqlite3
from datetime import datetime, timezone


def insert(
    conn: sqlite3.Connection,
    account_id: int,
    period: str,
    estimate_reading_id: int,
    actual_reading_id: int,
    estimate_kwh: float,
    actual_kwh: float,
    estimate_amount: float,
    actual_amount: float,
) -> int:
    """生成差值记录；不写 commit，事务边界由 service 层控制。"""
    now = datetime.now(timezone.utc).isoformat()
    cur = conn.execute(
        """
        INSERT INTO settlements(
            account_id, period, estimate_reading_id, actual_reading_id,
            estimate_kwh, actual_kwh, delta_kwh,
            estimate_amount, actual_amount, delta_amount, created_at
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            account_id,
            period,
            estimate_reading_id,
            actual_reading_id,
            float(estimate_kwh),
            float(actual_kwh),
            round(float(actual_kwh) - float(estimate_kwh), 3),
            float(estimate_amount),
            float(actual_amount),
            round(float(actual_amount) - float(estimate_amount), 2),
            now,
        ),
    )
    return int(cur.lastrowid)


def for_account(conn: sqlite3.Connection, account_id: int) -> list[dict]:
    q = "SELECT * FROM settlements WHERE account_id=? ORDER BY id DESC"
    return [dict(r) for r in conn.execute(q, (account_id,)).fetchall()]


def get(conn: sqlite3.Connection, settlement_id: int) -> dict | None:
    row = conn.execute("SELECT * FROM settlements WHERE id=?", (settlement_id,)).fetchone()
    return dict(row) if row else None

import sqlite3
from datetime import datetime, timezone

_COLS = (
    "id, account_id, period, estimate_reading_id, actual_reading_id,"
    " estimate_kwh, actual_kwh, delta_kwh,"
    " estimate_amount, actual_amount, delta_amount, created_at"
)


def insert(
    conn: sqlite3.Connection,
    account_id: int,
    period: str,
    estimate_reading_id: int,
    actual_reading_id: int,
    estimate_kwh: float,
    actual_kwh: float,
    delta_kwh: float,
    estimate_amount: float,
    actual_amount: float,
    delta_amount: float,
) -> int:
    now = datetime.now(timezone.utc).isoformat()
    cur = conn.execute(
        """
        INSERT INTO settlements(
            account_id, period, estimate_reading_id, actual_reading_id,
            estimate_kwh, actual_kwh, delta_kwh,
            estimate_amount, actual_amount, delta_amount, created_at)
        VALUES (?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            account_id,
            period,
            estimate_reading_id,
            actual_reading_id,
            estimate_kwh,
            actual_kwh,
            delta_kwh,
            estimate_amount,
            actual_amount,
            delta_amount,
            now,
        ),
    )
    return int(cur.lastrowid)


def for_account(conn: sqlite3.Connection, account_id: int) -> list[dict]:
    q = f"SELECT {_COLS} FROM settlements WHERE account_id=? ORDER BY period DESC, id"
    return [dict(r) for r in conn.execute(q, (account_id,)).fetchall()]


def get(conn: sqlite3.Connection, settlement_id: int) -> dict | None:
    row = conn.execute(f"SELECT {_COLS} FROM settlements WHERE id=?", (settlement_id,)).fetchone()
    return dict(row) if row else None

import sqlite3
from datetime import datetime, timezone

_READING_COLS = (
    "id, account_id, period, kind, status, kwh, peak, settled_by_reading_id, created_at"
)


def _row(conn: sqlite3.Connection, reading_id: int) -> dict | None:
    row = conn.execute(
        f"SELECT {_READING_COLS} FROM readings WHERE id=?", (reading_id,)
    ).fetchone()
    return dict(row) if row else None


def list_all(conn: sqlite3.Connection) -> list[dict]:
    return [
        dict(r)
        for r in conn.execute(f"SELECT {_READING_COLS} FROM readings ORDER BY id").fetchall()
    ]


def for_account(conn: sqlite3.Connection, account_id: int) -> list[dict]:
    q = f"SELECT {_READING_COLS} FROM readings WHERE account_id=? ORDER BY period DESC, id"
    return [dict(r) for r in conn.execute(q, (account_id,)).fetchall()]


def get(conn: sqlite3.Connection, reading_id: int) -> dict | None:
    return _row(conn, reading_id)


def find_active(conn: sqlite3.Connection, account_id: int, period: str) -> dict | None:
    """同户同账期当前有效抄表（估计或正式至多一条）。"""
    row = conn.execute(
        f"SELECT {_READING_COLS} FROM readings"
        " WHERE account_id=? AND period=? AND status='active'",
        (account_id, period),
    ).fetchone()
    return dict(row) if row else None


def insert(
    conn: sqlite3.Connection,
    account_id: int,
    period: str,
    kind: str,
    kwh: float,
    peak: bool,
    status: str = "active",
) -> int:
    now = datetime.now(timezone.utc).isoformat()
    cur = conn.execute(
        """
        INSERT INTO readings(account_id, period, kind, status, kwh, peak, created_at)
        VALUES (?,?,?,?,?,?,?)
        """,
        (account_id, period, kind, status, kwh, 1 if peak else 0, now),
    )
    return int(cur.lastrowid)


def mark_closed(conn: sqlite3.Connection, reading_id: int, settled_by_reading_id: int) -> None:
    conn.execute(
        "UPDATE readings SET status='closed', settled_by_reading_id=? WHERE id=?",
        (settled_by_reading_id, reading_id),
    )

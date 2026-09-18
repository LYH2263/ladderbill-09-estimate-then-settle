import sqlite3

# 有效态：同一户同一账期最多各一条（估计有效 / 正式有效）
ACTIVE_STATUSES = ("estimated", "confirmed")

# 老数据行没有 period/source/status，读取时按“正式抄表”兜底展示
SELECT_COLS = """
    id, account_id, period, kwh, peak,
    COALESCE(source, 'actual') AS source,
    COALESCE(status, 'confirmed') AS status
"""


def _row(r: sqlite3.Row) -> dict:
    d = dict(r)
    d["peak"] = int(d.get("peak") or 0)
    return d


def list_all(conn: sqlite3.Connection) -> list[dict]:
    q = f"SELECT {SELECT_COLS} FROM readings ORDER BY id"
    return [_row(r) for r in conn.execute(q).fetchall()]


def for_account(conn: sqlite3.Connection, account_id: int) -> list[dict]:
    q = f"SELECT {SELECT_COLS} FROM readings WHERE account_id=? ORDER BY id"
    return [_row(r) for r in conn.execute(q, (account_id,)).fetchall()]


def get(conn: sqlite3.Connection, reading_id: int) -> dict | None:
    q = f"SELECT {SELECT_COLS} FROM readings WHERE id=?"
    row = conn.execute(q, (reading_id,)).fetchone()
    return _row(row) if row else None


def active_for_period(
    conn: sqlite3.Connection, account_id: int, period: str, exclude_id: int | None = None
) -> dict | None:
    """查同户同账期的有效记录（estimated/confirmed），用于双有效冲突判定。"""
    q = f"SELECT {SELECT_COLS} FROM readings WHERE account_id=? AND period=? AND status IN ('estimated','confirmed')"
    params: list = [account_id, period]
    if exclude_id is not None:
        q += " AND id<>?"
        params.append(exclude_id)
    row = conn.execute(q, params).fetchone()
    return _row(row) if row else None


def insert(
    conn: sqlite3.Connection,
    account_id: int,
    period: str,
    kwh: float,
    peak: bool,
    source: str,
    status: str,
) -> int:
    """不写 commit：事务边界由 service 层控制。"""
    cur = conn.execute(
        "INSERT INTO readings(account_id, period, kwh, peak, source, status) VALUES (?,?,?,?,?,?)",
        (account_id, period, float(kwh), 1 if peak else 0, source, status),
    )
    return int(cur.lastrowid)


def update_status(conn: sqlite3.Connection, reading_id: int, status: str) -> None:
    conn.execute("UPDATE readings SET status=? WHERE id=?", (status, reading_id))

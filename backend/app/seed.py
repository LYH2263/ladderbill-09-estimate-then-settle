import json

from app.db import connect
from app.engines.peak_compare import compare_plain_vs_peak
from app.engines.tier_progressive import calc_bill


def _has_column(conn, table: str, column: str) -> bool:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return any(r["name"] == column for r in rows)


def init_db():
    conn = connect()
    conn.executescript(
        """
    CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT);
    CREATE TABLE IF NOT EXISTS accounts(
        id INTEGER PRIMARY KEY, name TEXT, meter_no TEXT, note TEXT);
    CREATE TABLE IF NOT EXISTS tiers(id INTEGER PRIMARY KEY, up_to REAL, price REAL, sort_order INTEGER);
    CREATE TABLE IF NOT EXISTS calc_runs(
        id INTEGER PRIMARY KEY,
        kind TEXT,
        account_id INTEGER,
        input_json TEXT,
        result_json TEXT,
        created_at TEXT
    );
    """
    )

    # readings: kind = estimate(估计) / confirmed(正式) / actual(结算实抄)
    # status = active(有效) / closed(已关闭，例如估计已被结算)
    conn.executescript(
        """
    CREATE TABLE IF NOT EXISTS readings(
        id INTEGER PRIMARY KEY,
        account_id INTEGER,
        period TEXT NOT NULL DEFAULT '',
        kind TEXT NOT NULL DEFAULT 'confirmed',
        status TEXT NOT NULL DEFAULT 'active',
        kwh REAL,
        peak INTEGER,
        settled_by_reading_id INTEGER,
        created_at TEXT
    );
    CREATE TABLE IF NOT EXISTS settlements(
        id INTEGER PRIMARY KEY,
        account_id INTEGER,
        period TEXT,
        estimate_reading_id INTEGER,
        actual_reading_id INTEGER,
        estimate_kwh REAL,
        actual_kwh REAL,
        delta_kwh REAL,
        estimate_amount REAL,
        actual_amount REAL,
        delta_amount REAL,
        created_at TEXT
    );
    """
    )

    # 迁移旧库（早期 readings 只有 account_id/kwh/peak）
    migrated = False
    for column, ddl in [
        ("period", "ALTER TABLE readings ADD COLUMN period TEXT NOT NULL DEFAULT ''"),
        ("kind", "ALTER TABLE readings ADD COLUMN kind TEXT NOT NULL DEFAULT 'confirmed'"),
        ("status", "ALTER TABLE readings ADD COLUMN status TEXT NOT NULL DEFAULT 'active'"),
        ("settled_by_reading_id", "ALTER TABLE readings ADD COLUMN settled_by_reading_id INTEGER"),
        ("created_at", "ALTER TABLE readings ADD COLUMN created_at TEXT"),
    ]:
        if not _has_column(conn, "readings", column):
            conn.execute(ddl)
            migrated = True
    if migrated:
        conn.execute(
            "UPDATE readings SET created_at=datetime('now') WHERE created_at IS NULL OR created_at=''"
        )
        # 旧数据没有账期：按记录 id 补唯一账期，避免同户多条空账期撞唯一索引
        conn.execute(
            "UPDATE readings SET period = 'legacy-' || id WHERE period IS NULL OR period=''"
        )
        conn.commit()

    # 同一户同一账期至多一条“有效”抄表：估计与正式不得双有效
    conn.executescript(
        """
    CREATE UNIQUE INDEX IF NOT EXISTS idx_readings_one_active
        ON readings(account_id, period) WHERE status='active';
    CREATE INDEX IF NOT EXISTS idx_readings_account ON readings(account_id, id);
    CREATE INDEX IF NOT EXISTS idx_settlements_account ON settlements(account_id, id);
    """
    )

    if conn.execute("SELECT COUNT(*) c FROM accounts").fetchone()["c"] == 0:
        conn.execute(
            "INSERT INTO accounts(name, meter_no, note) VALUES ('张家', 'M-1001', '对照：正常用量')"
        )
        conn.execute(
            "INSERT INTO accounts(name, meter_no, note) VALUES ('李家(种子偏高)', 'M-1002', '对照：高用量+尖峰')"
        )
        conn.executemany(
            "INSERT INTO tiers(up_to, price, sort_order) VALUES (?,?,?)",
            [(180, 0.52, 1), (260, 0.62, 2), (None, 0.82, 3)],
        )
        conn.execute(
            "INSERT INTO readings(account_id, period, kind, status, kwh, peak, created_at)"
            " VALUES (1, '2026-08', 'confirmed', 'active', 120, 0, datetime('now'))"
        )
        conn.execute(
            "INSERT INTO readings(account_id, period, kind, status, kwh, peak, created_at)"
            " VALUES (2, '2026-08', 'confirmed', 'active', 400, 1, datetime('now'))"
        )
        conn.execute("INSERT INTO settings(key, value) VALUES ('peak_factor', '1.2')")
        conn.execute("INSERT INTO settings(key, value) VALUES ('currency', 'CNY')")
        tiers = [{"up_to": r[0], "price": r[1]} for r in [(180, 0.52), (260, 0.62), (None, 0.82)]]
        bill1 = calc_bill(120, tiers, 1.0)
        conn.execute(
            "INSERT INTO calc_runs(kind, account_id, input_json, result_json, created_at) VALUES (?,?,?,?,datetime('now'))",
            ("bill", 1, json.dumps({"kwh": 120, "peak": False}), json.dumps(bill1, ensure_ascii=False)),
        )
        cmp2 = compare_plain_vs_peak(400, tiers, 1.2)
        conn.execute(
            "INSERT INTO calc_runs(kind, account_id, input_json, result_json, created_at) VALUES (?,?,?,?,datetime('now'))",
            ("compare", 2, json.dumps({"kwh": 400}), json.dumps(cmp2, ensure_ascii=False)),
        )
        conn.commit()
    conn.close()

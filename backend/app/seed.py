import json
import sqlite3

from app.db import connect
from app.engines.peak_compare import compare_plain_vs_peak
from app.engines.tier_progressive import calc_bill

# readings.status 取值：estimated（估计有效）/ confirmed（正式有效）/ settled（估计已结算关闭）
# 同一户同一账期只允许一条“有效”记录（estimated 或 confirmed），由部分唯一索引兜底。
READING_EXTRA_COLUMNS = {
    "period": "TEXT",
    "source": "TEXT",
    "status": "TEXT",
}

SCHEMA = """
CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS accounts(
    id INTEGER PRIMARY KEY, name TEXT, meter_no TEXT, note TEXT);
CREATE TABLE IF NOT EXISTS readings(
    id INTEGER PRIMARY KEY,
    account_id INTEGER,
    period TEXT,
    kwh REAL,
    peak INTEGER,
    source TEXT,
    status TEXT
);
CREATE TABLE IF NOT EXISTS tiers(id INTEGER PRIMARY KEY, up_to REAL, price REAL, sort_order INTEGER);
CREATE TABLE IF NOT EXISTS calc_runs(
    id INTEGER PRIMARY KEY,
    kind TEXT,
    account_id INTEGER,
    input_json TEXT,
    result_json TEXT,
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

# 索引引用 readings.status，须在 _migrate_readings 补列之后创建
SCHEMA_INDEXES = """
CREATE UNIQUE INDEX IF NOT EXISTS ux_readings_active_period
    ON readings(account_id, period)
    WHERE status IN ('estimated', 'confirmed') AND period IS NOT NULL;
"""


def _migrate_readings(conn: sqlite3.Connection):
    """老库缺列时补齐（ALTER TABLE 不能加 NOT NULL 列，故统一可空，读取端 COALESCE）。"""
    existing = {r["name"] for r in conn.execute("PRAGMA table_info(readings)").fetchall()}
    for col, ddl in READING_EXTRA_COLUMNS.items():
        if col not in existing:
            conn.execute(f"ALTER TABLE readings ADD COLUMN {col} {ddl}")


def init_db():
    conn = connect()
    conn.executescript(SCHEMA)
    _migrate_readings(conn)
    conn.executescript(SCHEMA_INDEXES)
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
            "INSERT INTO readings(account_id, period, kwh, peak, source, status) VALUES (1, '2026-08', 120, 0, 'actual', 'confirmed')"
        )
        conn.execute(
            "INSERT INTO readings(account_id, period, kwh, peak, source, status) VALUES (2, '2026-08', 400, 1, 'actual', 'confirmed')"
        )
        # 一条有效估计，演示估计→试算→结算链路
        conn.execute(
            "INSERT INTO readings(account_id, period, kwh, peak, source, status) VALUES (1, '2026-09', 150, 0, 'estimate', 'estimated')"
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

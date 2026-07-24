"""SQLite database setup and migrations for the health diet app."""

import os
import secrets
import sqlite3
import string


DB_PATH = os.environ.get(
    "HEALTH_DB_PATH",
    os.path.join(os.path.dirname(__file__), "health.db"),
)


def get_db():
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 10000")
    return conn


def _columns(conn, table):
    return {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}


def _add_missing_columns(conn, table, columns):
    existing = _columns(conn, table)
    for name, definition in columns:
        if name not in existing:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")


def _new_bind_code(conn, column):
    alphabet = string.ascii_uppercase + string.digits
    while True:
        code = "".join(secrets.choice(alphabet) for _ in range(8))
        if conn.execute(f"SELECT 1 FROM users WHERE {column}=?", (code,)).fetchone() is None:
            return code


def _migrate_legacy_schema(conn):
    """Bring databases created by earlier prototypes up to the current schema."""
    _add_missing_columns(conn, "users", [
        ("email", "TEXT"),
        ("avatar_url", "TEXT DEFAULT ''"),
        ("height", "REAL"),
        ("weight", "REAL"),
        ("age", "INTEGER"),
        ("gender", "TEXT"),
        ("health_goal", "TEXT DEFAULT 'weight_management'"),
        ("supervisor_code", "TEXT"),
        ("supervisee_code", "TEXT"),
        ("bound_to", "INTEGER REFERENCES users(id)"),
        # SQLite cannot add CURRENT_TIMESTAMP as a default to a populated table.
        ("created_at", "TIMESTAMP"),
    ])
    _add_missing_columns(conn, "verify_codes", [("email", "TEXT")])
    _add_missing_columns(conn, "food_library", [
        ("sodium_mg", "REAL DEFAULT 0"),
        ("potassium_mg", "REAL DEFAULT 0"),
        ("calcium_mg", "REAL DEFAULT 0"),
        ("magnesium_mg", "REAL DEFAULT 0"),
        ("iron_mg", "REAL DEFAULT 0"),
    ])

    user_columns = _columns(conn, "users")
    if "bind_code" in user_columns:
        conn.execute(
            "UPDATE users SET supervisor_code=bind_code "
            "WHERE supervisor_code IS NULL AND bind_code IS NOT NULL"
        )

    rows = conn.execute(
        "SELECT id, supervisor_code, supervisee_code FROM users"
    ).fetchall()
    for row in rows:
        supervisor_code = row["supervisor_code"] or _new_bind_code(conn, "supervisor_code")
        supervisee_code = row["supervisee_code"] or _new_bind_code(conn, "supervisee_code")
        conn.execute(
            "UPDATE users SET supervisor_code=?, supervisee_code=?, "
            "health_goal=COALESCE(health_goal, 'weight_management'), "
            "created_at=COALESCE(created_at, CURRENT_TIMESTAMP) WHERE id=?",
            (supervisor_code, supervisee_code, row["id"]),
        )


def init_db():
    conn = get_db()
    try:
        # Tables are created first. Migrations then add columns missing from old
        # databases before indexes reference those columns.
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                phone TEXT UNIQUE NOT NULL,
                email TEXT UNIQUE,
                password_hash TEXT NOT NULL,
                role TEXT NOT NULL CHECK(role IN ('supervisor', 'supervisee')),
                nickname TEXT NOT NULL,
                avatar_url TEXT DEFAULT '',
                height REAL,
                weight REAL,
                age INTEGER,
                gender TEXT CHECK(gender IN ('male', 'female')),
                health_goal TEXT DEFAULT 'weight_management'
                    CHECK(health_goal IN ('weight_management', 'blood_sugar', 'blood_pressure')),
                supervisor_code TEXT UNIQUE NOT NULL,
                supervisee_code TEXT UNIQUE NOT NULL,
                bound_to INTEGER REFERENCES users(id),
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS verify_codes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                phone TEXT,
                email TEXT,
                code TEXT NOT NULL,
                used INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS food_library (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                calories_per_100g REAL NOT NULL,
                category TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS diet_records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL REFERENCES users(id),
                food_name TEXT NOT NULL,
                weight_grams REAL NOT NULL CHECK(weight_grams > 0 AND weight_grams <= 5000),
                calories REAL NOT NULL CHECK(calories >= 0),
                intake_time TIMESTAMP NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)

        _migrate_legacy_schema(conn)
        conn.executescript("""
            CREATE INDEX IF NOT EXISTS idx_diet_user ON diet_records(user_id);
            CREATE INDEX IF NOT EXISTS idx_diet_time ON diet_records(intake_time);
            CREATE INDEX IF NOT EXISTS idx_verify_phone ON verify_codes(phone);
            CREATE INDEX IF NOT EXISTS idx_verify_email ON verify_codes(email);
            CREATE INDEX IF NOT EXISTS idx_verify_created ON verify_codes(created_at);
            CREATE INDEX IF NOT EXISTS idx_users_phone ON users(phone);
            CREATE UNIQUE INDEX IF NOT EXISTS idx_users_email ON users(email);
            CREATE INDEX IF NOT EXISTS idx_users_bound ON users(bound_to);
            CREATE UNIQUE INDEX IF NOT EXISTS idx_users_supervisor_code ON users(supervisor_code);
            CREATE UNIQUE INDEX IF NOT EXISTS idx_users_supervisee_code ON users(supervisee_code);
        """)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

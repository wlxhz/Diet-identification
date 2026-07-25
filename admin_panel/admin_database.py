import os
import sqlite3


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ADMIN_DB_PATH = os.environ.get("ADMIN_DB_PATH", os.path.join(BASE_DIR, "admin.db"))
USER_DB_PATH = os.environ.get(
    "USER_APP_DB_PATH",
    os.path.abspath(os.path.join(BASE_DIR, "..", "v2", "health.db")),
)


def connect(path):
    connection = sqlite3.connect(path, timeout=10)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA busy_timeout = 10000")
    return connection


def admin_db():
    return connect(ADMIN_DB_PATH)


def user_db():
    if not os.path.isfile(USER_DB_PATH):
        raise FileNotFoundError(f"找不到用户端数据库：{USER_DB_PATH}")
    return connect(USER_DB_PATH)


def init_admin_db():
    connection = admin_db()
    try:
        connection.executescript("""
            CREATE TABLE IF NOT EXISTS admins (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                display_name TEXT NOT NULL,
                role TEXT NOT NULL DEFAULT 'super_admin',
                active INTEGER NOT NULL DEFAULT 1,
                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                last_login_at TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS audit_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                admin_id INTEGER REFERENCES admins(id),
                admin_name TEXT NOT NULL,
                action TEXT NOT NULL,
                target_type TEXT NOT NULL,
                target_id TEXT,
                detail TEXT,
                ip_address TEXT,
                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS login_attempts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL,
                success INTEGER NOT NULL DEFAULT 0,
                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE INDEX IF NOT EXISTS idx_audit_created ON audit_logs(created_at);
            CREATE INDEX IF NOT EXISTS idx_login_username_time ON login_attempts(username, created_at);
        """)
        connection.commit()
    finally:
        connection.close()

"""SQLite schema and connection."""
import sqlite3
from contextlib import closing

SCHEMA = """
CREATE TABLE IF NOT EXISTS settings (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS users (
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL,
  username TEXT NOT NULL UNIQUE,
  email TEXT NOT NULL UNIQUE,
  salt TEXT NOT NULL,
  password_hash TEXT NOT NULL,
  iterations INTEGER NOT NULL,
  role TEXT NOT NULL DEFAULT 'member' CHECK (role IN ('admin', 'member')),
  status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('pending', 'active')),
  created_at REAL NOT NULL
);
-- The database itself guarantees there is never a second admin.
CREATE UNIQUE INDEX IF NOT EXISTS one_admin ON users (role) WHERE role = 'admin';
CREATE TABLE IF NOT EXISTS sessions (
  token_hash TEXT PRIMARY KEY,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  expires_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS reset_tokens (
  token_hash TEXT PRIMARY KEY,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  expires_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS rate_events (
  key TEXT NOT NULL,
  at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS rate_events_key ON rate_events (key, at);
CREATE TABLE IF NOT EXISTS months (
  id INTEGER PRIMARY KEY,
  ym TEXT NOT NULL UNIQUE
);
CREATE TABLE IF NOT EXISTS sides (
  id INTEGER PRIMARY KEY,
  month_id INTEGER NOT NULL REFERENCES months(id) ON DELETE CASCADE,
  name TEXT NOT NULL,
  bills_charged INTEGER NOT NULL DEFAULT 1,
  addon REAL NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS members (
  id INTEGER PRIMARY KEY,
  month_id INTEGER NOT NULL REFERENCES months(id) ON DELETE CASCADE,
  side_id INTEGER NOT NULL REFERENCES sides(id),
  user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
  name TEXT NOT NULL,
  rent REAL NOT NULL DEFAULT 0,
  UNIQUE (month_id, user_id)
);
CREATE TABLE IF NOT EXISTS meals (
  member_id INTEGER NOT NULL REFERENCES members(id) ON DELETE CASCADE,
  day INTEGER NOT NULL,
  qty REAL NOT NULL,
  PRIMARY KEY (member_id, day)
);
CREATE TABLE IF NOT EXISTS bazar (
  id INTEGER PRIMARY KEY,
  member_id INTEGER NOT NULL REFERENCES members(id) ON DELETE CASCADE,
  date TEXT NOT NULL,
  item TEXT NOT NULL,
  amount REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS bills (
  id INTEGER PRIMARY KEY,
  month_id INTEGER NOT NULL REFERENCES months(id) ON DELETE CASCADE,
  side_id INTEGER REFERENCES sides(id) ON DELETE CASCADE,
  owner_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
  name TEXT NOT NULL,
  amount REAL NOT NULL,
  breakdown TEXT NOT NULL DEFAULT '',
  round_up INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS payments (
  id INTEGER PRIMARY KEY,
  member_id INTEGER NOT NULL REFERENCES members(id) ON DELETE CASCADE,
  date TEXT,
  amount REAL NOT NULL,
  note TEXT NOT NULL DEFAULT ''
);
"""


def connect(path):
    db = sqlite3.connect(path, timeout=10)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")
    return db


def init_db(path):
    with closing(connect(path)) as db:
        columns = [r["name"] for r in db.execute("PRAGMA table_info(users)")]
        if columns and "status" not in columns:     # databases made before approval existed
            db.execute("ALTER TABLE users ADD COLUMN status TEXT NOT NULL DEFAULT 'active'"
                       " CHECK (status IN ('pending', 'active'))")
        db.executescript(SCHEMA)
        # Plain journal: hosted disks can be network filesystems, where WAL is
        # unsafe, and it keeps everything in one file for backups.
        db.execute("PRAGMA journal_mode = DELETE")
        db.commit()

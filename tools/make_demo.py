#!/usr/bin/env python3
"""Builds demo.db for trying the app locally, with sample accounts.

    python3 tools/make_demo.py OLD_MESS_DB

Sign-in details are written to DEMO_ACCOUNTS.md. Never deploy demo.db.
"""
import sys
import time
from contextlib import closing
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
import auth
import db as database
from import_v1 import import_v1

PASSWORD = "blueblood-demo"
ACCOUNTS = [("Rifat", "rifat", "admin"), ("Shuvo", "shuvo", "member"), ("Sakib", "sakib", "member")]


def main():
    target = ROOT / "demo.db"
    target.unlink(missing_ok=True)
    import_v1(sys.argv[1], target)
    with closing(database.connect(target)) as db:
        for name, username, role in ACCOUNTS:
            salt, hashed, iterations = auth.hash_password(PASSWORD)
            user_id = db.execute(
                "INSERT INTO users (name, username, email, salt, password_hash, iterations, role, status, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, 'active', ?)",
                (name, username, f"{username}@blueblood.test", salt, hashed, iterations, role, time.time())).lastrowid
            db.execute("UPDATE members SET user_id = ? WHERE name = ?", (user_id, name))
        db.commit()
    lines = ["# Demo accounts (local test build only)", "",
             f"Password for all of them: `{PASSWORD}`", "",
             "| Name | Username | Email | Role |", "|---|---|---|---|"]
    lines += [f"| {n} | `{u}` | `{u}@blueblood.test` | {r} |" for n, u, r in ACCOUNTS]
    (ROOT / "DEMO_ACCOUNTS.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("demo.db ready. Sign-in details are in DEMO_ACCOUNTS.md")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    main()

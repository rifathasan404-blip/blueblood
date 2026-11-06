#!/usr/bin/env python3
"""Copies months from the first Mess Hisab database into a BlueBlood database.

    python3 tools/import_v1.py OLD_MESS_DB NEW_DB

Dwellers arrive without accounts. The admin links each person to their name
when approving them. The old database is only read, never changed.
"""
import sqlite3
import sys
from contextlib import closing
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import db as database


def import_v1(old_path, new_path):
    database.init_db(new_path)
    with closing(sqlite3.connect(f"file:{old_path}?mode=ro", uri=True)) as old, \
            closing(database.connect(new_path)) as new:
        old.row_factory = sqlite3.Row
        if new.execute("SELECT 1 FROM months").fetchone():
            raise SystemExit("The new database already has months in it. Nothing was changed.")
        copies = [
            ("months", "SELECT id, ym FROM months"),
            ("sides", "SELECT id, month_id, name, bills_charged, addon FROM groups"),
            ("members", "SELECT id, month_id, group_id, name, rent FROM members"),
            ("meals", "SELECT member_id, day, qty FROM meals"),
            ("bazar", "SELECT id, member_id, date, item, amount FROM bazar"),
            ("bills", "SELECT id, month_id, group_id, name, amount, breakdown, round_up FROM bills"),
            ("payments", "SELECT id, member_id, date, amount, note FROM payments"),
        ]
        names = {"members": "id, month_id, side_id, name, rent",
                 "bills": "id, month_id, side_id, name, amount, breakdown, round_up"}
        for table, query in copies:
            rows = [tuple(r) for r in old.execute(query)]
            if rows:
                columns = names.get(table) or query.split(" FROM ")[0].removeprefix("SELECT ")
                marks = ", ".join("?" * len(rows[0]))
                new.executemany(f"INSERT INTO {table} ({columns}) VALUES ({marks})", rows)
            print(f"{table}: {len(rows)}")
        new.commit()


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit(__doc__)
    import_v1(sys.argv[1], sys.argv[2])

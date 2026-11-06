#!/usr/bin/env python3
"""Creates a one-time admin code, for setting up a new site.

    python3 tools/admin_code.py [DATABASE]

Run it on the server, then choose Admin on the sign-up page and enter the code.
It works once and expires in a week. After that, the admin creates new codes in Settings.
"""
import datetime
import sys
from contextlib import closing
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import api
import db as database


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else ROOT / "mess.db"
    database.init_db(path)
    with closing(database.connect(path)) as db:
        code, expires = api.new_admin_code(db, hours=7 * 24)
        db.commit()
    print(f"Admin code: {code}")
    print(f"Works once. Expires {datetime.datetime.fromtimestamp(expires):%d %B %Y %H:%M}.")


if __name__ == "__main__":
    main()

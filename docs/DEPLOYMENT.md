# Deploying BlueBlood

BlueBlood is a WSGI app with no dependencies outside the Python standard library. It needs Python 3.10 or newer and a disk that keeps files between restarts, because all data lives in one SQLite file, `mess.db`.

> Avoid hosts whose disk is wiped on every restart or redeploy. With SQLite, that wipes every account and entry.

## Who can do what

- Anyone can ask to join. New accounts see nothing until the admin approves them.
- When approving, the admin says who the person is: someone already listed, or a new dweller with a side and rent.
- Everyone approved can read everything.
- Dwellers change only their own meals, bazar and payments, and bills they added.
- The one admin changes everything: rent, sides, dwellers, months, accounts and the mess name.

The server enforces these rules. Hiding a button in the browser is only for convenience.

## PythonAnywhere (free tier)

1. **Get the code onto the server.** Open a Bash console and run:

   ```bash
   git clone https://github.com/rifathasan404-blip/blueblood.git
   cd blueblood
   python3 tests/test_app.py
   ```

2. **Create the web app.** On the Web tab: *Add a new web app* → *Manual configuration* → Python 3.10 or newer.

3. **Point it at BlueBlood.** Open the WSGI configuration file linked on the Web tab and replace its contents with:

   ```python
   import sys
   sys.path.insert(0, "/home/YOUR_USERNAME/blueblood")
   from server import application
   ```

4. **Set up email** (for password resets):

   ```bash
   cp mail.example.json mail.json
   chmod 600 mail.json
   ```

   Fill in a Gmail address, a Gmail [app password](https://myaccount.google.com/apppasswords), and set `public_url` to `https://YOUR_USERNAME.pythonanywhere.com`. Free accounts can reach `smtp.gmail.com`.

5. **Turn on HTTPS** with *Force HTTPS* on the Web tab, then click **Reload**.

6. **Become the admin.** Run `python3 tools/admin_code.py`, open the site, choose *Admin* when joining, and enter the code.

7. **Check it works.** Sign up a second account from a phone, approve it, add a meal, and request a password reset.

Free web apps must be renewed once a month with the *Run until 1 month from today* button on the Web tab. PythonAnywhere emails a reminder a week before.

### Updating

```bash
cd ~/blueblood
cp mess.db ~/mess-before-update.db   # back up first
git pull
python3 tests/test_app.py
```

Then click **Reload** on the Web tab. If something breaks, check the error log on the Web tab, and roll back with `git checkout <previous commit>` and Reload.

## Becoming the admin

There is always exactly one admin, and joining as admin needs a one-time code:

- **New site:** run `python3 tools/admin_code.py` on the server. Enter the code while setting up the mess. It expires in a week.
- **Local test run:** the first person needs no code, because nobody else can reach the app.
- **Handing over to someone without an account:** the admin creates a code in Settings. It works once, for 24 hours. The person chooses Admin when joining, and the old admin becomes a dweller.
- **Handing over to someone with an account:** use the crown button in Settings.

## Email

A local run with no mail set up shows the reset link on screen. Hosted runs never show the link on screen: copy `mail.example.json` to `mail.json` and fill it in. Some free hosts block outgoing email, so test a password reset before relying on it. Keep `mail.json` private; it is listed in `.gitignore`.

## Backups

All data is in `mess.db`. Copying it with `cp` while the app is writing can produce a corrupt copy, so use SQLite's backup API:

```bash
python3 -c "import sqlite3; s=sqlite3.connect('mess.db'); d=sqlite3.connect('backup.db'); s.backup(d)"
```

Download a backup to another machine regularly, and restore one once to check it works:

```bash
python3 server.py --db backup.db
```

## Bringing over data from the first version

```bash
python3 tools/import_v1.py OLD_MESS_DB mess.db
```

Do this before anyone signs up. Dwellers arrive without accounts; when the admin approves someone, they link that person to their listed name.

## Trying it with sample data

```bash
python3 tools/make_demo.py PATH_TO_OLD_MESS_DB
python3 server.py --db demo.db
```

Sign-in details are written to `DEMO_ACCOUNTS.md`. Never deploy `demo.db`.

## Other hosts

Any WSGI server can run `server:application`. On a VPS, run it under a production WSGI server behind a reverse proxy:

```bash
pip install gunicorn
gunicorn --bind 127.0.0.1:8100 --workers 1 --threads 4 server:application
```

Put nginx in front for HTTPS, and have it set `X-Real-IP` and `X-Forwarded-Proto` itself. Don't run `python3 server.py --host 127.0.0.1` behind a proxy in production: binding to localhost turns on development mode, where the first admin needs no code.

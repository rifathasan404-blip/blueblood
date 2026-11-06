"""The JSON API. Every handler takes (ctx, body, *url_parts).

Permission rule, enforced here and never only in the browser:
  a new account waits for the admin's approval and can see nothing until then;
  everyone approved can read everything in the mess;
  a dweller can change only their own meals, bazar, payments and bills;
  the one admin can change everything.

A person becomes the admin only with a one-time admin code. The single exception
is the very first account on a local test run, where nobody else can reach the app.
"""
import calendar
import datetime
import hmac
import re
import secrets
import sqlite3
import sys
import time

import auth
import mailer
from calc import calculate

DEFAULT_MESS_NAME = "BlueBlood"
USERNAME = re.compile(r"[a-z0-9_.]{3,30}")
EMAIL = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")
CODE_LETTERS = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"    # no look-alikes such as 0/O or 1/I
ADMIN_CODE_HOURS = 24


class ApiError(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status
        self.message = message


class Ctx:
    """What a handler needs to know about the request."""

    def __init__(self, db, user=None, ip="unknown", dev=False, mail=None, base_url="", token=""):
        self.db, self.user, self.ip = db, user, ip
        self.dev, self.mail, self.base_url = dev, mail, base_url
        self.token = token
        self.new_cookie = None      # (value, max_age) when the session changes

    @property
    def is_admin(self):
        return self.user is not None and self.user["role"] == "admin"

    def start_session(self, user_id):
        token, hashed = auth.new_token()
        self.db.execute("INSERT INTO sessions (token_hash, user_id, expires_at) VALUES (?, ?, ?)",
                        (hashed, user_id, time.time() + auth.SESSION_SECONDS))
        self.new_cookie = (token, auth.SESSION_SECONDS)


# ---- validation -----------------------------------------------------------

def text(body, key, required=True, limit=120):
    value = str(body.get(key) or "").strip()
    if required and not value:
        raise ApiError(400, f"{key.replace('_', ' ').capitalize()} is required")
    if len(value) > limit:
        raise ApiError(400, f"{key.replace('_', ' ').capitalize()} is too long")
    if any(ord(c) < 32 for c in value):
        raise ApiError(400, f"{key.replace('_', ' ').capitalize()} has invalid characters")
    return value


def clean_number(raw):
    """Lets people type a number as the app shows it: 1,200 or −223 or ৳500."""
    return re.sub(r"[\s,৳]", "", str(raw)).replace("−", "-")


def number(body, key, minimum=None, maximum=1e9, default=None):
    raw = body.get(key)
    if raw in (None, ""):
        if default is not None:
            return default
        raise ApiError(400, f"{key.capitalize()} is required")
    if isinstance(raw, bool):
        raise ApiError(400, f"{key.capitalize()} must be a number")
    try:
        value = float(clean_number(raw))
    except (TypeError, ValueError):
        raise ApiError(400, f"{key.capitalize()} must be a number") from None
    if value != value or abs(value) > maximum:
        raise ApiError(400, f"{key.capitalize()} is out of range")
    if minimum is not None and value < minimum:
        raise ApiError(400, f"{key.capitalize()} can't be less than {minimum:g}")
    return value


def parse_date(value):
    try:
        return datetime.date.fromisoformat(str(value)).isoformat()
    except ValueError:
        raise ApiError(400, "Enter a valid date") from None


def parse_amount_sum(raw):
    """Accepts `100+30+150+1800` as well as a plain number, like an Excel cell."""
    raw = clean_number(raw if raw is not None else "")
    if not re.fullmatch(r"\d+(\.\d+)?([+-]\d+(\.\d+)?)*", raw):
        raise ApiError(400, "Amount must be a number, or a sum like 100+30+150")
    total = sum(float(n) for n in re.findall(r"[+-]?\d+(?:\.\d+)?", raw))
    if total < 0 or total > 1e9:
        raise ApiError(400, "Amount is out of range")
    return total, raw if re.search(r"\d[+-]", raw) else ""


def valid_username(body):
    value = str(body.get("username") or "").strip().lower()
    if not USERNAME.fullmatch(value):
        raise ApiError(400, "Username needs 3 to 30 letters, numbers, dots or underscores")
    return value


def valid_email(body):
    value = str(body.get("email") or "").strip().lower()
    if len(value) > 120 or not EMAIL.fullmatch(value):
        raise ApiError(400, "Enter a valid email address")
    return value


def valid_password(body, key="password"):
    value = body.get(key)
    if not isinstance(value, str) or len(value) < auth.MIN_PASSWORD:
        raise ApiError(400, f"Password must be at least {auth.MIN_PASSWORD} characters")
    if len(value) > 200:
        raise ApiError(400, "Password is too long")
    return value


def int_or_none(value):
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        raise ApiError(400, "Invalid selection") from None


# ---- rate limits ----------------------------------------------------------

def recent_events(db, key, window):
    now = time.time()
    db.execute("DELETE FROM rate_events WHERE key = ? AND at < ?", (key, now - window))
    return db.execute("SELECT count(*) FROM rate_events WHERE key = ?", (key,)).fetchone()[0]


def record_event(db, key):
    db.execute("INSERT INTO rate_events (key, at) VALUES (?, ?)", (key, time.time()))


# ---- settings -------------------------------------------------------------

def get_setting(db, key):
    row = db.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else None


def set_setting(db, key, value):
    db.execute("INSERT INTO settings (key, value) VALUES (?, ?)"
               " ON CONFLICT (key) DO UPDATE SET value = excluded.value", (key, value))


def mess_name(db):
    return get_setting(db, "mess_name") or DEFAULT_MESS_NAME


def update_settings(ctx, body):
    name = text(body, "mess_name", limit=40)
    set_setting(ctx.db, "mess_name", name)
    return {"mess_name": name}


def admin_user(db):
    return db.execute("SELECT * FROM users WHERE role = 'admin'").fetchone()


def public_info(ctx, body):
    has_admin = admin_user(ctx.db) is not None
    return {"mess_name": mess_name(ctx.db), "has_admin": has_admin,
            "needs_code": has_admin or not ctx.dev}


# ---- admin codes ----------------------------------------------------------

def normal_code(value):
    return re.sub(r"[^A-Z0-9]", "", str(value or "").upper())


def new_admin_code(db, hours=ADMIN_CODE_HOURS):
    """Creates the one code that can make someone the admin. Only its hash is kept."""
    raw = "".join(secrets.choice(CODE_LETTERS) for _ in range(12))
    expires = time.time() + hours * 3600
    set_setting(db, "admin_code_hash", auth.token_hash(raw))
    set_setting(db, "admin_code_expires", str(expires))
    return f"{raw[:4]}-{raw[4:8]}-{raw[8:]}", expires


def clear_admin_code(db):
    db.execute("DELETE FROM settings WHERE key IN ('admin_code_hash', 'admin_code_expires')")


def admin_code_expires(db):
    expires = get_setting(db, "admin_code_expires")
    return float(expires) if expires and float(expires) > time.time() else None


def require_admin_code(ctx, value):
    db, key = ctx.db, f"admin-code:{ctx.ip}"
    if recent_events(db, key, 900) >= 5:
        db.commit()
        raise ApiError(429, "Too many wrong codes. Wait 15 minutes.")
    stored = get_setting(db, "admin_code_hash") or ""
    if not admin_code_expires(db) or not hmac.compare_digest(auth.token_hash(normal_code(value)), stored):
        record_event(db, key)
        db.commit()
        raise ApiError(403, "That admin code isn't valid. Ask for a new one.")


def create_admin_code(ctx, body):
    code, expires = new_admin_code(ctx.db)
    return {"code": code, "expires_at": expires}


def cancel_admin_code(ctx, body):
    clear_admin_code(ctx.db)
    return {"ok": True}


# ---- accounts -------------------------------------------------------------

def public_user(u):
    return {"id": u["id"], "name": u["name"], "username": u["username"],
            "email": u["email"], "role": u["role"], "status": u["status"]}


def signup(ctx, body):
    db = ctx.db
    if recent_events(db, f"signup:{ctx.ip}", 3600) >= 20:
        raise ApiError(429, "Too many new accounts from here. Try again later.")
    name = text(body, "name", limit=40)
    username, email = valid_username(body), valid_email(body)
    password = valid_password(body)
    as_admin = bool(body.get("as_admin"))
    current_admin = admin_user(db)
    if current_admin is None and not as_admin:
        raise ApiError(409, "This mess has no admin yet. The admin needs to join first.")
    if db.execute("SELECT 1 FROM users WHERE username = ?", (username,)).fetchone():
        raise ApiError(409, "That username is taken")
    if db.execute("SELECT 1 FROM users WHERE email = ?", (email,)).fetchone():
        raise ApiError(409, "An account already uses that email")
    if as_admin and (current_admin is not None or not ctx.dev):
        require_admin_code(ctx, body.get("admin_code"))
    record_event(db, f"signup:{ctx.ip}")
    salt, hashed, iterations = auth.hash_password(password)
    if as_admin and current_admin is not None:
        db.execute("UPDATE users SET role = 'member' WHERE id = ?", (current_admin["id"],))
    try:
        user_id = db.execute(
            "INSERT INTO users (name, username, email, salt, password_hash, iterations, created_at,"
            " role, status) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (name, username, email, salt, hashed, iterations, time.time(),
             "admin" if as_admin else "member", "active" if as_admin else "pending")).lastrowid
    except sqlite3.IntegrityError:
        raise ApiError(409, "That username or email is taken") from None
    if as_admin:
        clear_admin_code(db)
        if current_admin is None and body.get("mess_name"):
            set_setting(db, "mess_name", text(body, "mess_name", limit=40))
        if not db.execute("SELECT 1 FROM months").fetchone():
            make_month(db, datetime.date.today().strftime("%Y-%m"), None)
    ctx.start_session(user_id)
    return {"ok": True}


def login(ctx, body):
    db, who = ctx.db, str(body.get("login") or "").strip().lower()
    password = str(body.get("password") or "")
    pair_key, ip_key = f"login:{ctx.ip}:{who}", f"login-ip:{ctx.ip}"
    if recent_events(db, pair_key, 900) >= 8 or recent_events(db, ip_key, 900) >= 40:
        db.commit()
        raise ApiError(429, "Too many wrong tries. Wait 15 minutes.")
    user = db.execute("SELECT * FROM users WHERE username = ? OR email = ?", (who, who)).fetchone()
    if user is None:
        auth.burn_time(password)
    if user is None or not auth.check_password(
            password, user["salt"], user["iterations"], user["password_hash"]):
        record_event(db, pair_key)
        record_event(db, ip_key)
        db.commit()
        raise ApiError(401, "Wrong username, email or password")
    db.execute("DELETE FROM rate_events WHERE key = ?", (pair_key,))
    db.execute("DELETE FROM sessions WHERE expires_at < ?", (time.time(),))
    db.execute("DELETE FROM rate_events WHERE at < ?", (time.time() - 86400,))
    ctx.start_session(user["id"])
    return {"ok": True}


def logout(ctx, body):
    if ctx.token:
        ctx.db.execute("DELETE FROM sessions WHERE token_hash = ?", (auth.token_hash(ctx.token),))
    ctx.new_cookie = ("", 0)
    return {"ok": True}


def forgot(ctx, body):
    """Answers the same for known and unknown emails, so it can't reveal who has an account."""
    db, email = ctx.db, str(body.get("email") or "").strip().lower()
    answer = {"ok": True}
    if recent_events(db, f"forgot-ip:{ctx.ip}", 3600) >= 20:
        db.commit()
        raise ApiError(429, "Too many requests. Try again later.")
    record_event(db, f"forgot-ip:{ctx.ip}")
    user = db.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
    if user is None or recent_events(db, f"forgot:{email}", 900) >= 3:
        return answer
    record_event(db, f"forgot:{email}")
    token, hashed = auth.new_token()
    db.execute("DELETE FROM reset_tokens WHERE user_id = ?", (user["id"],))
    db.execute("INSERT INTO reset_tokens (token_hash, user_id, expires_at) VALUES (?, ?, ?)",
               (hashed, user["id"], time.time() + auth.RESET_SECONDS))
    # A configured address is used rather than the request's Host header, which
    # an attacker could forge to make the emailed link point at their own site.
    base = (ctx.mail or {}).get("public_url") or (ctx.base_url if ctx.dev else "")
    link = f"{base.rstrip('/')}/reset?token={token}"
    if ctx.mail:
        try:
            mailer.send_reset(ctx.mail, user["email"], user["name"], mess_name(db), link)
        except Exception as e:      # never reveal delivery trouble to the requester
            print(f"Password reset email failed: {e}", file=sys.stderr)
    elif ctx.dev:
        answer["dev_link"] = link
    else:
        print("Password reset requested, but mail.json is not set up", file=sys.stderr)
    return answer


def reset_password(ctx, body):
    db = ctx.db
    password = valid_password(body)
    hashed = auth.token_hash(str(body.get("token") or ""))
    row = db.execute("SELECT user_id FROM reset_tokens WHERE token_hash = ? AND expires_at > ?",
                     (hashed, time.time())).fetchone()
    if row is None:
        raise ApiError(400, "This reset link has expired or was already used")
    set_password(db, row["user_id"], password)
    db.execute("DELETE FROM reset_tokens WHERE user_id = ?", (row["user_id"],))
    db.execute("DELETE FROM sessions WHERE user_id = ?", (row["user_id"],))
    return {"ok": True}


def set_password(db, user_id, password):
    salt, hashed, iterations = auth.hash_password(password)
    db.execute("UPDATE users SET salt = ?, password_hash = ?, iterations = ? WHERE id = ?",
               (salt, hashed, iterations, user_id))


def latest_month(db):
    return db.execute("SELECT * FROM months ORDER BY ym DESC LIMIT 1").fetchone()


def join_options(db, month):
    return {
        "ym": month["ym"],
        "unclaimed": [dict(r) for r in db.execute(
            "SELECT id, name FROM members WHERE month_id = ? AND user_id IS NULL ORDER BY name",
            (month["id"],))],
        "sides": [dict(r) for r in db.execute(
            "SELECT id, name FROM sides WHERE month_id = ? ORDER BY id", (month["id"],))],
    }


def me(ctx, body):
    db, admin = ctx.db, admin_user(ctx.db)
    answer = {"user": public_user(ctx.user), "mess_name": mess_name(db),
              "admin_name": admin["name"] if admin else None, "join": None, "pending": 0}
    if ctx.is_admin:
        answer["pending"] = db.execute("SELECT count(*) FROM users WHERE status = 'pending'").fetchone()[0]
        latest = latest_month(db)
        if latest and not my_member(ctx, latest["id"]):
            answer["join"] = join_options(db, latest)
    return answer


def place_in_month(db, user, month, body):
    """Puts an account into a month, as a listed dweller or as someone new."""
    member_id = int_or_none(body.get("member_id"))
    if member_id is not None:
        row = owned(db, "members", member_id, month["id"])
        if row["user_id"] is not None:
            raise ApiError(409, f"{row['name']} already has an account")
        # Past months under the same name belong to this person too.
        db.execute("UPDATE members SET user_id = ? WHERE user_id IS NULL AND lower(name) = lower(?)"
                   " AND month_id NOT IN (SELECT month_id FROM members WHERE user_id = ?)",
                   (user["id"], row["name"], user["id"]))
        return
    if not body.get("side_id"):
        raise ApiError(400, "Pick a side")
    side = owned(db, "sides", int_or_none(body.get("side_id")), month["id"])
    if db.execute("SELECT 1 FROM members WHERE month_id = ? AND lower(name) = lower(?)",
                  (month["id"], user["name"])).fetchone():
        raise ApiError(409, f"{user['name']} is already listed. Pick that name instead of adding someone new.")
    db.execute("INSERT INTO members (month_id, side_id, user_id, name, rent) VALUES (?, ?, ?, ?, ?)",
               (month["id"], side["id"], user["id"], user["name"],
                number(body, "rent", minimum=0, default=0.0)))


def join_mess(ctx, body):
    """The admin places their own account; everyone else is placed when approved."""
    db, month = ctx.db, latest_month(ctx.db)
    if month is None:
        raise ApiError(400, "Start a month first")
    if my_member(ctx, month["id"]):
        raise ApiError(409, "You're already in this month")
    place_in_month(db, ctx.user, month, body)
    return me(ctx, body)


def approval_options(ctx, body):
    month = latest_month(ctx.db)
    return join_options(ctx.db, month) if month else {"ym": None, "unclaimed": [], "sides": []}


def approve_user(ctx, body, user_id):
    db = ctx.db
    target = db.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    if target is None:
        raise ApiError(404, "That account no longer exists")
    if target["status"] != "pending":
        raise ApiError(409, f"{target['name']} is already approved")
    month = latest_month(db)
    if month:
        place_in_month(db, target, month, body)
    db.execute("UPDATE users SET status = 'active' WHERE id = ?", (user_id,))
    return list_users(ctx, body)


def update_me(ctx, body):
    db, user = ctx.db, ctx.user
    name = text(body, "name", limit=40)
    username, email = valid_username(body), valid_email(body)
    if db.execute("SELECT 1 FROM users WHERE username = ? AND id != ?", (username, user["id"])).fetchone():
        raise ApiError(409, "That username is taken")
    if db.execute("SELECT 1 FROM users WHERE email = ? AND id != ?", (email, user["id"])).fetchone():
        raise ApiError(409, "An account already uses that email")
    clash = db.execute(
        "SELECT 1 FROM members WHERE lower(name) = lower(?) AND (user_id IS NULL OR user_id != ?)"
        " AND month_id IN (SELECT month_id FROM members WHERE user_id = ?)",
        (name, user["id"], user["id"])).fetchone()
    if clash:
        raise ApiError(409, f"{name} is already in the mess")
    db.execute("UPDATE users SET name = ?, username = ?, email = ? WHERE id = ?",
               (name, username, email, user["id"]))
    db.execute("UPDATE members SET name = ? WHERE user_id = ?", (name, user["id"]))
    ctx.user = db.execute("SELECT * FROM users WHERE id = ?", (user["id"],)).fetchone()
    return me(ctx, body)


def change_password(ctx, body):
    db, user = ctx.db, ctx.user
    new_password = valid_password(body)
    if not auth.check_password(str(body.get("current") or ""), user["salt"], user["iterations"],
                               user["password_hash"]):
        raise ApiError(403, "Your current password is wrong")
    set_password(db, user["id"], new_password)
    db.execute("DELETE FROM sessions WHERE user_id = ?", (user["id"],))
    ctx.start_session(user["id"])       # keeps this device signed in, ends all others
    return {"ok": True}


def list_users(ctx, body):
    return {"users": [
        {**public_user(u), "created_at": u["created_at"]}
        for u in ctx.db.execute("SELECT * FROM users ORDER BY name COLLATE NOCASE")],
        "admin_code_expires": admin_code_expires(ctx.db)}


def make_admin(ctx, body, user_id):
    db = ctx.db
    target = db.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    if target is None:
        raise ApiError(404, "That account no longer exists")
    if target["id"] == ctx.user["id"]:
        raise ApiError(400, "You're already the admin")
    if target["status"] != "active":
        raise ApiError(409, "Approve this account first")
    db.execute("UPDATE users SET role = 'member' WHERE id = ?", (ctx.user["id"],))
    db.execute("UPDATE users SET role = 'admin' WHERE id = ?", (target["id"],))
    return {"ok": True}


def delete_user(ctx, body, user_id):
    db = ctx.db
    if user_id == ctx.user["id"]:
        raise ApiError(400, "Make someone else the admin before removing your own account")
    if db.execute("DELETE FROM users WHERE id = ?", (user_id,)).rowcount == 0:
        raise ApiError(404, "That account no longer exists")
    return list_users(ctx, body)


# ---- reads ----------------------------------------------------------------

def get_month(db, ym):
    row = db.execute("SELECT * FROM months WHERE ym = ?", (ym,)).fetchone()
    if row is None:
        raise ApiError(404, f"No sheet for {ym}")
    return row


def owned(db, table, row_id, month_id):
    """Fetches a row, checking that it belongs to the month in the URL."""
    if table in ("bazar", "payments"):
        row = db.execute(
            f"SELECT t.* FROM {table} t JOIN members m ON m.id = t.member_id"
            " WHERE t.id = ? AND m.month_id = ?", (row_id, month_id)).fetchone()
    else:
        row = db.execute(f"SELECT * FROM {table} WHERE id = ? AND month_id = ?",
                         (row_id, month_id)).fetchone()
    if row is None:
        raise ApiError(404, "That record no longer exists")
    return row


def my_member(ctx, month_id):
    return ctx.db.execute("SELECT id, side_id FROM members WHERE month_id = ? AND user_id = ?",
                          (month_id, ctx.user["id"])).fetchone()


def list_months(ctx, body=None):
    return {"months": [r["ym"] for r in ctx.db.execute("SELECT ym FROM months ORDER BY ym DESC")]}


def month_state(ctx, ym):
    db = ctx.db
    month = get_month(db, ym)
    mid = month["id"]
    rows = lambda sql: [dict(r) for r in db.execute(sql, (mid,))]
    sides = rows("SELECT id, name, bills_charged, addon FROM sides WHERE month_id = ? ORDER BY id")
    for s in sides:
        s["bills_charged"] = bool(s["bills_charged"])
    members = rows("SELECT m.id, m.name, m.side_id, m.rent, m.user_id, u.role FROM members m"
                   " LEFT JOIN users u ON u.id = m.user_id WHERE m.month_id = ? ORDER BY m.id")
    bills = rows("SELECT b.id, b.side_id, b.name, b.amount, b.breakdown, b.round_up, b.owner_id,"
                 " u.name AS owner_name FROM bills b LEFT JOIN users u ON u.id = b.owner_id"
                 " WHERE b.month_id = ? ORDER BY b.id")
    for b in bills:
        b["round_up"] = bool(b["round_up"])
    bazar = rows("SELECT b.id, b.member_id, b.date, b.item, b.amount FROM bazar b"
                 " JOIN members m ON m.id = b.member_id WHERE m.month_id = ?"
                 " ORDER BY b.date DESC, b.id DESC")
    payments = rows("SELECT p.id, p.member_id, p.date, p.amount, p.note FROM payments p"
                    " JOIN members m ON m.id = p.member_id WHERE m.month_id = ?"
                    " ORDER BY p.date DESC, p.id DESC")
    meal_rows = rows("SELECT n.member_id, n.day, n.qty FROM meals n"
                     " JOIN members m ON m.id = n.member_id WHERE m.month_id = ?")

    meals, meal_totals = {}, {}
    for r in meal_rows:
        meals.setdefault(str(r["member_id"]), {})[str(r["day"])] = r["qty"]
        meal_totals[r["member_id"]] = meal_totals.get(r["member_id"], 0) + r["qty"]
    bazar_totals, paid_totals = {}, {}
    for r in bazar:
        bazar_totals[r["member_id"]] = bazar_totals.get(r["member_id"], 0) + r["amount"]
    for r in payments:
        paid_totals[r["member_id"]] = paid_totals.get(r["member_id"], 0) + r["amount"]

    mine = my_member(ctx, mid)
    year, mon = map(int, ym.split("-"))
    return {
        "ym": ym,
        "days": calendar.monthrange(year, mon)[1],
        "sides": sides,
        "members": members,
        "bills": bills,
        "bazar": bazar,
        "payments": payments,
        "meals": meals,
        "calc": calculate(sides, members, meal_totals, bazar_totals, bills, paid_totals),
        "me": {"user_id": ctx.user["id"], "member_id": mine["id"] if mine else None,
               "side_id": mine["side_id"] if mine else None, "admin": ctx.is_admin},
    }


# ---- permissions ----------------------------------------------------------

def writable_member(ctx, month, requested):
    """The dweller a record may belong to. Dwellers always get themselves."""
    if ctx.is_admin:
        try:
            return owned(ctx.db, "members", int(requested or 0), month["id"])["id"]
        except (TypeError, ValueError):
            raise ApiError(400, "Pick a dweller") from None
    mine = my_member(ctx, month["id"])
    if mine is None:
        raise ApiError(403, "You aren't a dweller in this month")
    return mine["id"]


def require_own_row(ctx, month, row):
    if ctx.is_admin:
        return
    mine = my_member(ctx, month["id"])
    if mine is None or row["member_id"] != mine["id"]:
        raise ApiError(403, "You can only change your own entries")


def require_own_bill(ctx, row):
    if not ctx.is_admin and row["owner_id"] != ctx.user["id"]:
        raise ApiError(403, "You can only change bills you added")


# ---- months ---------------------------------------------------------------

def make_month(db, ym, copy_from):
    new_id = db.execute("INSERT INTO months (ym) VALUES (?)", (ym,)).lastrowid
    if copy_from:
        copy_setup(db, get_month(db, copy_from)["id"], new_id)
    else:
        db.execute("INSERT INTO sides (month_id, name) VALUES (?, 'Main')", (new_id,))
    return new_id


def create_month(ctx, body):
    ym = text(body, "month")
    if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", ym):
        raise ApiError(400, "Pick a valid month")
    if ctx.db.execute("SELECT 1 FROM months WHERE ym = ?", (ym,)).fetchone():
        raise ApiError(409, f"{ym} already exists")
    make_month(ctx.db, ym, body.get("copy_from"))
    return {"ym": ym, **list_months(ctx)}


def copy_setup(db, source, target):
    """A new month keeps the people, rents, sides and bills; meals, bazar and
    payments start empty."""
    side_map = {}
    for s in db.execute("SELECT * FROM sides WHERE month_id = ? ORDER BY id", (source,)).fetchall():
        side_map[s["id"]] = db.execute(
            "INSERT INTO sides (month_id, name, bills_charged, addon) VALUES (?, ?, ?, ?)",
            (target, s["name"], s["bills_charged"], s["addon"])).lastrowid
    for m in db.execute("SELECT * FROM members WHERE month_id = ? ORDER BY id", (source,)).fetchall():
        db.execute("INSERT INTO members (month_id, side_id, user_id, name, rent) VALUES (?, ?, ?, ?, ?)",
                   (target, side_map[m["side_id"]], m["user_id"], m["name"], m["rent"]))
    for b in db.execute("SELECT * FROM bills WHERE month_id = ? ORDER BY id", (source,)).fetchall():
        db.execute("INSERT INTO bills (month_id, side_id, owner_id, name, amount, breakdown, round_up)"
                   " VALUES (?, ?, ?, ?, ?, ?, ?)",
                   (target, side_map.get(b["side_id"]), b["owner_id"], b["name"], b["amount"],
                    b["breakdown"], b["round_up"]))


def delete_month(ctx, body, ym):
    db, month = ctx.db, get_month(ctx.db, ym)
    # bills reference sides and members reference sides, so clear in order.
    db.execute("DELETE FROM bills WHERE month_id = ?", (month["id"],))
    db.execute("DELETE FROM members WHERE month_id = ?", (month["id"],))
    db.execute("DELETE FROM sides WHERE month_id = ?", (month["id"],))
    db.execute("DELETE FROM months WHERE id = ?", (month["id"],))
    return list_months(ctx)


# ---- dwellers and sides (admin) -------------------------------------------

def member_fields(ctx, month, body, skip_id=None):
    db = ctx.db
    name = text(body, "name", limit=40)
    clash = db.execute("SELECT id FROM members WHERE month_id = ? AND lower(name) = lower(?)",
                       (month["id"], name)).fetchone()
    if clash and clash["id"] != skip_id:
        raise ApiError(409, f"{name} is already in this month")
    if not body.get("side_id"):
        raise ApiError(400, "This month has no sides yet. Add one first.")
    side = owned(db, "sides", int_or_none(body.get("side_id")), month["id"])
    user_id = int_or_none(body.get("user_id"))
    if user_id is not None:
        if not db.execute("SELECT 1 FROM users WHERE id = ?", (user_id,)).fetchone():
            raise ApiError(404, "That account no longer exists")
        taken = db.execute("SELECT id FROM members WHERE month_id = ? AND user_id = ?",
                           (month["id"], user_id)).fetchone()
        if taken and taken["id"] != skip_id:
            raise ApiError(409, "That account is already linked to someone in this month")
    return name, side["id"], number(body, "rent", minimum=0, default=0.0), user_id


def add_member(ctx, body, ym):
    month = get_month(ctx.db, ym)
    name, side_id, rent, user_id = member_fields(ctx, month, body)
    ctx.db.execute("INSERT INTO members (month_id, side_id, name, rent, user_id) VALUES (?, ?, ?, ?, ?)",
                   (month["id"], side_id, name, rent, user_id))
    return month_state(ctx, ym)


def edit_member(ctx, body, ym, member_id):
    month = get_month(ctx.db, ym)
    owned(ctx.db, "members", int(member_id), month["id"])
    name, side_id, rent, user_id = member_fields(ctx, month, body, skip_id=int(member_id))
    ctx.db.execute("UPDATE members SET name = ?, side_id = ?, rent = ?, user_id = ? WHERE id = ?",
                   (name, side_id, rent, user_id, int(member_id)))
    return month_state(ctx, ym)


def delete_member(ctx, body, ym, member_id):
    month = get_month(ctx.db, ym)
    owned(ctx.db, "members", int(member_id), month["id"])
    ctx.db.execute("DELETE FROM members WHERE id = ?", (int(member_id),))
    return month_state(ctx, ym)


def side_fields(body):
    return (text(body, "name", limit=40), 1 if body.get("bills_charged") else 0,
            number(body, "addon", minimum=0, default=0.0))


def side_name_free(db, month_id, name, skip_id=None):
    clash = db.execute("SELECT id FROM sides WHERE month_id = ? AND lower(name) = lower(?)",
                       (month_id, name)).fetchone()
    if clash and clash["id"] != skip_id:
        raise ApiError(409, f"There is already a side called {name}")


def add_side(ctx, body, ym):
    month = get_month(ctx.db, ym)
    name, charged, addon = side_fields(body)
    side_name_free(ctx.db, month["id"], name)
    ctx.db.execute("INSERT INTO sides (month_id, name, bills_charged, addon) VALUES (?, ?, ?, ?)",
                   (month["id"], name, charged, addon))
    return month_state(ctx, ym)


def edit_side(ctx, body, ym, side_id):
    month = get_month(ctx.db, ym)
    owned(ctx.db, "sides", int(side_id), month["id"])
    name, charged, addon = side_fields(body)
    side_name_free(ctx.db, month["id"], name, skip_id=int(side_id))
    ctx.db.execute("UPDATE sides SET name = ?, bills_charged = ?, addon = ? WHERE id = ?",
                   (name, charged, addon, int(side_id)))
    return month_state(ctx, ym)


def delete_side(ctx, body, ym, side_id):
    owned(ctx.db, "sides", int(side_id), get_month(ctx.db, ym)["id"])
    if ctx.db.execute("SELECT 1 FROM members WHERE side_id = ?", (int(side_id),)).fetchone():
        raise ApiError(409, "Move this side's dwellers to another side first")
    ctx.db.execute("DELETE FROM sides WHERE id = ?", (int(side_id),))
    return month_state(ctx, ym)


# ---- meals, bazar, bills, payments ----------------------------------------

def set_meal(ctx, body, ym):
    db, month = ctx.db, get_month(ctx.db, ym)
    try:
        member_id, day = int(body.get("member_id")), int(body.get("day"))
    except (TypeError, ValueError):
        raise ApiError(400, "Bad meal cell") from None
    row = owned(db, "members", member_id, month["id"])
    require_own_row(ctx, month, {"member_id": row["id"]})
    year, mon = map(int, ym.split("-"))
    if not 1 <= day <= calendar.monthrange(year, mon)[1]:
        raise ApiError(400, "That day isn't in this month")
    if body.get("qty") in (None, ""):
        db.execute("DELETE FROM meals WHERE member_id = ? AND day = ?", (member_id, day))
    else:
        qty = number(body, "qty", minimum=0, maximum=100)
        db.execute("INSERT INTO meals (member_id, day, qty) VALUES (?, ?, ?)"
                   " ON CONFLICT (member_id, day) DO UPDATE SET qty = excluded.qty",
                   (member_id, day, qty))
    return month_state(ctx, ym)


def bazar_fields(ctx, month, body):
    day = parse_date(body.get("date"))
    if day[:7] != month["ym"]:
        raise ApiError(400, "The date must be inside this month")
    return (writable_member(ctx, month, body.get("member_id")), day,
            text(body, "item", required=False), number(body, "amount", minimum=0))


def add_bazar(ctx, body, ym):
    fields = bazar_fields(ctx, get_month(ctx.db, ym), body)
    ctx.db.execute("INSERT INTO bazar (member_id, date, item, amount) VALUES (?, ?, ?, ?)", fields)
    return month_state(ctx, ym)


def edit_bazar(ctx, body, ym, row_id):
    month = get_month(ctx.db, ym)
    require_own_row(ctx, month, owned(ctx.db, "bazar", int(row_id), month["id"]))
    ctx.db.execute("UPDATE bazar SET member_id = ?, date = ?, item = ?, amount = ? WHERE id = ?",
                   (*bazar_fields(ctx, month, body), int(row_id)))
    return month_state(ctx, ym)


def delete_bazar(ctx, body, ym, row_id):
    month = get_month(ctx.db, ym)
    require_own_row(ctx, month, owned(ctx.db, "bazar", int(row_id), month["id"]))
    ctx.db.execute("DELETE FROM bazar WHERE id = ?", (int(row_id),))
    return month_state(ctx, ym)


def bill_fields(ctx, month, body):
    db = ctx.db
    side_id = int_or_none(body.get("side_id"))
    if side_id is not None:
        side_id = owned(db, "sides", side_id, month["id"])["id"]
    if not ctx.is_admin:
        mine = my_member(ctx, month["id"])
        if mine is None:
            raise ApiError(403, "You aren't a dweller in this month")
        if side_id not in (None, mine["side_id"]):
            raise ApiError(403, "You can only add bills for your own side or for everyone")
    amount, breakdown = parse_amount_sum(body.get("amount"))
    return side_id, text(body, "name", limit=60), amount, breakdown, 1 if body.get("round_up") else 0


def add_bill(ctx, body, ym):
    month = get_month(ctx.db, ym)
    fields = bill_fields(ctx, month, body)
    ctx.db.execute("INSERT INTO bills (month_id, side_id, name, amount, breakdown, round_up, owner_id)"
                   " VALUES (?, ?, ?, ?, ?, ?, ?)", (month["id"], *fields, ctx.user["id"]))
    return month_state(ctx, ym)


def edit_bill(ctx, body, ym, row_id):
    month = get_month(ctx.db, ym)
    require_own_bill(ctx, owned(ctx.db, "bills", int(row_id), month["id"]))
    ctx.db.execute("UPDATE bills SET side_id = ?, name = ?, amount = ?, breakdown = ?, round_up = ?"
                   " WHERE id = ?", (*bill_fields(ctx, month, body), int(row_id)))
    return month_state(ctx, ym)


def delete_bill(ctx, body, ym, row_id):
    month = get_month(ctx.db, ym)
    require_own_bill(ctx, owned(ctx.db, "bills", int(row_id), month["id"]))
    ctx.db.execute("DELETE FROM bills WHERE id = ?", (int(row_id),))
    return month_state(ctx, ym)


def payment_fields(ctx, month, body):
    raw_date = body.get("date")
    # Payments can land after the month ends (October's rent paid in November),
    # and a negative amount records a charge, as the sheet's -223 does.
    return (writable_member(ctx, month, body.get("member_id")),
            parse_date(raw_date) if raw_date else None,
            number(body, "amount"), text(body, "note", required=False))


def add_payment(ctx, body, ym):
    fields = payment_fields(ctx, get_month(ctx.db, ym), body)
    ctx.db.execute("INSERT INTO payments (member_id, date, amount, note) VALUES (?, ?, ?, ?)", fields)
    return month_state(ctx, ym)


def edit_payment(ctx, body, ym, row_id):
    month = get_month(ctx.db, ym)
    require_own_row(ctx, month, owned(ctx.db, "payments", int(row_id), month["id"]))
    ctx.db.execute("UPDATE payments SET member_id = ?, date = ?, amount = ?, note = ? WHERE id = ?",
                   (*payment_fields(ctx, month, body), int(row_id)))
    return month_state(ctx, ym)


def delete_payment(ctx, body, ym, row_id):
    month = get_month(ctx.db, ym)
    require_own_row(ctx, month, owned(ctx.db, "payments", int(row_id), month["id"]))
    ctx.db.execute("DELETE FROM payments WHERE id = ?", (int(row_id),))
    return month_state(ctx, ym)


# ---- routes ---------------------------------------------------------------

PUBLIC, WAITING, USER, ADMIN = "public", "waiting", "user", "admin"
YM = r"(\d{4}-\d{2})"
ID = r"(\d+)"
ROUTES = [(m, re.compile(f"^/api/{p}$"), f, access) for m, p, f, access in [
    ("GET", "public", public_info, PUBLIC),
    ("POST", "signup", signup, PUBLIC),
    ("POST", "login", login, PUBLIC),
    ("POST", "logout", logout, PUBLIC),
    ("POST", "forgot", forgot, PUBLIC),
    ("POST", "reset", reset_password, PUBLIC),

    ("GET", "me", me, WAITING),
    ("PUT", "me", update_me, USER),
    ("PUT", "me/password", change_password, USER),
    ("GET", "months", list_months, USER),
    ("GET", f"months/{YM}", lambda c, b, ym: month_state(c, ym), USER),

    ("PUT", f"months/{YM}/meals", set_meal, USER),
    ("POST", f"months/{YM}/bazar", add_bazar, USER),
    ("PUT", f"months/{YM}/bazar/{ID}", edit_bazar, USER),
    ("DELETE", f"months/{YM}/bazar/{ID}", delete_bazar, USER),
    ("POST", f"months/{YM}/bills", add_bill, USER),
    ("PUT", f"months/{YM}/bills/{ID}", edit_bill, USER),
    ("DELETE", f"months/{YM}/bills/{ID}", delete_bill, USER),
    ("POST", f"months/{YM}/payments", add_payment, USER),
    ("PUT", f"months/{YM}/payments/{ID}", edit_payment, USER),
    ("DELETE", f"months/{YM}/payments/{ID}", delete_payment, USER),

    ("PUT", "settings", update_settings, ADMIN),
    ("POST", "join", join_mess, ADMIN),
    ("GET", "join-options", approval_options, ADMIN),
    ("POST", "admin-code", create_admin_code, ADMIN),
    ("DELETE", "admin-code", cancel_admin_code, ADMIN),
    ("GET", "users", list_users, ADMIN),
    ("POST", f"users/{ID}/approve", lambda c, b, i: approve_user(c, b, int(i)), ADMIN),
    ("DELETE", f"users/{ID}", lambda c, b, i: delete_user(c, b, int(i)), ADMIN),
    ("POST", f"users/{ID}/make-admin", lambda c, b, i: make_admin(c, b, int(i)), ADMIN),
    ("POST", "months", create_month, ADMIN),
    ("DELETE", f"months/{YM}", delete_month, ADMIN),
    ("POST", f"months/{YM}/members", add_member, ADMIN),
    ("PUT", f"months/{YM}/members/{ID}", edit_member, ADMIN),
    ("DELETE", f"months/{YM}/members/{ID}", delete_member, ADMIN),
    ("POST", f"months/{YM}/sides", add_side, ADMIN),
    ("PUT", f"months/{YM}/sides/{ID}", edit_side, ADMIN),
    ("DELETE", f"months/{YM}/sides/{ID}", delete_side, ADMIN),
]]

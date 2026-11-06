"""Run with: python3 tests/test_app.py"""
import io
import json
import re
import sys
import tempfile
import time
import unittest
from contextlib import closing
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import api
import auth
import db as database
import mailer
import server
from calc import roundup

YM = "2026-10"
PASSWORD = "correct horse"


def load_seed(path):
    """Loads the original October sheet, before anyone has an account."""
    seed = json.loads((ROOT / "seed" / "seed.json").read_text(encoding="utf-8"))
    with closing(database.connect(path)) as db:
        month = db.execute("INSERT INTO months (ym) VALUES (?)", (seed["ym"],)).lastrowid
        sides = {}
        for g in seed["groups"]:
            sides[g["name"]] = db.execute(
                "INSERT INTO sides (month_id, name, bills_charged, addon) VALUES (?, ?, ?, ?)",
                (month, g["name"], int(g["bills_charged"]), g["addon"])).lastrowid
        for m in seed["members"]:
            mid = db.execute("INSERT INTO members (month_id, side_id, name, rent) VALUES (?, ?, ?, ?)",
                             (month, sides[m["group"]], m["name"], m["rent"])).lastrowid
            db.executemany("INSERT INTO meals (member_id, day, qty) VALUES (?, ?, ?)",
                           [(mid, int(d), q) for d, q in m["meals"].items()])
            db.executemany("INSERT INTO bazar (member_id, date, item, amount) VALUES (?, ?, ?, ?)",
                           [(mid, b["date"], b["item"], b["amount"]) for b in m["bazar"]])
            db.executemany("INSERT INTO payments (member_id, date, amount, note) VALUES (?, ?, ?, ?)",
                           [(mid, p["date"], p["amount"], p["note"]) for p in m["payments"]])
        for b in seed["bills"]:
            db.execute("INSERT INTO bills (month_id, side_id, name, amount, breakdown, round_up)"
                       " VALUES (?, ?, ?, ?, ?, ?)",
                       (month, sides.get(b["group"]), b["name"], b["amount"], b["breakdown"], int(b["round_up"])))
        db.commit()


class Client:
    """A browser: keeps its cookie and talks to the WSGI app directly."""

    def __init__(self, ip="1.1.1.1"):
        self.cookie, self.ip = "", ip

    def raw(self, method, path, body=None, headers=None):
        data = json.dumps(body).encode() if body is not None else b""
        env = {"REQUEST_METHOD": method, "PATH_INFO": path, "CONTENT_LENGTH": str(len(data)),
               "CONTENT_TYPE": "application/json", "HTTP_COOKIE": self.cookie, "REMOTE_ADDR": self.ip,
               "wsgi.input": io.BytesIO(data), "wsgi.errors": sys.stderr, "wsgi.url_scheme": "https",
               "HTTP_HOST": "mess.example.com", **(headers or {})}
        seen = {}

        def start(status, response_headers):
            seen["status"], seen["headers"] = int(status[:3]), response_headers
        out = b"".join(server.application(env, start))
        for name, value in seen["headers"]:
            if name == "Set-Cookie":
                self.cookie = value.split(";")[0]
                seen["set_cookie"] = value
        return seen, out

    def call(self, method, path, body=None, **kw):
        seen, out = self.raw(method, f"/api/{path}", body, **kw)
        try:
            return seen["status"], json.loads(out)
        except ValueError:
            return seen["status"], {}


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        self.saved = server.DB_PATH, server.MAIL_PATH, server.DEV, auth.ITERATIONS
        server.DB_PATH, server.MAIL_PATH, server.DEV = base / "t.db", base / "mail.json", False
        auth.ITERATIONS = 1000
        database.init_db(server.DB_PATH)
        self.prepare()

    def prepare(self):
        pass

    def tearDown(self):
        server.DB_PATH, server.MAIL_PATH, server.DEV, auth.ITERATIONS = self.saved
        self.tmp.cleanup()

    def admin_code(self):
        with closing(database.connect(server.DB_PATH)) as db:
            code, _ = api.new_admin_code(db)
            db.commit()
        return code

    def signup_body(self, name, **extra):
        slug = name.lower().replace(" ", "")
        return {"name": name, "username": slug, "email": f"{slug}@x.test", "password": PASSWORD, **extra}

    def account(self, name, ip="1.1.1.1", admin=False):
        c = Client(ip)
        extra = {"as_admin": True, "admin_code": self.admin_code()} if admin else {}
        status, body = c.call("POST", "signup", self.signup_body(name, **extra))
        self.assertEqual(status, 200, body)
        return c

    def state(self, client):
        return client.call("GET", f"months/{YM}")[1]

    def member_id(self, client, name):
        return next(m["id"] for m in self.state(client)["members"] if m["name"] == name)

    def user_id(self, client):
        return client.call("GET", "me")[1]["user"]["id"]

    def approve(self, admin, client, listed=None, **body):
        """Approves an account as a listed dweller, or as new on the first side."""
        options = admin.call("GET", "join-options")[1]
        if listed:
            body["member_id"] = next(m["id"] for m in options["unclaimed"] if m["name"] == listed)
        elif "side_id" not in body:
            body["side_id"] = options["sides"][0]["id"]
        status, out = admin.call("POST", f"users/{self.user_id(client)}/approve", body)
        self.assertEqual(status, 200, out)

    def place_admin(self, admin, name):
        me = admin.call("GET", "me")[1]
        target = next(m["id"] for m in me["join"]["unclaimed"] if m["name"] == name)
        status, body = admin.call("POST", "join", {"member_id": target})
        self.assertEqual(status, 200, body)


class Mess(Base):
    """The October sheet with three linked accounts: Rifat (admin), Shuvo, Sakib."""

    def prepare(self):
        load_seed(server.DB_PATH)
        self.admin = self.account("Rifat", "1.1.1.1", admin=True)
        self.place_admin(self.admin, "Rifat")
        self.shuvo = self.account("Shuvo", "2.2.2.2")
        self.sakib = self.account("Sakib", "3.3.3.3")
        self.approve(self.admin, self.shuvo, listed="Shuvo")
        self.approve(self.admin, self.sakib, listed="Sakib")


class Rounding(unittest.TestCase):
    def test_matches_excel_roundup(self):
        self.assertEqual(roundup(-1079.12), -1080)
        self.assertEqual(roundup(6499.49), 6500)
        self.assertEqual(roundup(3000.0000000001), 3000)
        self.assertEqual(roundup(0), 0)


class OctoberSheet(Mess):
    def test_totals(self):
        c = self.state(self.shuvo)["calc"]
        self.assertEqual(c["total_meals"], 358)
        self.assertEqual(c["total_bazar"], 21333)
        self.assertAlmostEqual(c["meal_rate"], 59.58938547, places=6)
        self.assertEqual(c["total_paid"], 570)
        self.assertEqual(c["total_due"], 37062)

    def test_due_for_each_dweller(self):
        s = self.state(self.shuvo)
        due = {m["name"]: next(r for r in s["calc"]["members"] if r["id"] == m["id"])["due"] for m in s["members"]}
        self.assertEqual(due, {
            "Shuvo": 2171, "Nayeem": 7750, "Arif": 1475, "Sakib": 6146, "Rifat": 6500,
            "Mahim": 5290, "Rakib": 228, "Fahim": 2291, "Jubayer": 5211})

    def test_side_totals(self):
        s = self.state(self.shuvo)
        by_name = {x["name"]: next(r for r in s["calc"]["sides"] if r["id"] == x["id"]) for x in s["sides"]}
        self.assertEqual(by_name["North"]["total_due"], 3994)
        self.assertEqual(by_name["North"]["bills_per_head"], 1748)
        self.assertAlmostEqual(by_name["North"]["service_charge"], 1166.555556, places=5)
        self.assertAlmostEqual(by_name["South"]["service_charge"], 2354.555556, places=5)


class Accounts(Base):
    def test_admin_account_starts_a_month_when_there_is_none(self):
        first = self.account("Host", admin=True)
        me = first.call("GET", "me")[1]
        self.assertEqual((me["user"]["role"], me["user"]["status"]), ("admin", "active"))
        self.assertEqual(me["join"]["sides"][0]["name"], "Main")
        self.assertEqual((me["mess_name"], me["admin_name"]), ("BlueBlood", "Host"))

    def test_first_admin_can_name_the_mess(self):
        c = Client()
        body = self.signup_body("Host", as_admin=True, admin_code=self.admin_code(), mess_name="Royal Mess")
        self.assertEqual(c.call("POST", "signup", body)[0], 200)
        self.assertEqual(Client().call("GET", "public")[1]["mess_name"], "Royal Mess")

    def test_database_refuses_a_second_admin(self):
        self.account("Host", admin=True)
        self.account("Guest", "9.9.9.9")
        with closing(database.connect(server.DB_PATH)) as db, self.assertRaises(Exception):
            db.execute("UPDATE users SET role = 'admin' WHERE username = 'guest'")

    def test_signup_validation(self):
        self.account("Host", admin=True)
        c = Client("2.2.2.2")
        good = {"name": "A", "username": "abc", "email": "a@x.test", "password": PASSWORD}
        for bad in ({"username": "a"}, {"username": "has space"}, {"email": "nope"},
                    {"password": "short"}, {"name": ""}):
            self.assertEqual(c.call("POST", "signup", {**good, **bad})[0], 400, bad)
        self.assertEqual(c.call("POST", "signup", good)[0], 200)
        other = Client("3.3.3.3")
        self.assertEqual(other.call("POST", "signup", {**good, "email": "b@x.test"})[0], 409)
        self.assertEqual(other.call("POST", "signup", {**good, "username": "abd"})[0], 409)

    def test_login_with_username_or_email_any_case(self):
        self.account("Host", admin=True)
        for who in ("host", "HOST", "host@x.test", "Host@X.test"):
            status, _ = Client().call("POST", "login", {"login": who, "password": PASSWORD})
            self.assertEqual(status, 200, who)

    def test_wrong_login_looks_the_same_for_real_and_unknown_accounts(self):
        self.account("Host", admin=True)
        c = Client()
        real = c.call("POST", "login", {"login": "host", "password": "wrong-pass"})
        unknown = c.call("POST", "login", {"login": "nobody", "password": "wrong-pass"})
        self.assertEqual(real, unknown)
        self.assertEqual(real[0], 401)

    def test_repeated_wrong_passwords_lock_out(self):
        self.account("Host", admin=True)
        c = Client("5.5.5.5")
        for _ in range(8):
            self.assertEqual(c.call("POST", "login", {"login": "host", "password": "x"})[0], 401)
        self.assertEqual(c.call("POST", "login", {"login": "host", "password": PASSWORD})[0], 429)
        self.assertEqual(Client("6.6.6.6").call("POST", "login", {"login": "host", "password": PASSWORD})[0], 200)

    def test_cookie_flags_and_stored_session_hash(self):
        c = Client()
        seen, _ = c.raw("POST", "/api/signup", self.signup_body("Abc", as_admin=True, admin_code=self.admin_code()))
        for flag in ("HttpOnly", "Secure", "SameSite=Lax"):
            self.assertIn(flag, seen["set_cookie"])
        token = c.cookie.split("=", 1)[1]
        with closing(database.connect(server.DB_PATH)) as db:
            stored = db.execute("SELECT token_hash FROM sessions").fetchone()[0]
        self.assertNotEqual(stored, token)
        self.assertEqual(stored, auth.token_hash(token))

    def test_logout_really_ends_the_session(self):
        c = self.account("Host", admin=True)
        old = c.cookie
        self.assertEqual(c.call("POST", "logout")[0], 200)
        c.cookie = old
        self.assertEqual(c.call("GET", "me")[0], 401)

    def test_expired_session_is_refused(self):
        c = self.account("Host", admin=True)
        with closing(database.connect(server.DB_PATH)) as db:
            db.execute("UPDATE sessions SET expires_at = ?", (time.time() - 1,))
            db.commit()
        self.assertEqual(c.call("GET", "me")[0], 401)

    def test_pages_need_a_session(self):
        c = Client()
        seen, _ = c.raw("GET", "/")
        self.assertEqual((seen["status"], dict(seen["headers"])["Location"]), (302, "/login"))
        self.assertEqual(c.raw("GET", "/login")[0]["status"], 200)
        self.assertEqual(c.raw("GET", "/reset")[0]["status"], 200)
        self.assertEqual(c.raw("GET", "/mess.db")[0]["status"], 404)
        self.assertEqual(c.raw("GET", "/server.py")[0]["status"], 404)
        signed = self.account("Host", admin=True)
        self.assertEqual(signed.raw("GET", "/")[0]["status"], 200)
        self.assertEqual(signed.raw("GET", "/login")[0]["status"], 302)

    def test_change_password_needs_the_current_one_and_ends_other_devices(self):
        here = self.account("Host", admin=True)
        there = Client("7.7.7.7")
        there.call("POST", "login", {"login": "host", "password": PASSWORD})
        self.assertEqual(here.call("PUT", "me/password", {"current": "wrong-pass", "password": "new password"})[0], 403)
        self.assertEqual(here.call("PUT", "me/password", {"current": PASSWORD, "password": "new password"})[0], 200)
        self.assertEqual(here.call("GET", "me")[0], 200)
        self.assertEqual(there.call("GET", "me")[0], 401)
        self.assertEqual(Client().call("POST", "login", {"login": "host", "password": "new password"})[0], 200)

    def test_no_password_data_ever_leaves_the_server(self):
        c = self.account("Host", admin=True)
        _, users = c.call("GET", "users")
        _, me = c.call("GET", "me")
        text = json.dumps([users, me])
        for secret in ("salt", "password_hash", "iterations"):
            self.assertNotIn(secret, text)


class ForgotPassword(Base):
    def prepare(self):
        self.account("Host", admin=True)

    def stored_token(self):
        """Replaces the stored hash so the test knows the secret, as an email would."""
        token, hashed = auth.new_token()
        with closing(database.connect(server.DB_PATH)) as db:
            db.execute("UPDATE reset_tokens SET token_hash = ?", (hashed,))
            db.commit()
        return token

    def test_same_answer_for_known_and_unknown_email(self):
        c = Client()
        self.assertEqual(c.call("POST", "forgot", {"email": "host@x.test"}),
                         c.call("POST", "forgot", {"email": "nobody@x.test"}))

    def test_link_on_screen_only_in_a_local_run(self):
        c = Client()
        self.assertNotIn("dev_link", c.call("POST", "forgot", {"email": "host@x.test"})[1])
        server.DEV = True
        link = c.call("POST", "forgot", {"email": "host@x.test"})[1]["dev_link"]
        self.assertTrue(link.startswith("https://mess.example.com/reset?token="))

    def test_email_uses_the_configured_address_not_the_request_host(self):
        server.MAIL_PATH.write_text(json.dumps({"host": "h", "username": "u", "password": "p",
                                                "public_url": "https://real.example.com"}))
        with mock.patch("mailer.send_reset") as send:
            out = Client().call("POST", "forgot", {"email": "host@x.test"},
                                headers={"HTTP_HOST": "evil.example.com"})
        self.assertNotIn("dev_link", out[1])
        self.assertTrue(send.call_args.args[4].startswith("https://real.example.com/reset?token="))

    def test_mail_failure_gives_nothing_away(self):
        server.MAIL_PATH.write_text(json.dumps({"host": "h", "username": "u", "password": "p"}))
        with mock.patch("mailer.send_reset", side_effect=OSError("down")), mock.patch("sys.stderr", io.StringIO()):
            self.assertEqual(Client().call("POST", "forgot", {"email": "host@x.test"}), (200, {"ok": True}))

    def test_reset_changes_password_works_once_and_ends_sessions(self):
        signed_in = Client("8.8.8.8")
        signed_in.call("POST", "login", {"login": "host", "password": PASSWORD})
        c = Client()
        c.call("POST", "forgot", {"email": "host@x.test"})
        token = self.stored_token()
        self.assertEqual(c.call("POST", "reset", {"token": token, "password": "short"})[0], 400)
        self.assertEqual(c.call("POST", "reset", {"token": token, "password": "brand new pass"})[0], 200)
        self.assertEqual(c.call("POST", "reset", {"token": token, "password": "another pass"})[0], 400)
        self.assertEqual(signed_in.call("GET", "me")[0], 401)
        self.assertEqual(c.call("POST", "login", {"login": "host", "password": PASSWORD})[0], 401)
        self.assertEqual(c.call("POST", "login", {"login": "host", "password": "brand new pass"})[0], 200)

    def test_expired_and_invented_tokens_fail(self):
        c = Client()
        self.assertEqual(c.call("POST", "reset", {"token": "invented", "password": "brand new pass"})[0], 400)
        c.call("POST", "forgot", {"email": "host@x.test"})
        token = self.stored_token()
        with closing(database.connect(server.DB_PATH)) as db:
            db.execute("UPDATE reset_tokens SET expires_at = ?", (time.time() - 1,))
            db.commit()
        self.assertEqual(c.call("POST", "reset", {"token": token, "password": "brand new pass"})[0], 400)

    def test_requests_for_one_email_are_limited(self):
        server.DEV = True
        c = Client()
        links = [c.call("POST", "forgot", {"email": "host@x.test"})[1].get("dev_link") for _ in range(5)]
        self.assertEqual(sum(1 for link in links if link), 3)

    def test_email_message_contents(self):
        message = mailer.build_reset_message("a@x.test", "b@x.test", "Rifat", "BlueBlood", "https://x/reset?token=1")
        self.assertEqual(message["Subject"], "Reset your BlueBlood password")
        self.assertIn("https://x/reset?token=1", message.get_content())


class EveryRoute(Mess):
    """A sweep over the route table, so a new route can't quietly skip its guard."""

    def paths(self):
        for method, pattern, _, access in api.ROUTES:
            path = pattern.pattern.strip("^$")
            path = path.replace(r"(\d{4}-\d{2})", YM).replace(r"(\d+)", "1")
            yield method, path, access

    def test_nothing_private_is_open_to_strangers(self):
        for method, path, access in self.paths():
            if access != api.PUBLIC:
                self.assertEqual(Client("4.4.4.4").raw(method, path, {})[0]["status"], 401, path)

    def test_admin_routes_refuse_dwellers(self):
        for method, path, access in self.paths():
            if access == api.ADMIN:
                self.assertEqual(self.shuvo.raw(method, path, {})[0]["status"], 403, path)

    def test_a_waiting_account_can_reach_nothing(self):
        waiting = self.account("Waiting", "4.4.4.4")
        for method, path, access in self.paths():
            if access in (api.USER, api.ADMIN):
                self.assertEqual(waiting.raw(method, path, {})[0]["status"], 403, path)


class Permissions(Mess):
    def bazar_of(self, name):
        s = self.state(self.admin)
        mid = next(m["id"] for m in s["members"] if m["name"] == name)
        return next(b for b in s["bazar"] if b["member_id"] == mid)

    def form(self, row, **changes):
        return {"member_id": row["member_id"], "date": row["date"], "item": row["item"], "amount": row["amount"], **changes}

    def test_everyone_can_read_everything(self):
        s = self.state(self.sakib)
        self.assertEqual(len(s["bazar"]), 51)
        self.assertEqual(len(s["bills"]), 10)
        self.assertEqual(s["me"]["admin"], False)
        self.assertEqual(s["me"]["member_id"], self.member_id(self.sakib, "Sakib"))

    def test_bazar_own_yes_others_no_admin_yes(self):
        mine, theirs = self.bazar_of("Shuvo"), self.bazar_of("Sakib")
        path = f"months/{YM}/bazar"
        self.assertEqual(self.shuvo.call("PUT", f"{path}/{mine['id']}", self.form(mine, amount=999))[0], 200)
        self.assertEqual(self.shuvo.call("PUT", f"{path}/{theirs['id']}", self.form(theirs, amount=1))[0], 403)
        self.assertEqual(self.shuvo.call("DELETE", f"{path}/{theirs['id']}")[0], 403)
        self.assertEqual(self.admin.call("PUT", f"{path}/{theirs['id']}", self.form(theirs, amount=5))[0], 200)
        self.assertEqual(self.admin.call("DELETE", f"{path}/{theirs['id']}")[0], 200)
        self.assertEqual(self.shuvo.call("DELETE", f"{path}/{mine['id']}")[0], 200)

    def test_a_dweller_cannot_put_entries_on_someone_else(self):
        sakib = self.member_id(self.admin, "Sakib")
        shuvo = self.member_id(self.admin, "Shuvo")
        path = f"months/{YM}/bazar"
        status, s = self.shuvo.call("POST", path, {"member_id": sakib, "date": f"{YM}-20", "item": "sneaky", "amount": 10})
        self.assertEqual(status, 200)
        row = next(b for b in s["bazar"] if b["item"] == "sneaky")
        self.assertEqual(row["member_id"], shuvo)
        status, s = self.shuvo.call("PUT", f"{path}/{row['id']}", self.form(row, member_id=sakib))
        self.assertEqual(next(b for b in s["bazar"] if b["id"] == row["id"])["member_id"], shuvo)

    def test_admin_can_add_for_anyone(self):
        sakib = self.member_id(self.admin, "Sakib")
        _, s = self.admin.call("POST", f"months/{YM}/bazar", {"member_id": sakib, "date": f"{YM}-20", "item": "for sakib", "amount": 10})
        self.assertEqual(next(b for b in s["bazar"] if b["item"] == "for sakib")["member_id"], sakib)

    def test_meals_own_column_only(self):
        shuvo, sakib = self.member_id(self.admin, "Shuvo"), self.member_id(self.admin, "Sakib")
        path = f"months/{YM}/meals"
        self.assertEqual(self.shuvo.call("PUT", path, {"member_id": shuvo, "day": 1, "qty": 3})[0], 200)
        self.assertEqual(self.shuvo.call("PUT", path, {"member_id": sakib, "day": 1, "qty": 3})[0], 403)
        self.assertEqual(self.admin.call("PUT", path, {"member_id": sakib, "day": 1, "qty": 3})[0], 200)

    def test_payments_own_only(self):
        sakib = self.member_id(self.admin, "Sakib")
        path = f"months/{YM}/payments"
        _, s = self.admin.call("POST", path, {"member_id": sakib, "amount": 100})
        theirs = s["payments"][0]
        body = {"member_id": sakib, "amount": 1, "date": "", "note": ""}
        self.assertEqual(self.shuvo.call("PUT", f"{path}/{theirs['id']}", body)[0], 403)
        self.assertEqual(self.shuvo.call("DELETE", f"{path}/{theirs['id']}")[0], 403)
        self.assertEqual(self.sakib.call("PUT", f"{path}/{theirs['id']}", {**body, "amount": 200})[0], 200)
        status, s = self.shuvo.call("POST", path, {"member_id": sakib, "amount": 50})
        self.assertEqual(s["payments"][0]["member_id"], self.member_id(self.admin, "Shuvo"))

    def test_bills_belong_to_whoever_added_them(self):
        path = f"months/{YM}/bills"
        _, s = self.shuvo.call("POST", path, {"name": "Gas", "amount": "100+20", "side_id": "", "round_up": True})
        bill = next(b for b in s["bills"] if b["name"] == "Gas")
        self.assertEqual((bill["amount"], bill["owner_name"]), (120, "Shuvo"))
        body = {"name": "Gas 2", "amount": "130", "side_id": "", "round_up": True}
        self.assertEqual(self.sakib.call("PUT", f"{path}/{bill['id']}", body)[0], 403)
        self.assertEqual(self.sakib.call("DELETE", f"{path}/{bill['id']}")[0], 403)
        self.assertEqual(self.shuvo.call("PUT", f"{path}/{bill['id']}", body)[0], 200)
        self.assertEqual(self.admin.call("DELETE", f"{path}/{bill['id']}")[0], 200)

    def test_bills_from_the_sheet_are_admin_only(self):
        bill = self.state(self.admin)["bills"][0]
        path = f"months/{YM}/bills/{bill['id']}"
        body = {"name": "x", "amount": "1", "side_id": "", "round_up": True}
        self.assertEqual(self.shuvo.call("PUT", path, body)[0], 403)
        self.assertEqual(self.admin.call("PUT", path, {**body, "name": bill["name"], "amount": bill["amount"]})[0], 200)

    def test_dwellers_cannot_bill_another_side(self):
        s = self.state(self.shuvo)
        other = next(x["id"] for x in s["sides"] if x["id"] != s["me"]["side_id"])
        path = f"months/{YM}/bills"
        self.assertEqual(self.shuvo.call("POST", path, {"name": "x", "amount": "1", "side_id": other})[0], 403)
        self.assertEqual(self.shuvo.call("POST", path, {"name": "x", "amount": "1", "side_id": s["me"]["side_id"]})[0], 200)

    def test_someone_outside_the_month_can_read_but_not_write(self):
        stranger = self.account("Stranger", "4.4.4.4")
        self.approve(self.admin, stranger)
        path = f"months/{YM}"
        self.admin.call("DELETE", f"{path}/members/{self.member_id(self.admin, 'Stranger')}")
        self.assertEqual(stranger.call("GET", path)[0], 200)
        self.assertEqual(stranger.call("POST", f"{path}/bazar", {"date": f"{YM}-20", "amount": 1})[0], 403)
        self.assertEqual(stranger.call("POST", f"{path}/bills", {"name": "x", "amount": "1"})[0], 403)
        self.assertEqual(stranger.call("POST", f"{path}/payments", {"amount": 1})[0], 403)

    def test_records_from_other_months_are_refused(self):
        self.admin.call("POST", "months", {"month": "2026-11", "copy_from": YM})
        november = self.admin.call("GET", "months/2026-11")[1]
        self.assertEqual(self.admin.call("DELETE", f"months/{YM}/members/{november['members'][0]['id']}")[0], 404)


class Sides(Mess):
    def test_add_rename_and_delete_a_side(self):
        path = f"months/{YM}/sides"
        status, s = self.admin.call("POST", path, {"name": "Roof", "bills_charged": True, "addon": 50})
        self.assertEqual(status, 200)
        roof = next(x for x in s["sides"] if x["name"] == "Roof")
        self.assertEqual(self.admin.call("POST", path, {"name": "roof"})[0], 409)
        _, s = self.admin.call("PUT", f"{path}/{roof['id']}", {"name": "East", "bills_charged": False, "addon": 0})
        self.assertIn("East", [x["name"] for x in s["sides"]])
        self.assertEqual(self.admin.call("DELETE", f"{path}/{roof['id']}")[0], 200)

    def test_many_sides_work(self):
        for name in ("East", "West", "Roof", "Annex"):
            self.admin.call("POST", f"months/{YM}/sides", {"name": name, "bills_charged": True})
        s = self.state(self.admin)
        self.assertEqual(len(s["sides"]), 6)
        self.assertEqual(s["calc"]["total_due"], 37062)

    def test_side_with_dwellers_cannot_be_deleted(self):
        s = self.state(self.admin)
        side = s["members"][0]["side_id"]
        self.assertEqual(self.admin.call("DELETE", f"months/{YM}/sides/{side}")[0], 409)

    def test_deleting_a_side_deletes_its_bills(self):
        path = f"months/{YM}"
        _, s = self.admin.call("POST", f"{path}/sides", {"name": "Roof", "bills_charged": True})
        roof = next(x["id"] for x in s["sides"] if x["name"] == "Roof")
        self.admin.call("POST", f"{path}/bills", {"name": "Tank", "amount": "90", "side_id": roof})
        _, s = self.admin.call("DELETE", f"{path}/sides/{roof}")
        self.assertNotIn("Tank", [b["name"] for b in s["bills"]])


class Approval(Mess):
    def test_a_new_account_waits_and_sees_nothing(self):
        new = self.account("Tanvir", "4.4.4.4")
        me = new.call("GET", "me")[1]
        self.assertEqual((me["user"]["status"], me["user"]["role"], me["admin_name"]), ("pending", "member", "Rifat"))
        self.assertIsNone(me["join"])
        self.assertEqual(new.call("GET", f"months/{YM}")[0], 403)
        self.assertEqual(new.call("PUT", "me", {"name": "x", "username": "xyz", "email": "x@x.test"})[0], 403)

    def test_waiting_pages(self):
        new = self.account("Tanvir", "4.4.4.4")
        seen, _ = new.raw("GET", "/")
        self.assertEqual(dict(seen["headers"])["Location"], "/waiting")
        self.assertEqual(new.raw("GET", "/waiting")[0]["status"], 200)
        self.approve(self.admin, new)
        self.assertEqual(new.raw("GET", "/")[0]["status"], 200)
        seen, _ = new.raw("GET", "/waiting")
        self.assertEqual(dict(seen["headers"])["Location"], "/")
        seen, _ = Client("4.4.4.5").raw("GET", "/waiting")
        self.assertEqual(dict(seen["headers"])["Location"], "/login")

    def test_a_waiting_account_can_sign_in_and_out(self):
        self.account("Tanvir", "4.4.4.4")
        c = Client("4.4.4.5")
        self.assertEqual(c.call("POST", "login", {"login": "tanvir", "password": PASSWORD})[0], 200)
        self.assertEqual(c.call("GET", "me")[1]["user"]["status"], "pending")
        self.assertEqual(c.call("POST", "logout")[0], 200)

    def test_admin_sees_how_many_are_waiting(self):
        self.account("Tanvir", "4.4.4.4")
        self.assertEqual(self.admin.call("GET", "me")[1]["pending"], 1)
        self.assertEqual(self.shuvo.call("GET", "me")[1]["pending"], 0)

    def test_approving_someone_new_sets_side_and_rent(self):
        new = self.account("Tanvir", "4.4.4.4")
        sides = self.admin.call("GET", "join-options")[1]["sides"]
        self.approve(self.admin, new, side_id=sides[1]["id"], rent="3,000")
        s = self.state(new)
        mine = next(m for m in s["members"] if m["id"] == s["me"]["member_id"])
        self.assertEqual((mine["name"], mine["side_id"], mine["rent"]), ("Tanvir", sides[1]["id"], 3000))
        self.assertEqual(self.admin.call("GET", "me")[1]["pending"], 0)

    def test_approving_a_listed_name_links_past_months_too(self):
        self.admin.call("POST", "months", {"month": "2026-11", "copy_from": YM})
        arif = self.account("Arif", "4.4.4.4")
        self.approve(self.admin, arif, listed="Arif")
        for ym in (YM, "2026-11"):
            self.assertIsNotNone(arif.call("GET", f"months/{ym}")[1]["me"]["member_id"], ym)

    def test_a_linked_name_cannot_be_used_again(self):
        target = self.member_id(self.admin, "Shuvo")
        other = self.account("Other", "4.4.4.4")
        status, _ = self.admin.call("POST", f"users/{self.user_id(other)}/approve", {"member_id": target})
        self.assertEqual(status, 409)
        self.assertEqual(other.call("GET", "me")[1]["user"]["status"], "pending")

    def test_a_listed_name_is_not_duplicated(self):
        arif = self.account("Arif", "4.4.4.4")
        side = self.admin.call("GET", "join-options")[1]["sides"][0]["id"]
        status, _ = self.admin.call("POST", f"users/{self.user_id(arif)}/approve", {"side_id": side})
        self.assertEqual(status, 409)

    def test_approve_needs_a_place_and_only_works_once(self):
        new = self.account("Tanvir", "4.4.4.4")
        path = f"users/{self.user_id(new)}/approve"
        self.assertEqual(self.admin.call("POST", path, {})[0], 400)
        self.approve(self.admin, new)
        self.assertEqual(self.admin.call("POST", path, {"side_id": 1})[0], 409)

    def test_declining_deletes_the_account(self):
        new = self.account("Tanvir", "4.4.4.4")
        self.assertEqual(self.admin.call("DELETE", f"users/{self.user_id(new)}")[0], 200)
        self.assertEqual(new.call("GET", "me")[0], 401)

    def test_a_dweller_cannot_approve(self):
        new = self.account("Tanvir", "4.4.4.4")
        self.assertEqual(self.shuvo.call("POST", f"users/{self.user_id(new)}/approve", {"side_id": 1})[0], 403)

    def test_only_approved_accounts_can_become_admin(self):
        new = self.account("Tanvir", "4.4.4.4")
        self.assertEqual(self.admin.call("POST", f"users/{self.user_id(new)}/make-admin")[0], 409)

    def test_new_month_keeps_accounts_linked(self):
        self.admin.call("POST", "months", {"month": "2026-11", "copy_from": YM})
        self.assertIsNotNone(self.shuvo.call("GET", "months/2026-11")[1]["me"]["member_id"])


class FirstAdmin(Base):
    def test_a_dweller_cannot_join_before_there_is_an_admin(self):
        self.assertEqual(Client().call("POST", "signup", self.signup_body("Guest"))[0], 409)

    def test_a_hosted_site_needs_a_code_for_the_first_admin(self):
        self.assertEqual(Client().call("GET", "public")[1],
                         {"mess_name": "BlueBlood", "has_admin": False, "needs_code": True})
        c = Client()
        self.assertEqual(c.call("POST", "signup", self.signup_body("Host", as_admin=True))[0], 403)
        self.assertEqual(c.call("POST", "signup", self.signup_body("Host", as_admin=True, admin_code="AAAA-BBBB-CCCC"))[0], 403)

    def test_a_local_run_can_create_the_first_admin_without_a_code(self):
        server.DEV = True
        self.assertFalse(Client().call("GET", "public")[1]["needs_code"])
        self.assertEqual(Client().call("POST", "signup", self.signup_body("Host", as_admin=True))[0], 200)
        self.assertTrue(Client().call("GET", "public")[1]["needs_code"])
        other = self.signup_body("Other", as_admin=True)
        self.assertEqual(Client("2.2.2.2").call("POST", "signup", other)[0], 403)


class AdminCodes(Mess):
    def test_joining_with_a_code_hands_over_the_admin_role(self):
        code = self.admin.call("POST", "admin-code")[1]["code"]
        self.assertRegex(code, r"^[A-Z2-9]{4}-[A-Z2-9]{4}-[A-Z2-9]{4}$")
        new = Client("4.4.4.4")
        body = self.signup_body("Boss", as_admin=True, admin_code=code.lower().replace("-", " "))
        self.assertEqual(new.call("POST", "signup", body)[0], 200)
        me = new.call("GET", "me")[1]
        self.assertEqual((me["user"]["role"], me["user"]["status"]), ("admin", "active"))
        self.assertEqual(self.admin.call("GET", "me")[1]["user"]["role"], "member")
        self.assertEqual(self.admin.call("GET", "me")[1]["user"]["status"], "active")
        self.assertEqual(self.shuvo.call("GET", "me")[1]["admin_name"], "Boss")
        roles = [u["role"] for u in new.call("GET", "users")[1]["users"]]
        self.assertEqual(roles.count("admin"), 1)

    def test_a_code_works_once(self):
        code = self.admin.call("POST", "admin-code")[1]["code"]
        body = self.signup_body("Boss", as_admin=True, admin_code=code)
        self.assertEqual(Client("4.4.4.4").call("POST", "signup", body)[0], 200)
        again = self.signup_body("Boss Two", as_admin=True, admin_code=code)
        self.assertEqual(Client("4.4.4.5").call("POST", "signup", again)[0], 403)

    def test_expired_and_cancelled_codes_fail(self):
        code = self.admin.call("POST", "admin-code")[1]["code"]
        with closing(database.connect(server.DB_PATH)) as db:
            db.execute("UPDATE settings SET value = ? WHERE key = 'admin_code_expires'", (str(time.time() - 1),))
            db.commit()
        body = self.signup_body("Boss", as_admin=True, admin_code=code)
        self.assertEqual(Client("4.4.4.4").call("POST", "signup", body)[0], 403)
        code = self.admin.call("POST", "admin-code")[1]["code"]
        self.assertIsNotNone(self.admin.call("GET", "users")[1]["admin_code_expires"])
        self.assertEqual(self.admin.call("DELETE", "admin-code")[0], 200)
        self.assertIsNone(self.admin.call("GET", "users")[1]["admin_code_expires"])
        body["admin_code"] = code
        self.assertEqual(Client("4.4.4.5").call("POST", "signup", body)[0], 403)

    def test_a_bad_code_leaves_nothing_behind(self):
        body = self.signup_body("Boss", as_admin=True, admin_code="WRONG")
        self.assertEqual(Client("4.4.4.4").call("POST", "signup", body)[0], 403)
        names = [u["username"] for u in self.admin.call("GET", "users")[1]["users"]]
        self.assertNotIn("boss", names)
        self.assertEqual(self.admin.call("GET", "me")[1]["user"]["role"], "admin")

    def test_guessing_is_limited(self):
        c = Client("4.4.4.4")
        body = self.signup_body("Boss", as_admin=True, admin_code="WRONG")
        for _ in range(5):
            self.assertEqual(c.call("POST", "signup", body)[0], 403)
        body["admin_code"] = self.admin.call("POST", "admin-code")[1]["code"]
        self.assertEqual(c.call("POST", "signup", body)[0], 429)

    def test_only_a_hash_is_stored(self):
        code = self.admin.call("POST", "admin-code")[1]["code"]
        with closing(database.connect(server.DB_PATH)) as db:
            stored = [r["value"] for r in db.execute("SELECT value FROM settings")]
        self.assertNotIn(code, stored)
        self.assertNotIn(code.replace("-", ""), stored)

    def test_asking_for_admin_without_a_code_is_refused_quietly(self):
        status, _ = Client("4.4.4.4").call("POST", "signup", self.signup_body("Boss", as_admin=True))
        self.assertEqual(status, 403)
        status, _ = Client("4.4.4.5").call("POST", "signup", self.signup_body("Boss", role="admin", status="active"))
        self.assertEqual(status, 200)
        self.assertEqual(self.admin.call("GET", "me")[1]["pending"], 1)

    def test_only_the_admin_can_make_codes(self):
        self.assertEqual(self.shuvo.call("POST", "admin-code")[0], 403)


class Admin(Mess):
    def test_passing_the_crown(self):
        shuvo_id = self.shuvo.call("GET", "me")[1]["user"]["id"]
        self.assertEqual(self.admin.call("POST", f"users/{shuvo_id}/make-admin")[0], 200)
        self.assertEqual(self.shuvo.call("GET", "me")[1]["user"]["role"], "admin")
        self.assertEqual(self.admin.call("GET", "me")[1]["user"]["role"], "member")
        self.assertEqual(self.admin.call("GET", "users")[0], 403)
        roles = [u["role"] for u in self.shuvo.call("GET", "users")[1]["users"]]
        self.assertEqual(roles.count("admin"), 1)

    def test_admin_cannot_remove_themselves(self):
        me = self.admin.call("GET", "me")[1]["user"]["id"]
        self.assertEqual(self.admin.call("DELETE", f"users/{me}")[0], 400)

    def test_removing_an_account_keeps_the_sheet(self):
        before = self.state(self.admin)["calc"]["total_due"]
        shuvo_id = self.shuvo.call("GET", "me")[1]["user"]["id"]
        _, s = self.shuvo.call("POST", f"months/{YM}/bills", {"name": "Gas", "amount": "0"})
        self.assertEqual(self.admin.call("DELETE", f"users/{shuvo_id}")[0], 200)
        self.assertEqual(self.shuvo.call("GET", "me")[0], 401)
        after = self.state(self.admin)
        self.assertEqual(after["calc"]["total_due"], before)
        self.assertIn("Shuvo", [m["name"] for m in after["members"]])
        self.assertIsNone(next(b for b in after["bills"] if b["name"] == "Gas")["owner_id"])

    def test_mess_name(self):
        self.assertEqual(self.admin.call("PUT", "settings", {"mess_name": "Royal Mess"})[0], 200)
        self.assertEqual(Client().call("GET", "public")[1]["mess_name"], "Royal Mess")
        self.assertEqual(self.shuvo.call("GET", "me")[1]["mess_name"], "Royal Mess")
        self.assertEqual(self.admin.call("PUT", "settings", {"mess_name": ""})[0], 400)

    def test_dwellers(self):
        s = self.state(self.admin)
        path = f"months/{YM}/members"
        side = s["sides"][0]["id"]
        status, s = self.admin.call("POST", path, {"name": "Tanvir", "side_id": side, "rent": "3,000"})
        self.assertEqual(status, 200)
        tanvir = next(m for m in s["members"] if m["name"] == "Tanvir")
        self.assertEqual(tanvir["rent"], 3000)
        self.assertEqual(self.admin.call("POST", path, {"name": "tanvir", "side_id": side})[0], 409)
        _, s = self.admin.call("PUT", f"{path}/{tanvir['id']}", {"name": "Tanvir H", "side_id": side, "rent": 3500})
        self.assertEqual(next(m for m in s["members"] if m["id"] == tanvir["id"])["rent"], 3500)
        self.assertEqual(self.admin.call("DELETE", f"{path}/{tanvir['id']}")[0], 200)

    def test_linking_an_account(self):
        path = f"months/{YM}/members"
        s = self.state(self.admin)
        arif = next(m for m in s["members"] if m["name"] == "Arif")
        user = self.account("Someone", "4.4.4.4")
        self.approve(self.admin, user)
        self.admin.call("DELETE", f"{path}/{self.member_id(self.admin, 'Someone')}")
        uid = self.user_id(user)
        body = {"name": "Arif", "side_id": arif["side_id"], "rent": arif["rent"], "user_id": uid}
        self.assertEqual(self.admin.call("PUT", f"{path}/{arif['id']}", body)[0], 200)
        self.assertEqual(self.state(user)["me"]["member_id"], arif["id"])
        rakib = next(m for m in s["members"] if m["name"] == "Rakib")
        clash = {"name": "Rakib", "side_id": rakib["side_id"], "rent": 0, "user_id": uid}
        self.assertEqual(self.admin.call("PUT", f"{path}/{rakib['id']}", clash)[0], 409)

    def test_months(self):
        self.assertEqual(self.admin.call("POST", "months", {"month": "2026-11", "copy_from": YM})[0], 200)
        self.assertEqual(self.admin.call("POST", "months", {"month": "2026-11"})[0], 409)
        self.assertEqual(self.admin.call("POST", "months", {"month": "2026-13"})[0], 400)
        november = self.admin.call("GET", "months/2026-11")[1]
        self.assertEqual((len(november["members"]), len(november["bills"]), november["days"]), (9, 10, 30))
        self.assertEqual((november["bazar"], november["payments"]), ([], []))
        self.assertEqual(self.admin.call("POST", "months", {"month": "2026-12"})[0], 200)
        self.assertEqual(len(self.admin.call("GET", "months/2026-12")[1]["sides"]), 1)
        self.assertEqual(self.admin.call("DELETE", "months/2026-12")[1]["months"], ["2026-11", YM])
        self.assertEqual(self.admin.call("DELETE", "months/2026-11")[0], 200)
        self.assertEqual(self.state(self.admin)["calc"]["total_due"], 37062)


class Profile(Mess):
    def details(self, **changes):
        return {"name": "Shuvo", "username": "shuvo", "email": "shuvo@x.test", **changes}

    def test_name_change_shows_across_the_sheet(self):
        self.assertEqual(self.shuvo.call("PUT", "me", self.details(name="Shuvo Roy"))[0], 200)
        self.assertIn("Shuvo Roy", [m["name"] for m in self.state(self.admin)["members"]])

    def test_clashes_are_refused(self):
        self.assertEqual(self.shuvo.call("PUT", "me", self.details(name="Arif"))[0], 409)
        self.assertEqual(self.shuvo.call("PUT", "me", self.details(username="sakib"))[0], 409)
        self.assertEqual(self.shuvo.call("PUT", "me", self.details(email="sakib@x.test"))[0], 409)


class Inputs(Mess):
    def test_sum_amounts(self):
        self.assertEqual(api.parse_amount_sum("100+30+150+1800"), (2080, "100+30+150+1800"))
        self.assertEqual(api.parse_amount_sum("1,200"), (1200, ""))
        self.assertEqual(api.parse_amount_sum("500-100"), (400, "500-100"))
        for bad in ("abc", "", "1+", "2*3", "-5"):
            with self.assertRaises(api.ApiError):
                api.parse_amount_sum(bad)

    def test_numbers_as_shown_on_screen(self):
        self.assertEqual(api.number({"amount": "৳1,200.50"}, "amount"), 1200.5)
        self.assertEqual(api.number({"amount": "−223"}, "amount"), -223)

    def test_bad_values_are_refused(self):
        member = self.member_id(self.admin, "Shuvo")
        path = f"months/{YM}"
        for bad in ({"day": 32, "qty": 1}, {"day": 1, "qty": -1}, {"day": 1, "qty": "x"}):
            self.assertEqual(self.admin.call("PUT", f"{path}/meals", {"member_id": member, **bad})[0], 400, bad)
        out = {"member_id": member, "date": "2026-11-01", "item": "x", "amount": 1}
        self.assertEqual(self.admin.call("POST", f"{path}/bazar", out)[0], 400)

    def test_every_row_saves_unchanged(self):
        before = self.state(self.admin)
        path = f"months/{YM}"
        for b in before["bazar"]:
            self.assertEqual(self.admin.call("PUT", f"{path}/bazar/{b['id']}", b)[0], 200)
        for p in before["payments"]:
            self.assertEqual(self.admin.call("PUT", f"{path}/payments/{p['id']}", p)[0], 200)
        for b in before["bills"]:
            self.assertEqual(self.admin.call("PUT", f"{path}/bills/{b['id']}", {**b, "amount": b["breakdown"] or b["amount"]})[0], 200)
        for m in before["members"]:
            self.assertEqual(self.admin.call("PUT", f"{path}/members/{m['id']}", m)[0], 200)
        for s in before["sides"]:
            self.assertEqual(self.admin.call("PUT", f"{path}/sides/{s['id']}", s)[0], 200)
        self.assertEqual(self.state(self.admin), before)


class Hardening(Mess):
    def test_writes_from_another_site_are_refused(self):
        status, _ = self.shuvo.call("POST", f"months/{YM}/bills", {"name": "x", "amount": "1"},
                                     headers={"HTTP_ORIGIN": "https://evil.example.com"})
        self.assertEqual(status, 403)
        status, _ = self.shuvo.call("POST", f"months/{YM}/bills", {"name": "x", "amount": "1"},
                                     headers={"HTTP_ORIGIN": "https://mess.example.com"})
        self.assertEqual(status, 200)

    def test_only_json_is_accepted(self):
        status, _ = self.shuvo.call("POST", "logout", {"a": 1}, headers={"CONTENT_TYPE": "text/plain"})
        self.assertEqual(status, 415)

    def test_security_headers(self):
        seen, _ = Client().raw("GET", "/login")
        headers = dict(seen["headers"])
        self.assertIn("default-src 'self'", headers["Content-Security-Policy"])
        self.assertEqual(headers["X-Frame-Options"], "DENY")

    def test_form_fields_are_not_read_by_indexing_elements(self):
        # form.elements["item"] is the built-in item() method, which broke v1's bazar form.
        source = (ROOT / "static" / "app.js").read_text(encoding="utf-8")
        self.assertIsNone(re.search(r"\.elements\[", source))


if __name__ == "__main__":
    unittest.main()

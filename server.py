#!/usr/bin/env python3
"""BlueBlood: a monthly cost tracker for a shared bachelor flat.

Standard library only. Run `python3 server.py`, then open http://127.0.0.1:8100
Hosting services import `application` from this file (WSGI).
"""
import argparse
import json
import os
import time
import traceback
from contextlib import closing
from http.cookies import CookieError, SimpleCookie
from pathlib import Path
from socketserver import ThreadingMixIn
from urllib.parse import urlsplit
from wsgiref.simple_server import WSGIRequestHandler, WSGIServer, make_server

import api
import auth
import db as database
import mailer
from api import ApiError

ROOT = Path(__file__).resolve().parent
ASSETS = {
    "/style.css": ("style.css", "text/css; charset=utf-8"),
    "/theme.js": ("theme.js", "text/javascript; charset=utf-8"),
    "/motion.js": ("motion.js", "text/javascript; charset=utf-8"),
    "/app.js": ("app.js", "text/javascript; charset=utf-8"),
    "/auth.js": ("auth.js", "text/javascript; charset=utf-8"),
}
HTML = "text/html; charset=utf-8"
COOKIE = "bb_session"
MAX_BODY = 64 * 1024
DB_PATH = ROOT / "mess.db"
MAIL_PATH = ROOT / "mail.json"
DEV = False     # only main() sets this, and only for a run on this computer

REASONS = {200: "OK", 302: "Found", 400: "Bad Request", 401: "Unauthorized", 403: "Forbidden",
           404: "Not Found", 409: "Conflict", 413: "Content Too Large",
           415: "Unsupported Media Type", 429: "Too Many Requests",
           500: "Internal Server Error"}
SECURITY_HEADERS = [
    ("X-Content-Type-Options", "nosniff"),
    ("X-Frame-Options", "DENY"),
    ("Referrer-Policy", "same-origin"),
    ("Content-Security-Policy", "default-src 'self'; style-src 'self' 'unsafe-inline';"
                                " img-src 'self' data:; base-uri 'none'; form-action 'self'"),
]


def json_response(status, payload, headers=()):
    body = json.dumps(payload, ensure_ascii=False).encode()
    return status, [("Content-Type", "application/json; charset=utf-8"),
                    ("Cache-Control", "no-store"), *headers], body


def static_file(name, kind):
    return 200, [("Content-Type", kind), ("Cache-Control", "no-cache")], \
        (ROOT / "static" / name).read_bytes()


def redirect(where):
    return 302, [("Location", where), ("Cache-Control", "no-store")], b""


def read_body(environ):
    try:
        length = int(environ.get("CONTENT_LENGTH") or 0)
    except ValueError:
        raise ApiError(400, "Invalid request") from None
    if length > MAX_BODY:
        raise ApiError(413, "Request is too large")
    raw = environ["wsgi.input"].read(length) if length else b""
    # Requiring JSON stops other websites from posting here through a browser,
    # since a cross-origin JSON request needs a preflight we refuse.
    if raw and "application/json" not in environ.get("CONTENT_TYPE", ""):
        raise ApiError(415, "Send JSON")
    try:
        body = json.loads(raw or b"{}")
    except ValueError:
        raise ApiError(400, "Invalid JSON") from None
    if not isinstance(body, dict):
        raise ApiError(400, "Invalid JSON")
    return body


def session_cookie(environ, value, max_age):
    https = (environ.get("wsgi.url_scheme") == "https"
             or environ.get("HTTP_X_FORWARDED_PROTO") == "https")
    return ("Set-Cookie", f"{COOKIE}={value}; Path=/; Max-Age={max_age}; HttpOnly; SameSite=Lax"
            + ("; Secure" if https else ""))


def read_token(environ):
    cookies = SimpleCookie()
    try:
        cookies.load(environ.get("HTTP_COOKIE", ""))
    except CookieError:
        return ""
    return cookies[COOKIE].value if COOKIE in cookies else ""


def current_user(db, token):
    if not token:
        return None
    return db.execute(
        "SELECT u.* FROM users u JOIN sessions s ON s.user_id = u.id"
        " WHERE s.token_hash = ? AND s.expires_at > ?",
        (auth.token_hash(token), time.time())).fetchone()


def check_origin(environ, method):
    """A second guard on top of SameSite cookies: writes must come from this site."""
    origin = environ.get("HTTP_ORIGIN")
    if method != "GET" and origin and urlsplit(origin).netloc != environ.get("HTTP_HOST"):
        raise ApiError(403, "Request from another site")


def run_api(environ, db, user, token, method, path):
    check_origin(environ, method)
    for route_method, pattern, fn, access in api.ROUTES:
        match = pattern.match(path)
        if not match or route_method != method:
            continue
        if access != api.PUBLIC and user is None:
            raise ApiError(401, "Please sign in")
        if access in (api.USER, api.ADMIN) and user["status"] != "active":
            raise ApiError(403, "The admin hasn't approved your account yet")
        if access == api.ADMIN and user["role"] != "admin":
            raise ApiError(403, "Only the admin can do this")
        ctx = api.Ctx(db, user=user, token=token,
                      ip=environ.get("HTTP_X_REAL_IP") or environ.get("REMOTE_ADDR") or "unknown",
                      dev=DEV, mail=mailer.load(MAIL_PATH),
                      base_url=f"{environ.get('wsgi.url_scheme', 'http')}://{environ.get('HTTP_HOST', '')}")
        try:
            result = fn(ctx, read_body(environ), *match.groups())
            db.commit()
        except Exception:
            db.rollback()
            raise
        headers = []
        if ctx.new_cookie is not None:
            headers.append(session_cookie(environ, *ctx.new_cookie))
        return json_response(200, result, headers)
    raise ApiError(404, "Not found")


def route(environ):
    method, path = environ["REQUEST_METHOD"], environ.get("PATH_INFO", "/")
    if path in ASSETS and method == "GET":
        return static_file(*ASSETS[path])

    token = read_token(environ)
    with closing(database.connect(DB_PATH)) as db:
        user = current_user(db, token)
        if path.startswith("/api/"):
            return run_api(environ, db, user, token, method, path)
    if method == "GET":
        if path == "/login":
            return redirect("/") if user else static_file("auth.html", HTML)
        if path == "/reset":
            return static_file("auth.html", HTML)
        if path == "/waiting":
            if user is None:
                return redirect("/login")
            return static_file("auth.html", HTML) if user["status"] == "pending" else redirect("/")
        if path == "/":
            if user is None:
                return redirect("/login")
            return redirect("/waiting") if user["status"] == "pending" else static_file("index.html", HTML)
    raise ApiError(404, "Not found")


def application(environ, start_response):
    head = environ["REQUEST_METHOD"] == "HEAD"
    if head:
        environ = {**environ, "REQUEST_METHOD": "GET"}
    try:
        status, headers, body = route(environ)
    except ApiError as e:
        status, headers, body = json_response(e.status, {"error": e.message})
    except Exception:
        traceback.print_exc(file=environ["wsgi.errors"])
        status, headers, body = json_response(500, {"error": "Something went wrong on the server"})
    start_response(f"{status} {REASONS[status]}",
                   [*headers, ("Content-Length", str(len(body))), *SECURITY_HEADERS])
    return [b"" if head else body]


class QuietHandler(WSGIRequestHandler):
    def log_message(self, format, *args):
        pass


class ThreadingServer(ThreadingMixIn, WSGIServer):
    daemon_threads = True


def main():
    global DB_PATH, MAIL_PATH, DEV
    parser = argparse.ArgumentParser(description="BlueBlood server")
    parser.add_argument("--host", default="127.0.0.1",
                        help="use 0.0.0.0 to let phones on the same Wi-Fi connect")
    parser.add_argument("--port", type=int, default=int(os.environ.get("PORT", 8100)))
    parser.add_argument("--db", default=str(DB_PATH))
    parser.add_argument("--mail", default=str(MAIL_PATH))
    args = parser.parse_args()

    DB_PATH, MAIL_PATH = args.db, args.mail
    DEV = args.host in ("127.0.0.1", "localhost", "::1")
    database.init_db(DB_PATH)
    server = make_server(args.host, args.port, application,
                         server_class=ThreadingServer, handler_class=QuietHandler)
    print(f"BlueBlood is running at http://{args.host}:{args.port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
else:
    database.init_db(DB_PATH)

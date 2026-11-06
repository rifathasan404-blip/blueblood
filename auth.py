"""Passwords and random tokens. Only hashes are ever stored."""
import hashlib
import hmac
import secrets

ITERATIONS = 300_000
SESSION_SECONDS = 90 * 24 * 3600
RESET_SECONDS = 3600
MIN_PASSWORD = 8


def _derive(password, salt, iterations):
    return hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), iterations).hex()


def hash_password(password):
    salt = secrets.token_hex(16)
    return salt, _derive(password, salt, ITERATIONS), ITERATIONS


def check_password(password, salt, iterations, expected):
    return hmac.compare_digest(_derive(password, salt, iterations), expected)


# Used for unknown accounts, so a wrong username takes as long as a wrong password.
_DUMMY = secrets.token_hex(16)


def burn_time(password):
    _derive(password, _DUMMY, ITERATIONS)


def token_hash(token):
    return hashlib.sha256(token.encode()).hexdigest()


def new_token():
    """Returns (the secret for the browser or email, the hash for the database)."""
    token = secrets.token_urlsafe(32)
    return token, token_hash(token)

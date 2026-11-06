"""Sends password reset emails.

Copy mail.example.json to mail.json and fill it in to send real email. With no
mail.json nothing can be delivered: a local run shows the link on screen instead,
and a hosted run logs that mail is not set up.
"""
import json
import smtplib
import ssl
from email.message import EmailMessage


def load(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return None


def build_reset_message(sender, to, name, mess, link):
    message = EmailMessage()
    message["Subject"] = f"Reset your {mess} password"
    message["From"] = sender
    message["To"] = to
    message.set_content(
        f"Hi {name},\n\n"
        f"Someone asked to reset your {mess} password. Open this link to choose a new one:\n\n"
        f"{link}\n\n"
        "The link works once and expires in one hour.\n"
        "If this wasn't you, ignore this email and your password stays the same.\n")
    return message


def send_reset(config, to, name, mess, link):
    message = build_reset_message(config.get("from") or config["username"], to, name, mess, link)
    context = ssl.create_default_context()
    port = int(config.get("port", 587))
    if port == 465:
        with smtplib.SMTP_SSL(config["host"], port, timeout=20, context=context) as smtp:
            smtp.login(config["username"], config["password"])
            smtp.send_message(message)
    else:
        with smtplib.SMTP(config["host"], port, timeout=20) as smtp:
            smtp.starttls(context=context)
            smtp.login(config["username"], config["password"])
            smtp.send_message(message)

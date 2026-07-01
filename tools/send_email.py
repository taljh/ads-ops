#!/usr/bin/env python3
"""
send_email.py — send an HTML report by email via Gmail SMTP.

Credentials come from ENV (never hard-code, never pass on the CLI):
    GMAIL_ADDRESS        sender + default recipient (e.g. t.aljh98@gmail.com)
    GMAIL_APP_PASSWORD   a Gmail App Password (16 chars, from Google Account →
                         Security → App passwords). NOT your normal password.

Usage:
    python3 tools/send_email.py <html_file> --subject "Daily Brief — 2026-07-01" \
        [--to someone@x.com] [--dry-run]

Exit codes: 0 sent (or dry-run ok), 2 missing creds, 3 send failure.
"""

import argparse
import os
import smtplib
import ssl
import sys
from email.message import EmailMessage
from pathlib import Path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("html_file")
    ap.add_argument("--subject", required=True)
    ap.add_argument("--to", default=None, help="recipient (defaults to GMAIL_ADDRESS)")
    ap.add_argument("--dry-run", action="store_true", help="validate without sending")
    args = ap.parse_args()

    sender = os.environ.get("GMAIL_ADDRESS", "").strip()
    app_pw = os.environ.get("GMAIL_APP_PASSWORD", "").strip()
    recipient = (args.to or sender).strip()

    html = Path(args.html_file).read_text(encoding="utf-8")

    msg = EmailMessage()
    msg["Subject"] = args.subject
    msg["From"] = sender or "unset@localhost"
    msg["To"] = recipient
    msg.set_content("This report is best viewed as HTML. See the HTML part.")
    msg.add_alternative(html, subtype="html")

    if args.dry_run:
        print(f"[dry-run] would send '{args.subject}' from {sender or '<GMAIL_ADDRESS unset>'} "
              f"to {recipient or '<unset>'} ({len(html)} bytes html)")
        return 0

    if not sender or not app_pw:
        sys.stderr.write("ERROR: set GMAIL_ADDRESS and GMAIL_APP_PASSWORD env secrets.\n")
        return 2

    try:
        ctx = ssl.create_default_context()
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=ctx, timeout=30) as s:
            s.login(sender, app_pw)
            s.send_message(msg)
        print(f"sent '{args.subject}' to {recipient}")
        return 0
    except Exception as e:  # noqa: BLE001
        sys.stderr.write(f"ERROR sending email: {e}\n")
        return 3


if __name__ == "__main__":
    sys.exit(main())

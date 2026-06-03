#!/usr/bin/env python3
"""Smoke-test SMTP + usage alert helpers (loads .env from repo root)."""

from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

try:
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env")
except ImportError:
    pass

import usage_alerts as ua
from env_defaults import env_defaults_dict


def main() -> int:
    print("=== ACTR email smoke test ===\n")
    ed = env_defaults_dict()
    print("Resolved env_defaults:")
    for k, v in ed.items():
        print(f"  {k}: {v}")

    host = (os.getenv("SMTP_HOST") or "").strip()
    ops = ua._ops_recipients()
    print(f"\nSMTP_HOST: {host or '(not set)'}")
    print(f"ALERT_EMAIL_TO recipients: {len(ops)}")
    for addr in ops:
        print(f"  - {addr}")

    print(f"\n_cap_alerts_enabled: {ua._cap_alerts_enabled()}")
    print(f"_alert_enabled (burst/hourly): {ua._alert_enabled()}")

    if not host:
        print("\nFAIL: SMTP_HOST missing — set in .env")
        return 1
    if not ops:
        print("\nFAIL: ALERT_EMAIL_TO missing or invalid")
        return 1

    subject = "[ACTR] SMTP smoke test"
    body = (
        "This is a manual smoke test from scripts/test_email_alerts.py.\n"
        f"Time (UTC): {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')}\n"
        "If you received this, cap and burst alert email delivery is configured."
    )
    # Send only to first ops address to avoid spamming the whole list
    test_to = [ops[0]]
    print(f"\nSending test email to: {test_to[0]} ...")
    ok = ua._send_email(subject, body, test_to)
    if ok:
        print("OK: send succeeded (check inbox/spam).")
        return 0
    print("FAIL: _send_email returned False (see warning above).")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())

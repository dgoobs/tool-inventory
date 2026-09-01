# Tool Inventory

A small Flask app for tracking shop tool checkouts — who has which tool, which van it's in, and what's still in the shop.

## How it works

- Every tool gets a QR code sticker. **Scanning it is the only way to check a tool in or out** — there's no button for it on the dashboard, so nobody can claim a tool was returned without actually having its tag.
- Scan an in-shop tool to check it out (enter employee name + van number). Scan it again to check it back in.
- The dashboard shows live status for every tool, plus full checkout history.
- An **admin password** (separate from the everyday shop password) unlocks manual overrides — check-out/in without scanning, fixing a typo'd entry, and retiring a tool that's out of service — each still re-asking for the password before it takes effect. Every manual action is flagged in the history so it's clear when the normal QR flow was bypassed.
- Retiring a tool hides it from the dashboard and QR sheet without deleting its history; it can be reactivated later.

## Running locally

```bash
python -m venv .venv
.venv/Scripts/pip install -r requirements.txt   # .venv/bin/pip on macOS/Linux
.venv/Scripts/python app.py                     # .venv/bin/python on macOS/Linux
```

Opens at `http://localhost:5000`. With no `SHOP_PASSWORD`/`ADMIN_PASSWORD` env vars set, the login gate is disabled — handy for local dev, but set both before deploying anywhere real.

## Deploying

See [deploy/README.md](deploy/README.md) — scripts to run this on a Google Cloud Compute Engine VM (fits the always-free tier).

## Stack

Flask, SQLAlchemy + SQLite, `qrcode` for generating QR codes server-side. No JS framework — server-rendered templates only.

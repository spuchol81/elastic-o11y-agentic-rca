#!/usr/bin/env python3
"""
Kibana dashboard setup for the ShopEasy RCA demo.

Instruqt variant of ../setup_dashboard.py — identical import logic, pointed
at the self-hosted Kibana running inside the Instruqt sandbox VM instead of
an Elastic Cloud deployment. Only the connection bootstrap differs; the
dashboard NDJSON is read from the repo root so there is a single source of
truth for both deployment modes.

Imports (or overwrites) the ShopEasy Mission Control dashboard from
shopeasy_mission_control.ndjson into the default space.

Run after ingest.py — requires KB_URL/KB_USER/KB_PASS env vars
(see setup_elastic.sh for defaults).
"""

import os, json, base64, urllib.request, urllib.error
from pathlib import Path

# ── Connection (Instruqt self-hosted cluster) ───────────────────────────────────

KB_URL  = os.environ.get("KB_URL", "http://kubernetes-vm:30001")
KB_USER = os.environ.get("KB_USER", "elastic")
KB_PASS = os.environ.get("KB_PASS", "changeme")

NDJSON_FILE    = Path(__file__).resolve().parent.parent / "shopeasy_mission_control.ndjson"
DASHBOARD_NAME = "ShopEasy Mission Control"

# ── Setup ─────────────────────────────────────────────────────────────────────

def setup_dashboard() -> None:
    print("Setting up dashboard …\n")

    file_data = NDJSON_FILE.read_bytes()
    boundary  = "shopeasy-boundary-12345"
    body = (
        f"--{boundary}\r\n"
        f"Content-Disposition: form-data; name=\"file\"; filename=\"{NDJSON_FILE.name}\"\r\n"
        f"Content-Type: application/ndjson\r\n\r\n"
    ).encode() + file_data + f"\r\n--{boundary}--\r\n".encode()

    headers = {
        "Authorization": "Basic " + base64.b64encode(f"{KB_USER}:{KB_PASS}".encode()).decode(),
        "kbn-xsrf":      "true",
        "Content-Type":  f"multipart/form-data; boundary={boundary}",
    }

    req = urllib.request.Request(
        f"{KB_URL}/api/saved_objects/_import?overwrite=true",
        body, headers, method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            resp = json.loads(r.read())
    except urllib.error.HTTPError as e:
        print(f"  [FAILED]  HTTP {e.code}: {e.read().decode()[:200]}")
        return

    if resp.get("success"):
        print(f"  [ok]      {DASHBOARD_NAME}  ({resp['successCount']} object(s) imported)")
    else:
        for err in resp.get("errors", []):
            print(f"  [FAILED]  {err['meta'].get('title', err['id'])}  → {err['error']}")
    print()


if __name__ == "__main__":
    setup_dashboard()

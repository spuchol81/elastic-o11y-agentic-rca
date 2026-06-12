#!/usr/bin/env python3
"""
Kibana dashboard setup for the ShopEasy RCA demo.

Imports (or overwrites) the ShopEasy Mission Control dashboard from
shopeasy_mission_control.ndjson into the default space.

Run after ingest.py — requires ES_CLOUD_ID and ES_API_KEY env vars.
"""

import os, json, base64, urllib.request, urllib.error
from pathlib import Path

# ── Connection ────────────────────────────────────────────────────────────────

def _kb_url(cloud_id: str) -> str:
    _, b64 = cloud_id.split(":", 1)
    host, _es, kb_uuid = base64.b64decode(b64 + "==").decode().split("$")
    return f"https://{kb_uuid}.{host}"

KB_URL  = _kb_url(os.environ["ES_CLOUD_ID"])
API_KEY = os.environ["ES_API_KEY"]

NDJSON_FILE    = Path(__file__).parent / "shopeasy_mission_control.ndjson"
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
        "Authorization": f"ApiKey {API_KEY}",
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

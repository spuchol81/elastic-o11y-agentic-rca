#!/usr/bin/env python3
"""
Kibana Workflow setup for the ShopEasy alert triage demo.

Creates or updates:
  workflow_alert_triage  — alert-triggered RCA + case + Slack notification

If the workflow already exists it is updated in-place via
PUT /api/workflows/workflow/{id} so the ID is preserved.
Kibana permanently reserves deleted IDs — never delete and recreate.

Run after setup_agent.py — requires ES_CLOUD_ID and ES_API_KEY env vars.
"""

import os, json, base64, urllib.request, urllib.error
from pathlib import Path

# ── Connection ────────────────────────────────────────────────────────────────

def _kb_url(cloud_id: str) -> str:
    _, b64 = cloud_id.split(":", 1)
    host, _es, kb_uuid = base64.b64decode(b64 + "==").decode().split("$")
    return f"https://{kb_uuid}.{host}"

KB_URL  = _kb_url(os.environ["ES_CLOUD_ID"])
HEADERS = {
    "Authorization": f"ApiKey {os.environ['ES_API_KEY']}",
    "Content-Type":  "application/json",
    "kbn-xsrf":      "true",
}

WORKFLOW_FILE = Path(__file__).parent / "workflow_alert_triage.yaml"
WORKFLOW_NAME = "ShopEasy — Alert Triage"


def kb(method, path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req  = urllib.request.Request(f"{KB_URL}{path}", data, HEADERS, method=method)
    try:
        with urllib.request.urlopen(req) as r:
            raw = r.read()
            return (json.loads(raw) if raw else {}), r.status
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            return json.loads(raw), e.code
        except Exception:
            return {"raw": raw.decode(errors="replace")}, e.code


def get_workflow_id(name: str) -> str | None:
    """Return the current ID of the named workflow, or None if not found."""
    resp, status = kb("GET", "/api/workflows")
    if status != 200:
        return None
    for wf in resp.get("results", []):
        if wf.get("name") == name:
            return wf["id"]
    return None


def setup_workflow() -> None:
    print("Setting up workflow …\n")

    yaml_str    = WORKFLOW_FILE.read_text()
    existing_id = get_workflow_id(WORKFLOW_NAME)

    if existing_id:
        # Update in-place — ID is preserved (deleted IDs are permanently reserved by Kibana)
        resp, status = kb("PUT", f"/api/workflows/workflow/{existing_id}", {"yaml": yaml_str})
        if status in (200, 201):
            print(f"  [ok]  {WORKFLOW_NAME}  (updated, id={existing_id})")
            return
        print(f"  [FAILED]  update  → {status}: {resp}")
        return

    resp, status = kb("POST", "/api/workflows", {"workflows": [{"yaml": yaml_str}]})
    created = resp.get("created", [])
    failed  = resp.get("failed",  [])
    if status in (200, 201) and created:
        print(f"  [ok]  {WORKFLOW_NAME}  (created, id={created[0]['id']})")
        return
    if failed:
        print(f"  [FAILED]  {WORKFLOW_NAME}  → {failed[0].get('error')}")
        return

    print(f"  [FAILED]  {WORKFLOW_NAME}  → {status}: {resp}")


if __name__ == "__main__":
    setup_workflow()

#!/usr/bin/env python3
"""
Kibana Workflow setup for the ShopEasy alert triage demo.

Instruqt variant of ../setup_workflow.py — same create/update logic, pointed
at the self-hosted Kibana running inside the Instruqt sandbox VM instead of
an Elastic Cloud deployment. Reads its OWN workflow_alert_triage.yaml from
this directory (not the repo root) because the step-type syntax diverges:
this version targets Kibana 9.4.2's reorganized Workflows API (ai.agent for
Agent Builder calls, cases.* for case management, instead of the generic
kibana.request escape hatch the root file still uses).

Creates or updates:
  workflow_alert_triage  — alert-triggered RCA + case + Slack notification

If the workflow already exists it is updated in-place via
PUT /api/workflows/workflow/{id} so the ID is preserved.
Kibana permanently reserves deleted IDs — never delete and recreate.

Run after setup_agent.py — requires KB_URL/KB_USER/KB_PASS env vars
(see setup_elastic.sh for defaults).
"""

import os, json, base64, urllib.request, urllib.error
from pathlib import Path

# ── Connection (Instruqt self-hosted cluster) ───────────────────────────────────

KB_URL  = os.environ.get("KB_URL", "http://kubernetes-vm:30001")
KB_USER = os.environ.get("KB_USER", "elastic")
KB_PASS = os.environ.get("KB_PASS", "changeme")
HEADERS = {
    "Authorization": "Basic " + base64.b64encode(f"{KB_USER}:{KB_PASS}".encode()).decode(),
    "Content-Type":  "application/json",
    "kbn-xsrf":      "true",
}

WORKFLOW_FILE = Path(__file__).resolve().parent / "workflow_alert_triage.yaml"
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


def get_connector_id(name: str) -> str | None:
    """Return the current ID of the named Kibana connector, or None if not found."""
    resp, status = kb("GET", "/api/actions/connectors")
    if status != 200:
        return None
    for conn in resp:
        if conn.get("name") == name:
            return conn["id"]
    return None


def setup_workflow() -> None:
    print("Setting up workflow …\n")

    yaml_str = WORKFLOW_FILE.read_text()

    if "__MATTERMOST_CONNECTOR_ID__" in yaml_str:
        connector_id = get_connector_id("mattermost-incidents")
        if not connector_id:
            raise RuntimeError(
                "Mattermost connector 'mattermost-incidents' not found — "
                "run the Mattermost connector setup in setup_elastic.sh before setup_workflow.py"
            )
        yaml_str = yaml_str.replace("__MATTERMOST_CONNECTOR_ID__", connector_id)

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

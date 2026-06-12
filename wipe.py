#!/usr/bin/env python3
"""
Wipes all ShopEasy demo resources — data, ML, Kibana rules, agent builder, workflow, dashboard.
Does NOT recreate anything (run setup scripts after for idempotency testing).

Steps:
  1. Stop + delete all shopeasy ML datafeeds and jobs
  2. Delete Kibana alert rules tagged ["shopeasy", "ml"]
  3. Delete data streams and the APM index
  4. Delete Agent Builder: tools, skills, agent
  5. Delete cases
  6. Delete workflow
  7. Delete dashboard
  8. Query .ml-anomalies-* and report surviving job_ids + record counts

Run with: ES_CLOUD_ID=... ES_API_KEY=... python3 wipe.py
"""

import os, json, base64, urllib.request, urllib.error

# ── Connection ────────────────────────────────────────────────────────────────

def _urls_from_cloud_id(cloud_id: str) -> tuple[str, str]:
    _, b64 = cloud_id.split(":", 1)
    decoded = base64.b64decode(b64 + "==").decode()
    host, es_uuid, kb_uuid = decoded.split("$")
    return f"https://{es_uuid}.{host}", f"https://{kb_uuid}.{host}"

ES_URL, KB_URL = _urls_from_cloud_id(os.environ["ES_CLOUD_ID"])
API_KEY        = os.environ["ES_API_KEY"]
ES_HEADERS     = {"Authorization": f"ApiKey {API_KEY}", "Content-Type": "application/json"}
KB_HEADERS     = {**ES_HEADERS, "kbn-xsrf": "true"}

def call(method, path, body=None):
    data = json.dumps(body).encode() if body else None
    req  = urllib.request.Request(f"{ES_URL}{path}", data, ES_HEADERS, method=method)
    try:
        with urllib.request.urlopen(req) as r:
            return json.loads(r.read()), r.status
    except urllib.error.HTTPError as e:
        return json.loads(e.read()), e.code

def kb_call(method, path, body=None):
    data = json.dumps(body).encode() if body else None
    req  = urllib.request.Request(f"{KB_URL}{path}", data, KB_HEADERS, method=method)
    try:
        with urllib.request.urlopen(req) as r:
            raw = r.read()
            return (json.loads(raw) if raw else {}), r.status
    except urllib.error.HTTPError as e:
        raw = e.read()
        return (json.loads(raw) if raw else {}), e.code

JOB_IDS = [
    "shopeasy-firewall-rare-action",
    "shopeasy-checkout-errors",
    "shopeasy-vm-cpu-ready",
    "shopeasy-db-read-latency",
]

TOOL_IDS      = ["rca_app_availability", "rca_fetch_anomalies_in_window", "rca_lookup_datafeed"]
SKILL_IDS     = ["morning_meteo", "alert_analysis", "request_remediation"]
AGENT_ID      = "rca_agent"
WORKFLOW_NAME = "ShopEasy — Alert Triage"
DASHBOARD_ID  = "f8d67162-7acc-4403-b2d6-9a4c776b591a"

# ── 1. ML jobs + datafeeds ────────────────────────────────────────────────────

print("── ML jobs ──────────────────────────────────────────────────────────────")
for jid in JOB_IDS:
    _, s1 = call("POST",   f"/_ml/datafeeds/datafeed-{jid}/_stop?force=true")
    _, s2 = call("DELETE", f"/_ml/datafeeds/datafeed-{jid}")
    _, s3 = call("POST",   f"/_ml/anomaly_detectors/{jid}/_close?force=true")
    _, s4 = call("DELETE", f"/_ml/anomaly_detectors/{jid}")
    print(f"  {jid}: stop={s1} del-feed={s2} close={s3} del-job={s4}")

# ── 2. Kibana alert rules ─────────────────────────────────────────────────────

print("\n── Kibana alert rules ───────────────────────────────────────────────────")
resp, _ = kb_call("GET", "/api/alerting/rules/_find?per_page=200")
to_delete = [
    r["id"] for r in resp.get("data", [])
    if "shopeasy" in r.get("name", "").lower()
]
for rid in to_delete:
    _, status = kb_call("DELETE", f"/api/alerting/rule/{rid}")
    print(f"  [deleted] {rid} → {status}")
if not to_delete:
    print("  (none found)")

# ── 2b. Alert documents (.alerts-* indices) ───────────────────────────────────

print("\n── Alert documents ──────────────────────────────────────────────────────")
resp, status = call("POST", "/.alerts-*/_delete_by_query", {
    "query": {"wildcard": {"kibana.alert.rule.name": {"value": "*ShopEasy*"}}}
})
print(f"  deleted: {resp.get('deleted', 0)}  → {status}")

# ── 3. Data streams + APM index ───────────────────────────────────────────────

print("\n── Data streams + indices ───────────────────────────────────────────────")
for target, path in [
    ("logs-shopeasy.*",            "/_data_stream/logs-shopeasy.*"),
    ("metrics-shopeasy.*",         "/_data_stream/metrics-shopeasy.*"),
    ("traces-apm.shopeasy-default","traces-apm.shopeasy-default"),
]:
    _, status = call("DELETE", f"/{path}" if not path.startswith("/") else path)
    print(f"  {target}: {status}")

# ── 4. Agent Builder conversations ───────────────────────────────────────────

print("\n── Agent Builder conversations ──────────────────────────────────────────")
resp, _ = kb_call("GET", "/api/agent_builder/conversations")
convos = [c["id"] for c in resp.get("results", []) if c.get("agent_id") == AGENT_ID]
for cid in convos:
    _, s = kb_call("DELETE", f"/api/agent_builder/conversations/{cid}")
    print(f"  conversation {cid}: {s}")
if not convos:
    print("  (none found)")
else:
    print(f"  deleted {len(convos)} conversation(s)")

# ── 5. Agent Builder (tools, skills, agent) ──────────────────────────────────

print("\n── Agent Builder ────────────────────────────────────────────────────────")
_, s = kb_call("DELETE", f"/api/agent_builder/agents/{AGENT_ID}")
print(f"  agent  {AGENT_ID}: {s}")
for sid in SKILL_IDS:
    _, s = kb_call("DELETE", f"/api/agent_builder/skills/{sid}")
    print(f"  skill  {sid}: {s}")
for tid in TOOL_IDS:
    _, s = kb_call("DELETE", f"/api/agent_builder/tools/{tid}")
    print(f"  tool   {tid}: {s}")

# ── 5. Cases ─────────────────────────────────────────────────────────────────

print("\n── Cases ────────────────────────────────────────────────────────────────")
resp, _ = kb_call("GET", "/api/cases/_find?perPage=100")
case_ids = [c["id"] for c in resp.get("cases", []) if "shopeasy" in c.get("title", "").lower()]
if case_ids:
    # Cases delete requires repeated query params: ?ids=id1&ids=id2
    qs = "&".join(f"ids={cid}" for cid in case_ids)
    req = urllib.request.Request(f"{KB_URL}/api/cases?{qs}", None, KB_HEADERS, method="DELETE")
    try:
        with urllib.request.urlopen(req) as r:
            print(f"  deleted {len(case_ids)} case(s)  → {r.status}")
    except urllib.error.HTTPError as e:
        print(f"  [FAILED] cases delete → {e.code}: {e.read()}")
else:
    print("  (none found)")

# ── 6. Workflow ───────────────────────────────────────────────────────────────

print("\n── Workflow ─────────────────────────────────────────────────────────────")
wf_resp, _ = kb_call("GET", "/api/workflows")
wf_ids = [wf["id"] for wf in wf_resp.get("results", []) if wf.get("name") == WORKFLOW_NAME]
if wf_ids:
    resp, s = kb_call("DELETE", "/api/workflows", {"ids": wf_ids})
    print(f"  {wf_ids}: deleted={resp.get('deleted', 0)}  → {s}")
else:
    print(f"  (not found)")

# ── 7. Dashboard ─────────────────────────────────────────────────────────────

print("\n── Dashboard ────────────────────────────────────────────────────────────")
_, s = kb_call("DELETE", f"/api/saved_objects/dashboard/{DASHBOARD_ID}")
print(f"  ShopEasy Mission Control: {s}")

# ── 8. Check .ml-anomalies-* ─────────────────────────────────────────────────

print("\n── .ml-anomalies-* survivors ────────────────────────────────────────────")
resp, status = call("POST", "/.ml-anomalies-*/_search", {
    "size": 0,
    "query": {"term": {"result_type": "record"}},
    "aggs": {
        "by_job": {
            "terms": {"field": "job_id", "size": 50},
            "aggs": {"max_score": {"max": {"field": "record_score"}}},
        }
    },
})

if status != 200:
    print(f"  query failed ({status}): {resp}")
else:
    buckets = resp.get("aggregations", {}).get("by_job", {}).get("buckets", [])
    total   = resp["hits"]["total"]["value"]
    if not buckets:
        print("  ✓ no anomaly records remain")
    else:
        print(f"  {total} record(s) across {len(buckets)} job_id(s):\n")
        for b in sorted(buckets, key=lambda x: x["key"]):
            print(f"  {b['key']:<45}  count={b['doc_count']:>5}  max_score={b['max_score']['value']:.1f}")

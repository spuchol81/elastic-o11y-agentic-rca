#!/usr/bin/env python3
"""
Kibana Agent Builder setup for the ShopEasy RCA demo.

Creates:
  Tools (custom ESQL):
    rca_app_availability            — synthetics downtime buckets (incident windows)
    rca_fetch_anomalies_in_window   — ML anomalies scoped to one incident window
    rca_lookup_datafeed             — resolve ML job → source index

  Skills:
    morning_meteo                   — nightly weather-report procedure
    alert_analysis                  — alert-triggered single-incident RCA
    request_remediation             — remediation handoff + operator confirmation + case closure

  Agent:
    rca_agent                       — observability triage agent wired to the above

Run after ingest.py and setup_ml_jobs.py — requires ES_CLOUD_ID and ES_API_KEY env vars.
Use --force to delete and recreate existing resources.
"""

import os, json, base64, sys, urllib.request, urllib.error

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

def kb(method, path, body=None):
    data = json.dumps(body).encode() if body else None
    req  = urllib.request.Request(f"{KB_URL}{path}", data, HEADERS, method=method)
    try:
        with urllib.request.urlopen(req) as r:
            raw = r.read()
            return (json.loads(raw) if raw else {}), r.status
    except urllib.error.HTTPError as e:
        raw = e.read()
        return (json.loads(raw) if raw else {}), e.code

def upsert(resource, rid, post_path, put_path, body, force=False):
    """POST to create; if already exists PUT to update. --force deletes first."""
    if force:
        kb("DELETE", put_path)
    resp, status = kb("POST", post_path, body)
    if status in (200, 201):
        return True, "created"
    # Already exists — PUT without id/type (both are in the URL / immutable)
    put_body = {k: v for k, v in body.items() if k not in ("id", "type")}
    resp, status = kb("PUT", put_path, put_body)
    if status in (200, 201):
        return True, "updated"
    return False, f"{status}: {resp}"

# ── Custom tools ──────────────────────────────────────────────────────────────

TOOLS = [
    {
        "id": "rca_app_availability",
        "type": "esql",
        "description": (
            "Returns 10-minute buckets where synthetics detected failures over the last 24h.\n"
            "Use this to identify distinct incident windows: group contiguous non-zero buckets\n"
            "into a single window (start = first bucket, end = last bucket + 10 minutes)."
        ),
        "tags": ["RCA"],
        "configuration": {
            "query": (
                'FROM logs-shopeasy.synthetics-default\n'
                '| WHERE monitor.status == "down" AND @timestamp > NOW() - 1d\n'
                '| STATS failure_count = COUNT(*) BY time_bucket = DATE_TRUNC(10 minutes, @timestamp)\n'
                '| WHERE failure_count > 0\n'
                '| SORT time_bucket ASC\n'
                '| KEEP time_bucket, failure_count'
            ),
            "params": {},
        },
    },
    {
        "id": "rca_fetch_anomalies_in_window",
        "type": "esql",
        "description": (
            "Returns ML anomalies whose bucket falls within a specific incident window.\n"
            "Call once per incident window identified by rca_app_availability.\n"
            "Returns the highest-scoring record per (job_id, all_field_values) — naturally\n"
            "deduplicates without threshold tuning, and scopes to only the relevant incident.\n"
        ),
        "tags": ["RCA"],
        "configuration": {
            "query": (
                "FROM .ml-anomalies-*\n"
                "| WHERE result_type == \"record\"\n"
                "  AND timestamp >= ?window_start\n"
                "  AND timestamp <= ?window_end\n"
                "| SORT record_score DESC\n"
                "| KEEP job_id, all_field_values, timestamp, bucket_span, record_score"
            ),
            "params": {
                "window_start": {
                    "type": "date",
                    "description": "ncident start timestamp (from synthetics)",
                    "optional": False,
                },
                "window_end": {
                    "type": "date",
                    "description": "incident end timestamp (from synthetics)",
                    "optional": False,
                },
            },
        },
    },
    {
        "id": "rca_lookup_datafeed",
        "type": "esql",
        "description": (
            "Looks up the source indices a given ML job's datafeed reads from.\n"
            "Call this after identifying an anomaly to find out which index to query for raw signals.\n"
            "\n"
            "Parameter:\n"
            " ?job_id  — the job_id from the anomaly record (e.g. \"shopeasy-firewall-rare-action\")\n"
            "\n"
            "Output:\n"
            "indices  — list of index patterns the datafeed queries (e.g. \"logs-shopeasy.firewall-default\")\n"
        ),
        "tags": ["RCA"],
        "configuration": {
            "query": (
                "FROM .ml-config*\n"
                "| WHERE datafeed_id IS NOT NULL AND job_id == ?job_id\n"
                "| KEEP indices"
            ),
            "params": {
                "job_id": {
                    "type": "string",
                    "description": "the id of the ml job you want to get datafeed for",
                    "optional": False,
                },
            },
        },
    },
]

# ── Skill ─────────────────────────────────────────────────────────────────────

SKILLS = [
    {
        "id": "morning_meteo",
        "name": "morning_meteo",
        "description": "morning_meteo",
        "content": """\
# Skill: meteo — Nightly anomaly weather report

Surface all app incidents from the last 24 hours, identify the infrastructure and app components that contributed to each failure using ML anomalies, retrieve the raw signals that drove them, and explain the root cause from the logs.

---

## Procedure

### Step 1 — Identify incident windows
Call `rca_app_availability`. Group contiguous non-zero buckets into distinct windows
(gap of ≥ 20 minutes = separate incident). Record start and end for each window.
If none → stop.

### Step 2 — For each window: find correlated ML anomalies
Call `rca_fetch_anomalies_in_window(?window_start, ?window_end)`.

### Step 3 — For each anomaly: look up source index
Call `rca_lookup_datafeed(?job_id)` → returns `indices`.

### Step 4 — For each anomaly: fetch raw signals
```esql
FROM ?indices
| WHERE @timestamp >= ?bucketdate
  AND @timestamp < ?bucketdate + ?bucketspan
| SORT @timestamp ASC
```
### Step 5 — Build the story
One row per incident window in the summary table.

|Incident window |\tResponsible component |What happened|
|-----------------|--------------------------|-----------------|
|From synthetics timestamps|Designate the component based on logs/metrics index name and parameters|Root cause derived from raw log evidence

One sentence of root cause explanation per row, grounded in the log data — no speculation beyond what the signals show.

### Constraints

- Don't mention any ML job to the customer as it's purely backend stuff
""",
        "tool_ids": [],
    },
    {
        "id": "request_remediation",
        "name": "request_remediation",
        "description": "request_remediation",
        "content": """\
# Skill: request_remediation — Remediation handoff and case closure

You are given context about an incident that has been triaged, its case ID, and a workflow execution ID.

Do NOT call any tools for steps 1 and 2. Work only from the context provided.

## Procedure

### Step 1 — Post the remediation request
Output this exact message, nothing else:
"Please reply `resolved` here once you applied the fix for this issue and I will close the case automatically."

### Step 2 — Wait for operator confirmation
Pause and wait for the operator to reply `resolved` in this conversation.
Do not proceed until the operator sends that exact word.

### Step 3 — Resume the workflow to close the case
Call platform.core.resume_workflow_execution with:
  - execution_id: the workflow execution ID from the input
  - inputs: { "user_input": "resolved" }

Pass exactly that one field. Do not include resolved, notes, case_id, status, or any other field.

Confirm to the operator: "Case closed."
""",
        "tool_ids": [],
    },
    {
        "id": "alert_analysis",
        "name": "alert_analysis",
        "description": "alert_analysis",
        "content": """\
# Skill: alert_analysis — Alert-triggered incident RCA

Investigate the SINGLE incident that triggered the ML anomaly alert in the input.
Your investigation scope is strictly that one anomaly and its immediate time window.
Do NOT call rca_app_availability. Do NOT discover or report on other windows.

---

## Procedure

### Step 1 — Define the investigation window
Take the anomaly timestamp from the alert input. Do not call any tool for this step.
Set:
  window_start = anomaly_timestamp − 30 minutes
  window_end   = anomaly_timestamp + 30 minutes

### Step 2 — Fetch correlated anomalies in the window
Call `rca_fetch_anomalies_in_window(?window_start, ?window_end)`.
Multiple jobs may have fired for the same incident — include all of them.

### Step 3 — For each anomaly: resolve source index
Call `rca_lookup_datafeed(?job_id)` → returns `indices`.

### Step 4 — For each anomaly: fetch raw signals
```esql
FROM ?indices
| WHERE @timestamp >= ?bucketdate
  AND @timestamp < ?bucketdate + ?bucketspan
| SORT @timestamp ASC
```

### Step 5 — Produce structured RCA

Respond with this exact structure (one block, one incident).
Use Slack mrkdwn formatting: *bold* with single asterisks, plain bullet points with •.
Do NOT use Markdown: no **double asterisks**, no ## headers, no --- dividers.

*Time window:* start → end UTC
*User impact:* what was observed (service degradation, error types, affected endpoints)
*Root cause:* one sentence grounded in raw signal evidence
*Evidence chain:*
• earliest causal event
• next event
• …
*Responsible component:* the service, host, or system that caused the failure
*Responsible team:* one of — <!subteam^S0B9DGT8RST|@app-team> | <!subteam^S0B9DGUUFRV|@vmware-team> | <!subteam^S0B9NKM0YP5|@firewall-team>
*Recommended action:* what to do or verify next

### Responsible team assignment rules
- App code errors (NullPointerException, missing config, bad deploy) → <!subteam^S0B9DGT8RST|@app-team>
- VM / hypervisor / backup / disk I/O issues (cpu.ready, backup job, datastore) → <!subteam^S0B9DGUUFRV|@vmware-team>
- Firewall rules, routing, network configuration → <!subteam^S0B9NKM0YP5|@firewall-team>

### Hard constraints
- Investigate exactly ONE window derived from the anomaly timestamp. Stop after Step 5.
- Never call rca_app_availability — it returns all windows and will derail the scope.
- Never query unbounded time ranges.
- Do not mention ML jobs or anomaly scores in the output.
- Root cause must follow from raw signal evidence, not speculation.
- Output format must be Slack mrkdwn only — no Markdown headers, no double asterisks, no horizontal rules.
""",
        "tool_ids": [],
    },
]

# ── Agent ─────────────────────────────────────────────────────────────────────

AGENT_ID = "rca_agent"
AGENT_BODY = {
    "name": "rca_agent",
    "description": "rca_agent",
    "visibility": "public",
    "configuration": {
        "instructions": """\
You are an observability triage agent. Your job is to investigate incidents, identify root causes, and produce clear, evidence-based findings from Elastic observability data.

## How you work

You have access to tools that let you query Elastic. Use them to gather evidence before drawing conclusions. Follow the data — do not speculate beyond what the signals show.

When investigating:
1. **Start with symptoms** — establish what the user-facing impact was and when it started.
2. **Identify anomalies** — use available tools to surface ML anomaly signals near the incident window.
3. **Drill into raw signals** — for each anomaly, query the underlying data scoped to the anomaly bucket.
4. **Follow the signal chain** — move from user-facing symptoms toward root cause, layer by layer. Stop at the earliest causal event.
5. **Find the trigger** — root causes are almost always a change: a deployment, a config change, a scheduled job, a resource limit hit.

## General rules

- Always scope queries to a relevant time window. Never query unbounded ranges.
- All timestamps in Elastic are stored as UTC.
- Anomaly bucket timestamps mark the START of the bucket. The full window is `timestamp` to `timestamp + bucket_span`.
- If a query returns no results, widen the window by one bucket before concluding no signal exists.
- If the data is insufficient to determine root cause, say so and state what additional signal would be needed.

## Output

For each incident investigated, produce:

- **Time window** — start → end UTC
- **User impact** — what was observed from the outside
- **Root cause** — one sentence
- **Evidence chain** — ordered list of signals, earliest first
- **Recommended action** — what should be done or verified next
""",
        "tools": [
            {
                "tool_ids": [
                    "platform.core.list_indices",
                    "platform.core.get_index_mapping",
                    "platform.core.get_workflow_execution_status",
                    "platform.core.resume_workflow_execution",
                    "rca_lookup_datafeed",
                    "rca_app_availability",
                    "rca_fetch_anomalies_in_window",
                    "platform.core.execute_esql",
                    "platform.core.generate_esql",
                ]
            }
        ],
        "skill_ids": ["morning_meteo", "alert_analysis", "request_remediation"],
        "enable_elastic_capabilities": False,
        "workflow_ids": [],
        "plugin_ids": [],
    },
}

# ── Setup ─────────────────────────────────────────────────────────────────────

def setup_tools(force=False):
    print("Setting up custom tools …\n")
    for tool in TOOLS:
        tid = tool["id"]
        ok, msg = upsert("tool", tid, "/api/agent_builder/tools",
                         f"/api/agent_builder/tools/{tid}", tool, force)
        print(f"  {'[ok]' if ok else '[FAILED]'}  {tid}  ({msg})")
    print()


def setup_skills(force=False):
    print("Setting up skills …\n")
    for skill in SKILLS:
        sid = skill["id"]
        ok, msg = upsert("skill", sid, "/api/agent_builder/skills",
                         f"/api/agent_builder/skills/{sid}", skill, force)
        print(f"  {'[ok]' if ok else '[FAILED]'}  {sid}  ({msg})")
    print()


def setup_agent(force=False):
    print("Setting up agent …\n")
    if force:
        kb("DELETE", f"/api/agent_builder/agents/{AGENT_ID}")
    resp, status = kb("POST", "/api/agent_builder/agents",
                      {"id": AGENT_ID, **AGENT_BODY})
    if status in (200, 201):
        print(f"  [ok]      {AGENT_ID}  (created)")
    else:
        # Already exists — update via PUT
        resp, status = kb("PUT", f"/api/agent_builder/agents/{AGENT_ID}", AGENT_BODY)
        if status in (200, 201):
            print(f"  [ok]      {AGENT_ID}  (updated)")
        else:
            print(f"  [FAILED]  {AGENT_ID}  → {status}: {resp}")
    print()


if __name__ == "__main__":
    force = "--force" in sys.argv
    setup_tools(force=force)
    setup_skills(force=force)
    setup_agent(force=force)

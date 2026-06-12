---
name: project-context
description: Elastic agentic RCA demo — ShopEasy app scenario, data files, scripts, outage timeline, current status
metadata:
  type: project
---

Building an agentic incident triage + weather report demo inside Elastic using agents and skills.

**Why:** Demo showcasing automated RCA using Elastic observability data across multiple signal types.

---

## Repo layout

```
elastic-o11y-agentic-rca/
  generate.py                     # generates all NDJSON files — 5d baseline + outage night
  ingest.py                       # wipes cluster, calls generate.py, then ingests into Elastic
  setup_ml_jobs.py                # creates 4 ML jobs + 4 Kibana alert rules (wired to workflow)
  setup_agent.py                  # creates custom tools, skills, rca_agent
  setup_workflow.py               # creates/updates ShopEasy — Alert Triage workflow (update in-place)
  setup_dashboard.py              # imports ShopEasy Mission Control dashboard (overwrite=true)
  wipe.py                         # full wipe: data + ML + alert rules + agent builder + workflow + dashboard
  workflow_alert_triage.yaml      # workflow definition YAML
  shopeasy_mission_control.ndjson # exported dashboard (by-value, self-contained)
  data/                           # output NDJSON files (regenerated on every ingest run)
```

---

## Procedures

### From scratch (first time or after full wipe)

```bash
export ES_CLOUD_ID=<cloud-id>
export ES_API_KEY=<api-key>
python3 ingest.py            # wipe data + generate + ingest  [no deps]
python3 setup_agent.py       # create tools + skills + agent  [no deps]
python3 setup_workflow.py    # create workflow                [needs: agent]
python3 setup_ml_jobs.py     # create ML jobs + alert rules  [needs: data + workflow]
python3 setup_dashboard.py   # import dashboard               [no deps]
```

**Dependency order (no cycles):**
```
ingest.py ──────────────────────────────────┐
                                             ▼
setup_agent.py ──► setup_workflow.py ──► setup_ml_jobs.py

setup_dashboard.py  (independent)
```
- `ingest.py` and `setup_agent.py` have no mutual dependency — can run in either order or in parallel
- `setup_workflow.py` must follow `setup_agent.py` (workflow invokes `rca_agent` at runtime)
- `setup_ml_jobs.py` must be last — alert rules need the workflow ID and datafeeds need the ingested data
- `setup_dashboard.py` is fully independent

All scripts must run on the **same calendar day** — they share the time anchor `BASE = yesterday 21:00 UTC`.

### Refresh (data drifted to yesterday — run next morning)

```bash
python3 ingest.py                 # rewipes data, regenerates anchored to last night
python3 setup_ml_jobs.py --force  # rewipes ML jobs + alert rules, restarts datafeeds on new window
```

Agent, skills, workflow, and dashboard do NOT need to be refreshed — they are time-agnostic.

### Full wipe (clean slate, no recreation)

```bash
python3 wipe.py
```

Wipes in order: ML datafeeds + jobs → Kibana alert rules + alert documents → data streams + APM index → Agent Builder conversations → Agent Builder (tools, skills, agent) → cases → workflow → dashboard. No recreation — run setup scripts after.

### Selective reset (force-recreate one layer)

```bash
python3 setup_ml_jobs.py --force    # wipe + recreate ML jobs + alert rules only
python3 setup_agent.py --force      # wipe + recreate tools, skills, agent only
python3 setup_workflow.py           # update workflow in-place (no --force needed)
python3 setup_dashboard.py          # re-import dashboard (always overwrites)
```

---

## Script internals

`ingest.py` sequence:
1. `wipe_existing_data()` — deletes all `logs-shopeasy.*`, `metrics-shopeasy.*` data streams AND `traces-apm.shopeasy-default` (regular index — needs explicit DELETE)
2. `generate.generate_all()` — regenerates all NDJSON anchored to last night
3. `ensure_apm_template()` — idempotent PUT of `traces-apm-shopeasy` index template
4. `ensure_all_streams()` — creates streams via `PUT /_streams/{name}`
5. Bulk-ingests all 7 NDJSON files

`setup_ml_jobs.py` sequence:
1. (`--force`) Stops + deletes all ML datafeeds and jobs; deletes alert rules tagged `["shopeasy", "ml"]`
2. Recreates 4 ML jobs, opens them, starts datafeeds over `[BASE-5d, BASE+10h30m]`
3. Creates 4 Kibana ESQL alert rules, each with a `system-connector-.workflows` action — workflow ID resolved at runtime by name lookup (never hardcoded)

`setup_agent.py` sequence:
1. (`--force`) Deletes then recreates 3 custom ESQL tools, 3 skills, rca_agent
2. Without `--force`: idempotent upsert (PUT if already exists)

`setup_workflow.py` sequence:
1. Looks up existing workflow by name → gets current ID
2. If found: `PUT /api/workflows/workflow/{id}` with `{"yaml": "..."}` — updates in-place, ID preserved
3. If not found: `POST /api/workflows` to create (Kibana assigns a new ID)
- No `--force` flag — always updates in-place. Never delete-and-recreate (deleted IDs are permanently reserved).

`setup_dashboard.py` sequence:
1. POSTs `shopeasy_mission_control.ndjson` to `/api/saved_objects/_import?overwrite=true`
2. Always overwrites the existing dashboard (same fixed ID `f8d67162-7acc-4403-b2d6-9a4c776b591a`)

`wipe.py` sequence:
1. Stop + delete ML datafeeds + jobs (4 jobs: firewall-rare-action, checkout-errors, vm-cpu-ready, db-read-latency)
2. Delete Kibana alert rules matching "shopeasy" by name
3. Delete alert documents from `.alerts-*` matching `*ShopEasy*`
4. Delete data streams `logs-shopeasy.*`, `metrics-shopeasy.*` and index `traces-apm.shopeasy-default`
5. Delete Agent Builder conversations for `rca_agent`
6. Delete Agent Builder: agent `rca_agent`, skills, tools
7. Delete cases matching "shopeasy" in title
8. Delete workflow by name
9. Delete dashboard by fixed ID `f8d67162-7acc-4403-b2d6-9a4c776b591a`
10. Report surviving `.ml-anomalies-*` records

---

## Kibana Workflows API notes

- `GET /api/workflows` — list all workflows (each has `id`, `name`, `yaml`, etc.)
- `POST /api/workflows` — bulk create `{"workflows": [{"yaml": "..."}]}` → returns `{created: [], failed: []}`
- `PUT /api/workflows/workflow/{id}` — update existing workflow `{"yaml": "..."}` → returns `{id, lastUpdatedAt}`
- `DELETE /api/workflows` — bulk delete `{"ids": [...]}`
- Kibana permanently reserves deleted workflow IDs — never reuse them, always update in-place

---

## Elastic Streams / indices

| File | Target | Type | Notes |
|---|---|---|---|
| synthetics.ndjson | `logs-shopeasy.synthetics-default` | data stream | zero-config logsdb |
| firewall-logs.ndjson | `logs-shopeasy.firewall-default` | data stream | zero-config logsdb |
| app-logs.ndjson | `logs-shopeasy.app-default` | data stream | zero-config logsdb |
| app-traces.ndjson | `traces-apm.shopeasy-default` | **regular index** | needs APM template; NOT a data stream |
| postgresql-logs.ndjson | `logs-shopeasy.postgresql-default` | data stream | zero-config logsdb |
| postgresql-metrics.ndjson | `metrics-shopeasy.postgresql-default` | data stream | zero-config |
| vmware-metrics.ndjson | `metrics-shopeasy.vmware-default` | data stream | zero-config |

**Critical:** `traces-apm.shopeasy-default` is a regular index, not a data stream.
`DELETE /_data_stream/...` does not touch it — `ingest.py` and `wipe.py` delete it explicitly.

---

## App scenario: ShopEasy e-commerce

**Services:** api-gateway (app-prod-01), checkout-service (app-prod-02), payment-service / inventory-service (app-prod-03)
**Database:** PostgreSQL 15.4 on VM db-prod-01, hosted on VMware esx-host-02
**Firewall:** Palo Alto PA-5220 (fw-edge-01)

## 3 outages (all UTC, last night = BASE night)

| # | Window | Root cause | Key signal chain |
|---|---|---|---|
| 1 | 22:05–23:15 | Firewall rule 1042 flipped ALLOW→REJECT on TCP/443 by netops-bot automation job #3871 | synthetics(connection refused) → firewall DENY logs → config-change event 1 min before |
| 2 | 01:00–02:45 | PR #847 deployed checkout-service 2.1.1 missing `DATABASE_POOL_SIZE` env var → NullPointerException | synthetics(HTTP 500 checkout only) → app-logs NPE v2.1.1 → deployment log missing config |
| 3 | 03:30–05:15 | VMware backup job on esx-host-02 floods shared datastore; db-prod-01 cpu.ready 5→500ms; PG queries 200ms→16s | synthetics(slow→504) → app-logs(timeout) → pg-logs(slow query) → pg-metrics(blk_read_time_ms, connections) → vmware(cpu.ready.ms spike + backup-agent-01 disk flood) |

---

## ML anomaly detection jobs

All jobs: 5m bucket span, datafeed window `BASE-5d → BASE+10h30m`.

| Job | Outage | Detector | Source | Peak score |
|---|---|---|---|---|
| `shopeasy-firewall-rare-action` | 1 | `rare by event.action` | firewall (allow+deny) | 69 (decays by design) |
| `shopeasy-checkout-errors` | 2 | `rare by service.version` | app-logs, checkout-service all levels | 53 |
| `shopeasy-vm-cpu-ready` | 3 | `mean(cpu.ready.ms) partition by VM` | vmware metrics | 97 |
| `shopeasy-db-read-latency` | 3 | `mean(blocks.read_time_ms)` | pg metrics | 91 |

**Key design decisions:**
- 5-day baseline is mandatory — without it, count-based jobs produce 0 anomalies
- `shopeasy-checkout-errors`: `rare by service.version` with ALL checkout-service logs (no level filter). v2.1.0 dominates baseline (~640 docs), v2.1.1 never seen → fires on first appearance. Score caps at ~53 due to sparse baseline.

---

## Kibana alert rules

**Rule type: `.es-query` (ESQL) querying `.ml-anomalies*` directly.**

Do NOT use `xpack.ml.anomaly_detection_alert` — it only fires on anomalies produced *after* the rule is created. ESQL rules have no state tracking and fire immediately against existing results.

| Rule name | Job | Threshold |
|---|---|---|
| ShopEasy — Checkout errors anomaly | `shopeasy-checkout-errors` | ≥ 50 |
| ShopEasy — Firewall rare-action anomaly | `shopeasy-firewall-rare-action` | ≥ 50 |
| ShopEasy — VM CPU-ready anomaly | `shopeasy-vm-cpu-ready` | ≥ 75 |
| ShopEasy — DB read-latency anomaly | `shopeasy-db-read-latency` | ≥ 75 |

Rules tagged `["shopeasy", "ml", job_id]` — the third tag is the job_id, read by the workflow as `event.rule.tags[2]`.
`excludeHitsFromPreviousRun: false` keeps them active on every check within the 7d window.
Each rule has a `system-connector-.workflows` action — workflow ID resolved at runtime by name lookup in `setup_ml_jobs.py`.

There is also "ShopEasy — App unreachable" — ESQL on synthetics `error.message IS NOT NULL`, 24h window, `excludeHitsFromPreviousRun: true`, `alert_delay: 1`, no workflow action. Managed by `setup_ml_jobs.py`, deleted by `wipe.py`.

---

## Agent configuration

**Agent:** `rca_agent`

**Custom tools (ESQL, tagged RCA):**
- `rca_app_availability` — synthetics downtime buckets; caller groups contiguous buckets into incident windows
- `rca_fetch_anomalies_in_window` — ML anomalies scoped to `?window_start / ?window_end`
- `rca_lookup_datafeed` — resolves `?job_id` → source indices from `.ml-config*`

**Skills:**
- `morning_meteo` — nightly weather-report: identify windows → anomalies → lookup index → raw signals → summary table
- `alert_analysis` — alert-triggered single-incident RCA: never calls `rca_app_availability`, uses anomaly timestamp ±30min, outputs Slack mrkdwn with `<!subteam^ID|@handle>` team mentions
- `request_remediation` — operator handoff: outputs exactly "Please reply `resolved` here once you applied the fix for this issue and I will close the case automatically.", waits for reply, calls `platform.core.resume_workflow_execution` with `{user_input: "resolved"}`

**Responsible team mapping (Slack user group IDs):**
- App errors → `<!subteam^S0B9DGT8RST|@app-team>`
- VM/backup/disk → `<!subteam^S0B9DGUUFRV|@vmware-team>`
- Firewall/network → `<!subteam^S0B9NKM0YP5|@firewall-team>`

---

## Workflow: ShopEasy — Alert Triage

**ID:** Kibana-managed (assigned on first create, preserved via in-place updates). Current: `shopeasy-alert-triage-21`
**File:** `workflow_alert_triage.yaml`
**Trigger:** `type: alert` — fires when any wired alert rule transitions to active

**Steps:**
1. `fetch_anomaly` — ESQL on `.ml-anomalies-*` using `event.rule.tags[2]` as job_id filter
2. `run_rca` — calls `rca_agent` via `/api/agent_builder/converse` with anomaly timestamp; 10m timeout
3. `create_case` — Kibana observability case with RCA summary and conversation link
4. `attach_alert_to_case` — attaches triggering alert to the case
5. `notify_slack` — posts to `#all-spuchol-intregration` via `elastic-integration` connector
6. `run_remediation_request` — continues the same conversation (passes `conversation_id`), invokes `request_remediation` skill; 35m timeout
7. `await_remediation` — `waitForInput` pauses workflow; schema: `{user_input: string}`
8. `add_resolution_comment` — adds "Incident resolved" comment to case (unconditional — reaching this step means operator confirmed)
9. `refetch_case` — GET case to get current version
10. `close_case` — `kibana.updateCase` sets status to closed

**Critical design notes:**
- No `if` condition on close — `waitForInput` itself is the gate; any resume → close
- `waitForInput` schema uses `user_input: string` (not `resolved: boolean`) — LLM naturally uses this field name
- `run_remediation_request` input does NOT pass `Case ID` to avoid LLM confusing it with resume inputs
- `event.alerts[0].*` fields are EMPTY for ESQL-type alert rules — job context comes from `event.rule.tags[2]`

**Kibana URL const:** `https://agentic-rca-demo-e9c331.kb.europe-west1.gcp.cloud.es.io`
**Slack connector:** `elastic-integration` (`.slack_api` type)
**Slack channel:** `#all-spuchol-intregration`

**Wiring mechanism:** Alert rules use `system-connector-.workflows` action type (not a regular connector). Format:
```json
{"id": "system-connector-.workflows", "params": {"subAction": "run", "subActionParams": {"workflowId": "<resolved-at-runtime>", "summaryMode": true}}}
```

---

## Dashboard

**Name:** ShopEasy Mission Control
**ID:** `f8d67162-7acc-4403-b2d6-9a4c776b591a` (fixed — embedded in the NDJSON)
**File:** `shopeasy_mission_control.ndjson`
**Type:** By-value dashboard — all 30 panels embedded inline, ad-hoc data views, no external saved object references. Fully self-contained for import.
**Data views (ad-hoc, inline):** `logs-shopeasy.synthetics-default`, `logs-shopeasy.firewall-default`, `logs-shopeasy.app-default`, `logs-shopeasy.postgresql-default`, `metrics-shopeasy.postgresql-default`, `metrics-shopeasy.vmware-default`, `traces-apm.shopeasy-default`

---

## Known issues / decisions

- APM Application view in Kibana requires the index template (handled by `ingest.py`).
- Data view for Discover: `POST /api/data_views/data_view` with title `logs-shopeasy.*,metrics-shopeasy.*,traces-apm.shopeasy-*` — created manually.
- `setup_agent.py` API notes: PUT strips `id` and `type` from body (both rejected by the API on updates).
- `event.alerts[0].*` fields are EMPTY for ESQL-type alert rules — job context comes from `event.rule.tags[2]`.
- Kibana permanently reserves deleted workflow IDs — `setup_workflow.py` uses in-place PUT, never delete-and-recreate.
- LLM (`platform.core.resume_workflow_execution`) unreliable with custom field names/types — use `user_input: string` and remove the `if` condition gating case closure.

**How to apply:** Read this fully at the start of each session — it has everything needed to resume without re-exploring the repo.

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
  instruqt/
    setup_mattermost.sh           # bootstraps Mattermost as the Instruqt-lab Slack replacement
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

**Steps (root/Cloud version — see below, the instruqt version has diverged):**
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

**Critical design notes (root/Cloud version):**
- No `if` condition on close — `waitForInput` itself is the gate; any resume → close
- `waitForInput` schema uses `user_input: string` (not `resolved: boolean`) — LLM naturally uses this field name
- `run_remediation_request` input does NOT pass `Case ID` to avoid LLM confusing it with resume inputs
- `event.alerts[0].*` fields are EMPTY for ESQL-type alert rules — job context comes from `event.rule.tags[2]`

**Instruqt version diverged further (2026-07-02): human-in-the-loop remediation cut entirely.** `instruqt/workflow_alert_triage.yaml` no longer has `run_remediation_request` / `await_remediation` — after `attach_alert_to_case` it goes straight to `add_resolution_comment` ("Incident resolved — confirmed by operator.") then `close_case`, simulating operator confirmation instead of actually waiting for it. Explicit user decision: "We cut the human in the loop scenario and simulate operator case close instead" — likely to keep the Instruqt lab self-paced/short rather than requiring a real wait-for-input round-trip. The `request_remediation` skill in `instruqt/setup_agent.py` is left defined but now unused by this workflow. The top-of-file `description:` block still mentions "accept remediation" — stale text, not yet cleaned up.
Instruqt steps now: `fetch_anomaly` → `run_rca` (with structured `schema`) → `open_case` → `notify_mattermost` → `attach_alert_to_case` → `add_resolution_comment` → `close_case`.

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

## Instruqt port: Mattermost as Slack replacement

**Why:** Want a version of this demo deliverable as a self-paced Instruqt lab. Slack can't be the on-call notify target there (no frictionless self-hosted trial for an ephemeral sandbox). Evaluated PagerDuty / Opsgenie / Microsoft Teams / TheHive / Mattermost / Grafana OnCall against two criteria: (1) a native Elastic connector to post the RCA, (2) self-hostable inside the sandbox with no signup or trial-expiry friction. Landed on **Mattermost** (self-hosted `mattermost-preview` Docker image), wired via Kibana's generic **Webhook** connector — Mattermost has no named Kibana connector type, only Slack and Teams do.

**Status:** Mattermost bootstrap inside the Instruqt sandbox VM works end-to-end, AND the workflow rewiring is done: `instruqt/workflow_alert_triage.yaml` has a `notify_mattermost` step (`kibana.request` → `POST /api/actions/connector/{{ consts.mattermost_connector_id }}/_execute`) between `open_case` and `attach_alert_to_case`, posting an RCA summary card (time window, root cause, responsible team, case link) built from `run_rca`'s `structured_output` fields. `run_rca` now declares a `schema` (time_window, user_impact, root_cause, responsible_component, responsible_team, recommended_action) to produce that structured output. Slack subteam-mention syntax in the `alert_analysis` skill HAS been retired in the instruqt version — see "`alert_analysis` skill retargeted for Mattermost" below.

**Connector ID wiring (fixed 2026-07-02):** `instruqt/setup_elastic.sh` creates the Kibana Webhook connector `mattermost-incidents` by delete-then-recreate (`instruqt/setup_elastic.sh:75-98`) — this assigns a **new ID every run**, so the workflow can never hardcode it. Fix: the YAML carries `consts.mattermost_connector_id: "__MATTERMOST_CONNECTOR_ID__"` as a placeholder; `instruqt/setup_workflow.py`'s `get_connector_id(name)` looks it up by name via `GET /api/actions/connectors` and does a plain string-replace on the placeholder before creating/updating the workflow (raises if the connector isn't found yet). This mirrors the existing by-name-lookup pattern used for `system-connector-.workflows` action IDs in `setup_ml_jobs.py`. **Ordering requirement:** the Mattermost connector block in `setup_elastic.sh` must run before `python3 setup_workflow.py` — the script was reordered so `setup_workflow.py`/`setup_ml_jobs.py`/`setup_dashboard.py` now run *after* the connector-creation block instead of all five scripts running as one batch up front.

**Public case URL wiring (2026-07-02):** The `notify_mattermost` step's "Open case" link must be reachable from the learner's browser, not just from inside the sandbox VM — `http://kubernetes-vm:30001` only resolves inside the cluster network. Instruqt exposes internal ports at a per-participant public URL of the form `https://kubernetes-vm-30001-<INSTRUQT_PARTICIPANT_ID>.env.play.instruqt.com`, where the participant ID is already present in the sandbox VM's process environment (`env | grep INSTRUQT_PARTICIPANT_ID`, no explicit sourcing needed). Same placeholder pattern as the connector ID: YAML carries `consts.instruqt_participant_id: "__INSTRUQT_PARTICIPANT_ID__"`, and `setup_workflow.py` substitutes it from `os.environ["INSTRUQT_PARTICIPANT_ID"]` (raises if unset) right before the Mattermost-connector-ID substitution. The `open_case` case description was also simplified to embed a rotating-light RCA summary (time window / root cause / responsible team) instead of the full `run_rca.output.message` + "Open AI Conversation" link.

**Script:** `instruqt/setup_mattermost.sh` — idempotent. Starts/reuses the `mattermost-preview` container, waits for `/api/v4/system/ping`, bootstraps `admin` (first-ever user auto-promotes to System Admin), disables `RequireEmailVerification` + enables `EnableIncomingWebhooks`, creates team `shopeasy` ("ShopEasy Ops"), channel `#incidents`, three on-call users (`app-team`, `vmware-team`, `firewall-team` — mirrors the Slack subteam mapping below), adds them to team+channel, force-verifies each one's email, and creates an incoming webhook on `#incidents`. Default password for every account: `Instruqt123!`.

**Gotchas hit (non-obvious — would re-bite on a fresh attempt):**
- Mattermost error responses put the error *code* in the `.id` field (never null) — `jq -r '.id // empty'` can't distinguish "not found" from "found" this way. Idempotency checks must test `has("status_code")` instead.
- Users created via the authenticated admin API are NOT auto-email-verified the way the bootstrap admin is — needs an explicit `POST /api/v4/users/{id}/email/verify/member` per user, even with `RequireEmailVerification` already patched to `false`.
- Channel-by-name lookup (`GET /teams/{id}/channels/name/{name}`) still returns **archived** (soft-deleted) channels. An idempotency check based on this will report "exists" for an archived channel, but `POST /hooks/incoming` rejects archived channels as "doesn't exist." Fix: `POST /channels/{id}/restore` if `delete_at != 0`.
- `mattermost-preview` keeps data across `docker start`/`stop` of the *same* container, but not across container recreation — an Instruqt environment reset wipes everything, including any script placed by hand (only what's actually wired into the track survives).
- Passwords containing `!` (e.g. `Instruqt123!`) trigger bash interactive history expansion ("event not found") when pasted into a live terminal inside double quotes. `set +H` disables it; script files are unaffected since non-interactive shells skip history expansion.
- Mattermost's **Custom Groups** feature (the @group-mention equivalent of Slack subteams) requires an Enterprise/Professional license — not available on the free Team Edition that `mattermost-preview` runs. Worked around with one real user per responsible team instead of group mentions.

**Instruqt track exists and is already wired (discovered 2026-07-02):** Slug `agentic-rca-track-1noreo` (id `uqsbfy4iof6w`), team `elastic`, manage URL `https://play.instruqt.com/manage/elastic/tracks/agentic-rca-track-1noreo` (renamed from an earlier `untitled-track-*` slug in the UI — old URLs go stale, always re-check the slug in-browser before `instruqt track pull`). Pulled locally via `instruqt track pull agentic-rca-track-1noreo` into `instruqt/agentic-rca-track-1noreo/`. Structure: one challenge `01-take-the-shift-challenge-bbrndv` with two VM tabs (`kubernetes-vm`, `host-1`) plus two service tabs (Mattermost on `host-1:8065`, Kibana dashboards on `kubernetes-vm:30001`). Lifecycle setup scripts ARE wired already: `setup-kubernetes-vm` runs `git clone https://github.com/spuchol81/elastic-o11y-agentic-rca.git && elastic-o11y-agentic-rca/instruqt/setup_elastic.sh`; `setup-host-1` runs the same clone + `elastic-o11y-agentic-rca/instruqt/setup_mattermost.sh`. These clone from GitHub `origin/main` at sandbox-launch time (user manages the commit/push flow), so track behavior always reflects whatever is currently pushed there.

**Not yet done:** nothing tracked here currently — Mattermost wiring, connector ID resolution, and track lifecycle wiring are all confirmed done as of 2026-07-02.

**"Taking the Shift" learner scenario — designed 2026-07-03, NOT yet implemented (no files written).** Goal: turn the single empty challenge (`01-take-the-shift-challenge-bbrndv`, `assignment.md` currently frontmatter-only) into a 3-challenge learning flow where a learner plays an on-call operator: (1) investigate the overnight shift via the Mission Control dashboard, (2) answer one quiz question, (3) ask `rca_agent` directly and compare. Explicit user decision: don't touch any automation/setup scripts this round — content only (`assignment.md` + `track.yml` challenge entries).

Final agreed design (superseded two earlier drafts — a per-outage 5-challenge version and a per-outage 3-quiz version — both rejected as too complex):
1. **Challenge 1 "Take the Shift"** (existing folder, add body only) — scene-set as operator starting a shift, direct them to the `elastic` tab → Mission Control dashboard, name the 3 signal domains to check (network/firewall, application/checkout, compute/VM+Postgres) using real panel titles, no root causes given away, no check script.
2. **Challenge 2 — single quiz question** (new, `type: quiz`), final phrasing (Option B, in-character, confirmed by user):
   Stem: *"You've reviewed the dashboard. If you had to page one team right now, what's your call on last night?"*
   Answers: `["It was a network problem", "It was a bad code deploy", "It was a compute/infra problem", "It was a combination of all the above"]`, `solution: [3]` — correct answer is the last one, since the 3 real outages map exactly onto network (firewall)/code (bad deploy)/compute (VMware backup→DB latency).
3. **Challenge 3 "Ask Your RCA Co-Pilot"** (new, regular challenge) — learner navigates to Kibana's Agent Chat UI (found via global search "Agent Builder"/"Agents" — no hardcoded deep-link path exists/is documented, so instructions must say "use global search" not a guessed URL), picks `rca_agent`, asks an open-ended question like *"What happened to the ShopEasy platform last night? Give me a full incident report."* This triggers the `morning_meteo` skill (confirmed human-invocable in both root & instruqt `setup_agent.py`, identical content) — NOT `alert_analysis`, which is workflow-only and explicitly forbids the broad incident-scan tool.

All 3 challenges reuse the same 4 tabs as challenge 1 (`kubernetes-vm` terminal, `host-1` terminal, `mattermost` service, `elastic` dashboard service) — no new tabs needed.

**Execution plan for next session (not yet run):** use `instruqt challenge create --title "..."` (CLI confirmed installed at `/opt/homebrew/bin/instruqt`) from the track root to scaffold challenges 2 & 3 — mints real IDs and registers in `track.yml`, avoiding hand-rolled IDs. Then hand-edit `assignment.md` bodies/frontmatter and copy tabs. Run `instruqt track validate` before considering it done. Do NOT run `instruqt track push`/`deploy` without separately confirming with the user — that publishes to the shared remote track.

Full plan detail saved at `/Users/spuchol/.claude/plans/tranquil-singing-aurora.md` (local Claude plan file, not in repo) if resuming this exact session's reasoning is useful.

**`alert_analysis` skill retargeted for Mattermost (2026-07-02, instruqt only):** `instruqt/setup_agent.py`'s `alert_analysis` skill content now uses plain `@app-team` / `@vmware-team` / `@firewall-team` mentions instead of Slack's `<!subteam^ID|@handle>` syntax, and replaced Step 3's `rca_lookup_datafeed(?job_id)` + raw-ESQL-signals step with two new instruqt-only tools: `rca_fetch_firewall_change(?window_start, ?window_end)` and `rca_fetch_app_errors(?window_start, ?window_end)`. These two tools exist ONLY in `instruqt/setup_agent.py` (not in root `setup_agent.py`) — the instruqt tool/skill set has diverged from root beyond the "identical business logic" that used to hold; root still uses the 3-tool/Slack-subteam version. Root `setup_agent.py` was NOT touched.

**Challenge 04 assignment.md finished (2026-07-07):** `instruqt/agentic-rca-track-1noreo/04-not-under-agent-builder-watch/assignment.md`'s "What Actually Happened While You Slept" section (previously just "to be continued") now has a 4-step walkthrough of the Kibana Alerts page → one alert's ML detail → the rule's Actions tab (workflow wiring) → the actual Workflows run, closing the loop back to the Mattermost thread from earlier in the challenge. Uses 4 placeholder image filenames (`alerts-list-image.png`, `alert-detail-image.png`, `alert-actions-image.png`, `workflow-run-image.png`) — **real screenshots from the live sandbox still need to be captured and dropped into `assets/`** before this is publishable; nothing else is blocking. The closing note was also rewritten from a generic "same skill/agent" callback into a value-selling wrap-up: operator quality-of-life (no page, no manual log-diving, no blank-page report writing) + SLO protection (MTTR in minutes not hours, consistent investigation rigor day or night) — this is the track's closing pitch, keep it in that frame if it gets edited again.

**`morning_meteo` skill reliability fix (2026-07-07, instruqt only):** Live testing surfaced that the agent sometimes skipped the raw-signal tools (`rca_fetch_firewall_change` / `rca_fetch_app_errors`) for some incident windows, producing a partial RCA backed only by the ML anomaly. Root cause was the skill's step structure — the anomaly lookup and the two raw-signal lookups were split across two separate steps ("Process EVERY window" then "Deepen knowledge"), giving the model a seam where it would treat the second step as optional/skippable. Fix (user-validated by testing in the live sandbox before I synced it back to source): collapsed into a single "Process EVERY window" step that calls all three tools (`rca_fetch_anomalies_in_window`, `rca_fetch_firewall_change`, `rca_fetch_app_errors`) back-to-back per window, cutting the skill from 4 steps to 3. **Lesson for future skill-authoring:** when a procedure needs several tool calls done together per iteration/window, put them in one step rather than splitting into sequential steps — splitting creates a completion gate the model can silently fail. Applied to `instruqt/setup_agent.py` only — root `setup_agent.py`'s `morning_meteo` (different, older 5-step structure using `rca_lookup_datafeed` + generic ESQL) was explicitly left un-synced per user decision, since only the instruqt track is under active iteration. **Not yet redeployed** — user will re-run `setup_agent.py`/`setup_elastic.sh` against the sandbox themselves; I did not touch the live agent.

### Elastic-side setup: `instruqt/setup_elastic.sh`

**Why:** Root `ingest.py` / `setup_agent.py` / `setup_workflow.py` / `setup_ml_jobs.py` / `setup_dashboard.py` connect via `ES_CLOUD_ID` (Elastic Cloud only). The Instruqt sandbox is self-hosted (`http://elasticsearch-es-http.default.svc:9200` for ES, `http://kubernetes-vm:30001` for Kibana, API key from the Instruqt env file at `/home/kubernetes-vm/env`). User explicitly required **zero changes to the root ECH scripts** — the two deployment modes must fully coexist.

**Design:** `instruqt/` holds near-identical Python copies of all 5 root scripts — only the connection-bootstrap block (URL derivation + auth headers) differs; all business logic (tools, skills, agent, ML job/alert defs, ingestion) is copy-pasted unchanged. `instruqt/setup_elastic.sh` is a thin bash entry point: sources the Instruqt env file, exports `ES_URL`/`KB_URL`/`KB_USER`/`KB_PASS` (with sane defaults), `pip install`s the `elasticsearch` client, runs `ingest.py` + `setup_agent.py`, then creates/refreshes the Mattermost Kibana Webhook connector, then runs `setup_workflow.py` + `setup_ml_jobs.py` + `setup_dashboard.py` (`set -euxo pipefail`). The connector block must sit between those two script groups — see "Connector ID wiring" above.

**Connection convention observed in other Instruqt scripts (e.g. the BBQ lab) and followed here:**
- Elasticsearch calls → `Authorization: ApiKey $ELASTICSEARCH_APIKEY` against `ES_URL`.
- Kibana calls → HTTP Basic `elastic:changeme` against `KB_URL` (NOT the API key — Kibana auth uses basic in this environment, ES uses ApiKey).

**What's intentionally still shared with root (no duplication, read-only references):**
- `instruqt/ingest.py` imports `generate.py` from the repo root via `sys.path` (pure data-generation logic, no connection code — duplicating it would create drift risk for zero benefit) and writes to the root `data/` dir by default.
- `instruqt/setup_dashboard.py` reads `../shopeasy_mission_control.ndjson`. Single source of truth for both deployment modes.

**Diverged from root, NOT shared:** `instruqt/workflow_alert_triage.yaml` is its own file (read by `instruqt/setup_workflow.py` from its own directory, not `../workflow_alert_triage.yaml`) because the Instruqt Kibana version (9.4.2) requires different step-type syntax than whatever the root file currently targets — `ai.agent` for Agent Builder calls and `cases.*` for case management, instead of the generic `kibana.request` escape hatch. The root `workflow_alert_triage.yaml` has NOT been updated to match (as of this writing) — the two files will drift unless someone ports fixes both ways by hand. The instruqt version has also since dropped the human-in-the-loop remediation wait entirely (see "Workflow: ShopEasy — Alert Triage" above) and gained Mattermost notification — root has neither change.

---

## Known issues / decisions

- APM Application view in Kibana requires the index template (handled by `ingest.py`).
- Data view for Discover: `POST /api/data_views/data_view` with title `logs-shopeasy.*,metrics-shopeasy.*,traces-apm.shopeasy-*` — created manually.
- `setup_agent.py` API notes: PUT strips `id` and `type` from body (both rejected by the API on updates).
- `event.alerts[0].*` fields are EMPTY for ESQL-type alert rules — job context comes from `event.rule.tags[2]`.
- Kibana permanently reserves deleted workflow IDs — `setup_workflow.py` uses in-place PUT, never delete-and-recreate.
- LLM (`platform.core.resume_workflow_execution`) unreliable with custom field names/types — use `user_input: string` and remove the `if` condition gating case closure.

**How to apply:** Read this fully at the start of each session — it has everything needed to resume without re-exploring the repo.

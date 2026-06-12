# ShopEasy — Elastic Agentic RCA Demo

An end-to-end demo of automated incident triage using Elastic observability.
A simulated e-commerce app ("ShopEasy") suffers three production outages overnight.
Elastic ML detects anomalies, alert rules trigger a Kibana Workflow, and an AI agent
investigates each incident, creates a case, notifies Slack, and waits for operator confirmation before closing.

---

## What it demonstrates

| Layer | Technology |
|---|---|
| Synthetic monitoring | Elastic Synthetics (heartbeat) |
| Log & metric ingestion | Elastic data streams (logsdb) |
| Anomaly detection | Elastic ML (4 jobs, 5-day baseline) |
| Alerting | Kibana ESQL alert rules |
| Automated triage | Kibana Workflows |
| Root cause analysis | Elastic Agent Builder (rca_agent) |
| Case management | Kibana Observability Cases |
| Notification | Slack via Elastic connector |

---

## Prerequisites

### Elastic Cloud deployment

- Elastic Cloud deployment running **Elastic 9.4+**
- The following features enabled:
  - Machine Learning
  - Kibana Alerting
  - Kibana Cases
  - Kibana Workflows
  - Agent Builder
- A Slack connector configured in Kibana (`.slack_api` type) named `elastic-integration`
- An API key with cluster-level privileges (see below)

### API key permissions

Create an API key in Kibana → Stack Management → API Keys with:
- **Elasticsearch:** `all` on indices `logs-shopeasy.*`, `metrics-shopeasy.*`, `traces-apm.shopeasy-*`, `.ml-*`, `.alerts-*`; `manage_ml` cluster privilege
- **Kibana:** `All` on Spaces, Alerting, Cases, Machine Learning, Observability

### Python

- Python 3.10+
- `elasticsearch` package:

```bash
pip install elasticsearch
```

All other scripts use the Python standard library only.

---

## Setup

### 1. Export credentials

```bash
export ES_CLOUD_ID="your-deployment-name:base64encodedvalue=="
export ES_API_KEY="your-api-key=="
```

### 2. Run setup scripts in order

```bash
python3 ingest.py            # Generate + ingest 5-day baseline and outage night data
python3 setup_agent.py       # Create ESQL tools, skills, and rca_agent
python3 setup_workflow.py    # Create the Alert Triage workflow
python3 setup_ml_jobs.py     # Create ML jobs, start datafeeds, create alert rules
python3 setup_dashboard.py   # Import the ShopEasy Mission Control dashboard
```

> **Order matters:** `ingest.py` and `setup_agent.py` can run in parallel.
> `setup_workflow.py` must follow `setup_agent.py`.
> `setup_ml_jobs.py` must run last — it wires alert rules to the workflow and needs ingested data.
> `setup_dashboard.py` is independent.

All scripts are idempotent — safe to re-run. They will update existing resources in place.

### 3. Wait for ML jobs to complete (~2–5 minutes)

ML datafeeds process 5 days of baseline + the outage night. You can monitor progress in
Kibana → Machine Learning → Anomaly Detection.

### 4. Verify alert rules are active

Kibana → Observability → Alerts → Rules — four "ShopEasy" rules should be in **Active** state.

---

## Outage scenarios

All outages occurred **last night** (relative to when `ingest.py` was run).

| # | Time window (UTC) | Root cause |
|---|---|---|
| 1 | 22:05 – 23:15 | Firewall rule 1042 flipped ALLOW → REJECT on TCP/443 by automation job |
| 2 | 01:00 – 02:45 | checkout-service v2.1.1 deployed with missing `DATABASE_POOL_SIZE` → NullPointerException |
| 3 | 03:30 – 05:15 | VMware backup job flooded shared datastore → db-prod-01 cpu.ready spike → PostgreSQL queries slow to 16s |

---

## Automated triage flow

When an ML anomaly exceeds the alert threshold:

1. Alert rule triggers → Kibana Workflow fires
2. Workflow fetches the anomaly and calls `rca_agent` to investigate
3. Agent runs `alert_analysis` skill: queries raw signals, builds evidence chain
4. Workflow creates an Observability case with the RCA summary
5. Slack notification sent to `#your-channel` with links to case and conversation
6. Agent posts: *"Please reply `resolved` here once you applied the fix"*
7. Operator types `resolved` in the Agent Builder conversation
8. Workflow resumes, adds resolution comment, closes the case

---

## Daily refresh

Data timestamps are anchored to **last night**. Run this each morning to keep the demo fresh:

```bash
python3 ingest.py
python3 setup_ml_jobs.py --force
```

Agent, workflow, and dashboard do not need refreshing.

---

## Full reset

```bash
python3 wipe.py
```

Deletes everything: data streams, ML jobs, alert rules, Agent Builder resources, cases, workflow, dashboard.
Re-run the setup scripts afterwards to start from scratch.

---

## Configuration

Before running, update these values in the respective files if your environment differs:

| Setting | File | Variable |
|---|---|---|
| Slack connector name | `setup_agent.py` | `alert_analysis` skill — `<!subteam^...>` user group IDs |
| Slack channel | `workflow_alert_triage.yaml` | `channels` in `notify_slack` step |
| Kibana public URL | `workflow_alert_triage.yaml` | `kibana_url` const |

---

## Repository structure

```
generate.py                     # Synthetic data generator (called by ingest.py)
ingest.py                       # Data ingestion — requires: elasticsearch package
setup_agent.py                  # Agent Builder setup (tools, skills, agent)
setup_workflow.py               # Workflow setup
setup_ml_jobs.py                # ML jobs + alert rules
setup_dashboard.py              # Dashboard import
wipe.py                         # Full teardown
workflow_alert_triage.yaml      # Workflow definition
shopeasy_mission_control.ndjson # Dashboard export (self-contained)
```

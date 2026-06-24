#!/usr/bin/env python3
"""
ML anomaly detection jobs + Kibana alert rules for the ShopEasy RCA demo.

Instruqt variant of ../setup_ml_jobs.py — identical job/alert definitions,
pointed at the self-hosted Elasticsearch/Kibana running inside the Instruqt
sandbox VM instead of an Elastic Cloud deployment. Only the connection
bootstrap differs.

Creates, opens, and runs 4 jobs:

  Job                          Signal
  ─────────────────────────────────────────────────────────────────────
  shopeasy-firewall-rare-action  rare event.action=deny
  shopeasy-checkout-errors       rare service.version in checkout-service (v2.1.1 never seen in baseline)
  shopeasy-vm-cpu-ready          mean(cpu.ready.ms) per VM
  shopeasy-db-read-latency       mean(blocks.read_time_ms)

Also creates 4 Kibana alerting rules (ESQL on .ml-anomalies*) so alerts
fire immediately against historical data without a live datafeed.

Run after ingest.py — requires ES_URL/KB_URL/ELASTICSEARCH_APIKEY/KB_USER/KB_PASS
env vars (see setup_elastic.sh for defaults).
"""

import os, json, base64, urllib.request, urllib.error
from datetime import datetime, timedelta, timezone

# ── Connection (Instruqt self-hosted cluster) ───────────────────────────────────

ES_URL  = os.environ.get("ES_URL", "http://elasticsearch-es-http.default.svc:9200")
KB_URL  = os.environ.get("KB_URL", "http://kubernetes-vm:30001")
API_KEY = os.environ.get("ELASTICSEARCH_APIKEY")
KB_USER = os.environ.get("KB_USER", "elastic")
KB_PASS = os.environ.get("KB_PASS", "changeme")

ES_HEADERS = {"Authorization": f"ApiKey {API_KEY}", "Content-Type": "application/json"}
KB_HEADERS = {
    "Authorization": "Basic " + base64.b64encode(f"{KB_USER}:{KB_PASS}".encode()).decode(),
    "Content-Type":  "application/json",
    "kbn-xsrf":      "true",
}

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

# ── Time window ───────────────────────────────────────────────────────────────
# Mirrors generate.py: BASE = yesterday 21:00 UTC, HIST_DAYS = 5

BASE       = datetime.now(timezone.utc).replace(hour=21, minute=0, second=0, microsecond=0) - timedelta(days=1)
DATA_START = (BASE - timedelta(days=5)).strftime("%Y-%m-%dT%H:%M:%SZ")
DATA_END   = (BASE + timedelta(minutes=630)).strftime("%Y-%m-%dT%H:%M:%SZ")

# ── Job definitions ───────────────────────────────────────────────────────────

JOBS = [
    {
        "id": "shopeasy-firewall-rare-action",
        "job": {
            "description": "rare event.action detects deny appearing for the first time; source.ip + destination.ip influencers surface affected flows",
            "analysis_config": {
                "bucket_span": "5m",
                "detectors": [{
                    "function":      "rare",
                    "by_field_name": "event.action",
                }],
                "influencers": ["event.action", "destination.ip", "source.ip", "rule.id"],
            },
            "data_description": {"time_field": "@timestamp"},
            "analysis_limits": {"model_memory_limit": "50mb"},
        },
        "datafeed": {
            "indices": ["logs-shopeasy.firewall-default"],
            "query": {"terms": {"event.action": ["allow", "deny"]}},
        },
    },
    {
        "id": "shopeasy-checkout-errors",
        "job": {
            "description": "rare service.version in checkout-service — v2.1.0 dominates baseline, v2.1.1 appears for the first time at deployment and fires immediately",
            "analysis_config": {
                "bucket_span": "5m",
                "detectors": [{
                    "function":      "rare",
                    "by_field_name": "service.version",
                }],
                "influencers": ["service.version", "log.level", "error.type", "host.name"],
            },
            "data_description": {"time_field": "@timestamp"},
            "analysis_limits": {"model_memory_limit": "50mb"},
        },
        "datafeed": {
            "indices": ["logs-shopeasy.app-default"],
            "query": {"term": {"service.name": "checkout-service"}},
        },
    },
    {
        "id": "shopeasy-vm-cpu-ready",
        "job": {
            "description": "mean(cpu.ready.ms) spike on db-prod-01 caused by VMware backup disk flood on esx-host-02",
            "analysis_config": {
                "bucket_span": "5m",
                "detectors": [{
                    "function":              "mean",
                    "field_name":            "vsphere.virtualmachine.cpu.ready.ms",
                    "partition_field_name":  "vsphere.virtualmachine.name",
                }],
                "influencers": [
                    "vsphere.virtualmachine.name",
                    "vsphere.virtualmachine.host.hostname",
                ],
            },
            "data_description": {"time_field": "@timestamp"},
            "analysis_limits": {"model_memory_limit": "50mb"},
        },
        "datafeed": {
            "indices": ["metrics-shopeasy.vmware-default"],
            "query": {"term": {"metricset.name": "virtualmachine"}},
        },
    },
    {
        "id": "shopeasy-db-read-latency",
        "job": {
            "description": "mean(blocks.read_time_ms) spike on db-prod-01; disk I/O saturation from VMware backup job",
            "analysis_config": {
                "bucket_span": "5m",
                "detectors": [{
                    "function":   "mean",
                    "field_name": "postgresql.database.blocks.read_time_ms",
                }],
                "influencers": ["host.name", "postgresql.database.name"],
            },
            "data_description": {"time_field": "@timestamp"},
            "analysis_limits": {"model_memory_limit": "50mb"},
        },
        "datafeed": {
            "indices": ["metrics-shopeasy.postgresql-default"],
            "query": {"match_all": {}},
        },
    },
]

# ── Setup ─────────────────────────────────────────────────────────────────────

def setup_jobs(force=False):
    print(f"Data window: {DATA_START} → {DATA_END}\n")

    for job in JOBS:
        jid = job["id"]
        print(f"[{jid}]")

        if force:
            call("POST", f"/_ml/datafeeds/datafeed-{jid}/_stop?force=true")
            call("DELETE", f"/_ml/datafeeds/datafeed-{jid}")
            call("POST", f"/_ml/anomaly_detectors/{jid}/_close?force=true")
            call("DELETE", f"/_ml/anomaly_detectors/{jid}")

        # Check if job already exists
        _, exists_status = call("GET", f"/_ml/anomaly_detectors/{jid}")
        if exists_status == 200:
            print(f"  [already exists — skipping create/start]")
            print()
            continue

        resp, status = call("PUT", f"/_ml/anomaly_detectors/{jid}", job["job"])
        print(f"  create  → {status}", "" if status == 200 else resp)

        df_body = {**job["datafeed"], "job_id": jid}
        resp, status = call("PUT", f"/_ml/datafeeds/datafeed-{jid}", df_body)
        print(f"  datafeed → {status}", "" if status == 200 else resp)

        resp, status = call("POST", f"/_ml/anomaly_detectors/{jid}/_open")
        print(f"  open     → {status}", "" if status == 200 else resp)

        resp, status = call("POST", f"/_ml/datafeeds/datafeed-{jid}/_start",
                            {"start": DATA_START, "end": DATA_END})
        print(f"  start    → {status}", resp)
        print()

# ── Alert rule definitions ────────────────────────────────────────────────────
# ESQL rules on .ml-anomalies* so they fire against historical/closed-datafeed
# data. xpack.ml.anomaly_detection_alert only works with live datafeeds.

ALERTS = [
    {
        "name": "ShopEasy — Checkout errors anomaly",
        "job_id": "shopeasy-checkout-errors",
        "score_threshold": 50,
    },
    {
        "name": "ShopEasy — Firewall rare-action anomaly",
        "job_id": "shopeasy-firewall-rare-action",
        "score_threshold": 50,  # rare detector peaks at ~69 by design
    },
    {
        "name": "ShopEasy — VM CPU-ready anomaly",
        "job_id": "shopeasy-vm-cpu-ready",
        "score_threshold": 75,
    },
    {
        "name": "ShopEasy — DB read-latency anomaly",
        "job_id": "shopeasy-db-read-latency",
        "score_threshold": 75,
    },
]


def get_triage_workflow_id() -> str | None:
    """Look up the ShopEasy Alert Triage workflow ID by name (ID changes across recreations)."""
    resp, status = kb_call("GET", "/api/workflows")
    if status != 200:
        return None
    for wf in resp.get("results", []):
        if wf.get("name") == "ShopEasy — Alert Triage":
            return wf["id"]
    return None


def setup_alerts(force=False):
    print("Setting up Kibana alert rules …\n")

    if force:
        resp, _ = kb_call("GET", "/api/alerting/rules/_find?per_page=200")
        to_delete = [
            r["id"] for r in resp.get("data", [])
            if "shopeasy" in r.get("name", "").lower()
        ]
        for rid in to_delete:
            _, status = kb_call("DELETE", f"/api/alerting/rule/{rid}")
            print(f"  [deleted]  {rid}  → {status}")
        if to_delete:
            print()

    # Build set of existing rule names to skip duplicates
    existing_resp, _ = kb_call("GET", "/api/alerting/rules/_find?per_page=200")
    existing_names = {r["name"] for r in existing_resp.get("data", [])}

    # Resolve workflow ID by name — ID changes on every recreation
    workflow_id = get_triage_workflow_id()
    if not workflow_id:
        print("  [WARN] ShopEasy — Alert Triage workflow not found; ML rules will have no workflow action")
        print("         Run setup_workflow.py first, then rerun setup_ml_jobs.py\n")

    # ── Synthetics availability alert ─────────────────────────────────────────
    if "ShopEasy — App unreachable" in existing_names:
        print(f"  [exists]   ShopEasy — App unreachable")
    else:
        resp, status = kb_call("POST", "/api/alerting/rule", {
        "name": "ShopEasy — App unreachable",
        "tags": ["shopeasy"],
        "rule_type_id": ".es-query",
        "consumer": "alerts",
        "schedule": {"interval": "1m"},
        "params": {
            "searchType": "esqlQuery",
            "timeWindowSize": 24,
            "timeWindowUnit": "h",
            "threshold": [0],
            "thresholdComparator": ">",
            "size": 100,
            "esqlQuery": {"esql": (
                "FROM logs-shopeasy.synthetics-default\n"
                "| where error.message IS NOT NULL \n"
                "| keep @timestamp, url.full, error.message"
            )},
            "aggType": "count",
            "groupBy": "all",
            "termSize": 5,
            "sourceFields": [],
            "timeField": "@timestamp",
            "excludeHitsFromPreviousRun": True,
        },
            "actions": [],
            "alert_delay": {"active": 1},
        })
        ok = status == 200
        print(f"  {'[created]' if ok else '[FAILED] '}  ShopEasy — App unreachable")
        if not ok:
            print(f"             {resp}")

    # ── ML anomaly alerts (wired to triage workflow) ───────────────────────────
    for a in ALERTS:
        if a["name"] in existing_names:
            print(f"  [exists]   {a['name']}")
            continue
        esql = "\n".join([
            'FROM .ml-anomalies* metadata _id',
            f'| WHERE job_id == "{a["job_id"]}"',
            '  AND result_type == "record"',
            f'  AND record_score >= {a["score_threshold"]}',
            '| KEEP _id, job_id, record_score, `by_field_value`, timestamp',
        ])
        resp, status = kb_call("POST", "/api/alerting/rule", {
            "name": a["name"],
            "tags": ["shopeasy", "ml", a["job_id"]],
            "rule_type_id": ".es-query",
            "consumer": "alerts",
            "schedule": {"interval": "1m"},
            "params": {
                "searchType": "esqlQuery",
                "timeWindowSize": 7,
                "timeWindowUnit": "d",
                "threshold": [0],
                "thresholdComparator": ">",
                "size": 100,
                "esqlQuery": {"esql": esql},
                "aggType": "count",
                "groupBy": "all",
                "termSize": 5,
                "sourceFields": [],
                "timeField": "@timestamp",
                "excludeHitsFromPreviousRun": False,
            },
            "actions": [{
                "id": "system-connector-.workflows",
                "params": {
                    "subAction": "run",
                    "subActionParams": {
                        "workflowId": workflow_id,
                        "summaryMode": True,
                    },
                },
            }] if workflow_id else [],
            "notify_when": "onActiveAlert",
        })
        ok = status == 200
        print(f"  {'[created]' if ok else '[FAILED] '}  {a['name']}")
        if not ok:
            print(f"             {resp}")
    print()


if __name__ == "__main__":
    import sys
    force = "--force" in sys.argv
    setup_jobs(force=force)
    setup_alerts(force=force)

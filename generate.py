#!/usr/bin/env python3
"""
Demo data generator for Elastic agentic incident triage (RCA) demo.
Multi-tier e-commerce app "ShopEasy" — 3 night outages.

Timestamps are always "last night": yesterday 21:00 UTC through today 07:00 UTC,
computed at runtime so the data is fresh relative to when ingest.py is run.

Timeline (all UTC, yesterday night):
  21:00 - 22:05  Normal operations
  22:05 - 23:15  OUTAGE 1 — Firewall rule 1042 misconfigured: REJECT on TCP/443
  23:15 - 01:00  Normal operations
  01:00 - 02:45  OUTAGE 2 — checkout-service v2.1.1 deployed with missing DATABASE_POOL_SIZE config
  02:45 - 03:30  Normal operations
  03:30 - 05:15  OUTAGE 3 — VMware backup job floods esx-host-02 disk; cpu.ready spikes on db-prod-01; PG queries slow
  05:15 - 07:00  Normal operations
"""

import json, random, os
from pathlib import Path
from datetime import datetime, timedelta, timezone

random.seed(42)

OUTPUT_DIR = str(Path(__file__).parent / "data")
os.makedirs(OUTPUT_DIR, exist_ok=True)

# Always "the night before this run": yesterday at 21:00 UTC.
# Works at any time of day — the 10-hour window ends at 07:00 this morning.
BASE = datetime.now(timezone.utc).replace(hour=21, minute=0, second=0, microsecond=0) - timedelta(days=1)
TOTAL_MIN = 600        # 21:00 → 07:00
HIST_DAYS = 5
HIST_MIN  = HIST_DAYS * 24 * 60  # 7200 min of clean baseline before the outage night

# Outage windows in minutes-from-BASE
O1_S, O1_E = 65,  135   # 22:05 – 23:15  Firewall
O2_S, O2_E = 240, 345   # 01:00 – 02:45  Software update
O3_S, O3_E = 390, 495   # 03:30 – 05:15  VMware / DB

def at(m, s=0):
    return BASE + timedelta(minutes=m, seconds=s)

def jdt(dt, spread=20):
    return dt + timedelta(seconds=random.uniform(-spread, spread))

def fmt(dt):
    ms = dt.microsecond // 1000
    return dt.strftime(f"%Y-%m-%dT%H:%M:%S.{ms:03d}Z")

def state(m):
    if O1_S <= m < O1_E: return 1
    if O2_S <= m < O2_E: return 2
    if O3_S <= m < O3_E: return 3
    return 0

def progress(m, s, e):
    return min(1.0, max(0.0, (m - s) / (e - s)))

def rnd_trace():
    return ''.join(random.choices('0123456789abcdef', k=32))

def rnd_span():
    return ''.join(random.choices('0123456789abcdef', k=16))

def write_ndjson(fname, records):
    path = os.path.join(OUTPUT_DIR, fname)
    with open(path, 'w') as f:
        for r in records:
            f.write(json.dumps(r) + '\n')
    print(f"  {len(records):5d} records  →  {fname}")


# ─────────────────────────────────────────────────────────────────────────────
# 1. SYNTHETICS  (Elastic Heartbeat / Synthetics format, ECS)
# ─────────────────────────────────────────────────────────────────────────────
MONITORS = [
    {"id": "checkout-user-flow",  "name": "Checkout User Flow",   "url": "https://shop.example.com/checkout",     "type": "browser"},
    {"id": "api-products",        "name": "Product Search API",   "url": "https://api.example.com/v1/products",   "type": "http"},
    {"id": "api-health",          "name": "API Health Check",     "url": "https://api.example.com/health",        "type": "http"},
]
PROBES = [
    {"name": "probe-us-east-1", "geo": {"name": "US East", "continent_name": "North America"}},
    {"name": "probe-eu-west-1", "geo": {"name": "EU West", "continent_name": "Europe"}},
]

def gen_synthetics():
    recs = []
    for m in range(-HIST_MIN, TOTAL_MIN, 1):
        s = state(m)
        for mon in MONITORS:
            for probe in PROBES:
                dt = jdt(at(m), 5)
                rec = {
                    "@timestamp": fmt(dt),
                    "monitor": {
                        "id":           mon["id"],
                        "name":         mon["name"],
                        "type":         mon["type"],
                        "check_group":  f"{mon['id']}-{m:05d}-{probe['name']}",
                    },
                    "url": {"full": mon["url"], "scheme": "https",
                            "domain": mon["url"].split("/")[2],
                            "path": "/" + "/".join(mon["url"].split("/")[3:]) or "/"},
                    "observer": {"name": probe["name"], "geo": probe["geo"]},
                    "agent":    {"name": probe["name"], "type": "heartbeat", "version": "8.12.0"},
                    "event":    {"dataset": "synthetics", "type": ["heartbeat_monitor"]},
                }

                if s == 0:  # Normal
                    dur = random.randint(80_000, 360_000)
                    rec["monitor"]["status"]   = "up"
                    rec["monitor"]["duration"] = {"us": dur}
                    rec["http"] = {"response": {"status_code": 200, "body": {"bytes": random.randint(1000, 50000)}}}

                elif s == 1:  # Firewall blocking — TCP connection refused
                    rec["monitor"]["status"]   = "down"
                    rec["monitor"]["duration"] = {"us": random.randint(30_000_000, 60_000_000)}
                    rec["error"] = {
                        "type": "io",
                        "message": "dial tcp 10.0.1.10:443: connect: connection refused",
                    }

                elif s == 2:  # App 500 — only checkout fails
                    if mon["id"] == "checkout-user-flow":
                        rec["monitor"]["status"]   = "down"
                        rec["monitor"]["duration"] = {"us": random.randint(180_000, 520_000)}
                        rec["http"] = {"response": {"status_code": 500}}
                        rec["error"] = {"type": "http", "message": "HTTP 500 Internal Server Error"}
                    else:
                        dur = random.randint(80_000, 340_000)
                        rec["monitor"]["status"]   = "up"
                        rec["monitor"]["duration"] = {"us": dur}
                        rec["http"] = {"response": {"status_code": 200, "body": {"bytes": random.randint(1000, 20000)}}}

                elif s == 3:  # DB slow — gradual degradation
                    p = progress(m, O3_S, O3_E)
                    if p < 0.15:
                        dur = random.randint(1_500_000, 6_000_000)
                        rec["monitor"]["status"]   = "up"
                        rec["monitor"]["duration"] = {"us": dur}
                        rec["http"] = {"response": {"status_code": 200}}
                    elif p < 0.5:
                        if random.random() < 0.55:
                            rec["monitor"]["status"]   = "down"
                            rec["monitor"]["duration"] = {"us": 30_000_000}
                            rec["http"] = {"response": {"status_code": 504}}
                            rec["error"] = {"type": "http", "message": "HTTP 504 Gateway Timeout"}
                        else:
                            dur = random.randint(4_000_000, 12_000_000)
                            rec["monitor"]["status"]   = "up"
                            rec["monitor"]["duration"] = {"us": dur}
                            rec["http"] = {"response": {"status_code": 200}}
                    else:
                        if random.random() < 0.80:
                            rec["monitor"]["status"]   = "down"
                            rec["monitor"]["duration"] = {"us": 30_000_000}
                            rec["http"] = {"response": {"status_code": 504}}
                            rec["error"] = {"type": "http", "message": "HTTP 504 Gateway Timeout"}
                        else:
                            rec["monitor"]["status"]   = "up"
                            rec["monitor"]["duration"] = {"us": random.randint(8_000_000, 20_000_000)}
                            rec["http"] = {"response": {"status_code": 200}}

                recs.append(rec)

    recs.sort(key=lambda r: r["@timestamp"])
    return recs


# ─────────────────────────────────────────────────────────────────────────────
# 2. FIREWALL LOGS  (ECS network / observer)
# ─────────────────────────────────────────────────────────────────────────────
APP_IPS   = ["10.0.1.10", "10.0.1.11", "10.0.1.12"]
EXT_IPS   = [f"203.{random.randint(0,255)}.{random.randint(0,255)}.{random.randint(1,250)}" for _ in range(60)]
FW_OBS    = {"name": "fw-edge-01", "type": "firewall", "vendor": "Palo Alto Networks",
             "product": "PA-5220", "version": "10.2.4"}

def fw_base(dt, action, rule_id, rule_name, src_ip, src_port, dst_ip, dst_port, proto="tcp", outcome="success"):
    return {
        "@timestamp": fmt(dt),
        "event": {
            "action":   action,
            "outcome":  outcome,
            "category": ["network"],
            "type":     ["allowed" if action == "allow" else "denied"],
            "dataset":  "firewall.traffic",
        },
        "source":      {"ip": src_ip, "port": src_port},
        "destination": {"ip": dst_ip, "port": dst_port},
        "network":     {"transport": proto, "direction": "inbound", "protocol": "https" if dst_port == 443 else "ssh"},
        "rule":        {"id": rule_id, "name": rule_name},
        "observer":    FW_OBS,
    }

def gen_firewall():
    recs = []

    # Config change event: 22:04 — rule 1042 accidentally changed to REJECT
    recs.append({
        "@timestamp": fmt(at(64)),
        "event": {
            "action":   "config-change",
            "outcome":  "success",
            "category": ["configuration"],
            "type":     ["change"],
            "dataset":  "firewall.config",
        },
        "message": (
            "Ruleset 'prod-external-v2.3' applied. Rule 1042 (allow-https-inbound) modified: "
            "action=ALLOW → action=REJECT for dst_net=10.0.1.0/24 dst_port=443. "
            "Deployed by: netops-bot via automation pipeline job #3871."
        ),
        "observer": FW_OBS,
        "user":     {"name": "netops-bot"},
        "rule":     {"id": "1042", "name": "allow-https-inbound", "ruleset": "prod-external-v2.3"},
        "log":      {"level": "notice"},
        "tags":     ["firewall", "config-change"],
    })

    for m in range(-HIST_MIN, TOTAL_MIN):
        s = state(m)

        if s == 1:
            # Dense DENY logs while firewall is misconfigured
            for _ in range(random.randint(18, 28)):
                dt   = jdt(at(m), 29)
                src  = random.choice(EXT_IPS)
                dst  = random.choice(APP_IPS)
                sport = random.randint(10000, 65000)
                r    = fw_base(dt, "deny", "1042", "allow-https-inbound", src, sport, dst, 443, outcome="failure")
                r["message"] = f"REJECT rule=1042 src={src}:{sport} dst={dst}:443 proto=TCP flags=SYN"
                r["log"] = {"level": "warning"}
                r["tags"] = ["firewall", "deny", "https", "outage-1"]
                recs.append(r)
            # Occasional SSH management still works
            for _ in range(2):
                dt = jdt(at(m), 29)
                r  = fw_base(dt, "allow", "5010", "allow-mgmt-ssh",
                             "10.0.0.5", random.randint(10000, 65000), random.choice(APP_IPS), 22)
                r["message"] = f"ALLOW rule=5010 src=10.0.0.5 dst={r['destination']['ip']}:22 proto=TCP"
                r["log"] = {"level": "informational"}
                recs.append(r)

        elif m % 2 == 0:
            # Normal: sample every 2 minutes
            for _ in range(random.randint(6, 12)):
                dt   = jdt(at(m), 55)
                src  = random.choice(EXT_IPS)
                dst  = random.choice(APP_IPS)
                sport = random.randint(10000, 65000)
                r    = fw_base(dt, "allow", "1042", "allow-https-inbound", src, sport, dst, 443)
                r["message"] = f"ALLOW rule=1042 src={src}:{sport} dst={dst}:443 proto=TCP bytes={random.randint(500,8000)}"
                r["log"] = {"level": "informational"}
                recs.append(r)

    # Rollback event: 23:15 — on-call SRE reverts to v2.2
    recs.append({
        "@timestamp": fmt(at(135, 45)),
        "event": {
            "action":   "config-change",
            "outcome":  "success",
            "category": ["configuration"],
            "type":     ["change"],
            "dataset":  "firewall.config",
        },
        "message": (
            "ROLLBACK: ruleset reverted 'prod-external-v2.3' → 'prod-external-v2.2'. "
            "Rule 1042 (allow-https-inbound) restored: action=REJECT → action=ALLOW. "
            "Initiated by: on-call-sre. Incident: INC-2024-0115-001."
        ),
        "observer": FW_OBS,
        "user":     {"name": "on-call-sre"},
        "rule":     {"id": "1042", "name": "allow-https-inbound", "ruleset": "prod-external-v2.2"},
        "log":      {"level": "notice"},
        "tags":     ["firewall", "config-change", "rollback"],
    })

    recs.sort(key=lambda r: r["@timestamp"])
    return recs


# ─────────────────────────────────────────────────────────────────────────────
# 3. APP LOGS  (ECS log / apm)
# ─────────────────────────────────────────────────────────────────────────────
SERVICES = {
    "api-gateway":       {"host": "app-prod-01", "version": "1.8.3"},
    "checkout-service":  {"host": "app-prod-02", "version": "2.1.0"},
    "payment-service":   {"host": "app-prod-03", "version": "3.0.1"},
    "inventory-service": {"host": "app-prod-03", "version": "1.5.2"},
}

def gen_app_logs():
    recs = []

    # ── Deployment event (checkout-service v2.1.1) at 00:58 ──
    recs.append({
        "@timestamp": fmt(at(238)),
        "log.level": "info",
        "message": (
            "Deployment started — PR #847 'feat: cart persistence'. "
            "Services: checkout-service 2.1.0 → 2.1.1. "
            "Deploy ID: deploy-847. Operator: ci-pipeline."
        ),
        "service.name": "deployment-manager",
        "host.name": "deploy-prod-01",
        "event.action": "deployment-start",
        "labels": {
            "deploy_id": "deploy-847",
            "checkout_version": "2.1.1",
        },
    })
    # checkout-service starts with missing config
    recs.append({
        "@timestamp": fmt(at(239, 40)),
        "log.level": "warn",
        "message": (
            "Application started with configuration warnings: "
            "environment variable DATABASE_POOL_SIZE is not set — defaulting to null. "
            "CartService connection pool will fail at first invocation."
        ),
        "service.name":    "checkout-service",
        "service.version": "2.1.1",
        "host.name": SERVICES["checkout-service"]["host"],
        "labels": {"missing_config": "DATABASE_POOL_SIZE", "deploy_id": "deploy-847"},
    })

    for m in range(-HIST_MIN, TOTAL_MIN):
        s = state(m)

        if s == 0:
            if m % 3 == 0:
                svc, info = random.choice(list(SERVICES.items()))
                dt = jdt(at(m), 50)
                recs.append({
                    "@timestamp": fmt(dt),
                    "log.level": "info",
                    "message": f"Request OK — {random.choice(['POST /v1/checkout/process','GET /v1/products?q=shoes','GET /v1/user/cart','GET /health'])} {random.randint(50,320)}ms",
                    "service.name":    svc,
                    "service.version": info["version"],
                    "host.name":       info["host"],
                    "trace.id":  rnd_trace(),
                    "span.id":   rnd_span(),
                    "http.response.status_code": 200,
                    "event.duration": random.randint(50_000_000, 320_000_000),
                })

        elif s == 1:
            # App sees no inbound requests; log traffic drop warning every 10 min
            if m % 10 == 0:
                recs.append({
                    "@timestamp": fmt(at(m)),
                    "log.level": "warn",
                    "message": "Traffic anomaly: inbound request rate = 0 req/min (expected ≥100). No upstream errors — possible network-level block.",
                    "service.name":    "api-gateway",
                    "service.version": SERVICES["api-gateway"]["version"],
                    "host.name": SERVICES["api-gateway"]["host"],
                    "labels": {"alert": "zero_traffic"},
                })

        elif s == 2:
            # checkout-service NullPointerException on every cart operation
            for _ in range(random.randint(3, 7)):
                dt = jdt(at(m), 55)
                recs.append({
                    "@timestamp": fmt(dt),
                    "log.level": "error",
                    "message": (
                        "Unhandled exception — CheckoutController.processCheckout(): "
                        "NullPointerException: 'poolSize' config key not found. "
                        "CartService.initPool() failed to read DATABASE_POOL_SIZE."
                    ),
                    "service.name":    "checkout-service",
                    "service.version": "2.1.1",
                    "host.name": SERVICES["checkout-service"]["host"],
                    "trace.id":  rnd_trace(),
                    "span.id":   rnd_span(),
                    "error.type":        "java.lang.NullPointerException",
                    "error.message":     "'poolSize' config key not found in environment",
                    "error.stack_trace": (
                        "java.lang.NullPointerException: 'poolSize' config key not found\n"
                        "\tat com.shopeasy.CartService.initPool(CartService.java:247)\n"
                        "\tat com.shopeasy.CheckoutController.processCheckout(CheckoutController.java:89)\n"
                        "\tat org.springframework.web.servlet.FrameworkServlet.service(FrameworkServlet.java:897)"
                    ),
                    "http.request.method":    "POST",
                    "http.request.body.content": "/v1/checkout/process",
                    "http.response.status_code": 500,
                    "labels": {"deploy_id": "deploy-847", "version": "2.1.1"},
                })
            # api-gateway propagates 500 upstream
            for _ in range(random.randint(2, 4)):
                dt = jdt(at(m), 55)
                recs.append({
                    "@timestamp": fmt(dt),
                    "log.level": "error",
                    "message": "Upstream checkout-service returned HTTP 500 — propagating error to client.",
                    "service.name":    "api-gateway",
                    "service.version": SERVICES["api-gateway"]["version"],
                    "host.name": SERVICES["api-gateway"]["host"],
                    "trace.id": rnd_trace(),
                    "http.response.status_code": 500,
                    "labels": {"upstream": "checkout-service"},
                })

        elif s == 3:
            p     = progress(m, O3_S, O3_E)
            db_ms = int(80 + p * 9920)   # 80ms → 10000ms
            if m % 2 == 0:
                dt = jdt(at(m), 50)
                if db_ms < 2000:
                    recs.append({
                        "@timestamp": fmt(dt),
                        "log.level": "warn",
                        "message": f"Slow DB query: SELECT orders JOIN cart_items took {db_ms}ms (SLA threshold=200ms). Host: db-prod-01:5432.",
                        "service.name":    "checkout-service",
                        "service.version": SERVICES["checkout-service"]["version"],
                        "host.name": SERVICES["checkout-service"]["host"],
                        "trace.id": rnd_trace(),
                        "labels": {"db_host": "db-prod-01", "query_ms": str(db_ms)},
                    })
                else:
                    recs.append({
                        "@timestamp": fmt(dt),
                        "log.level": "error",
                        "message": f"DB connection timeout after {db_ms}ms — HikariCP pool exhausted waiting for db-prod-01:5432. Returning 504 to client.",
                        "service.name":    "checkout-service",
                        "service.version": SERVICES["checkout-service"]["version"],
                        "host.name": SERVICES["checkout-service"]["host"],
                        "trace.id": rnd_trace(),
                        "error.type":    "com.zaxxer.hikari.pool.HikariPool$PoolInitializationException",
                        "error.message": f"Connection is not available, request timed out after {db_ms}ms",
                        "http.response.status_code": 504,
                        "labels": {"db_host": "db-prod-01", "query_ms": str(db_ms)},
                    })


    # Rollback checkpoint at 02:45 (minute 345)
    recs.append({
        "@timestamp": fmt(at(345)),
        "log.level": "info",
        "message": "Rollback: checkout-service 2.1.1 → 2.1.0. Incident: INC-2024-0115-002. Operator: on-call-sre.",
        "service.name": "deployment-manager",
        "host.name": "deploy-prod-01",
        "event.action": "rollback",
        "labels": {
            "deploy_id":   "deploy-847",
            "rolled_back": "checkout-service",
        },
    })

    recs.sort(key=lambda r: r["@timestamp"])
    return recs


# ─────────────────────────────────────────────────────────────────────────────
# 4. APP TRACES  (Elastic APM wire format)
#
# The APM UI requires:
#   - processor.event = "transaction" | "span" | "error"
#   - processor.name  = "transaction"
#   - service.environment
#   - agent.name + agent.version
#   - transaction.sampled = true
#   - span documents linked via parent.id → transaction.id
# ─────────────────────────────────────────────────────────────────────────────

APM_COMMON = {
    "processor.name":      "transaction",
    "service.environment": "production",
    "service.language.name": "Java",
    "agent.name":          "java",
    "agent.version":       "1.44.0",
    "observer.type":       "apm-server",
    "observer.version":    "8.12.0",
}

def txn(dt, tid, txn_id, name, svc, svc_ver, host, dur_us, result, outcome, extra=None):
    doc = {
        "@timestamp":              fmt(dt),
        "processor.event":         "transaction",
        "trace.id":                tid,
        "transaction.id":          txn_id,
        "transaction.name":        name,
        "transaction.type":        "request",
        "transaction.duration.us": dur_us,
        "transaction.result":      result,
        "transaction.outcome":     outcome,
        "transaction.sampled":     True,
        "service.name":            svc,
        "service.version":         svc_ver,
        "host.name":               host,
        **APM_COMMON,
    }
    if extra:
        doc.update(extra)
    return doc

def span(dt, tid, txn_id, span_id, name, span_type, subtype, dur_us, svc, svc_ver, host, extra=None):
    doc = {
        "@timestamp":          fmt(dt),
        "processor.event":     "span",
        "trace.id":            tid,
        "transaction.id":      txn_id,
        "span.id":             span_id,
        "parent.id":           txn_id,
        "span.name":           name,
        "span.type":           span_type,
        "span.subtype":        subtype,
        "span.duration.us":    dur_us,
        "span.outcome":        "success" if dur_us < 5_000_000 else "failure",
        "service.name":        svc,
        "service.version":     svc_ver,
        "host.name":           host,
        **APM_COMMON,
    }
    if extra:
        doc.update(extra)
    return doc

def err(dt, tid, txn_id, svc, svc_ver, host, exc_type, exc_msg, stack=None):
    doc = {
        "@timestamp":                   fmt(dt),
        "processor.event":              "error",
        "processor.name":               "error",
        "trace.id":                     tid,
        "transaction.id":               txn_id,
        "error.id":                     rnd_trace(),
        "error.exception.type":         exc_type,
        "error.exception.message":      exc_msg,
        "error.exception.handled":      False,
        "service.name":                 svc,
        "service.version":              svc_ver,
        "host.name":                    host,
        "agent.name":                   "java",
        "agent.version":                "1.44.0",
        "service.environment":          "production",
        "observer.type":                "apm-server",
        "observer.version":             "8.12.0",
    }
    if stack:
        doc["error.stack_trace"] = stack
    return doc

def gen_traces():
    recs = []
    for m in range(-HIST_MIN, TOTAL_MIN, 2):
        s     = state(m)
        dt    = jdt(at(m), 25)
        tid   = rnd_trace()
        txn_id = rnd_span()

        if s == 0:
            dur_us = random.randint(90_000, 380_000)
            db_us  = random.randint(5_000, 40_000)
            span_id = rnd_span()
            recs.append(txn(dt, tid, txn_id,
                            "POST /v1/checkout/process",
                            "checkout-service", SERVICES["checkout-service"]["version"],
                            SERVICES["checkout-service"]["host"],
                            dur_us, "HTTP 2xx", "success"))
            recs.append(span(dt, tid, txn_id, span_id,
                             "SELECT orders JOIN cart_items", "db", "postgresql", db_us,
                             "checkout-service", SERVICES["checkout-service"]["version"],
                             SERVICES["checkout-service"]["host"],
                             extra={"span.db.statement": "SELECT o.*, ci.* FROM orders o JOIN cart_items ci ON o.id=ci.order_id WHERE o.user_id=$1",
                                    "span.db.type": "sql", "span.db.instance": "shopeasy_prod",
                                    "destination.service.resource": "postgresql"}))

        elif s == 2:
            dur_us = random.randint(180_000, 550_000)
            recs.append(txn(dt, tid, txn_id,
                            "POST /v1/checkout/process",
                            "checkout-service", "2.1.1",
                            SERVICES["checkout-service"]["host"],
                            dur_us, "HTTP 5xx", "failure"))
            recs.append(err(dt, tid, txn_id,
                            "checkout-service", "2.1.1",
                            SERVICES["checkout-service"]["host"],
                            "java.lang.NullPointerException",
                            "'poolSize' config key not found in environment",
                            stack=(
                                "java.lang.NullPointerException: 'poolSize' config key not found\n"
                                "\tat com.shopeasy.CartService.initPool(CartService.java:247)\n"
                                "\tat com.shopeasy.CheckoutController.processCheckout(CheckoutController.java:89)\n"
                                "\tat org.springframework.web.servlet.FrameworkServlet.service(FrameworkServlet.java:897)"
                            )))

        elif s == 3:
            p      = progress(m, O3_S, O3_E)
            db_us  = int(5_000 + p * 9_995_000)
            tot    = min(db_us + random.randint(10_000, 40_000), 30_000_000)
            result = "HTTP 5xx" if tot > 10_000_000 else "HTTP 2xx"
            outcome = "failure" if tot > 10_000_000 else "success"
            span_id = rnd_span()
            recs.append(txn(dt, tid, txn_id,
                            "POST /v1/checkout/process",
                            "checkout-service", SERVICES["checkout-service"]["version"],
                            SERVICES["checkout-service"]["host"],
                            tot, result, outcome,
                            extra={"labels": {"db_slow": "true", "vmware_cause": "disk-congestion-backup-job"}}))
            recs.append(span(dt, tid, txn_id, span_id,
                             "SELECT orders JOIN cart_items", "db", "postgresql",
                             min(db_us, 30_000_000),
                             "checkout-service", SERVICES["checkout-service"]["version"],
                             SERVICES["checkout-service"]["host"],
                             extra={"span.db.statement": "SELECT o.order_id, o.user_id, o.total_amount, ci.product_id, ci.quantity FROM orders o JOIN cart_items ci ON o.id=ci.order_id WHERE o.user_id=$1 ORDER BY o.created_at DESC LIMIT 50",
                                    "span.db.type": "sql", "span.db.instance": "shopeasy_prod",
                                    "destination.service.resource": "postgresql",
                                    "labels": {"db_slow": "true"}}))


    recs.sort(key=lambda r: r["@timestamp"])
    return recs


# ─────────────────────────────────────────────────────────────────────────────
# 5. POSTGRESQL LOGS  (ECS + postgresql.log.*)
# ─────────────────────────────────────────────────────────────────────────────
def gen_pg_logs():
    recs = []

    for m in range(-HIST_MIN, TOTAL_MIN, 4):
        s = state(m)
        dt = jdt(at(m), 30)

        if s == 0:
            if m % 40 == 0:
                recs.append({
                    "@timestamp": fmt(dt),
                    "log.level": "info",
                    "message": f"checkpoint complete: wrote {random.randint(80,600)} buffers; {random.randint(0,3)} WAL files added; sync took {random.randint(1,8)}ms.",
                    "postgresql.log.database":       "shopeasy_prod",
                    "postgresql.log.query_duration_ms": 0,
                    "host.name": "db-prod-01",
                    "service.name":    "postgresql",
                    "service.version": "15.4",
                })

        elif s == 3:
            p     = progress(m, O3_S, O3_E)
            qms   = int(200 + p * 15800)   # 200ms → 16000ms
            severity = "ERROR" if qms > 3000 else "WARNING"
            recs.append({
                "@timestamp": fmt(dt),
                "log.level": severity.lower(),
                "message": (
                    f"duration: {qms} ms  statement: "
                    "SELECT o.order_id, o.user_id, o.total_amount, ci.product_id, ci.quantity, ci.unit_price "
                    "FROM orders o JOIN cart_items ci ON o.id = ci.order_id "
                    "WHERE o.user_id = $1 AND o.status = 'pending' ORDER BY o.created_at DESC LIMIT 50"
                ),
                "postgresql.log.database":         "shopeasy_prod",
                "postgresql.log.application_name": "checkout-service",
                "postgresql.log.remote_host":      "10.0.1.11",
                "postgresql.log.query": (
                    "SELECT o.order_id, o.user_id, o.total_amount, ci.product_id, ci.quantity, ci.unit_price "
                    "FROM orders o JOIN cart_items ci ON o.id = ci.order_id "
                    "WHERE o.user_id = $1 AND o.status = 'pending' ORDER BY o.created_at DESC LIMIT 50"
                ),
                "postgresql.log.query_duration_ms": qms,
                "postgresql.log.error_severity":   severity,
                "postgresql.log.session_id": ''.join(random.choices('0123456789abcdef', k=8)),
                "host.name": "db-prod-01",
                "service.name":    "postgresql",
                "service.version": "15.4",
                "labels": {"slow_query": "true", "query_ms": str(qms)},
            })

            # Checkpoint / fsync latency message
            if m % 20 == 0:
                fsync_ms = int(5 + p * 195)
                recs.append({
                    "@timestamp": fmt(jdt(at(m, 90), 15)),
                    "log.level": "warn",
                    "message": f"I/O performance degraded: fsync avg latency {fsync_ms}ms. Checkpointer falling behind. Possible disk congestion on underlying storage.",
                    "postgresql.log.database":       "shopeasy_prod",
                    "postgresql.log.query_duration_ms": 0,
                    "postgresql.log.error_severity": "WARNING",
                    "host.name": "db-prod-01",
                    "service.name":    "postgresql",
                    "service.version": "15.4",
                    "labels": {"io_degraded": "true", "fsync_ms": str(fsync_ms)},
                })

            # Lock wait / idle-in-transaction pileup
            if m % 16 == 0 and p > 0.3:
                recs.append({
                    "@timestamp": fmt(jdt(at(m, 45), 10)),
                    "log.level": "warn",
                    "message": f"process {random.randint(10000,30000)} still waiting for ShareLock on transaction {random.randint(1000000,9999999)} after {int(p*5000)}ms",
                    "postgresql.log.database":       "shopeasy_prod",
                    "postgresql.log.query_duration_ms": int(p * 5000),
                    "postgresql.log.error_severity": "WARNING",
                    "postgresql.log.session_id": ''.join(random.choices('0123456789abcdef', k=8)),
                    "host.name": "db-prod-01",
                    "service.name":    "postgresql",
                    "service.version": "15.4",
                    "labels": {"lock_wait": "true"},
                })

    recs.sort(key=lambda r: r["@timestamp"])
    return recs


# ─────────────────────────────────────────────────────────────────────────────
# 6. POSTGRESQL METRICS  (Metricbeat postgresql module)
# ─────────────────────────────────────────────────────────────────────────────
def gen_pg_metrics():
    recs = []
    for m in range(-HIST_MIN, TOTAL_MIN, 1):
        s = state(m)
        dt = at(m, random.randint(0, 55))
        p  = progress(m, O3_S, O3_E)

        if s == 3:
            tup_fetched    = max(0, int(5000 - p * 4900))
            active_conns   = int(18 + p * 80)     # connections pile up waiting for slow queries
            blk_read_ms    = int(0   + p * 9500)  # block I/O wait skyrockets
            tup_returned   = max(100, int(55000 - p * 54000))
            rolled_back    = int(p * 60)
        elif s == 1:                               # firewall: no traffic
            tup_fetched    = random.randint(0, 30)
            active_conns   = random.randint(2, 4)
            blk_read_ms    = random.randint(0, 3)
            tup_returned   = random.randint(50, 200)
            rolled_back    = 0
        else:
            tup_fetched    = random.randint(3000, 7500)
            active_conns   = random.randint(12, 28)
            blk_read_ms    = random.randint(0, 8)
            tup_returned   = random.randint(28000, 65000)
            rolled_back    = random.randint(0, 5)

        recs.append({
            "@timestamp":                           fmt(dt),
            "metricset.name":                       "database",
            "metricset.period":                     60000,
            "postgresql.database.name":             "shopeasy_prod",
            "postgresql.database.oid":              16384,
            "postgresql.database.number_of_backends": active_conns,
            "postgresql.database.transactions.committed":   random.randint(80, 600),
            "postgresql.database.transactions.rolled_back": rolled_back,
            "postgresql.database.blocks.read":      random.randint(200, 2000),
            "postgresql.database.blocks.hit":       random.randint(8000, 120000),
            "postgresql.database.blocks.read_time_ms":  blk_read_ms,
            "postgresql.database.blocks.write_time_ms": int(blk_read_ms * 0.25),
            "postgresql.database.rows.returned":    tup_returned,
            "postgresql.database.rows.fetched":     tup_fetched,
            "postgresql.database.rows.inserted":    random.randint(5, 120),
            "postgresql.database.rows.updated":     random.randint(2, 60),
            "postgresql.database.rows.deleted":     random.randint(0, 20),
            "host.name":          "db-prod-01",
            "host.ip":            ["10.0.2.10"],
            "service.name":       "postgresql",
            "service.address":    "10.0.2.10:5432",
            "service.version":    "15.4",
            "event.duration":     random.randint(1_000_000, 6_000_000),
            "agent.name":         "metricbeat",
        })

    recs.sort(key=lambda r: r["@timestamp"])
    return recs


# ─────────────────────────────────────────────────────────────────────────────
# 7. VMWARE METRICS  (Metricbeat vsphere module)
# ─────────────────────────────────────────────────────────────────────────────
VMS = [
    {"name": "db-prod-01",      "host": "esx-host-02", "ip": "10.0.2.10", "role": "database",  "mem_gb": 16, "vcpu": 4},
    {"name": "app-prod-01",     "host": "esx-host-01", "ip": "10.0.1.10", "role": "app",        "mem_gb": 8,  "vcpu": 4},
    {"name": "app-prod-02",     "host": "esx-host-01", "ip": "10.0.1.11", "role": "app",        "mem_gb": 8,  "vcpu": 4},
    {"name": "backup-agent-01", "host": "esx-host-02", "ip": "10.0.3.20", "role": "backup",     "mem_gb": 4,  "vcpu": 2},
]
ESX_HOSTS = [
    {"name": "esx-host-01", "cpu_mhz_total": 40000, "mem_gb": 128},
    {"name": "esx-host-02", "cpu_mhz_total": 40000, "mem_gb": 128},
]

def gen_vmware_metrics():
    recs = []

    for m in range(-HIST_MIN, TOTAL_MIN, 1):
        s  = state(m)
        dt = at(m, random.randint(0, 59))
        p  = progress(m, O3_S, O3_E)

        # ── Per-VM metrics ──
        for vm in VMS:
            is_db_during_outage3   = (s == 3 and vm["name"] == "db-prod-01")
            is_bkp_during_outage3  = (s == 3 and vm["name"] == "backup-agent-01")

            if is_db_during_outage3:
                cpu_ready_ms       = int(5  + p * 495)    # 5 → 500ms — KEY SIGNAL
                disk_read_lat_ms   = int(1  + p * 199)    # 1 → 200ms
                disk_write_lat_ms  = int(1  + p * 149)
                disk_read_kbps     = int(400 + p * 49600) # flooded by backup reads on same datastore
                cpu_used_mhz       = int(600 + p * 1200)
                mem_used_bytes     = random.randint(10, 13) * 1024**3
                status             = "yellow" if cpu_ready_ms > 250 else "green"
            elif is_bkp_during_outage3:
                cpu_ready_ms       = random.randint(3, 12)
                disk_read_lat_ms   = int(1 + p * 60)
                disk_write_lat_ms  = int(1 + p * 120)
                disk_read_kbps     = int(2000 + p * 78000)  # massive backup throughput
                cpu_used_mhz       = int(1500 + p * 2500)
                mem_used_bytes     = random.randint(2, 4) * 1024**3
                status             = "green"
            else:
                cpu_ready_ms       = random.randint(2, 14)
                disk_read_lat_ms   = random.randint(1, 5)
                disk_write_lat_ms  = random.randint(1, 3)
                disk_read_kbps     = random.randint(100, 1500)
                cpu_used_mhz       = random.randint(200, 1800)
                mem_used_bytes     = random.randint(2, vm["mem_gb"] - 1) * 1024**3
                status             = "green"

            recs.append({
                "@timestamp":   fmt(dt),
                "metricset.name":  "virtualmachine",
                "metricset.period": 60000,
                "vsphere.virtualmachine.name":                          vm["name"],
                "vsphere.virtualmachine.host.hostname":                 vm["host"],
                "vsphere.virtualmachine.status":                        status,
                "vsphere.virtualmachine.cpu.used.mhz":                  cpu_used_mhz,
                "vsphere.virtualmachine.cpu.total.mhz":                 vm["vcpu"] * 3000,
                "vsphere.virtualmachine.cpu.free.mhz":                  max(0, vm["vcpu"] * 3000 - cpu_used_mhz),
                "vsphere.virtualmachine.cpu.ready.ms":                  cpu_ready_ms,
                "vsphere.virtualmachine.memory.used.guest.bytes":       mem_used_bytes,
                "vsphere.virtualmachine.memory.total.guest.bytes":      vm["mem_gb"] * 1024**3,
                "vsphere.virtualmachine.memory.free.guest.bytes":       max(0, vm["mem_gb"] * 1024**3 - mem_used_bytes),
                "vsphere.virtualmachine.storage.committed.bytes":       random.randint(80, 200) * 1024**3,
                "vsphere.virtualmachine.storage.uncommitted.bytes":     random.randint(10, 60) * 1024**3,
                "vsphere.virtualmachine.disk.read.average.kbps":        disk_read_kbps,
                "vsphere.virtualmachine.disk.write.average.kbps":       random.randint(50, 500),
                "vsphere.virtualmachine.disk.read.latency.ms":          disk_read_lat_ms,
                "vsphere.virtualmachine.disk.write.latency.ms":         disk_write_lat_ms,
                "vsphere.virtualmachine.network.received.kbps":         random.randint(100, 5000),
                "vsphere.virtualmachine.network.transmitted.kbps":      random.randint(50, 2000),
                "host.name":        vm["host"],
                "agent.name":       "metricbeat",
                "labels": {"vm_role": vm["role"], "vm_ip": vm["ip"]},
            })

        # ── Per-ESX-host metrics ──
        if m % 2 == 0:
            for esx in ESX_HOSTS:
                is_congested = (s == 3 and esx["name"] == "esx-host-02")
                if is_congested:
                    host_cpu_used    = int(8000 + p * 12000)
                    host_disk_read   = int(5000 + p * 125000)  # dominated by backup job
                    host_disk_lat    = int(1   + p * 199)
                    host_mem_used_gb = random.randint(60, 90)
                else:
                    host_cpu_used    = random.randint(3000, 12000)
                    host_disk_read   = random.randint(500, 8000)
                    host_disk_lat    = random.randint(1, 5)
                    host_mem_used_gb = random.randint(30, 80)

                recs.append({
                    "@timestamp":   fmt(dt),
                    "metricset.name":  "host",
                    "metricset.period": 120000,
                    "vsphere.host.name":                  esx["name"],
                    "vsphere.host.cpu.used.mhz":          host_cpu_used,
                    "vsphere.host.cpu.total.mhz":         esx["cpu_mhz_total"],
                    "vsphere.host.cpu.free.mhz":          max(0, esx["cpu_mhz_total"] - host_cpu_used),
                    "vsphere.host.memory.used.bytes":     host_mem_used_gb * 1024**3,
                    "vsphere.host.memory.total.bytes":    esx["mem_gb"]    * 1024**3,
                    "vsphere.host.memory.free.bytes":     max(0, (esx["mem_gb"] - host_mem_used_gb) * 1024**3),
                    "vsphere.host.disk.read.average.kbps":  host_disk_read,
                    "vsphere.host.disk.write.average.kbps": random.randint(500, 5000),
                    "vsphere.host.disk.latency.total.ms":   host_disk_lat,
                    "vsphere.host.network.received.kbps":   random.randint(5000, 50000),
                    "vsphere.host.network.transmitted.kbps": random.randint(5000, 50000),
                    "host.name":  esx["name"],
                    "agent.name": "metricbeat",
                })

    recs.sort(key=lambda r: r["@timestamp"])
    return recs


# ─────────────────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────────────────

def generate_all():
    """Generate all NDJSON files. Called directly or imported by ingest.py."""
    hist_start = BASE - timedelta(minutes=HIST_MIN)
    print(f"Generating ShopEasy demo data — {HIST_DAYS}d baseline ({hist_start.date()} → {BASE.date()}) + outage night …\n")
    write_ndjson("synthetics.ndjson",          gen_synthetics())
    write_ndjson("firewall-logs.ndjson",        gen_firewall())
    write_ndjson("app-logs.ndjson",             gen_app_logs())
    write_ndjson("app-traces.ndjson",           gen_traces())
    write_ndjson("postgresql-logs.ndjson",      gen_pg_logs())
    write_ndjson("postgresql-metrics.ndjson",   gen_pg_metrics())
    write_ndjson("vmware-metrics.ndjson",       gen_vmware_metrics())
    print(f"\nData written to {OUTPUT_DIR}")

if __name__ == "__main__":
    generate_all()

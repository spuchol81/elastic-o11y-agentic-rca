#!/usr/bin/env python3
"""
Ingest ShopEasy demo NDJSON files into Elastic Streams.

Instruqt variant of ../ingest.py — same ingestion logic, pointed at the
self-hosted cluster running inside the Instruqt sandbox VM instead of an
Elastic Cloud deployment. Only the connection bootstrap differs.

Usage (run by setup_elastic.sh, which exports these first):
    export ES_URL=http://elasticsearch-es-http.default.svc:9200
    export ELASTICSEARCH_APIKEY=<api-key>
    python3 ingest.py

Optional:
    export BATCH_SIZE=500    # documents per bulk request (default 500)
    export DATA_DIR=./data   # path to NDJSON files (default ../data)
"""

import json
import os
import sys
import time
from pathlib import Path

from elasticsearch import Elasticsearch, helpers, BadRequestError, NotFoundError

# generate.py lives at the repo root and has no connection logic of its own —
# reused as-is so the time-anchored data generation stays a single source of truth.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from generate import generate_all

# ── Config ────────────────────────────────────────────────────────────────────

ES_URL      = os.environ.get("ES_URL", "http://elasticsearch-es-http.default.svc:9200")
API_KEY     = os.environ.get("ELASTICSEARCH_APIKEY")
BATCH_SIZE  = int(os.environ.get("BATCH_SIZE", 500))
DATA_DIR    = Path(os.environ.get("DATA_DIR", Path(__file__).resolve().parent.parent / "data"))

# Map each NDJSON file to its target stream name.
# Stream name prefixes drive index mode automatically:
#   logs-*     → logsdb  (compression-optimised, synthetic _source)
#   metrics-*  → time_series
#   traces-*   → standard APM
STREAMS = {
    "synthetics.ndjson":         "logs-shopeasy.synthetics-default",
    "firewall-logs.ndjson":      "logs-shopeasy.firewall-default",
    "app-logs.ndjson":           "logs-shopeasy.app-default",
    "app-traces.ndjson":         "traces-apm.shopeasy-default",
    "postgresql-logs.ndjson":    "logs-shopeasy.postgresql-default",
    "postgresql-metrics.ndjson": "metrics-shopeasy.postgresql-default",
    "vmware-metrics.ndjson":     "metrics-shopeasy.vmware-default",
}


# ── Client ────────────────────────────────────────────────────────────────────

def build_client() -> Elasticsearch:
    if not API_KEY:
        print("ERROR: ELASTICSEARCH_APIKEY is not set")
        sys.exit(1)
    return Elasticsearch(hosts=[ES_URL], api_key=API_KEY, request_timeout=60)


# ── APM index template ───────────────────────────────────────────────────────

APM_TEMPLATE_NAME    = "traces-apm-shopeasy"
APM_TEMPLATE_PATTERN = "traces-apm.shopeasy-*"

APM_MAPPINGS = {
    "properties": {
        "@timestamp":                       {"type": "date"},
        "processor.event":                  {"type": "keyword"},
        "processor.name":                   {"type": "keyword"},
        "trace.id":                         {"type": "keyword"},
        "transaction.id":                   {"type": "keyword"},
        "transaction.name":                 {"type": "keyword"},
        "transaction.type":                 {"type": "keyword"},
        "transaction.result":               {"type": "keyword"},
        "transaction.outcome":              {"type": "keyword"},
        "transaction.duration.us":          {"type": "long"},
        "transaction.sampled":              {"type": "boolean"},
        "span.id":                          {"type": "keyword"},
        "span.name":                        {"type": "keyword"},
        "span.type":                        {"type": "keyword"},
        "span.subtype":                     {"type": "keyword"},
        "span.outcome":                     {"type": "keyword"},
        "span.duration.us":                 {"type": "long"},
        "span.db.statement":                {"type": "text"},
        "span.db.type":                     {"type": "keyword"},
        "span.db.instance":                 {"type": "keyword"},
        "parent.id":                        {"type": "keyword"},
        "error.id":                         {"type": "keyword"},
        "error.exception.type":             {"type": "keyword"},
        "error.exception.message":          {"type": "text"},
        "error.exception.handled":          {"type": "boolean"},
        "error.stack_trace":                {"type": "text", "index": False},
        "service.name":                     {"type": "keyword"},
        "service.version":                  {"type": "keyword"},
        "service.environment":              {"type": "keyword"},
        "service.language.name":            {"type": "keyword"},
        "agent.name":                       {"type": "keyword"},
        "agent.version":                    {"type": "keyword"},
        "host.name":                        {"type": "keyword"},
        "observer.type":                    {"type": "keyword"},
        "observer.version":                 {"type": "keyword"},
        "destination.service.resource":     {"type": "keyword"},
        "labels":                           {"type": "object", "dynamic": True},
    }
}

def ensure_apm_template(es: Elasticsearch) -> None:
    """Put the APM index template so traces-apm.shopeasy-* gets keyword mappings."""
    es.indices.put_index_template(
        name=APM_TEMPLATE_NAME,
        body={
            "index_patterns": [APM_TEMPLATE_PATTERN],
            "priority": 500,
            "template": {"mappings": APM_MAPPINGS},
        },
    )
    print(f"  [template] {APM_TEMPLATE_NAME}  →  {APM_TEMPLATE_PATTERN}")


# ── Wipe existing data ────────────────────────────────────────────────────────

def wipe_existing_data(es: Elasticsearch) -> None:
    """Delete all shopeasy data streams and the traces regular index so each run is clean."""
    print("\nWiping existing demo data …")

    # Data streams (logs-* and metrics-*)
    for pattern in ("logs-shopeasy.*", "metrics-shopeasy.*"):
        try:
            es.indices.delete_data_stream(name=pattern, expand_wildcards="all")
            print(f"  [deleted stream]  {pattern}")
        except NotFoundError:
            print(f"  [not found]       {pattern}")

    # traces-apm.shopeasy-default is a regular index (not a data stream)
    traces_index = "traces-apm.shopeasy-default"
    try:
        es.indices.delete(index=traces_index)
        print(f"  [deleted index]   {traces_index}")
    except NotFoundError:
        print(f"  [not found]       {traces_index}")


# ── Stream management ─────────────────────────────────────────────────────────

def ensure_stream(es: Elasticsearch, name: str) -> None:
    """Create stream if it doesn't exist; skip if already present."""
    try:
        # The Streams API (8.16+) — PUT /_streams/{name}
        es.transport.perform_request(
            "PUT",
            f"/_streams/{name}",
            headers={"Content-Type": "application/json"},
            body={},
        )
        print(f"  [created]  {name}")
    except BadRequestError as e:
        # resource_already_exists_exception is fine
        if "resource_already_exists" in str(e).lower() or "already exists" in str(e).lower():
            print(f"  [exists]   {name}")
        else:
            raise


def ensure_all_streams(es: Elasticsearch) -> None:
    print("\nEnsuring streams exist …")
    for stream_name in set(STREAMS.values()):
        ensure_stream(es, stream_name)


# ── Ingestion ─────────────────────────────────────────────────────────────────

def read_ndjson(path: Path):
    """Yield parsed JSON objects from an NDJSON file."""
    with open(path) as f:
        for lineno, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError as e:
                print(f"    WARN: skipping malformed line {lineno} in {path.name}: {e}")


def bulk_actions(path: Path, stream: str):
    """Yield bulk action dicts for the helpers.bulk API."""
    for doc in read_ndjson(path):
        yield {
            "_index":  stream,
            "_op_type": "create",
            "_source": doc,
        }


def ingest_file(es: Elasticsearch, path: Path, stream: str) -> tuple[int, int]:
    """Bulk-ingest one NDJSON file. Returns (ok_count, error_count)."""
    ok = err = 0
    actions = bulk_actions(path, stream)

    for success, info in helpers.parallel_bulk(
        es,
        actions,
        chunk_size=BATCH_SIZE,
        raise_on_error=False,
        raise_on_exception=False,
    ):
        if success:
            ok += 1
        else:
            err += 1
            op = list(info.values())[0]
            print(f"    ERROR: {op.get('error', info)}")

    return ok, err


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    # Step 1: regenerate NDJSON with timestamps anchored to last night
    generate_all()
    print()

    # Step 2: connect and ingest
    print(f"Connecting to {ES_URL} …")
    es = build_client()

    # Quick connectivity check
    try:
        info = es.info()
        print(f"Connected: Elasticsearch {info['version']['number']} "
              f"({info['cluster_name']})")
    except Exception as e:
        print(f"ERROR: cannot reach Elasticsearch — {e}")
        sys.exit(1)

    wipe_existing_data(es)

    print("\nEnsuring index templates …")
    ensure_apm_template(es)

    ensure_all_streams(es)

    print("\nIngesting files …")
    total_ok = total_err = 0
    t0 = time.time()

    for fname, stream in STREAMS.items():
        path = DATA_DIR / fname
        if not path.exists():
            print(f"  SKIP  {fname}  (file not found)")
            continue

        t1 = time.time()
        ok, err = ingest_file(es, path, stream)
        elapsed = time.time() - t1
        rate    = ok / elapsed if elapsed else 0

        status = "OK" if err == 0 else f"PARTIAL ({err} errors)"
        print(f"  {status:20s}  {ok:5d} docs  {elapsed:5.1f}s  ({rate:,.0f} docs/s)  →  {stream}")
        total_ok  += ok
        total_err += err

    elapsed_total = time.time() - t0
    print(f"\nDone — {total_ok:,} docs indexed, {total_err} errors, "
          f"{elapsed_total:.1f}s total ({total_ok/elapsed_total:,.0f} docs/s avg)")

    if total_err:
        sys.exit(1)


if __name__ == "__main__":
    main()

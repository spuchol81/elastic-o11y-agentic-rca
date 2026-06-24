#!/usr/bin/env bash
# Provisions the ShopEasy RCA demo (data, agent, workflow, ML jobs, alert
# rules, dashboard) against the self-hosted Elastic cluster running inside
# the Instruqt sandbox VM.
#
# Equivalent of, against an Elastic Cloud deployment:
#   python3 ingest.py && python3 setup_agent.py && python3 setup_workflow.py \
#     && python3 setup_ml_jobs.py && python3 setup_dashboard.py
#
# The instruqt/ copies of those scripts are identical except for the
# connection bootstrap (self-hosted URL + auth instead of ES_CLOUD_ID).
#
# Usage: ./setup_elastic.sh
#
# Requires: python3, pip3, curl

set -euxo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

######### ENV ##########

ENV_FILE_PARENT_DIR=/home/kubernetes-vm
ENV_FILE=$ENV_FILE_PARENT_DIR/env
export $(cat "$ENV_FILE" | xargs)

export ES_URL="${ES_URL:-http://elasticsearch-es-http.default.svc:9200}"
export KB_URL="${KB_URL:-http://kubernetes-vm:30001}"
export KB_USER="${KB_USER:-elastic}"
export KB_PASS="${KB_PASS:-changeme}"
# ELASTICSEARCH_APIKEY is expected to come from $ENV_FILE

######### DEPENDENCIES ##########

python3 -m pip install --quiet elasticsearch

######### PIPELINE ##########

cd "$SCRIPT_DIR"

python3 ingest.py
python3 setup_agent.py
python3 setup_workflow.py
python3 setup_ml_jobs.py
python3 setup_dashboard.py

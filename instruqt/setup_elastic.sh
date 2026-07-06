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

########### AI SETUP ###########
/opt/workshops/elastic-llm.sh -k true

########## Solution view ##########

/opt/workshops/elastic-view.sh -v oblt

######### DEPENDENCIES ##########

python3 -m pip install --quiet elasticsearch

######### PIPELINE ##########

cd "$SCRIPT_DIR"

python3 ingest.py
python3 setup_agent.py

######### MATTERMOST CONNECTOR ##########
# Must run before setup_workflow.py — the workflow's notify_mattermost step
# resolves this connector's ID by name at update time (see setup_workflow.py).

MM_URL="${MM_URL:-http://host-1:8065}"

MM_TOKEN=$(curl -sf -i -X POST "$MM_URL/api/v4/users/login" \
  -H "Content-Type: application/json" \
  -d '{"login_id":"admin","password":"Instruqt123!"}' \
  | grep -i '^Token:' | awk '{print $2}' | tr -d '\r')

TEAM_ID=$(curl -sf -H "Authorization: Bearer $MM_TOKEN" \
  "$MM_URL/api/v4/teams/name/shopeasy" | jq -r '.id')

CHANNEL_ID=$(curl -sf -H "Authorization: Bearer $MM_TOKEN" \
  "$MM_URL/api/v4/teams/$TEAM_ID/channels/name/incidents" | jq -r '.id')

WEBHOOK_ID=$(curl -sf -H "Authorization: Bearer $MM_TOKEN" \
  "$MM_URL/api/v4/hooks/incoming?channel_id=$CHANNEL_ID" | jq -r '.[0].id')

MM_WEBHOOK_URL="$MM_URL/hooks/$WEBHOOK_ID"

KB_AUTH="Basic $(echo -n "$KB_USER:$KB_PASS" | base64)"

# Idempotent: delete existing connector by name before recreating
EXISTING_ID=$(curl -sf "$KB_URL/api/actions/connectors" \
  -H "Authorization: $KB_AUTH" \
  | jq -r '.[] | select(.name == "mattermost-incidents") | .id // empty')
if [[ -n "$EXISTING_ID" ]]; then
  curl -sf -X DELETE "$KB_URL/api/actions/connector/$EXISTING_ID" \
    -H "Authorization: $KB_AUTH" -H "kbn-xsrf: true" > /dev/null
fi

curl -sf -X POST "$KB_URL/api/actions/connector" \
  -H "Authorization: $KB_AUTH" \
  -H "Content-Type: application/json" \
  -H "kbn-xsrf: true" \
  -d "{
    \"connector_type_id\": \".webhook\",
    \"name\": \"mattermost-incidents\",
    \"config\": {
      \"method\": \"post\",
      \"url\": \"$MM_WEBHOOK_URL\",
      \"headers\": {\"Content-Type\": \"application/json\"},
      \"hasAuth\": false
    },
    \"secrets\": {}
  }" > /dev/null

echo "[setup-elastic] Kibana Webhook connector 'mattermost-incidents' -> $MM_WEBHOOK_URL"

python3 setup_workflow.py
python3 setup_ml_jobs.py
python3 setup_dashboard.py

#!/usr/bin/env bash
# Starts Mattermost (preview image) and provisions the ShopEasy workshop
# scenario: one team, one incidents channel, one on-call user per
# responsible team (mirrors the Slack subteam mapping used in setup_agent.py),
# and an incoming webhook for the Kibana Webhook connector.
#
# Usage: ./setup_mattermost.sh
#
# Requires: docker, curl, jq

set -euo pipefail

MM_URL="${MM_URL:-http://localhost:8065}"
CONTAINER_NAME="mattermost-preview"

ADMIN_USER="admin"
ADMIN_PASS="Instruqt123!"
ADMIN_EMAIL="admin@instruqt.local"
DEFAULT_PASS="Instruqt123!"

TEAM_NAME="shopeasy"
TEAM_DISPLAY="ShopEasy Ops"
CHANNEL_NAME="incidents"
CHANNEL_DISPLAY="Incidents"

# username -> display name, mirrors the Slack subteam mapping:
#   App errors        -> app-team
#   VM/backup/disk     -> vmware-team
#   Firewall/network   -> firewall-team
USERS=(app-team vmware-team firewall-team)

log() { echo "[setup-mattermost] $*"; }

start_mattermost() {
  if docker ps -a --format '{{.Names}}' | grep -qx "$CONTAINER_NAME"; then
    log "container '$CONTAINER_NAME' already exists, starting it"
    docker start "$CONTAINER_NAME" > /dev/null
  else
    log "starting new '$CONTAINER_NAME' container"
    docker run --name "$CONTAINER_NAME" -d \
      --publish 8065:8065 --publish 8443:8443 \
      mattermost/mattermost-preview > /dev/null
  fi
}

wait_for_mattermost() {
  log "waiting for mattermost at $MM_URL ..."
  until curl -sf "$MM_URL/api/v4/system/ping" > /dev/null 2>&1; do
    sleep 2
  done
  log "mattermost is up"
}

bootstrap_admin() {
  # First user ever created is auto-promoted to System Admin.
  # Harmless if the admin account already exists.
  curl -s -X POST "$MM_URL/api/v4/users" \
    -H "Content-Type: application/json" \
    -d "{\"email\":\"$ADMIN_EMAIL\",\"username\":\"$ADMIN_USER\",\"password\":\"$ADMIN_PASS\"}" \
    > /dev/null || true
}

login_admin() {
  curl -s -i -X POST "$MM_URL/api/v4/users/login" \
    -H "Content-Type: application/json" \
    -d "{\"login_id\":\"$ADMIN_USER\",\"password\":\"$ADMIN_PASS\"}" \
    | grep -i '^Token:' | awk '{print $2}' | tr -d '\r'
}

patch_config() {
  curl -s -X PUT "$MM_URL/api/v4/config/patch" \
    -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
    -d '{"EmailSettings": {"RequireEmailVerification": false}, "ServiceSettings": {"EnableIncomingWebhooks": true}}' \
    > /dev/null
}

get_team_id() {
  curl -s -H "Authorization: Bearer $TOKEN" "$MM_URL/api/v4/teams/name/$TEAM_NAME" | jq -r 'if has("status_code") then "" else .id end'
}

create_team() {
  curl -s -X POST "$MM_URL/api/v4/teams" \
    -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
    -d "{\"name\":\"$TEAM_NAME\",\"display_name\":\"$TEAM_DISPLAY\",\"type\":\"O\"}" \
    | jq -r '.id'
}

get_user_id() {
  curl -s -H "Authorization: Bearer $TOKEN" "$MM_URL/api/v4/users/username/$1" | jq -r 'if has("status_code") then "" else .id end'
}

create_user() {
  curl -s -X POST "$MM_URL/api/v4/users" \
    -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
    -d "{\"email\":\"${1}@instruqt.local\",\"username\":\"$1\",\"password\":\"$DEFAULT_PASS\"}" \
    | jq -r '.id'
}

verify_user_email() {
  # Admin-created users aren't auto-verified the way the bootstrap admin is.
  # Force-verify so login doesn't depend on RequireEmailVerification timing.
  curl -s -X POST "$MM_URL/api/v4/users/$1/email/verify/member" \
    -H "Authorization: Bearer $TOKEN" > /dev/null
}

add_user_to_team() {
  curl -s -X POST "$MM_URL/api/v4/teams/$1/members" \
    -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
    -d "{\"team_id\":\"$1\",\"user_id\":\"$2\"}" > /dev/null
}

get_channel_id() {
  curl -s -H "Authorization: Bearer $TOKEN" "$MM_URL/api/v4/teams/$1/channels/name/$CHANNEL_NAME" | jq -r 'if has("status_code") then "" else .id end'
}

create_channel() {
  curl -s -X POST "$MM_URL/api/v4/channels" \
    -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
    -d "{\"team_id\":\"$1\",\"name\":\"$CHANNEL_NAME\",\"display_name\":\"$CHANNEL_DISPLAY\",\"type\":\"O\"}" \
    | jq -r '.id'
}

add_user_to_channel() {
  curl -s -X POST "$MM_URL/api/v4/channels/$1/members" \
    -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
    -d "{\"user_id\":\"$2\"}" > /dev/null
}

get_webhook_id() {
  curl -s -H "Authorization: Bearer $TOKEN" "$MM_URL/api/v4/hooks/incoming?channel_id=$1" | jq -r '.[0].id // empty'
}

create_webhook() {
  curl -s -X POST "$MM_URL/api/v4/hooks/incoming" \
    -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
    -d "{\"channel_id\":\"$1\",\"display_name\":\"ShopEasy RCA\",\"description\":\"Posts RCA summaries from the Elastic Webhook connector\"}" \
    | jq -r '.id'
}

main() {
  start_mattermost
  wait_for_mattermost
  bootstrap_admin

  TOKEN=$(login_admin)
  if [[ -z "$TOKEN" ]]; then
    log "ERROR: failed to log in as admin"
    exit 1
  fi

  patch_config

  TEAM_ID=$(get_team_id)
  if [[ -z "$TEAM_ID" ]]; then
    log "creating team '$TEAM_DISPLAY'"
    TEAM_ID=$(create_team)
  fi
  add_user_to_team "$TEAM_ID" "$(get_user_id "$ADMIN_USER")"

  CHANNEL_ID=$(get_channel_id "$TEAM_ID")
  if [[ -z "$CHANNEL_ID" ]]; then
    log "creating channel '$CHANNEL_DISPLAY'"
    CHANNEL_ID=$(create_channel "$TEAM_ID")
  fi

  for username in "${USERS[@]}"; do
    USER_ID=$(get_user_id "$username")
    if [[ -z "$USER_ID" ]]; then
      log "creating user '$username'"
      USER_ID=$(create_user "$username")
    fi
    verify_user_email "$USER_ID"
    add_user_to_team "$TEAM_ID" "$USER_ID"
    add_user_to_channel "$CHANNEL_ID" "$USER_ID"
  done

  WEBHOOK_ID=$(get_webhook_id "$CHANNEL_ID")
  if [[ -z "$WEBHOOK_ID" ]]; then
    log "creating incoming webhook on #$CHANNEL_NAME"
    WEBHOOK_ID=$(create_webhook "$CHANNEL_ID")
  fi

  echo
  echo "=== ShopEasy Mattermost workshop setup complete ==="
  echo "URL:           $MM_URL"
  echo "Admin login:   $ADMIN_USER / $ADMIN_PASS"
  echo "Team:          $TEAM_DISPLAY  ($TEAM_NAME)"
  echo "Channel:       #$CHANNEL_NAME"
  echo "On-call users:"
  for username in "${USERS[@]}"; do
    echo "  - $username / $DEFAULT_PASS"
  done
  echo "Webhook URL:   $MM_URL/hooks/$WEBHOOK_ID"
  echo "==================================================="
}

main "$@"

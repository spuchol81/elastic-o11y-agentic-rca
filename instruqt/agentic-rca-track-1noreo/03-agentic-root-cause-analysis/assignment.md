---
slug: agentic-root-cause-analysis
id: 0prei9narmbh
type: challenge
title: Agentic Root Cause Analysis
tabs:
- id: kqpyfvrzxtxx
  title: elastic
  type: terminal
  hostname: kubernetes-vm
- id: ff7rvbtj60zd
  title: host-1
  type: terminal
  hostname: host-1
- id: cqmitgbmeqve
  title: mattermost
  type: service
  hostname: host-1
  port: 8065
  protocol: http
- id: cv372gjo4xt3
  title: elastic
  type: service
  hostname: kubernetes-vm
  path: /app/dashboards#
  port: 30001
  custom_request_headers:
  - key: Content-Security-Policy
    value: 'script-src ''self''; worker-src blob: ''self''; style-src ''unsafe-inline''
      ''self'''
  custom_response_headers:
  - key: Content-Security-Policy
    value: 'script-src ''self''; worker-src blob: ''self''; style-src ''unsafe-inline''
      ''self'''
difficulty: ""
enhanced_loading: null
---

## Ask the Agent That Beat You To It

Every incident from last night is already closed. Before you send Priya anything, you want to know exactly how that happened — and get a second opinion on your own read of the night while you're at it.

Head back to the **elastic** tab. Use the global search (top nav) and look for **Agent Builder** — that's where the on-call automation actually lives. Open it and start a new conversation with **rca_agent**.

Ask it something like:

> "What happened to the ShopEasy platform last night? Give me a full incident report."

Read what it comes back with — the time windows, the root causes, the responsible teams. This is the same agent that triaged every alert overnight, opened the cases, and closed them out before your shift even started. So there's your answer from the last challenge: nobody pulled an all-nighter watching dashboards — this agent did.

Compare its report line by line against your own read of the dashboard. Where does it confirm what you found? Where does it catch something you missed?

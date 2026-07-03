---
slug: take-the-shift-challenge-bbrndv
id: fkzysdypybrn
type: challenge
title: Taking the shift
tabs:
- id: csyu4cxyvnwa
  title: elastic
  type: terminal
  hostname: kubernetes-vm
- id: o3kvml4igups
  title: host-1
  type: terminal
  hostname: host-1
- id: xdt8g0khx6sx
  title: mattermost
  type: service
  hostname: host-1
  port: 8065
  protocol: http
- id: r9okvzyimqo2
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

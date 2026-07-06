---
slug: not-under-agent-builder-watch
id: q9asqwnjxz2l
type: challenge
title: Not under Agent builder watch!
tabs:
- id: iqi2kcqfy6ts
  title: elastic
  type: service
  hostname: kubernetes-vm
  path: /app/observability/alerts
  port: 30001
  custom_request_headers:
  - key: Content-Security-Policy
    value: 'script-src ''self''; worker-src blob: ''self''; style-src ''unsafe-inline''
      ''self'''
  custom_response_headers:
  - key: Content-Security-Policy
    value: 'script-src ''self''; worker-src blob: ''self''; style-src ''unsafe-inline''
      ''self'''
- id: pf7ckwvkuhvl
  title: mattermost
  type: service
  hostname: host-1
  port: 8065
  protocol: http
difficulty: ""
enhanced_loading: null
---

## The Alert That Never Woke You Up

Head to the **elastic** tab and open **Observability → Alerts**. Filter or scan for anything tagged `shopeasy`. You'll find four rules that fired overnight — one per incident — all already back to **recovered**. Open one and check its timeline: notice how close together the alert firing and its resolution are. Nobody was staring at a screen watching that happen in real time.

Now flip to the **mattermost** tab and open **#incidents**. Scroll back through last night. You'll find a card for each incident, posted automatically, with the time window, the root cause, the responsible team, and a link straight to the case — the same summary you just pulled out of the agent yourself, except this one landed hours before your alarm went off.

## What Actually Happened While You Slept

Put the pieces together: every one of those alert rules is wired to a workflow. The moment an anomaly crossed its threshold, that workflow woke up `rca_agent`, asked it to investigate that exact incident, opened a case, posted the summary to Mattermost, attached the alert to the case, and closed it out — all without a human in the loop.

> [!NOTE]
> That's the same skill and the same agent you talked to directly in the last challenge — it's just as capable running unattended off an alert as it is answering you in chat.

You didn't get paged, because by the time you would have been, there was nothing left to page you for. Priya gets her answer, on-call gets to sleep through the night, and the write-up basically already existed before you sat down with your coffee.

That's the shift.

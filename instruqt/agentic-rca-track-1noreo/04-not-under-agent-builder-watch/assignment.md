---
slug: not-under-agent-builder-watch
id: q9asqwnjxz2l
type: challenge
title: Not under Agent builder watch!
tabs:
- id: pf7ckwvkuhvl
  title: mattermost
  type: service
  hostname: host-1
  port: 8065
  protocol: http
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
difficulty: ""
enhanced_loading: null
---


 The Alert That Never Woke You Up
===
Inside  [Mattermost](tab-0) tab  log into the server with the following credentials
- User: ```vmware-team```
- Password:  ```Instruqt123!```
![Jul-06-2026_at_18.49.59-image.png](../assets/Jul-06-2026_at_18.49.59-image.png)
Click on the incidents channel
![Jul-06-2026_at_19.02.48-image.png](../assets/Jul-06-2026_at_19.02.48-image.png)
You will see  several message about last night issues
![Jul-06-2026_at_19.02.14-image.png](../assets/Jul-06-2026_at_19.02.14-image.png)
Each alerts have been analyzed so you have in these messages:
- The time slot of the issue
- the description of the root cause found during the investigation
- The team responsible to solve the issue, called out via its Mattermost handle for notification
- A link to the case that have been created into the case management system to log the alert

If you follow this link you will see that the reponsible team have solved the issue and closed this case
![Jul-06-2026_at_19.04.59-image.png](../assets/Jul-06-2026_at_19.04.59-image.png)

> [!NOTE]
> Elastic his watching continuously you observablity data and has analyzed every alert thrown and routed it to the corresponding on-call team on the dedicated Mattermost incident channel.
>
>  It basically did the L0/L1 support duty in complete autonomy during the night, waking up on-call experts with an analysis of the problem to solve.

## What Actually Happened While You Slept
 Pause a bit and understand what happened
===
Inside  [elastic](tab-A) You will see alert thrown  during the night.
Thes are machine learning

to be continued

> [!NOTE]
> That's the same skill and the same agent you talked to directly in the last challenge — it's just as capable running unattended off an alert as it is answering you in chat.

You didn't get paged, because by the time you would have been, there was nothing left to page you for. Priya gets her answer, on-call gets to sleep through the night, and the write-up basically already existed before you sat down with your coffee.

That's the shift.

---
slug: take-the-shift-challenge-bbrndv
id: fkzysdypybrn
type: challenge
title: Taking the shift
tabs:
- id: r9okvzyimqo2
  title: elastic
  type: service
  hostname: kubernetes-vm
  path: /app/dashboards#/list?_g=(filters:!(),refreshInterval:(pause:!t,value:1000),time:(from:now-24h,to:now))&s=Shopeasy
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
## 06:42 — You Sit Down With Your Coffee
===
You drop into your chair, coffee still too hot to drink, and wake your laptop up. Before you've even taken a sip, the screen tells you it wasn't a quiet night...
![Jul-06-2026_at_11.30.28-image.png](../assets/Jul-06-2026_at_11.30.28-image.png)
Then this lands in Mattermost from your VP:

> **Priya:** "Heard we had a rough night. I'm in the exec sync in under two hours and I need something concrete to bring — not 'we're looking into it.' What broke, when, and how bad. Have an answer for me before I walk into that room."

Let's use the ShopEasy Dashboard to find out the root cause of the overnight Issue

> [!IMPORTANT]
> If you don't know where to start, unfold the [Guided Investigations](section-guided-investigations)

Guided Investigations
===
On the [ **elastic**](tab-0) tab, pull up the **ShopEasy Mission Control** dashboard — it's your single pane of glass across the whole stack:

1. **Start with the synthetics up top.** *Monitor Status (Up/Down) Over Time* and *Uptime Percentage per Monitor* will tell you *when* things actually broke, not just that they did.
2. **Then chase it down through the three places trouble hides on this stack:**
   - **Firewall / Network** — *Firewall DENY Rate on TCP/443 Over Time* and *Palo alto DENY vs ALLOW* — is traffic even making it past the edge?
   - **Checkout / Application** — *Checkout Service Error Rate by Service Version Over Time* and *Error Rate (%) by Service Version — Regression Detection on New Deploys* — is the app falling over, and did something just get shipped?
   - **Database / Compute** — *Average CPU Ready Time by VM (ms)* and *PostgreSQL Slow Query Block Read Time Over Time* — is the database, or the box underneath it, choking?

> [!NOTE]
> You don't need to write anything down yet — just build the picture: what broke, roughly when, and which of these three areas is actually to blame.
When you are ready to provide your analysis, go to the next challenge.



---
slug: take-the-shift-challenge-bbrndv
id: fkzysdypybrn
type: challenge
title: Taking the shift
notes:
- type: text
  contents: '![Jul-07-2026_at_12.30.46-image.png](../assets/Jul-07-2026_at_12.30.46-image.png)'
- type: text
  contents: '![Jul-07-2026_at_12.31.07-image.png](../assets/Jul-07-2026_at_12.31.07-image.png)'
- type: text
  contents: '![Jul-07-2026_at_12.31.36-image.png](../assets/Jul-07-2026_at_12.31.36-image.png)'
- type: text
  contents: '![Jul-07-2026_at_12.32.11-image.png](../assets/Jul-07-2026_at_12.32.11-image.png)'
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

> **Priya:** "Heard we had a rough night. I'm in the exec sync in under two hours and I need something concrete to bring,  not a *we're looking into it*... I want to know what broke, when, and how bad. Have an answer for me before I walk into that room please"

Let's use the ShopEasy Dashboard to find out the root cause of the overnight Issue

> [!NOTE]
> Walk through the dashboard to catch  anomaly that could have affected the Shopeasy service. When you are ready, click next to answer a Quizz.

> [!IMPORTANT]
> If you don't know where to start, unfold the [Guided Investigations](section-guided-investigations)

Guided Investigations
===
On the [ **elastic**](tab-0) tab, pull up the **ShopEasy Mission Control** dashboard — it's your single pane of glass across the whole stack:
![Jul-07-2026_at_10.25.14-image.png](../assets/Jul-07-2026_at_10.25.14-image.png)

1. **Start with the synthetics up top.** *Monitor Status (Up/Down) Over Time* and *Uptime Percentage per Monitor* will tell you *when* things actually broke, not just that they did.
![Jul-07-2026_at_10.26.05-image.png](../assets/Jul-07-2026_at_10.26.05-image.png)
2. open the **Firewall / Network**  collapsible section
![Jul-07-2026_at_10.28.13-image.png](../assets/Jul-07-2026_at_10.28.13-image.png)
The *Palo alto DENY vs ALLOW*  visualization flags a lot more deny than usual during a 2hours period last night
![Jul-07-2026_at_10.30.30-image.png](../assets/Jul-07-2026_at_10.30.30-image.png)
3. open the **Software status**  collapsible section
![Jul-07-2026_at_10.32.14-image.png](../assets/Jul-07-2026_at_10.32.14-image.png)
We see error rate rising connected to a code version change
![Jul-07-2026_at_10.33.51-image.png](../assets/Jul-07-2026_at_10.33.51-image.png)
4. open the **Postgresql**  collapsible section
 ![Jul-07-2026_at_10.36.47-image.png](../assets/Jul-07-2026_at_10.36.47-image.png)
We see slow queries and locks at the end of the night
![Jul-07-2026_at_10.35.58-image.png](../assets/Jul-07-2026_at_10.35.58-image.png)
5. open the **VMware**  collapsible section
![Jul-07-2026_at_10.37.09-image.png](../assets/Jul-07-2026_at_10.37.09-image.png)
We see cpu ready time raising at the end of the night
![Jul-07-2026_at_10.38.15-image.png](../assets/Jul-07-2026_at_10.38.15-image.png)




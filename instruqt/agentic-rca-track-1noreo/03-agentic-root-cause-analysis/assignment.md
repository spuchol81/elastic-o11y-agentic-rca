---
slug: agentic-root-cause-analysis
id: 0prei9narmbh
type: challenge
title: Agentic Root Cause Analysis
tabs:
- id: cv372gjo4xt3
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


The reporting urgency
===


Now you know the root cause of the overnight disruption. But you already know a short answer and description of what happened will not be enough for Priya... Let's use agentic power of elastic to deliver this report lightning fast!

Use your dedicated agent to create the report
===
1. Click on **AI Agent** on the top right of Kibana tab
![Jul-06-2026_at_14.26.01-image.png](../assets/Jul-06-2026_at_14.26.01-image.png)
2. Click on the burger Menu and click the arrow to unfold available agents
![Jul-06-2026_at_14.27.48-image.png](../assets/Jul-06-2026_at_14.27.48-image.png)
3. Select rca_agent to start a conversation
![Jul-06-2026_at_14.28.37-image.png](../assets/Jul-06-2026_at_14.28.37-image.png)
4. Copy and paste the following inside the conversation and press enter
```
Morning meteo report
```
![Jul-06-2026_at_14.33.16-image.png](../assets/Jul-06-2026_at_14.33.16-image.png)
5. After nearly 30 seconds you should see the report of the agent. It should give you insights from the logs you may not even have noticed during the previous challenge
 ![Jul-06-2026_at_14.45.29-image.png](../assets/Jul-06-2026_at_14.45.29-image.png)
 > [!NOTE]
> This is AI generated data, so content may differ.

Pausing a bit and understand how it works
===
Have a look at the reasoning tab of the conversation
![Jul-06-2026_at_15.15.56-image.png](../assets/Jul-06-2026_at_15.15.56-image.png)
See how the agent goes through synthetics monitoring to state downtime of the App thanks to dedicated tools, and how it correlates these downtimes to machine learning anomaly to get the big picture of potential responsible components
![Jul-06-2026_at_15.19.43-image.png](../assets/Jul-06-2026_at_15.19.43-image.png)
It then confirms these feelings with lightweight logs statistics during the downtime to deepen its knowledge of the situation
![Jul-06-2026_at_15.21.44-image.png](../assets/Jul-06-2026_at_15.21.44-image.png)

This logic is the exact same an operator specialist would apply, following your internal knowledge base. This procedure has been captured thanks to agent builder in a specific skill to orchestrate tool usage and data understanding.
![Jul-06-2026_at_15.53.14-image.png](../assets/Jul-06-2026_at_15.53.14-image.png)
To check this out go to Agent details by clicking the three dots on top of the conversation
![Jul-06-2026_at_15.54.52-image.png](../assets/Jul-06-2026_at_15.54.52-image.png)
click skills menu and select meteo_morning to see the details of the procedure
![Jul-06-2026_at_15.55.42-image.png](../assets/Jul-06-2026_at_15.55.42-image.png)
> [!NOTE]
> During this challenge we learned how to use an agent interactively inside the platform to accelerate the diagnostics and root causes analysis of issues. We've seen how fast a well tooled LLM is able to get and correlate signals to analyse complex situation and provide holistic reporting about it
>
> But it's not the end of the story, do you remember this synthetics view?
>![Jul-06-2026_at_16.04.12-image.png](../assets/Jul-06-2026_at_16.04.12-image.png)
>These closed incident windows mean the problem has been solved during the night!
>
>The on-call people must have been notified to fix the situation!
>
>  Let's discover how in the next challenge!


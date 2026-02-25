# Pulse Demo (copy/paste)

This is a **2-minute demo** you can run locally to show what Pulse does.

## 0) Prereqs
- OpenClaw running
- Pulse running (daemon)

## 1) Show the live drive state
```bash
curl -s http://127.0.0.1:9720/state | jq
```
(If `jq` isn’t installed, omit `| jq`.)

## 2) Trigger a controlled, safe Pulse turn
This simulates a high-pressure event without touching any external systems.

```bash
curl -s -X POST http://127.0.0.1:9720/test-trigger \
  -H "Content-Type: application/json" \
  -d '{
    "reason": "demo_high_pressure_override",
    "drive": "goals",
    "pressure": 12.3,
    "idleSeconds": 1800
  }'
```

## 3) What you should see
- A new Pulse webhook event lands in the agent session
- Agent runs a CORTEX loop (SENSE → THINK → ACT → MEASURE → EVOLVE)
- Agent posts feedback:
```bash
curl -s -X POST http://127.0.0.1:9720/feedback \
  -H "Content-Type: application/json" \
  -d '{
    "drives_addressed": ["goals"],
    "outcome": "success",
    "summary": "<what the agent did>"
  }'
```
- Drive decays ~70%

## 4) Demo script for humans (what to say)
Pulse gives an OpenClaw agent **initiative**:
- It watches goals/emotions/unfinished tasks
- When pressure crosses threshold, it pings the agent
- The agent self-directs work, then closes the loop with feedback

It’s an autonomous nervous system.

## Notes
- If `test-trigger` doesn’t exist in this build, skip step 2 and just show the existing webhook flow + feedback decay (Pulse is still demonstrable).
- For ClawHub screenshots, capture:
  1) `/state` output before feedback
  2) the feedback call
  3) `/state` output after feedback

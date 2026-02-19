# Pulse Screenshot + GIF Guide (ClawHub)

Goal: capture **2 screenshots + 1 short GIF** that make Pulse’s value obvious.

## Screenshot 1 — Drive State (before feedback)
**What it shows:** drives have pressure; agent is being pulled to act.

Command:
```bash
curl -s http://127.0.0.1:9720/state | jq
```
Capture the JSON where one drive is clearly elevated (e.g., goals/emotions/unfinished).

## Screenshot 2 — Feedback Decay (after work)
**What it shows:** closed loop; drives decay after action.

Command:
```bash
curl -s -X POST http://127.0.0.1:9720/feedback \
  -H "Content-Type: application/json" \
  -d '{
    "drives_addressed": ["goals"],
    "outcome": "success",
    "summary": "Demo: completed a Pulse-triggered task"
  }'
```
Then run:
```bash
curl -s http://127.0.0.1:9720/state | jq
```
Capture the “before → after” change (pressure drops ~70%).

## GIF — File change → trigger → agent action
**What it shows:** Pulse gives initiative.

1) Split screen:
- Left: `tail -f` the Pulse log (or the OpenClaw session where triggers land)
- Right: edit a watched file (e.g., goals.json) to increase pressure

2) Make a simple change:
```bash
echo "# demo $(date)" >> memory/notes-demo.md
```

3) Record a 5–10 second clip showing:
- file change
- trigger reason
- agent does a loop
- feedback sent

## Notes
- Keep it boring + real. No hype. Show causality.
- If `jq` isn’t installed, omit it.
- If you don’t have a clean `state` endpoint view, capture the webhook payload + feedback response instead.

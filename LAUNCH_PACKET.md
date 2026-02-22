# Pulse Launch Packet (Josh)

**Goal:** Publish Pulse as a public GitHub repo + submit to ClawHub.

## Status
Everything is already prepared locally:
- Docs written (architecture/config/deployment) + examples
- README + LICENSE (MIT) + .gitignore + requirements.txt
- CHANGELOG.md
- CLAWHUB_LISTING.md drafted w/ URLs
- Repo is committed locally and ready to push

The only blocker is **approval to create the public repo under your GitHub**.

## What you need to do (5 minutes)
From `/Users/iris/.openclaw/workspace/pulse/`:

1) Ensure you’re logged into GitHub CLI:
```bash
gh auth status
```

2) Create the public repo:
```bash
gh repo create jcap93/pulse --public --source . --remote origin --push
```
(If the repo already exists, skip create and just push.)

3) Verify URLs:
- https://github.com/jcap93/pulse
- Docs + examples render correctly

## ClawHub submission (10 minutes)
Use `CLAWHUB_LISTING.md` as the submission copy.

## Product Hunt launch (30 minutes, 7-14 days after GitHub)
Use `PULSE_PRODUCTHUNT.md` — tagline, description, maker comment, gallery plan, X post, and response templates all ready. Just paste.
- Category: OpenClaw / Agents / Automation
- Pricing: Free core + Pro/Enterprise (as listed)
- Add 2 screenshots (can be minimal):
  - Pulse dashboard/log example
  - YAML config example

## Launch checklist
- [ ] Public GitHub repo exists + README looks good
- [ ] ClawHub submission posted
- [ ] Announce on X (when unblocked): short demo GIF + link
- [ ] Schedule Product Hunt 7–14 days later

## Notes
- If you want to keep your personal GitHub clean, we can publish under `astra-ventures/pulse` instead. (I can swap URLs in CLAWHUB_LISTING.md in 30 seconds.)
- **New:** `pulse/RELEASE_RUNBOOK.md` contains the minimal-step GitHub→ClawHub flow + verification checklist.

**My recommendation:** publish under your personal (`jcap93`) for speed, then transfer later if needed.

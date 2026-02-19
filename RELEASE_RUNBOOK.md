# Pulse Release Runbook (GitHub + ClawHub)

This is the shortest, lowest-friction path from “launch-ready locally” → “public on GitHub” → “submitted on ClawHub”.

## Preconditions
- You are in the Pulse repo root.
- `gh auth status` shows you’re logged in.

## 1) Sanity checks (fast)
```bash
python3 -m compileall src
python3 -m compileall pulse
```

## 2) Git status
```bash
git status
```

If you have uncommitted changes, either commit or stash.

## 3) Create GitHub repo + push
> Choose ONE. (A) is preferred.

### A) Create under your GitHub user
```bash
gh repo create jcap93/pulse --public --source . --remote origin --push
```

### B) Create under an org
```bash
gh repo create <ORG>/pulse --public --source . --remote origin --push
```

## 4) Verify
```bash
git remote -v
open https://github.com/jcap93/pulse
```

## 5) ClawHub submission
Use the info in:
- `pulse/CLAWHUB_LISTING.md`

Suggested submission assets:
- README (already written)
- 2 screenshots + 1 short GIF (see `pulse/SCREENSHOT_GUIDE.md`)

## 6) Post-submit checklist
- Add a GitHub Release tag (optional): `v1.0.0`
- Create an issue template / roadmap (optional)

## Notes
- This runbook intentionally doesn’t automate anything beyond `gh repo create ... --push`.
- If you want a fully automated publish script, we can add it, but the one-liner above is less fragile.

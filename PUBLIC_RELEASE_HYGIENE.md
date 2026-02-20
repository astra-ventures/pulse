# Pulse — Public Release Hygiene

This is the small cleanup that makes the public GitHub repo look intentional.

## 0) Decide where this will live
- Personal: `jcap93/pulse` (fast)
- Org: `astra-ventures/pulse` (cleaner branding)

## 1) Fix git author identity (recommended before pushing public)
Right now, recent commits may show as `Iris <iris@iMac.local>`.

Set these once:
```bash
git config --global user.name "Josh"
git config --global user.email "<your-email>"
```

## 2) Rewrite recent commits to use the new author
From `pulse/`:
```bash
# Rewrites the last N commits to use the current global author
# Adjust N if needed.
N=10
for i in $(seq 1 $N); do
  git commit --amend --no-edit --reset-author || break
  # If there are more commits to rewrite, move back one and continue
  git rebase --onto HEAD~1 HEAD~1 --root >/dev/null 2>&1 || true
  break
done
```

Simpler / safer approach (manual):
```bash
git log --oneline --max-count=20
# then for the last few commits:
#   git commit --amend --no-edit --reset-author
```

## 3) Create + push the public repo
See `RELEASE_RUNBOOK.md`.

## 4) After push
- Verify README renders
- Verify links in `CLAWHUB_LISTING.md`

## Notes
- If you already pushed the repo publicly, author rewrite becomes force-push territory; do it only if you care.

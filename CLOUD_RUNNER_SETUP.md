# Always-on cloud runner — setup checklist

Goal: the daily paper-trade engine fires every day on GitHub's servers, so it no
longer depends on your Mac being awake. The repo itself stores the ledger, so
state carries over between runs.

Why GitHub Actions: the engine only needs `requests` and hits public Polymarket
endpoints (no API keys), so there are no secrets to manage and the free tier is
more than enough for one run a day.

## One-time setup

1. **Make the project a git repo** (if it isn't already). From the project folder:
   - `git init`
   - Add a `.gitignore` containing at least:
     ```
     .pmc_cache/
     __pycache__/
     *.pyc
     ```
     (The `.pmc_cache/` folder is ~13k throwaway files — keep it out of git.)
   - `git add -A && git commit -m "initial commit"`

2. **Create a PRIVATE GitHub repo** and push to it:
   - `git remote add origin git@github.com:<you>/polymarket-paper.git`
   - `git branch -M main`
   - `git push -u origin main`
   Keep it private — the ledger is your research record.

3. **The workflow is already in place** at
   `.github/workflows/paper-trade-daily.yml`. Once pushed, GitHub picks it up
   automatically. Confirm under the repo's **Actions** tab.

4. **Allow the job to push commits back:** repo **Settings → Actions → General →
   Workflow permissions → "Read and write permissions"** → Save.
   (The workflow also declares `permissions: contents: write`.)

5. **Test it now:** Actions tab → "Polymarket paper-trade daily" → **Run
   workflow** (the `workflow_dispatch` button). Watch it run, then check that a
   `daily paper-trade run …` commit appears with the updated `paper_ledger.csv`.

6. **Pull results to your Mac** whenever you want the latest: `git pull`. You can
   keep the launchd job too, but it's now redundant — consider disabling it to
   avoid double-runs (they're idempotent, so it's safe either way):
   `launchctl unload ~/Library/LaunchAgents/com.peter.polymarket-paper.plist`

## Good to know / caveats

- **Timing:** GitHub cron is UTC. `0 8 * * *` = 09:00 Lisbon in summer, 08:00 in
  winter. The job is idempotent and once-daily, so the exact hour doesn't matter;
  add a second `0 9 * * *` line if you want 09:00 Lisbon year-round.
- **Cron isn't second-precise:** GitHub may delay scheduled runs by a few minutes
  (occasionally more) under load. Fine for a daily job.
- **60-day idle rule:** GitHub auto-disables scheduled workflows after 60 days of
  *no repo activity*. Our daily commit counts as activity, so it stays alive on
  its own. (If you ever pause it, re-enable in the Actions tab.)
- **iCloud vs git:** the folder currently lives in iCloud Drive. Git and iCloud
  can both sync the same folder, but it's cleaner to treat the GitHub repo as the
  source of truth for the code + ledger and let iCloud just be a local mirror.

## Recovering the vacation gaps (separate, one-time)

`reconstruct_gap.py` is now pointed at the outstanding gap days. Run it **on your
Mac** (it needs Polymarket API access, which CI and the sandbox both have too —
but your Mac already has `pmc` configured):

```
/opt/anaconda3/bin/python3 reconstruct_gap.py
```

It writes `paper_ledger_reconstructed.csv` (a separate, labelled file — your
live `paper_ledger.csv` is never touched) and prints a report comparing
live-only vs reconstructed vs combined. Remember it under-counts by design
(fast markets that already resolved can't be rewound), so treat it as a
lower-bound, lower-confidence supplement — not a full restoration.

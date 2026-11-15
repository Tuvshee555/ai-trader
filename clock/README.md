# The clock

A tiny Vercel project (`ai-trader-clock`, Pro plan) whose cron jobs start the GitHub
Actions workflows on time. GitHub's own `schedule:` triggers stay in the workflows as a
backup, but they fire late or not at all.

| Cron (UTC) | Starts |
| --- | --- |
| `7 * * * *` | `crypto.yml`, every hour |
| `45 14 * * 1-5` | `daily.yml`, 15 minutes after the New York open |
| `0 18 * * 1-5` | `daily.yml` again, a backup that does nothing if the session already ran |

Env vars on the Vercel project (sensitive, not readable back): `CRON_SECRET` (Vercel sends
it with every cron call; anything else gets 401) and `GH_DISPATCH_TOKEN` (a GitHub token
that can start workflows in this repo).

Deploy from a copy outside this git repo so Vercel does not connect the repo and build on
every bot commit (`git.deploymentEnabled` is off as well):

    cp -r clock /tmp/clock && cd /tmp/clock && vercel deploy --prod --yes

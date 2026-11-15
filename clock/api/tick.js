// The clock. Vercel Cron calls this on the schedule in ../vercel.json and it starts
// the matching GitHub Actions workflow. GitHub's own schedule is only a backup: on
// 2026-11-14 it fired 3 of about 20 hourly slots, each about 45 minutes late.
const REPO = "Tuvshee555/ai-trader";
const WORKFLOWS = {
  crypto: { file: "crypto.yml", inputs: { source: "clock" } },
  daily: { file: "daily.yml" },
};

module.exports = async (req, res) => {
  const secret = process.env.CRON_SECRET;
  if (!secret || req.headers.authorization !== `Bearer ${secret}`) {
    return res.status(401).json({ error: "unauthorized" });
  }
  const wf = WORKFLOWS[req.query.wf];
  if (!wf) return res.status(400).json({ error: "unknown workflow" });

  const r = await fetch(`https://api.github.com/repos/${REPO}/actions/workflows/${wf.file}/dispatches`, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${process.env.GH_DISPATCH_TOKEN}`,
      Accept: "application/vnd.github+json",
      "X-GitHub-Api-Version": "2022-11-28",
      "User-Agent": "ai-trader-clock",
    },
    body: JSON.stringify({ ref: "main", ...(wf.inputs ? { inputs: wf.inputs } : {}) }),
  });
  const ok = r.status === 204;
  if (!ok) console.error("dispatch failed", wf.file, r.status, (await r.text()).slice(0, 300));
  return res.status(ok ? 200 : 502).json({ workflow: wf.file, github: r.status });
};

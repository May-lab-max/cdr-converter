// Vercel Cron calls this endpoint (schedules in vercel.json). It asks GitHub
// to run the "Refresh rates" workflow now. GitHub's own cron schedule runs
// 4–11 hours late on this repo, so it stays only as a backup.
//
// Needs the env var GH_DISPATCH_TOKEN: a fine-grained GitHub token limited to
// this repository with "Actions: Read and write".

const REPO = 'May-lab-max/cdr-converter';
const WORKFLOW = 'refresh.yml';
const MIN_GAP_MIN = 30; // skip if a run started recently; also limits abuse of this public URL

module.exports = async (req, res) => {
  const token = process.env.GH_DISPATCH_TOKEN;
  if (!token) return res.status(500).json({ ok: false, error: 'GH_DISPATCH_TOKEN is not set' });

  const gh = (path, init = {}) => fetch(`https://api.github.com/repos/${REPO}${path}`, {
    ...init,
    headers: {
      Authorization: `Bearer ${token}`,
      Accept: 'application/vnd.github+json',
      'X-GitHub-Api-Version': '2022-11-28',
      'User-Agent': 'cdr-converter-cron',
      ...(init.headers || {}),
    },
  });

  try {
    const runs = await gh(`/actions/workflows/${WORKFLOW}/runs?per_page=1`);
    if (!runs.ok) return res.status(502).json({ ok: false, step: 'list runs', status: runs.status });
    const last = ((await runs.json()).workflow_runs || [])[0];
    if (last) {
      const age = (Date.now() - Date.parse(last.created_at)) / 60000;
      if (age < MIN_GAP_MIN)
        return res.status(200).json({ ok: true, skipped: `a run started ${Math.round(age)} min ago` });
    }

    const r = await gh(`/actions/workflows/${WORKFLOW}/dispatches`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ref: 'main' }),
    });
    if (r.status !== 204) return res.status(502).json({ ok: false, step: 'dispatch', status: r.status });
    return res.status(200).json({ ok: true, dispatched: true });
  } catch (e) {
    return res.status(502).json({ ok: false, error: String(e) });
  }
};

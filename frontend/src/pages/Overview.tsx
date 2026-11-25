import { Link } from "react-router-dom";
import { Page, Score, Stat, useApi } from "../ui";

export default function Overview() {
  const { data: s } = useApi("/api/insights/summary");
  const { data: top } = useApi("/api/jobs?freshness=24h&min_score=70&size=8");
  const { data: gaps } = useApi("/api/insights/skill-gaps");
  const { data: sigs } = useApi("/api/outreach/signals");
  return (
    <Page title="Overview">
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        <Stat label="Jobs discovered today" value={s?.jobs_discovered_today ?? "…"} />
        <Stat label="New in last 24h" value={s?.new_last_24h ?? "…"} />
        <Stat label="Highly relevant" value={s?.highly_relevant ?? "…"} hint="≥ alert threshold" />
        <Stat label="Pending approvals" value={s?.pending_approvals ?? "…"} />
        <Stat label="Applications submitted" value={s?.applications_submitted ?? "…"} />
        <Stat label="Recruiters contacted" value={s?.recruiters_contacted ?? "…"} />
        <Stat label="Interview calls" value={s?.interview_calls ?? "…"} />
        <Stat label="Offers" value={s?.offers ?? "…"} />
      </div>
      <div className="grid lg:grid-cols-3 gap-4">
        <div className="card lg:col-span-2">
          <h2 className="font-medium mb-2">🔥 Fresh high matches (24h) — apply today</h2>
          {top?.items?.length ? top.items.map((j: any) => (
            <Link key={j.id} to={`/jobs/${j.id}`} className="flex items-center gap-3 py-2 border-b last:border-0 hover:bg-slate-50">
              <Score v={j.match?.score} />
              <div className="min-w-0"><div className="truncate font-medium">{j.title}</div>
                <div className="text-xs text-slate-500 truncate">{j.company_name} · {j.city || j.country || j.location} · {j.source}</div></div>
            </Link>)) : <p className="text-sm text-slate-500">No fresh high matches right now.</p>}
        </div>
        <div className="space-y-4">
          <div className="card">
            <h2 className="font-medium mb-2">Skill-gap radar</h2>
            {gaps?.missing?.slice(0, 6).map((g: any) => (
              <div key={g.skill} className="flex justify-between text-sm py-0.5"><span>{g.skill}</span><span className="text-slate-500">{g.pct}% of jobs</span></div>))}
            <p className="text-xs text-slate-400 mt-2">From {gaps?.jobs_analysed ?? 0} relevant jobs, 14 days</p>
          </div>
          <div className="card">
            <h2 className="font-medium mb-2">Hiring signals (funding)</h2>
            {(sigs || []).slice(0, 5).map((x: any) => (
              <a key={x.url} href={x.url} target="_blank" rel="noreferrer" className="block text-sm py-1 hover:underline truncate">{x.title}</a>))}
            {!sigs?.length && <p className="text-sm text-slate-500">No signals yet.</p>}
          </div>
        </div>
      </div>
    </Page>
  );
}

import { useState } from "react";
import { Link } from "react-router-dom";
import { ago } from "../api";
import { Err, Page, Score, useApi } from "../ui";

const F0 = { q: "", country: "", city: "", remote_type: "", source: "", min_score: "", max_experience: "",
  min_salary_lpa: "", posted_within_hours: "", status: "", sort: "score" };

export default function Jobs({ matching = false }: { matching?: boolean }) {
  const [f, setF] = useState({ ...F0, min_score: matching ? "55" : "", sort: matching ? "score" : "discovered" });
  const [page, setPage] = useState(1);
  const qs = new URLSearchParams(Object.entries({ ...f, page: String(page), size: "30" }).filter(([, v]) => v) as [string, string][]);
  const { data, error, loading } = useApi(`/api/jobs?${qs}`);
  const set = (k: string) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) => { setPage(1); setF({ ...f, [k]: e.target.value }); };
  const sel = (k: string, opts: string[], label: string) => (
    <select className="input" value={(f as any)[k]} onChange={set(k)}><option value="">{label}</option>{opts.map((o) => <option key={o}>{o}</option>)}</select>);
  return (
    <Page title={matching ? "Job Matching" : "Live Job Feed"} actions={<span className="text-sm text-slate-500">{loading ? "Loading…" : `${data?.total ?? 0} jobs`}</span>}>
      <div className="card flex flex-wrap gap-2">
        <input className="input w-48" placeholder="Title or company" value={f.q} onChange={set("q")} />
        {sel("country", ["India", "Worldwide", "USA", "UK", "Germany", "Netherlands", "Singapore", "UAE", "Canada"], "Any country")}
        {sel("city", ["Bengaluru", "Hyderabad", "Pune", "Chennai", "Mumbai", "Delhi NCR"], "Any city")}
        {sel("remote_type", ["remote", "hybrid", "onsite"], "Any work mode")}
        {sel("source", ["greenhouse", "lever", "ashby", "remoteok", "weworkremotely", "adzuna", "jsearch", "email_alerts"], "Any source")}
        {sel("posted_within_hours", ["24", "72", "168"], "Any posting date")}
        <input className="input w-24" placeholder="Min score" value={f.min_score} onChange={set("min_score")} />
        <input className="input w-24" placeholder="Max exp (y)" value={f.max_experience} onChange={set("max_experience")} />
        <input className="input w-28" placeholder="Min LPA" value={f.min_salary_lpa} onChange={set("min_salary_lpa")} />
        {sel("status", ["new", "shortlisted", "dismissed"], "Any status")}
        <select className="input" value={f.sort} onChange={set("sort")}><option value="score">Best match</option><option value="posted">Newest posted</option><option value="discovered">Newest found</option></select>
      </div>
      <Err e={error} />
      <div className="card overflow-x-auto p-0">
        <table className="w-full">
          <thead><tr><th>Score</th><th>Role</th><th className="hidden md:table-cell">Why</th><th>Posted</th></tr></thead>
          <tbody>
            {data?.items?.map((j: any) => (
              <tr key={j.id} className="border-t hover:bg-slate-50">
                <td><Score v={j.match?.score} /></td>
                <td className="min-w-56"><Link to={`/jobs/${j.id}`} className="font-medium hover:underline">{j.title}</Link>
                  <div className="text-xs text-slate-500">{j.company_name} · {j.city || j.country || j.location} · {j.remote_type} · {j.source}</div></td>
                <td className="hidden md:table-cell text-xs text-slate-600 max-w-lg">{j.match?.explanation}</td>
                <td className="text-xs whitespace-nowrap">{ago(j.posted_at)}</td>
              </tr>))}
          </tbody>
        </table>
      </div>
      <div className="flex gap-2">
        <button className="btn" disabled={page === 1} onClick={() => setPage(page - 1)}>← Prev</button>
        <button className="btn" disabled={!data || page * 30 >= data.total} onClick={() => setPage(page + 1)}>Next →</button>
      </div>
    </Page>
  );
}

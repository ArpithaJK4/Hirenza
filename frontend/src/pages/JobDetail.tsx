import { useNavigate, useParams } from "react-router-dom";
import { api, fmtDate } from "../api";
import { Err, Flash, Page, Score, useAction, useApi } from "../ui";

export default function JobDetail() {
  const { id } = useParams();
  const nav = useNavigate();
  const { data: j, error, reload } = useApi(`/api/jobs/${id}`);
  const a = useAction();
  if (!j) return <Err e={error} />;
  const m = j.match;
  return (
    <Page title={j.title} actions={<>
      <a className="btn" href={j.url} target="_blank" rel="noreferrer">Open posting ↗</a>
      <button className="btn" disabled={a.busy} onClick={() => a.run(async () => { await api(`/api/jobs/${id}/status`, { method: "PATCH", json: { status: "dismissed" } }); reload(); }, "Dismissed")}>Dismiss</button>
      <button className="btn btn-primary" disabled={a.busy} onClick={() => a.run(async () => { const r = await api(`/api/jobs/${id}/prepare`, { method: "POST" }); nav(`/review/${r.id}`); })}>Prepare application →</button>
    </>}>
      <Flash msg={a.msg} err={a.err} />
      <div className="grid lg:grid-cols-3 gap-4">
        <div className="card lg:col-span-2 space-y-2">
          <div className="text-sm text-slate-600">{j.company_name} · {j.location} · {j.remote_type} · via {j.source} · posted {fmtDate(j.posted_at)}</div>
          <pre className="whitespace-pre-wrap text-sm font-sans">{j.description || "No description available — open the posting."}</pre>
        </div>
        <div className="space-y-4">
          <div className="card space-y-2">
            <div className="flex items-center gap-2"><Score v={m?.score} /><span className="text-sm text-slate-500">{m?.freshness_bucket}</span></div>
            <p className="text-sm">{m?.explanation}</p>
            {m && Object.entries(m.breakdown).map(([k, v]: any) => (
              <div key={k} className="flex justify-between text-xs"><span>{k}</span><span className="tabular-nums">{typeof v === "number" ? v.toFixed(2) : v}</span></div>))}
          </div>
          {m?.matched_skills?.length > 0 && <div className="card"><div className="text-xs text-slate-500 mb-1">Matched</div>{m.matched_skills.map((s: string) => <span key={s} className="chip mr-1 mb-1 bg-emerald-50">{s}</span>)}</div>}
          {m?.missing_skills?.length > 0 && <div className="card"><div className="text-xs text-slate-500 mb-1">Missing</div>{m.missing_skills.map((s: string) => <span key={s} className="chip mr-1 mb-1 bg-amber-50">{s}</span>)}</div>}
          {m?.suspicious_reasons?.length > 0 && <div className="card bg-red-50 text-sm text-red-800">⚠ {m.suspicious_reasons.join("; ")}</div>}
        </div>
      </div>
    </Page>
  );
}

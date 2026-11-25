import { useEffect, useState } from "react";
import { api, fmtDate } from "../api";
import { Flash, Page, useAction, useApi } from "../ui";

const LIST = ["skills", "target_roles", "priority_cities", "target_countries"] as const;
const NUM = ["years_experience", "salary_min_lpa", "salary_max_lpa", "match_threshold", "alert_threshold"] as const;

export default function Config() {
  const prof = useApi("/api/profile"); const aa = useApi("/api/auto-apply"); const [aaRun, setAaRun] = useState<any>(null); const w = useApi("/api/config/matching-weights"); const src = useApi<any[]>("/api/sources");
  const [p, setP] = useState<any>(null); const [weights, setWeights] = useState<any>(null);
  const a = useAction();
  useEffect(() => setP(prof.data && { ...prof.data, ...Object.fromEntries(LIST.map((k) => [k, prof.data[k].join(", ")])) }), [prof.data]);
  useEffect(() => setWeights(w.data), [w.data]);
  if (!p || !weights) return null;
  const save = () => a.run(async () => {
    await api("/api/profile", { method: "PUT", json: { headline: p.headline, ...Object.fromEntries(NUM.map((k) => [k, Number(p[k])])),
      ...Object.fromEntries(LIST.map((k) => [k, String(p[k]).split(",").map((s) => s.trim()).filter(Boolean)])) } }); prof.reload(); }, "Profile saved — new jobs are scored with it");
  return (
    <Page title="Agent Configuration">
      <Flash msg={a.msg} err={a.err} />
      <div className="grid lg:grid-cols-2 gap-4">
        <div className="card space-y-2"><div className="font-medium">Profile & thresholds</div>
          <label className="block text-sm">Headline<input className="input w-full" value={p.headline} onChange={(e) => setP({ ...p, headline: e.target.value })} /></label>
          {LIST.map((k) => <label key={k} className="block text-sm">{k.replace("_", " ")}<textarea className="input w-full h-16" value={p[k]} onChange={(e) => setP({ ...p, [k]: e.target.value })} /></label>)}
          <div className="grid grid-cols-2 gap-2">{NUM.map((k) => <label key={k} className="text-sm">{k.replaceAll("_", " ")}<input className="input w-full" type="number" value={p[k]} onChange={(e) => setP({ ...p, [k]: e.target.value })} /></label>)}</div>
          <button className="btn btn-primary" onClick={save}>Save profile</button>
        </div>
        <div className="space-y-4">
          <div className="card space-y-2"><div className="font-medium">Matching weights</div>
            {Object.entries(weights).map(([k, v]: any) => <label key={k} className="flex items-center gap-2 text-sm"><span className="w-24">{k}</span>
              <input type="range" min={0} max={0.5} step={0.01} value={v} onChange={(e) => setWeights({ ...weights, [k]: Number(e.target.value) })} className="flex-1" /><span className="w-10 tabular-nums">{v.toFixed(2)}</span></label>)}
            <button className="btn btn-primary" onClick={() => a.run(async () => { await api("/api/config/matching-weights", { method: "PUT", json: { value: weights } }); w.reload(); }, "Weights saved")}>Save weights</button>
          </div>
          <div className="card space-y-1"><div className="font-medium">Job sources</div>
            {src.data?.map((s) => <div key={s.key} className="flex flex-wrap items-center gap-2 text-sm border-t pt-1">
              <input type="checkbox" checked={s.enabled} onChange={() => a.run(async () => { await api(`/api/sources/${s.key}`, { method: "PATCH", json: { enabled: !s.enabled } }); src.reload(); })} />
              <span className="w-32">{s.key}</span><span className="chip">{s.last_status || "never run"}</span>
              <span className="text-xs text-slate-500">every {s.min_interval_minutes}m · {s.jobs_found_total} jobs · {fmtDate(s.last_run_at)}</span>
              {s.last_error && <div className="w-full text-xs text-red-600 truncate">{s.last_error}</div>}</div>)}
            <button className="btn mt-2" disabled={a.busy} onClick={() => a.run(async () => { await api("/api/agents/pipeline/run", { method: "POST" }); src.reload(); }, "Pipeline run complete")}>Run pipeline now</button>
          </div>
          <div className="card space-y-2"><div className="font-medium">Auto-apply (company career sites only)</div>
            {aa.data && <>
              <div className="text-sm">Status: <b>{!aa.data.enabled ? "off (set AUTO_APPLY_ENABLED=true in .env)" : aa.data.paused ? "paused" : aa.data.dry_run ? "on — TEST MODE (never submits)" : "on — LIVE"}</b></div>
              <div className="text-xs text-slate-500">Score ≥ {aa.data.min_score} · max {aa.data.daily_cap}/day (used {aa.data.used_today}) · {aa.data.countries.join(", ")} · Greenhouse/Lever/Ashby only · never Naukri/LinkedIn/Indeed · CAPTCHAs and unknown questions go to your Review Queue</div>
              {aa.data.missing_answers.length > 0 && <div className="text-xs text-amber-700">Fill in .env to auto-answer more forms: {aa.data.missing_answers.join(", ")}</div>}
              <div className="flex gap-2">
                <button className="btn" onClick={() => a.run(async () => { await api("/api/auto-apply/pause", { method: "PUT", json: { paused: !aa.data.paused } }); aa.reload(); })}>{aa.data.paused ? "Resume" : "Pause"}</button>
                <button className="btn" disabled={a.busy} onClick={() => a.run(async () => { setAaRun(await api("/api/auto-apply/test-run", { method: "POST" })); aa.reload(); }, "Test run finished (nothing submitted)")}>Run test now</button>
              </div>
              {aaRun?.items && <div className="text-xs space-y-1">{aaRun.items.map((i: any, k: number) => <div key={k}><span className="chip">{i.result}</span> {i.job} @ {i.company} {i.reason && <span className="text-slate-500">— {i.reason}</span>}</div>)}</div>}
              {aaRun?.skipped && <div className="text-xs text-slate-500">{aaRun.skipped}</div>}
            </>}
          </div>
          <div className="card text-xs text-slate-500">Hard rules: no LinkedIn/Naukri/Indeed automation · never apply to or contact your current employer · auto-submit only on public company forms under your auto-apply rule · never bypass CAPTCHAs · nothing guessed.</div>
        </div>
      </div>
    </Page>
  );
}

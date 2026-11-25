import { useState } from "react";
import { api, fmtDate } from "../api";
import { Flash, Page, useAction, useApi } from "../ui";

export default function Outreach() {
  const [tab, setTab] = useState<"messages" | "referrals" | "people" | "signals" | "pow">("messages");
  const msgs = useApi<any[]>("/api/outreach/messages");
  const refs = useApi<any[]>(tab === "referrals" ? "/api/outreach/referrals" : null, [tab]);
  const people = useApi<any[]>(tab === "people" ? "/api/outreach/people" : null, [tab]);
  const sigs = useApi<any[]>(tab === "signals" ? "/api/outreach/signals" : null, [tab]);
  const [p, setP] = useState({ name: "", company_name: "", title: "", email: "", linkedin_url: "", relationship_type: "recruiter" });
  const [image, setImage] = useState(""); const [scan, setScan] = useState<any>(null);
  const a = useAction();
  const draft = (recruiter_id: number, channel: string, job_id?: number) =>
    a.run(async () => { await api("/api/outreach/messages", { method: "POST", json: { recruiter_id, channel, job_id } }); msgs.reload(); setTab("messages"); }, "Draft created — review it below");
  const act = (id: number, action: string) => a.run(async () => { await api(`/api/outreach/messages/${id}/${action}`, { method: "POST" }); msgs.reload(); }, `Done: ${action}`);
  const importCsv = (e: React.ChangeEvent<HTMLInputElement>) => {
    const f = e.target.files?.[0]; if (!f) return; const fd = new FormData(); fd.append("file", f);
    a.run(async () => { const r = await api("/api/outreach/import-linkedin-connections", { method: "POST", body: fd }); a.run(async () => {}, `Imported ${r.imported} (excluded ${r.excluded_current_employer} at current employer)`); people.reload(); });
  };
  return (
    <Page title="Recruiter Outreach" actions={<label className="btn cursor-pointer">Import LinkedIn Connections.csv<input type="file" accept=".csv" hidden onChange={importCsv} /></label>}>
      <p className="text-xs text-slate-500">Everything is a draft until you approve it. LinkedIn messages are never sent automatically — copy and send them yourself. People at your current employer are always blocked.</p>
      <div className="flex gap-1 border-b">{(["messages", "referrals", "people", "signals", "pow"] as const).map((t) => (
        <button key={t} onClick={() => setTab(t)} className={`px-3 py-1.5 text-sm ${tab === t ? "border-b-2 border-indigo-600 font-medium" : "text-slate-500"}`}>{t === "pow" ? "proof-of-work" : t}</button>))}</div>
      <Flash msg={a.msg} err={a.err} />
      {tab === "messages" && <div className="space-y-3">{msgs.data?.map((m) => (
        <div key={m.id} className="card space-y-2">
          <div className="flex flex-wrap justify-between gap-2 text-sm"><span><b>{m.recruiter_name}</b> · {m.company} · <span className="chip">{m.channel}</span> <span className="chip">{m.status}</span></span><span className="text-xs text-slate-400">{fmtDate(m.created_at)} · {m.generated_by}</span></div>
          {m.subject && <div className="text-sm font-medium">{m.subject}</div>}
          <pre className="whitespace-pre-wrap text-sm font-sans bg-slate-50 rounded p-2">{m.body}</pre>
          <div className="flex flex-wrap gap-2">
            {m.status === "draft" && <><button className="btn btn-primary" onClick={() => act(m.id, "approve")}>Approve</button><button className="btn btn-danger" onClick={() => act(m.id, "reject")}>Reject</button></>}
            {m.status === "approved" && <>
              <button className="btn" onClick={() => navigator.clipboard.writeText(m.body)}>Copy</button>
              {m.channel !== "linkedin_note" && <button className="btn btn-primary" onClick={() => act(m.id, "send")}>Send email</button>}
              <button className="btn" onClick={() => act(m.id, "mark-sent")}>I sent it</button></>}
            {m.status === "sent" && <button className="btn" onClick={() => act(m.id, "mark-replied")}>They replied</button>}
          </div>
        </div>))}{!msgs.data?.length && <div className="card text-sm text-slate-500">No messages yet. Use Referrals or People to draft one.</div>}</div>}
      {tab === "referrals" && <div className="space-y-2">{refs.data?.map((r) => (
        <div key={r.recruiter_id} className="card flex flex-wrap justify-between gap-2">
          <div><div className="font-medium">{r.name} <span className="text-sm text-slate-500">· {r.title} @ {r.company}</span></div>
            {r.jobs.map((j: any) => <div key={j.job_id} className="text-xs text-slate-600">{Math.round(j.score)} · {j.title}</div>)}</div>
          <div className="flex gap-2"><button className="btn btn-primary" onClick={() => draft(r.recruiter_id, "referral_request", r.jobs[0].job_id)}>Draft referral ask</button>
            <button className="btn" onClick={() => draft(r.recruiter_id, "linkedin_note", r.jobs[0].job_id)}>LinkedIn note</button></div>
        </div>))}{!refs.data?.length && <div className="card text-sm text-slate-500">Import your LinkedIn Connections.csv (LinkedIn → Settings → Data privacy → Get a copy of your data → Connections) to find people at companies with your best matches.</div>}</div>}
      {tab === "people" && <div className="space-y-3">
        <div className="card flex flex-wrap gap-2">
          {(["name", "company_name", "title", "email", "linkedin_url"] as const).map((k) => <input key={k} className="input" placeholder={k.replace("_", " ")} value={p[k]} onChange={(e) => setP({ ...p, [k]: e.target.value })} />)}
          <select className="input" value={p.relationship_type} onChange={(e) => setP({ ...p, relationship_type: e.target.value })}><option>recruiter</option><option>hiring_manager</option><option>connection</option></select>
          <button className="btn btn-primary" onClick={() => a.run(async () => { await api("/api/outreach/people", { method: "POST", json: { ...p, email: p.email || null, linkedin_url: p.linkedin_url || null } }); people.reload(); }, "Saved")}>Add person</button>
        </div>
        <div className="card p-0 overflow-x-auto"><table className="w-full"><thead><tr><th>Name</th><th>Company</th><th>Type</th><th /></tr></thead><tbody>
          {people.data?.map((r) => <tr key={r.id} className="border-t"><td>{r.name}<div className="text-xs text-slate-500">{r.title}</div></td><td>{r.company_name}{r.is_excluded && <span className="chip bg-red-50 text-red-700 ml-1">blocked</span>}</td><td className="text-xs">{r.relationship_type}</td>
            <td className="whitespace-nowrap">{!r.is_excluded && <><button className="btn mr-1" onClick={() => draft(r.id, "email")}>Email</button><button className="btn" onClick={() => draft(r.id, "linkedin_note")}>Note</button></>}</td></tr>)}
        </tbody></table></div></div>}
      {tab === "signals" && <div className="card divide-y">{sigs.data?.map((s) => <a key={s.url} href={s.url} target="_blank" rel="noreferrer" className="block py-2 text-sm hover:underline">{s.title}<span className="text-xs text-slate-400"> · {s.source} · {fmtDate(s.published_at)}</span></a>)}{!sigs.data?.length && <p className="text-sm text-slate-500">No funding signals yet (refreshed hourly).</p>}</div>}
      {tab === "pow" && <div className="card space-y-2">
        <p className="text-sm text-slate-600">Scan a company's <b>public</b> container image with Trivy and get a helpful, non-alarmist note to include in outreach. Requires Trivy installed locally.</p>
        <div className="flex gap-2"><input className="input flex-1" placeholder="e.g. ghcr.io/org/app:latest" value={image} onChange={(e) => setImage(e.target.value)} />
          <button className="btn btn-primary" disabled={a.busy} onClick={() => a.run(async () => setScan(await api("/api/outreach/proof-of-work", { method: "POST", json: { image } })))}>Scan</button></div>
        {scan && <pre className="whitespace-pre-wrap text-xs bg-slate-50 p-2 rounded">{JSON.stringify(scan, null, 2)}</pre>}
      </div>}
    </Page>
  );
}

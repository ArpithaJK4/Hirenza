import { useState } from "react";
import { api, fmtDate } from "../api";
import { Flash, Page, Score, useAction, useApi } from "../ui";

const COLS = ["applied", "screening", "technical", "hr", "offer", "hired", "rejected"];

export default function Tracker() {
  const { data, reload } = useApi<any[]>("/api/applications?status=submitted");
  const ivs = useApi<any[]>("/api/interviews");
  const [sel, setSel] = useState<any>(null);
  const [kind, setKind] = useState("technical"); const [when, setWhen] = useState("");
  const a = useAction();
  const move = (id: number, stage: string) => a.run(async () => { await api(`/api/applications/${id}/stage`, { method: "PATCH", json: { stage } }); reload(); });
  const prep = ivs.data?.filter((i) => i.application_id === sel?.id) ?? [];
  return (
    <Page title="Application Tracker">
      <Flash msg={a.msg} err={a.err} />
      <div className="flex gap-3 overflow-x-auto pb-2">
        {COLS.map((c) => {
          const items = data?.filter((x) => x.stage === c) ?? [];
          return (
            <div key={c} className="w-60 shrink-0 bg-slate-100 rounded-xl p-2 space-y-2"
              onDragOver={(e) => e.preventDefault()} onDrop={(e) => move(Number(e.dataTransfer.getData("id")), c)}>
              <div className="text-xs font-semibold uppercase text-slate-500 px-1">{c} · {items.length}</div>
              {items.map((x) => (
                <div key={x.id} draggable onDragStart={(e) => e.dataTransfer.setData("id", String(x.id))} onClick={() => setSel(x)}
                  className={`bg-white rounded-lg p-2 shadow-sm cursor-pointer text-sm ${sel?.id === x.id ? "ring-2 ring-indigo-500" : ""}`}>
                  <div className="flex justify-between gap-1"><span className="font-medium truncate">{x.company}</span><Score v={x.match_score} /></div>
                  <div className="text-xs text-slate-500 truncate">{x.job_title}</div>
                  {x.follow_up_at && <div className="text-xs text-amber-700 mt-1">Follow up {fmtDate(x.follow_up_at)}</div>}
                </div>))}
            </div>);
        })}
      </div>
      {sel && <div className="card space-y-3">
        <div className="flex flex-wrap justify-between gap-2"><div className="font-semibold">{sel.job_title} · {sel.company}</div>
          <select className="input" value={sel.stage} onChange={(e) => { move(sel.id, e.target.value); setSel({ ...sel, stage: e.target.value }); }}>{COLS.concat("withdrawn").map((c) => <option key={c}>{c}</option>)}</select></div>
        <div className="flex flex-wrap gap-2 items-center">
          <span className="text-sm">Log interview:</span>
          <select className="input" value={kind} onChange={(e) => setKind(e.target.value)}>{["screening", "technical", "hr", "managerial"].map((k) => <option key={k}>{k}</option>)}</select>
          <input className="input" type="datetime-local" value={when} onChange={(e) => setWhen(e.target.value)} />
          <button className="btn btn-primary" onClick={() => a.run(async () => { await api(`/api/applications/${sel.id}/interviews`, { method: "POST", json: { kind, scheduled_at: when || null } }); ivs.reload(); reload(); }, "Logged — prep pack generated below")}>Add + prep pack</button>
          <button className="btn" onClick={() => { const ctc = prompt("Offer CTC (INR per year)?"); if (ctc) a.run(async () => { await api(`/api/applications/${sel.id}/offer`, { method: "PUT", json: { ctc: Number(ctc) } }); reload(); }, "Offer logged 🎉"); }}>Log offer</button>
        </div>
        {prep.map((i) => <details key={i.id} className="border rounded-lg p-2" open><summary className="text-sm font-medium cursor-pointer">{i.kind} · {fmtDate(i.scheduled_at)} · {i.status}/{i.outcome}</summary>
          <pre className="whitespace-pre-wrap text-sm font-sans mt-2">{i.prep_pack}</pre>
          <div className="flex gap-2 mt-2">{["passed", "failed"].map((o) => <button key={o} className="btn" onClick={() => a.run(async () => { await api(`/api/interviews/${i.id}`, { method: "PATCH", json: { status: "done", outcome: o } }); ivs.reload(); })}>{o}</button>)}</div>
        </details>)}
      </div>}
    </Page>
  );
}

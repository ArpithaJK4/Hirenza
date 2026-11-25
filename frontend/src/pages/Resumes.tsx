import { useState } from "react";
import { api, fmtDate } from "../api";
import { Flash, Page, useAction, useApi } from "../ui";

export default function Resumes() {
  const { data, reload } = useApi<any[]>("/api/resumes");
  const [name, setName] = useState("Main");
  const a = useAction();
  const upload = (e: React.ChangeEvent<HTMLInputElement>) => {
    const f = e.target.files?.[0]; if (!f) return;
    const fd = new FormData(); fd.append("file", f);
    a.run(async () => { await api(`/api/resumes?name=${encodeURIComponent(name)}`, { method: "POST", body: fd }); reload(); }, "Uploaded and parsed");
    e.target.value = "";
  };
  return (
    <Page title="Resume Management" actions={<>
      <input className="input w-32" value={name} onChange={(e) => setName(e.target.value)} placeholder="Name" />
      <label className="btn btn-primary cursor-pointer">Upload PDF/DOCX<input type="file" accept=".pdf,.docx,.txt,.md" hidden onChange={upload} /></label>
    </>}>
      <Flash msg={a.msg} err={a.err} />
      <p className="text-sm text-slate-500">Each application gets a tailored copy (content re-ordered for the job, never invented). Variants A (skills first) and B (experience first) are rotated and compared in Analytics.</p>
      <div className="grid md:grid-cols-2 gap-3">
        {data?.map((r) => (
          <div key={r.id} className="card space-y-2">
            <div className="flex justify-between"><div className="font-medium">{r.name} {r.is_default && <span className="chip bg-indigo-50">default</span>}</div>
              <div className="text-xs text-slate-500">{fmtDate(r.created_at)}</div></div>
            <div className="text-xs text-slate-500">{r.file_name} · sections: {Object.keys(r.sections).join(", ")}</div>
            <div>{r.skills.map((s: string) => <span key={s} className="chip mr-1 mb-1">{s}</span>)}</div>
            <div className="flex gap-2">
              {!r.is_default && <button className="btn" onClick={() => a.run(async () => { await api(`/api/resumes/${r.id}/default`, { method: "POST" }); reload(); })}>Make default</button>}
              <button className="btn btn-danger" onClick={() => confirm("Delete this resume?") && a.run(async () => { await api(`/api/resumes/${r.id}`, { method: "DELETE" }); reload(); })}>Delete</button>
            </div>
          </div>))}
        {!data?.length && <div className="card text-sm text-slate-500">Upload your resume to start preparing applications.</div>}
      </div>
    </Page>
  );
}

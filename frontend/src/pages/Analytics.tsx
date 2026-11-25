import { api } from "../api";
import { Bar, Flash, Page, Stat, useAction, useApi } from "../ui";

function Table({ title, rows }: { title: string; rows: any[] }) {
  return (
    <div className="card p-0 overflow-x-auto"><div className="px-3 pt-3 font-medium text-sm">{title}</div>
      <table className="w-full"><thead><tr><th>Key</th><th>Applied</th><th>Responded</th><th>Interviews</th><th>Offers</th><th>Response %</th></tr></thead>
        <tbody>{rows.map((r) => <tr key={r.key} className="border-t"><td>{r.key}</td><td>{r.applied}</td><td>{r.responded}</td><td>{r.interviews}</td><td>{r.offers}</td><td className="tabular-nums">{r.response_rate}%</td></tr>)}
          {!rows.length && <tr><td colSpan={6} className="text-slate-400">No submitted applications yet</td></tr>}</tbody></table></div>);
}

export default function Analytics() {
  const { data: d, reload } = useApi("/api/analytics?days=30");
  const usage = useApi("/api/llm/usage");
  const a = useAction();
  if (!d) return null;
  const t = d.totals; const maxDaily = Math.max(1, ...d.daily.map((x: any) => x.discovered || 0));
  const maxFunnel = Math.max(1, ...Object.values(d.funnel) as number[]);
  return (
    <Page title="Analytics" actions={<button className="btn" onClick={() => a.run(async () => { const r = await api("/api/analytics/optimise", { method: "POST" }); reload(); a.run(async () => {}, r.updated ? "Ranking boosts updated from outcomes" : r.reason); })}>Learn from outcomes</button>}>
      <Flash msg={a.msg} err={a.err} />
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        <Stat label="Submitted" value={t.submitted} /><Stat label="Response rate" value={`${t.response_rate}%`} />
        <Stat label="Interview rate" value={`${t.interview_rate}%`} /><Stat label="Offers" value={t.offers} />
        <Stat label="Outreach sent" value={t.outreach_sent} /><Stat label="Outreach reply rate" value={`${t.outreach_reply_rate}%`} />
        <Stat label="Pending approval" value={t.prepared} /><Stat label="Approved, not submitted" value={t.approved_pending_submit} />
      </div>
      <div className="grid lg:grid-cols-2 gap-4">
        <div className="card space-y-2"><div className="font-medium text-sm">Funnel</div>{Object.entries(d.funnel).map(([k, v]: any) => <Bar key={k} label={k} value={v} max={maxFunnel} />)}</div>
        <div className="card space-y-1"><div className="font-medium text-sm">Daily: jobs discovered / applied (30d)</div>
          {d.daily.slice(-14).map((x: any) => <Bar key={x.date} label={x.date} value={x.discovered || 0} max={maxDaily} right={`${x.discovered || 0} / ${x.applied || 0}`} />)}</div>
      </div>
      <Table title="By job source (which sources produce results)" rows={d.by_source} />
      <Table title="By role family" rows={d.by_role_family} />
      <Table title="Resume A/B test (A = skills first, B = experience first)" rows={d.by_resume_variant} />
      <Table title="Company-wise history" rows={d.by_company} />
      <div className="card text-sm"><div className="font-medium mb-1">LLM usage (30d) — provider: {usage.data?.provider}</div>
        {usage.data?.by_purpose?.map((u: any) => <div key={u.purpose}>{u.purpose}: {u.calls} calls · {u.input_tokens} in / {u.output_tokens} out tokens</div>)}
        {!usage.data?.by_purpose?.length && <div className="text-slate-500">No LLM calls (rule/template mode).</div>}</div>
    </Page>
  );
}

import { useState } from "react";
import { fmtDate } from "../api";
import { Page, useApi } from "../ui";

export default function Logs() {
  const [tab, setTab] = useState<"runs" | "audit" | "notifications">("runs");
  const path = { runs: "/api/agents/executions?limit=100", audit: "/api/logs/audit?limit=200", notifications: "/api/notifications?limit=100" }[tab];
  const { data, reload } = useApi<any[]>(path);
  const color = (s: string) => ({ success: "bg-emerald-100", sent: "bg-emerald-100", partial: "bg-amber-100", failed: "bg-red-100", running: "bg-sky-100" } as any)[s] || "";
  return (
    <Page title="System Logs" actions={<button className="btn" onClick={reload}>Refresh</button>}>
      <div className="flex gap-1 border-b">{(["runs", "audit", "notifications"] as const).map((t) => <button key={t} onClick={() => setTab(t)} className={`px-3 py-1.5 text-sm ${tab === t ? "border-b-2 border-indigo-600 font-medium" : "text-slate-500"}`}>{t}</button>)}</div>
      <div className="card p-0 overflow-x-auto"><table className="w-full"><tbody>
        {data?.map((r) => tab === "runs" ? (
          <tr key={r.id} className="border-t"><td className="whitespace-nowrap text-xs">{fmtDate(r.started_at)}</td><td>{r.agent}</td><td><span className={`chip ${color(r.status)}`}>{r.status}</span></td><td className="text-xs">{r.trigger}</td>
            <td className="text-xs font-mono max-w-xl truncate" title={JSON.stringify(r.stats)}>{r.error || JSON.stringify(r.stats).slice(0, 160)}</td></tr>
        ) : tab === "audit" ? (
          <tr key={r.id} className="border-t"><td className="whitespace-nowrap text-xs">{fmtDate(r.created_at)}</td><td>{r.action}</td><td className="text-xs">{r.entity} {r.entity_id}</td><td className="text-xs font-mono truncate max-w-xl">{JSON.stringify(r.details)}</td></tr>
        ) : (
          <tr key={r.id} className="border-t"><td className="whitespace-nowrap text-xs">{fmtDate(r.created_at)}</td><td>{r.channel}</td><td><span className={`chip ${color(r.status)}`}>{r.status}</span></td><td className="text-sm">{r.title}</td><td className="text-xs text-red-600">{r.error}</td></tr>
        ))}
      </tbody></table></div>
    </Page>
  );
}

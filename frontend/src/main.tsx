import { StrictMode, useState } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter, NavLink, Route, Routes } from "react-router-dom";
import "./index.css";
import { api, token } from "./api";
import { Err } from "./ui";
import Overview from "./pages/Overview";
import Jobs from "./pages/Jobs";
import JobDetail from "./pages/JobDetail";
import Resumes from "./pages/Resumes";
import Review from "./pages/Review";
import Outreach from "./pages/Outreach";
import Tracker from "./pages/Tracker";
import Analytics from "./pages/Analytics";
import Config from "./pages/Config";
import Logs from "./pages/Logs";

const NAV = [
  ["/", "Overview"], ["/jobs", "Live Job Feed"], ["/matching", "Job Matching"], ["/resumes", "Resumes"],
  ["/review", "Review Queue"], ["/outreach", "Outreach"], ["/tracker", "Tracker"], ["/analytics", "Analytics"],
  ["/config", "Agent Config"], ["/logs", "System Logs"],
];

function Login() {
  const [email, setEmail] = useState(""); const [pw, setPw] = useState(""); const [err, setErr] = useState<string | null>(null);
  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      const r = await api<{ access_token: string }>("/api/auth/login", { method: "POST", body: new URLSearchParams({ username: email, password: pw }) });
      token.set(r.access_token); window.location.reload();
    } catch (e: any) { setErr(e.message); }
  };
  return (
    <form onSubmit={submit} className="max-w-sm mx-auto mt-24 card space-y-3">
      <h1 className="text-lg font-semibold">Hirenza</h1>
      <input className="input w-full" placeholder="Email" value={email} onChange={(e) => setEmail(e.target.value)} />
      <input className="input w-full" type="password" placeholder="Password" value={pw} onChange={(e) => setPw(e.target.value)} />
      <Err e={err} />
      <button className="btn btn-primary w-full justify-center">Sign in</button>
    </form>
  );
}

function App() {
  const [open, setOpen] = useState(false);
  if (!token.get()) return <Login />;
  return (
    <BrowserRouter>
      <div className="md:flex min-h-screen">
        <aside className={`${open ? "block" : "hidden"} md:block md:w-52 shrink-0 bg-slate-900 text-slate-200 p-3 space-y-1`}>
          <div className="font-semibold text-white px-2 py-2">Hirenza</div>
          {NAV.map(([to, label]) => (
            <NavLink key={to} to={to} end={to === "/"} onClick={() => setOpen(false)}
              className={({ isActive }) => `block rounded-md px-2 py-1.5 text-sm ${isActive ? "bg-slate-700 text-white" : "hover:bg-slate-800"}`}>
              {label}
            </NavLink>
          ))}
          <button className="text-xs text-slate-400 px-2 pt-4" onClick={() => { token.set(null); location.reload(); }}>Sign out</button>
        </aside>
        <main className="flex-1 min-w-0 p-4 md:p-6">
          <button className="btn md:hidden mb-3" onClick={() => setOpen(!open)}>☰ Menu</button>
          <Routes>
            <Route path="/" element={<Overview />} />
            <Route path="/jobs" element={<Jobs />} />
            <Route path="/matching" element={<Jobs matching />} />
            <Route path="/jobs/:id" element={<JobDetail />} />
            <Route path="/resumes" element={<Resumes />} />
            <Route path="/review" element={<Review />} />
            <Route path="/review/:id" element={<Review />} />
            <Route path="/outreach" element={<Outreach />} />
            <Route path="/tracker" element={<Tracker />} />
            <Route path="/analytics" element={<Analytics />} />
            <Route path="/config" element={<Config />} />
            <Route path="/logs" element={<Logs />} />
          </Routes>
        </main>
      </div>
    </BrowserRouter>
  );
}

createRoot(document.getElementById("root")!).render(<StrictMode><App /></StrictMode>);

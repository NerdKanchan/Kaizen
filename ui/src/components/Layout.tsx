import { CaretLeft, CaretRight, ChartBar, ClipboardText, Files, Folder, Folders, GitDiff, Lightbulb, ListChecks, List, X, ArrowRight, SignOut, SquaresFour, TextAa, UserCircle } from "@phosphor-icons/react";
import { useEffect, useRef, useState, type ReactNode } from "react";
import { Link, NavLink, Outlet, matchPath, useLocation, useNavigate } from "react-router-dom";
import { api } from "../api";
import { displayName, enc } from "../lib/format";
import { useReviewer } from "../lib/reviewer";
import { useAsync } from "../lib/useAsync";
import { backendProblem } from "../lib/backend";
import { useDataRefresh } from "../lib/dataRefresh";
import { ErrorBox } from "./Feedback";
import { ScrollMemory } from "./ScrollMemory";
import { SignIn } from "./SignIn";
import { ThemeToggle } from "./ThemeToggle";
import { SidebarSection } from "./SidebarSection";
import { Button } from "./ui";

const LAST_RUN_KEY = "kaizen.lastRun";
const RAIL_KEY = "kaizen.railCollapsed";

// The browser's history menu is how people jump back several steps at once, and it lists document
// titles. One title for eleven pages makes that menu useless, so every route names itself.
const SECTIONS: [RegExp, string][] = [
  [/^\/runs\/[^/]+\/review$/, "Review queue"],
  [/^\/runs\/[^/]+\/rows\//, "Evidence"],
  [/^\/runs\/[^/]+\/documents\//, "Document"],
  [/^\/runs\/[^/]+\/documents$/, "Documents"],
  [/^\/runs\/[^/]+\/mining$/, "Suggested matches"],
  [/^\/runs\/[^/]+\/learning$/, "Closed testing"],
  [/^\/runs\/[^/]+\/business$/, "Business case"],
  [/^\/runs\/[^/]+\/diff$/, "Compare runs"],
  [/^\/runs\/[^/]+$/, "Overview"],
  [/^\/terminology$/, "Terminology"],
  [/^\/action-items$/, "Action items"],
  [/^\/admin$/, "Manage users"],
  [/^\/profile$/, "Profile"],
  [/^\/$/, "All runs"],
];

function initials(name: string): string {
  return name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((p) => p[0]?.toUpperCase() ?? "")
    .join("");
}

export function Layout() {
  const loc = useLocation();
  const nav = useNavigate();
  const match = matchPath("/runs/:runId/*", loc.pathname) ?? matchPath("/runs/:runId", loc.pathname);
  const routeRun = match?.params.runId ?? null;
  const [lastRun, setLastRun] = useState<string | null>(() => {
    try {
      return localStorage.getItem(LAST_RUN_KEY);
    } catch {
      return null;
    }
  });
  useEffect(() => {
    if (!routeRun) return;
    setLastRun(routeRun);
    try {
      localStorage.setItem(LAST_RUN_KEY, routeRun);
    } catch {
      /* ignore */
    }
  }, [routeRun]);
  const runId = routeRun ?? lastRun;
  const [mobileOpen, setMobileOpen] = useState(false);
  const menuButton = useRef<HTMLButtonElement>(null);
  const sidebar = useRef<HTMLElement>(null);
  useEffect(() => {
    if (!mobileOpen) return;
    const first = [...(sidebar.current?.querySelectorAll<HTMLElement>('button, a[href]') ?? [])].find(element => element.getClientRects().length > 0);
    first?.focus();
    const close = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        setMobileOpen(false);
        menuButton.current?.focus();
      }
    };
    document.addEventListener("keydown", close);
    return () => document.removeEventListener("keydown", close);
  }, [mobileOpen]);
  useEffect(() => { setMobileOpen(false); }, [loc.pathname]);
  useEffect(() => {
    const section = SECTIONS.find(([re]) => re.test(loc.pathname))?.[1];
    document.title = [section, routeRun, "Kaizen Cross-Check"].filter(Boolean).join(" · ");
  }, [loc.pathname, routeRun]);
  const { session, loading, signOut } = useReviewer();
  const health = useAsync(api.health, []);
  useEffect(() => {
    const refresh = () => health.reload();
    window.addEventListener("focus", refresh);
    const timer = window.setInterval(refresh, 30000);
    return () => { window.removeEventListener("focus", refresh); window.clearInterval(timer); };
  }, [health.reload]);
  const runs = useAsync(() => session ? api.listRuns() : Promise.resolve([]), [loc.pathname, session?.reviewer]);
  useDataRefresh(runs.reload);
  // The rail collapses two ways: by hand (remembered per browser) and, below lg, because there is
  // no room. Collapsing by hand only removes the wide state; the narrow one is the same either way.
  const [railCollapsed, setRailCollapsed] = useState<boolean>(() => {
    try {
      return localStorage.getItem(RAIL_KEY) === "1";
    } catch {
      return false;
    }
  });
  const toggleRail = () =>
    setRailCollapsed((c) => {
      const next = !c;
      try {
        localStorage.setItem(RAIL_KEY, next ? "1" : "0");
      } catch {
        /* private mode: the rail still moves for this page */
      }
      return next;
    });

  if (health.error) return <div className="p-6"><ErrorBox error={health.error} onRetry={health.reload} /></div>;
  const problem = health.data && backendProblem(health.data);
  if (problem) return <div className="p-6"><ErrorBox error={problem} onRetry={() => window.location.reload()} /></div>;
  if (loading || !health.data) return <div className="p-6 text-sm text-ink-3">Loading…</div>;
  if (!session) return <SignIn />;

  const currentRun = runs.data?.find(x => x.run_id === runId);
  const section = SECTIONS.find(([re]) => re.test(loc.pathname))?.[1] ?? "Workspace";
  const r = (suffix: string) => runId ? `/runs/${enc(runId)}${suffix}` : null;
  const disclosureKey = (key: string) => `kaizen.navigation.${session.reviewer}.${key}`;
  const accessibleRuns = runs.data ?? (routeRun ? [{ run_id: routeRun, name: routeRun }] : []);
  const item = (to: string | null, label: string, icon: ReactNode, end = false) => to ? (
    <NavLink to={to} end={end} title={label} className={({ isActive }) => `nav-item ${isActive ? "is-active" : ""}`}>
      {icon}<span className="nav-label">{label}</span>
    </NavLink>
  ) : null;

  return (
    <div className={`app-shell ${railCollapsed ? "nav-collapsed" : ""}`}>
      <ScrollMemory />
      <a href="#main" onClick={e => { e.preventDefault(); document.getElementById("main")?.focus(); }} className="sr-only focus:not-sr-only focus:fixed focus:top-2 focus:left-2 focus:z-[70] btn btn-primary">Skip to content</a>
      <aside ref={sidebar} className={`app-sidebar ${mobileOpen ? "mobile-open" : ""}`} id="app-navigation">
        <div className="sidebar-brand">
          <NavLink to="/" className="brand-link" title="Kaizen Cross-Check">
            <span className="brand-mark"><img src="/bd-logo.png" alt="BD" /></span>
            <span className="nav-label"><strong>Kaizen</strong><small>Cross-Check workspace</small></span>
          </NavLink>
          <button type="button" onClick={toggleRail} className="sidebar-collapse" aria-label={railCollapsed ? "Expand sidebar" : "Collapse sidebar"}>{railCollapsed ? <CaretRight size={16} /> : <CaretLeft size={16} />}</button>
        </div>
        <nav aria-label="Main navigation" className="sidebar-links">
          <div className="nav-tree">
          <SidebarSection label="Workspace" storageKey={disclosureKey("workspace")} activePath={["/", "/action-items", "/terminology"].includes(loc.pathname) ? loc.pathname : undefined}>
          {item("/", "All runs", <Folders size={20} />, true)}
          {item("/action-items", "Action items", <ClipboardText size={20} />)}
          {item("/terminology", "Terminology", <TextAa size={20} />)}
          </SidebarSection>
          <SidebarSection label="Runs" storageKey={disclosureKey("runs")} activePath={routeRun ? loc.pathname : undefined}>
            {runs.error && <div className="sidebar-hint">Couldn’t load runs. <button onClick={runs.reload}>Retry</button></div>}
            {runs.loading && !accessibleRuns.length && <p className="sidebar-hint">Loading runs…</p>}
            {!runs.loading && !runs.error && runs.data?.length === 0 && <p className="sidebar-hint">Your runs will appear here.</p>}
            {accessibleRuns.map(run => {
              const base = `/runs/${enc(run.run_id)}`;
              const active = routeRun === run.run_id ? loc.pathname : undefined;
              return <SidebarSection key={run.run_id} label={run.name || run.run_id} icon={<Folder size={18} />} className={`sidebar-run-group ${active ? "contains-active" : ""}`} storageKey={disclosureKey(`run.${run.run_id}`)} activePath={active} defaultOpen={false}>
                <div className="sidebar-run-pages">
                  {item(base, "Overview", <SquaresFour size={18} />, true)}
                  {item(`${base}/review`, "Review queue", <ListChecks size={18} />)}
                  {item(`${base}/documents`, "Documents", <Files size={18} />)}
                  {item(`${base}/learning`, "Closed testing", <ChartBar size={18} />)}
                  <SidebarSection label="Analysis" className="sidebar-analysis" storageKey={disclosureKey(`analysis.${run.run_id}`)} activePath={active && /\/(mining|diff|business)$/.test(active) ? active : undefined} defaultOpen={false}>
                    {item(`${base}/mining`, "Suggested matches", <Lightbulb size={18} />)}
                    {item(`${base}/diff`, "Compare runs", <GitDiff size={18} />)}
                    {item(`${base}/business`, "Business case", <ChartBar size={18} />)}
                  </SidebarSection>
                </div>
              </SidebarSection>;
            })}
          </SidebarSection>
          {session.is_admin && <SidebarSection label="Administration" storageKey={disclosureKey("admin")} activePath={loc.pathname === "/admin" ? loc.pathname : undefined}>{item("/admin", "Manage users", <ClipboardText size={20} />)}</SidebarSection>}
          </div>
          <div className="nav-compact">
            {item("/", "All runs", <Folders size={20} />, true)}
            {item("/action-items", "Action items", <ClipboardText size={20} />)}
            {item("/terminology", "Terminology", <TextAa size={20} />)}
            {runId && <div className="compact-run-links">
            {item(r(""), "Overview", <SquaresFour size={20} />, true)}
            {item(r("/review"), "Review queue", <ListChecks size={20} />)}
            {item(r("/documents"), "Documents", <Files size={20} />)}
            {item(r("/learning"), "Closed testing", <ChartBar size={20} />)}
            {item(r("/mining"), "Suggested matches", <Lightbulb size={20} />)}
            {item(r("/diff"), "Compare runs", <GitDiff size={20} />)}
            {item(r("/business"), "Business case", <ChartBar size={20} />)}
            </div>}
            {session.is_admin && item("/admin", "Manage users", <ClipboardText size={20} />)}
          </div>
        </nav>
        <div className="sidebar-footer">{item("/profile", "Profile", <UserCircle size={20} />)}</div>
      </aside>
      <div className="app-body">
        <header className="app-topbar">
          <button type="button" ref={menuButton} className="btn btn-ghost btn-icon mobile-menu" aria-label={mobileOpen ? "Close navigation" : "Open navigation"} aria-expanded={mobileOpen} aria-controls="app-navigation" onClick={() => setMobileOpen(!mobileOpen)} >{mobileOpen ? <X size={20} /> : <List size={20} />}</button>
          <nav aria-label="Breadcrumb" className="breadcrumbs"><Link to="/">Workspace</Link><CaretRight size={14} /><span aria-current="page">{section}</span></nav>
          <div className="topbar-account">
            <ThemeToggle />
            <Link to="/profile" className="account-avatar" aria-label="Open your profile" title="Your profile">{initials(displayName(session.reviewer))}</Link>
            <span className="account-name">{displayName(session.reviewer)}<small>{session.is_admin ? "Administrator" : "Reviewer"}</small></span>
            {session.blind && <span className="chip bg-brand-100 text-brand-700 border-brand-200">Blind</span>}
            <Button variant="ghost" size="sm" iconOnly aria-label="Sign out" onClick={() => void signOut()} icon={<SignOut size={18} />} />
          </div>
        </header>
        {routeRun && <div className="run-context">
          <label htmlFor="current-run">Run</label>
          <select id="current-run" className="input input-sm" value={runId ?? ""} onChange={e => e.target.value && nav(`/runs/${enc(e.target.value)}`)}>
            {(runs.data ?? []).map(x => <option key={x.run_id} value={x.run_id}>{x.name || x.run_id}</option>)}
            {!currentRun && <option value={runId ?? ""}>{runId}</option>}
          </select>
          <Link to="/">All runs <ArrowRight size={14} /></Link>
        </div>}
        <main id="main" tabIndex={-1} className="app-main"><Outlet /></main>
      </div>
    </div>
  );
}

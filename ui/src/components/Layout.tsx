// App shell: a BD-navy navigation rail, a top bar with the run switcher, the theme toggle and the
// reviewer's identity, and the page. Routes and behaviour are unchanged from the first build.
import { CaretLeft, CaretRight, ChartBar, ClipboardText, Files, Folders, GitDiff, Lightbulb, ListChecks, List, X, ArrowRight, SignOut, SquaresFour, TextAa } from "@phosphor-icons/react";
import { useEffect, useRef, useState, type ReactNode } from "react";
import { Link, NavLink, Outlet, matchPath, useLocation, useNavigate } from "react-router-dom";
import { api } from "../api";
import { displayName, enc } from "../lib/format";
import { useReviewer } from "../lib/reviewer";
import { useAsync } from "../lib/useAsync";
import { ScrollMemory } from "./ScrollMemory";
import { SignIn } from "./SignIn";
import { ThemeToggle } from "./ThemeToggle";
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
  [/^\/runs\/[^/]+\/business$/, "Business case"],
  [/^\/runs\/[^/]+\/diff$/, "Compare runs"],
  [/^\/runs\/[^/]+$/, "Overview"],
  [/^\/terminology$/, "Terminology"],
  [/^\/action-items$/, "Action items"],
  [/^\/admin$/, "Manage users"],
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
    sidebar.current?.querySelector<HTMLAnchorElement>('a.nav-item')?.focus();
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
  const runs = useAsync(() => session ? api.listRuns() : Promise.resolve([]), [routeRun, session?.reviewer]);
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

  if (loading) return <div className="p-6 text-sm text-ink-3">Loading…</div>;
  if (!session) return <SignIn />;

  const currentRun = runs.data?.find(x => x.run_id === runId);
  const section = SECTIONS.find(([re]) => re.test(loc.pathname))?.[1] ?? "Workspace";
  const r = (suffix: string) => runId ? `/runs/${enc(runId)}${suffix}` : null;
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
          <div className="nav-section-label nav-label">Workspace</div>
          {item("/", "All runs", <Folders size={20} />, true)}
          {item("/action-items", "Action items", <ClipboardText size={20} />)}
          {item("/terminology", "Terminology", <TextAa size={20} />)}
          {runId ? <>
            <div className="nav-section-label nav-label">{routeRun ? "Current run" : "Recent run"}</div>
            <Link className="sidebar-run nav-label" to={r("")!} title={currentRun?.name || runId}>{currentRun?.name || runId}</Link>
            {item(r(""), "Overview", <SquaresFour size={20} />, true)}
            {item(r("/review"), "Review queue", <ListChecks size={20} />)}
            {item(r("/documents"), "Documents", <Files size={20} />)}
            <div className="nav-section-label nav-label">Analysis</div>
            {item(r("/mining"), "Suggested matches", <Lightbulb size={20} />)}
            {item(r("/diff"), "Compare runs", <GitDiff size={20} />)}
            {item(r("/business"), "Business case", <ChartBar size={20} />)}
          </> : <p className="sidebar-hint nav-label">Open a run to review results and explore its documents.</p>}
          {session.is_admin && <><div className="nav-section-label nav-label">Administration</div>{item("/admin", "Manage users", <ClipboardText size={20} />)}</>}
        </nav>
        <div className="sidebar-footer nav-label"><img src="/bd-logo.png" alt="BD" /><span>Kaizen Cross-Check</span></div>
      </aside>
      <div className="app-body">
        <header className="app-topbar">
          <button type="button" ref={menuButton} className="btn btn-ghost btn-icon mobile-menu" aria-label={mobileOpen ? "Close navigation" : "Open navigation"} aria-expanded={mobileOpen} aria-controls="app-navigation" onClick={() => setMobileOpen(!mobileOpen)} >{mobileOpen ? <X size={20} /> : <List size={20} />}</button>
          <nav aria-label="Breadcrumb" className="breadcrumbs"><Link to="/">Workspace</Link><CaretRight size={14} /><span aria-current="page">{section}</span></nav>
          <div className="topbar-account">
            <ThemeToggle />
            <span className="account-avatar" title={session.reviewer}>{initials(displayName(session.reviewer))}</span>
            <span className="account-name">{displayName(session.reviewer)}<small>{session.is_admin ? "Administrator" : "Reviewer"}</small></span>
            {session.blind && <span className="chip bg-brand-100 text-brand-700 border-brand-200">Blind</span>}
            <Button variant="ghost" size="sm" iconOnly aria-label="Sign out" onClick={() => void signOut()} icon={<SignOut size={18} />} />
          </div>
        </header>
        {routeRun && <div className="run-context">
          <label htmlFor="current-run">Current run</label>
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

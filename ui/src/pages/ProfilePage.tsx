import { ArrowRight, Moon, SignOut, Sun } from "@phosphor-icons/react";
import { useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import { ErrorBox } from "../components/Feedback";
import { useTheme } from "../components/ThemeToggle";
import { Button, Card, CardHead, PageHeader } from "../components/ui";
import { displayName, fmtDate } from "../lib/format";
import { useReviewer } from "../lib/reviewer";
import { useToast } from "../lib/toast";
import { errorMessage, useAsync } from "../lib/useAsync";

export default function ProfilePage() {
  const { session, signOut } = useReviewer();
  const [theme, toggleTheme] = useTheme();
  const toast = useToast();
  const runs = useAsync(api.listRuns, []);
  const [signingOut, setSigningOut] = useState(false);
  if (!session) return null;
  const name = displayName(session.reviewer);
  const initials = name.split(/\s+/).slice(0, 2).map(word => word[0]).join("");
  const endSession = async () => {
    setSigningOut(true);
    try { await signOut(); } catch (error) { toast({ tone: "bad", title: "Couldn’t sign out", description: errorMessage(error) }); }
    finally { setSigningOut(false); }
  };
  return <div className="profile-page">
    <PageHeader title="Profile" description="Your account, review session and appearance preferences." />
    <Card className="profile-identity">
      <span className="profile-avatar" aria-hidden>{initials}</span>
      <div><h2>{name}</h2><p>{session.reviewer}</p><span className="profile-role">{session.is_admin ? "Administrator" : "Reviewer"}</span></div>
    </Card>
    <div className="profile-grid">
      <Card>
        <CardHead title="Account details" />
        <dl className="profile-details">
          <div><dt>Email</dt><dd>{session.reviewer}</dd></div>
          <div><dt>Role</dt><dd>{session.is_admin ? "Administrator" : "Reviewer"}</dd></div>
          <div><dt>Signed in</dt><dd>{fmtDate(session.created_at)}</dd></div>
        </dl>
      </Card>
      <Card>
        <CardHead title="Review session" />
        <dl className="profile-details">
          <div><dt>Reviewer slot</dt><dd>Reviewer {session.slot}</dd></div>
          <div><dt>Review mode</dt><dd>{session.blind ? "Blind review" : "Standard review"}</dd></div>
        </dl>
        <p className="profile-note">{session.blind ? "Other reviewers’ decisions are hidden during this session." : "Other reviewers’ decisions are visible when your access allows it."} To change your reviewer slot, sign out and choose a slot when you sign in.</p>
      </Card>
      <Card>
        <CardHead title="Appearance" />
        <div className="profile-preference"><span>{theme === "dark" ? <Moon size={22} /> : <Sun size={22} />}<span><strong>{theme === "dark" ? "Dark" : "Light"} theme</strong><small>Remembered in this browser.</small></span></span><Button size="sm" onClick={toggleTheme}>Use {theme === "dark" ? "light" : "dark"} theme</Button></div>
      </Card>
      <Card>
        <CardHead title="Your runs" />
        {runs.error ? <div className="p-4"><ErrorBox error={runs.error} onRetry={runs.reload} /></div> : <div className="profile-run-links">
          <Link to="/?view=mine"><span>My runs</span><strong>{runs.data ? runs.data.filter(run => run.permission === "owner").length : "—"}</strong><ArrowRight size={16} /></Link>
          <Link to="/?view=shared"><span>Shared with me</span><strong>{runs.data ? runs.data.filter(run => run.permission !== "owner").length : "—"}</strong><ArrowRight size={16} /></Link>
        </div>}
      </Card>
    </div>
    <div className="profile-signout"><span>Signed in as {session.reviewer}</span><Button loading={signingOut} onClick={() => void endSession()} icon={<SignOut size={17} />}>Sign out</Button></div>
  </div>;
}

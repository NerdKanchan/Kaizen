"""Application membership and explicit run grants, independent of the password provider."""
import re
from datetime import datetime, timezone

from kaizen.review.sessions import UserStore
from kaizen.storage.db import Database


def bd_email(value: str) -> str:
    email = str(value or '').strip().lower()
    if not re.fullmatch(r"[a-z0-9.!#$%&'*+/=?^_`{|}~-]+@bd\.com", email):
        raise ValueError('Only BD email addresses can register or sign in.')
    return email


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


class AccessStore:
    def __init__(self, db: Database):
        self.db = db
        self.conn = db.conn

    def profile(self, email: str) -> dict | None:
        row = self.conn.execute('SELECT * FROM profiles WHERE email = ?', (email,)).fetchone()
        return dict(row) if row else None

    def register(self, email: str) -> dict:
        email = bd_email(email)
        with self.db.lock:
            self.conn.execute("INSERT OR IGNORE INTO profiles (email, status, is_admin, created_at) VALUES (?, 'pending', 0, ?)", (email, now()))
            self.conn.commit()
        return self.profile(email)

    def bootstrap(self, email: str, password: str | None = None) -> None:
        """Operator-only initial setup. Never promotes users merely because they register first."""
        email = bd_email(email)
        with self.db.lock:
            if self.conn.execute("SELECT 1 FROM profiles WHERE is_admin = 1 AND status = 'approved'").fetchone():
                return
            users = UserStore(self.db)
            if password:
                if users.exists(email):
                    if not users.verify(email, password):
                        raise ValueError('Bootstrap account exists with a different password.')
                else:
                    users.create(email, password)
            elif not users.exists(email):
                raise ValueError('Set KAIZEN_ADMIN_PASSWORD to create the initial local administrator.')
            self.register(email)
            self.conn.execute("UPDATE profiles SET status = 'approved', is_admin = 1 WHERE email = ?", (email,))
            self.db.audit(email, 'account.bootstrap', 'Initial application administrator configured')
            # Pre-sharing runs have no known uploader. Explicit operator bootstrap assigns them.
            self.conn.execute("UPDATE runs SET owner = ? WHERE owner = ''", (email,))
            self.conn.execute("UPDATE runs SET name = 'BOM review · ' || substr(created_at,1,10) WHERE name = ''")
            self.conn.commit()

    def update(self, email: str, actor: str, status: str, admin: bool) -> dict:
        if status not in ('pending', 'approved', 'rejected'):
            raise ValueError('Invalid account status.')
        with self.db.lock:
            current = self.profile(email)
            if not current:
                raise KeyError(email)
            if current['is_admin'] and current['status'] == 'approved' and (not admin or status != 'approved'):
                count = self.conn.execute("SELECT COUNT(*) FROM profiles WHERE is_admin = 1 AND status = 'approved'").fetchone()[0]
                if count <= 1:
                    raise ValueError('At least one approved administrator must remain.')
            self.conn.execute('UPDATE profiles SET status = ?, is_admin = ? WHERE email = ?', (status, int(admin and status == 'approved'), email))
            if status != 'approved':
                self.conn.execute("UPDATE sessions SET ended_at = ? WHERE reviewer = ? AND ended_at = ''", (now(), email))
            self.db.audit(actor, 'account.updated', f'{email}: {status}, admin={admin and status == "approved"}')
            self.conn.commit()
        return self.profile(email)

    def permission(self, run_id: str, email: str) -> str | None:
        row = self.conn.execute('SELECT owner FROM runs WHERE run_id = ?', (run_id,)).fetchone()
        if not row:
            return None
        if row['owner'] == email:
            return 'owner'
        grant = self.conn.execute('SELECT permission FROM run_shares WHERE run_id = ? AND email = ?', (run_id, email)).fetchone()
        return grant['permission'] if grant else None

    def share(self, run_id: str, email: str, permission: str | None, actor: str) -> None:
        email = bd_email(email)
        profile = self.profile(email)
        if not profile or profile['status'] != 'approved':
            raise ValueError('Choose an approved user.')
        if permission not in ('view', 'edit', None):
            raise ValueError('Permission must be view or edit.')
        if self.permission(run_id, email) == 'owner':
            raise ValueError('The owner already has full access.')
        with self.db.lock:
            if permission is None:
                self.conn.execute('DELETE FROM run_shares WHERE run_id = ? AND email = ?', (run_id, email))
            else:
                self.conn.execute('INSERT INTO run_shares VALUES (?,?,?,?,?) ON CONFLICT(run_id,email) DO UPDATE SET permission=excluded.permission, shared_by=excluded.shared_by, shared_at=excluded.shared_at', (run_id, email, permission, actor, now()))
            self.db.audit(actor, 'run.shared', f'{run_id}: {email} → {permission or "revoked"}')
            self.conn.commit()

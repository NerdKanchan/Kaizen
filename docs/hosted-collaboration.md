# Shared Kaizen app

## Accounts and permissions

Only `@bd.com` registrations are accepted. Registration creates a pending profile; an application administrator approves it in **Manage users**. Approved users sign in without selecting a reviewer role. Administrators can appoint other administrators and revoke accounts. Revocation ends active sessions. The last approved administrator cannot be removed.

The uploader owns each run. **Share and rename** grants approved profiles View or Edit access. Owners manage sharing and names. Editors can record decisions, approve, download, create action items, import workbooks, and make independent copies. Viewers can browse results and source previews but cannot change, approve, copy, or export the run. Application administrator status does not grant access to other people's private runs. Shared terminology is an application-wide library managed by application administrators; it does not alter existing run snapshots.

Each saved decision records the signed-in user's identity in append-only history. Approval uses the displayed row revision; concurrent changes require a refresh. An uploader or the author of the current decision must explicitly confirm self-approval, which is recorded as **Self-approved**. A subsequent edit clears the approval and retains the old approval in history.

**Make a copy** creates a private run owned by the copier, with independent source documents, working decisions and action items. Sharing and approvals do not carry over. **Download independent copy** includes source files, portable run JSON, history and an editable workbook. For round-trip work, make the in-app copy first, download its workbook, edit offline, then import into that copy. Workbooks are bound to their run IDs to prevent accidental changes to the original.

## Deploy on Render

This application uses Python, Tesseract, SQLite and document files. The supplied Dockerfile serves the React frontend and API on the same origin. A single Render web service with a persistent disk preserves the workspace across deployments. See [Render disks](https://render.com/docs/disks) and [Docker services](https://render.com/docs/docker).

1. Push the application changes to the GitHub repository.
2. In Render, create a Blueprint from that repository using `render.yaml`.
3. Set the secret `KAIZEN_ADMIN_PASSWORD` to the initial administrator password. The configured email is `rahulreddy.basireddy@bd.com`. No password is embedded in the repository or image.
4. Deploy. The first start creates the administrator account with a salted scrypt hash. Subsequent starts preserve accounts, passwords, approvals and run grants. Remove the bootstrap password environment variable after the first successful setup. Keep the persistent disk attached.
5. Open the Render HTTPS URL, sign in, and use **Manage users** for registrations and admin appointments.

Use one instance and one worker with this SQLite deployment. Back up the complete `/var/data/kaizen` directory, including SQLite and document files; stop writes or use SQLite's backup API for a consistent database backup. Move to a shared database and object storage before scaling across instances. A persistent disk requires a paid Render service; this configuration does not deploy or purchase a service automatically.

The hosted app disables arbitrary server-path imports; users upload files through the browser. Secure cookies are enabled in the deployment configuration. For local development, run `kaizen serve` without `KAIZEN_SECURE_COOKIES=1` on HTTP.

## Existing workspace

The schema migration preserves legacy review data. Run the operator-only bootstrap once with `KAIZEN_ADMIN_EMAIL` and `KAIZEN_ADMIN_PASSWORD`; existing runs without ownership are assigned to that administrator because their original uploader was not stored. Existing accounts require administrator approval on their next sign-in. Historical two-reviewer records remain readable; new work uses one shared review and an explicit approval.

The optional Supabase password provider remains supported. Bootstrap the initial local administrator before enabling it and ensure the same administrator address exists in the provider. Kaizen's approval and sharing database must still be hosted centrally. Supabase credentials alone do not synchronize runs.

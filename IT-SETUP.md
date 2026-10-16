# DreamFolks Call Audit: server setup

Same pattern as the Sales Dashboard (b2csales.dreamfolks.co.in):

- **The page** (`index.html` + `config.js`) is a static file served by nginx at `https://salesaudit.dreamfolks.co.in/`.
- **The `/api` helper** (`api/server.py`, plain Python 3) runs on the same server behind nginx at `/api/`. It stores audits, questionnaire lists and the lead pool in **MySQL**.
- **Logins** use a Login ID and password. Users and their tab rights are kept in `users.json` in this repository, which admins manage on the page's **Users** tab and deploy through git. Passwords in `users.json` are salted PBKDF2 hashes, never plain text. The helper checks every login and every request, including tab rights, on the server.

No Microsoft 365, SharePoint or Entra app is used.

Owner / contact: Simran Singh (simran.singh@dreamfolks.com)

---

## 1. MySQL

```bash
sudo mysql < deploy/schema.sql        # first edit CHANGE-ME in that file to a real password
```

This creates the database `call_audit`, the user `callaudit`@`localhost` and three tables (`audits`, `settings`, `lead_pool`). `audits.phone` is **UNIQUE**, so a lead can only ever be audited once.
The existing b2csales MySQL server can be used. It's a separate database.

## 2. The /api helper

```bash
sudo mkdir -p /opt/callaudit && sudo chown deploy:deploy /opt/callaudit
# copy api/, users.json and requirements.txt into /opt/callaudit (the deploy workflow does this; see step 5)
sudo apt-get install -y python3-pip && sudo pip3 install -r /opt/callaudit/requirements.txt   # mysql-connector-python

sudo cp deploy/callaudit.env.example /etc/callaudit.env
sudo nano /etc/callaudit.env          # CALL_AUDIT_SECRET = output of `openssl rand -hex 32`, MYSQL_PASS from step 1
sudo chmod 600 /etc/callaudit.env

sudo cp deploy/callaudit-api.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now callaudit-api
curl -s http://127.0.0.1:8770/api/ping      # -> {"ok": true, "db": "mysql", "users": N}
```

`Restart=always` brings the helper back after a crash or reboot. The b2csales helper has been down (502) since August because nothing restarted it, so please keep this setting.
If you prefer Docker like b2csales, run `python3 api/server.py` in a `python:3.11-slim` image with the same environment variables and `restart: unless-stopped`.

## 3. nginx

Add the `location /api/` block from `deploy/nginx-salesaudit.conf` to the existing `server { }` for salesaudit.dreamfolks.co.in, then run:

```bash
sudo nginx -t && sudo systemctl reload nginx
curl -s https://salesaudit.dreamfolks.co.in/api/ping
```

## 4. First admin

`users.json` needs at least one admin before anyone can sign in. On any machine with this repository:

```bash
python tools/add_user.py simran.singh@dreamfolks.com "Simran Singh" --admin
```

It asks for a password without showing it, and writes only the hash. Commit and push `users.json`. From then on, admins add and change everyone else on the **Users** tab: **Save users file**, put `users.json` in the repo, push.

## 5. Automatic deployment (GitHub Actions)

`.github/workflows/deploy.yml` runs on every push to `main`:

- copies `index.html` and `config.js` to the web root;
- copies `api/`, `users.json` and `requirements.txt` to `/opt/callaudit`;
- restarts the helper and checks `/api/ping` on the live site.

One-time setup:

1. A `deploy` user on the server that owns the web root and `/opt/callaudit`, with rsync installed. Allow it to restart the helper without a password:
   ```bash
   echo 'deploy ALL=(root) NOPASSWD: /bin/systemctl restart callaudit-api' | sudo tee /etc/sudoers.d/callaudit-deploy
   ```
2. An SSH key for GitHub:
   ```bash
   ssh-keygen -t ed25519 -N "" -C github-deploy-salesaudit -f salesaudit_deploy
   ```
   Add `salesaudit_deploy.pub` to `/home/deploy/.ssh/authorized_keys`.
3. The server's host key: `ssh-keyscan <server>`.
4. GitHub → repository → Settings → Secrets and variables → Actions:

   | Secret | Value |
   |---|---|
   | `DEPLOY_HOST` | server host name or IP |
   | `DEPLOY_USER` | `deploy` |
   | `DEPLOY_PATH` | nginx web root for salesaudit, e.g. `/var/www/salesaudit` |
   | `DEPLOY_API_PATH` | `/opt/callaudit` |
   | `DEPLOY_SSH_KEY` | contents of `salesaudit_deploy` (private key) |
   | `DEPLOY_KNOWN_HOSTS` | output of step 3 |
   | `DEPLOY_PORT` | only if SSH isn't on port 22 |

Until these exist, each run is marked **skipped**, not failed.

## 6. Check

1. `https://salesaudit.dreamfolks.co.in/` shows the **Sign in** screen.
2. The admin signs in → **Settings** → **Upload leads.json** (from `tools/build_leads.py`).
3. **Users** tab: add an auditor, **Save users file**, commit and push `users.json`.
4. The auditor signs in, submits an audit, and sees it in **All Audits** and **Auditors**. A second audit on the same lead is refused.

## Backups

Everything lives in the MySQL database `call_audit`. Back it up with the rest of the server, e.g. `mysqldump call_audit > call_audit_$(date +%F).sql`.

## Access rules (enforced by the helper)

| | Viewer | Auditor | Admin |
|---|---|---|---|
| Tabs | All Audits, Auditors, Coverage (as ticked) | + New Audit | Every tab, including Settings and Users |
| Submit an audit | ✘ | ✔ | ✔ |
| Edit, delete or download audits | ✘ | ✘ | ✔ |
| Questionnaire lists, lead pool, users | ✘ | ✘ | ✔ |

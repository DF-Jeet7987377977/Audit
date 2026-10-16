# DreamFolks Call Audit

Shared, lead-level audit tool for obsolete and rejected sales leads. Auditors look up a lead by phone number or Lead ID, listen to its calls in the calling tool, and record one audit: a call synopsis, the questionnaire, and Agent / Customer / Marketing / Product / Other issues. Admins decide on the **Users** tab who can open the tool and which tabs each person sees. The presets are Auditor, Viewer and Admin, and tabs can be ticked per person. Only admins edit, delete, download, or change settings.

- `index.html`: the app (static HTML, Login ID + password, talks to `/api`)
- `config.js`: where the `/api` helper is
- `api/server.py`: the `/api` helper (Python; MySQL; checks logins and tab rights)
- `users.json`: users, hashed passwords and tab rights, managed on the Users tab and deployed through git
- `deploy/`: MySQL schema, systemd unit, nginx snippet, environment example
- `IT-SETUP.md`: server setup and automatic deployment
- `tools/add_user.py`: create the first admin (asks for the password; stores only a hash)
- `tools/build_leads.py`: builds the masked `leads.json` lead pool from the Excel sources

## Refreshing the lead pool

In the app: **Settings → Lead pool**. Choose the updated Excel files (Talk Time Bands, plus Lead Data and Calling Data if they changed), then click **Upload and build**. There's no size limit. The server (`api/leadpool.py`) matches, masks and replaces the pool. `tools/build_leads.py` runs the same builder offline if ever needed.

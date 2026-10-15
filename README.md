# DreamFolks Call Audit

Shared, lead-level audit tool for obsolete and rejected sales leads. Auditors look up a lead by phone number or Lead ID, listen to its calls in the calling tool, and record one audit: a call synopsis, the questionnaire, and Agent / Customer / Marketing / Product / Other issues. Everyone sees every audit and an auditor-wise scoreboard. Only owners edit, delete, download, or change settings.

- `index.html`: the app (static HTML; Microsoft 365 sign-in; data in SharePoint through Microsoft Graph)
- `config.js`: tenant, app client ID, SharePoint site, owners
- `IT-SETUP.md`: hosting, app registration, SharePoint site and permissions
- `tools/build_leads.py`: builds the masked `leads.json` lead pool from the Excel sources

## Refreshing the lead pool

```bash
python -I tools/build_leads.py <out_dir>
```

Then, in the app: **Settings → Lead pool → Upload leads.json**. `leads.json` holds no readable phone numbers or Lead IDs, but keep it out of git anyway (see `.gitignore`).

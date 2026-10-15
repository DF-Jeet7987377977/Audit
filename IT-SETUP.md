# DreamFolks Call Audit: IT setup

A static web page (`index.html` + `config.js`) where sales auditors record lead-level call audits.
People sign in with their DreamFolks Microsoft 365 account. Audits are stored in a SharePoint list.
The page only ever acts **as the signed-in user** (delegated permissions), so SharePoint permissions decide who can do what.

Owner / contact: Simran Singh (simran.singh@dreamfolks.com)

---

## 1. Host the page (static, HTTPS)

Serve the repository files as static content over HTTPS, for example `https://callaudit.dreamfolks.co.in/` or `https://b2csales.dreamfolks.co.in/audit/`.

- Files: `index.html`, `config.js`. No server-side code, database or build step.
- The page loads Microsoft's sign-in library from `https://alcdn.msauth.net` and the Excel export library from `https://cdn.jsdelivr.net`. Allow both if a Content-Security-Policy is set.
- Note the **exact URL** of `index.html`. Step 2 needs it.

## 2. Register the app in Microsoft Entra ID

Entra admin centre → **App registrations → New registration**

| Setting | Value |
|---|---|
| Name | `DreamFolks Call Audit` |
| Supported account types | Accounts in this organizational directory only (single tenant) |
| Redirect URI | Platform **Single-page application (SPA)**, URI = the exact page URL from step 1 (for example `https://callaudit.dreamfolks.co.in/`) |

Then:

1. **API permissions → Add a permission → Microsoft Graph → Delegated permissions**: `User.Read` and `Sites.ReadWrite.All`.
2. Click **Grant admin consent for DreamFolks**.
3. Copy the **Application (client) ID** into `config.js` → `clientId`. The tenant ID (`6c120c14-40ec-4ef0-ab13-6e996c48c6a3`) is already filled in.

`Sites.ReadWrite.All` is delegated. The page can never do more than the signed-in person is already allowed to do in SharePoint. If you prefer `Sites.Selected`, grant it on the Call Audit site only.

## 3. Create the SharePoint site

Create a site (a team site without a Microsoft 365 group, or a communication site) at
`https://itdreamfolks.sharepoint.com/sites/CallAudit`, and make **Simran Singh a site owner**.
If you use a different address, update `sitePath` in `config.js`.

## 4. Create the lists (the owner does this from the page)

Once steps 1–3 are done, the owner opens the page, signs in, goes to **Settings → Create the SharePoint lists**. This creates:

- **Call Audits**: one item per audited lead. The `Phone` column is indexed and **enforces unique values**, so a lead can't be audited twice. The other columns are `LeadId, Agent, AgentHeard, Category, TalkBand, Source, City, Campaign, Interested, WhyNoSale, SubmittedAt` and `RecordJson`, which holds the full audit.
- **Call Audit Settings**: the questionnaire dropdown lists, pre-filled.
- **Call Audit Users**: who may open the tool and which tabs each person sees (`Email` unique, `DisplayName`, `Tabs`, `IsAdmin`, `Active`). It starts with the owners from `config.js` as admins. Admins manage it on the page's **Users** tab.

The owner then uploads `leads.json` (Settings → Lead pool). It is saved to `Documents/CallAudit/leads.json`.

## 5. Permissions: auditors add and view only

Auditors must be able to read everything and **add** audits, but not edit or delete them. Only owners edit.

1. **Site permissions**: put auditors in the site's **Visitors** group (Read).
2. **Create a permission level**: Site settings → Site permissions → **Permission Levels → Add a Permission Level**:
   - Name: `Add and View`
   - List permissions: **Add Items**, **View Items**, **Open Items**, View Versions
   - Site permissions: **View Pages**, **Browse User Information**, **Use Remote Interfaces**, **Open**
   - Leave **Edit Items** and **Delete Items** unticked.
3. **Call Audits list** → List settings → Permissions for this list → **Stop Inheriting Permissions** → grant the auditors group **Add and View**. Owners keep Full Control.
4. Leave **Call Audit Settings**, **Call Audit Users** and **Documents** inheriting: everyone reads, owners edit. Everyone must be able to read **Call Audit Users**, because the page reads it to decide which tabs each person sees.
5. **Viewers**, meaning people given only All Audits / Auditors / Coverage on the Users tab: keep them in Visitors (Read) and do **not** give them **Add and View** on Call Audits.
6. **Admins** added on the Users tab also need **Edit** or **Full Control** on the site. Otherwise SharePoint refuses their edit, delete and settings changes.

### Two layers of access

- **The page's Users tab** decides who can open the tool and which tabs they see.
- **SharePoint permissions** decide what anyone can actually read or change, including through SharePoint itself. Keep the two in line: auditors get Add and View, viewers get Read, admins get Edit or Full Control.

Result:

| | Viewers | Auditors | Admins |
|---|---|---|---|
| Tabs | All Audits, Auditors, Coverage (as ticked) | + New Audit | All, including Settings and Users |
| See all audits | ✔ | ✔ | ✔ |
| Submit an audit | ✘ | ✔ | ✔ |
| Edit or delete an audit, download | ✘ | ✘ | ✔ |
| Change questionnaire lists, lead pool or users | ✘ | ✘ | ✔ |

## 6. Check

- An auditor signs in, finds a lead, submits an audit, and sees it in **All Audits** and **Auditors**.
- The same auditor gets "Already audited" on that lead and has no Edit or Delete buttons. SharePoint would refuse those actions anyway.
- In SharePoint, the **Call Audits** list shows the audit as a row and can be exported to Excel from the list toolbar.

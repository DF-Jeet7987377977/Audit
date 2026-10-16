// DreamFolks Call Audit: deployment settings. See IT-SETUP.md.
window.AUDIT_CONFIG = {
  // Microsoft Entra ID (Azure AD)
  tenantId: "6c120c14-40ec-4ef0-ab13-6e996c48c6a3",          // DreamFolks tenant
  clientId: "57140927-4cf0-4352-a9bd-f80a3b7e4253",           // Entra app registration "Sales Audit"

  // SharePoint site that stores the audits
  siteHost: "itdreamfolks.sharepoint.com",
  sitePath: "/sites/CallAudit",                               // change if IT names the site differently
  auditsList: "Call Audits",
  settingsList: "Call Audit Settings",
  usersList: "Call Audit Users",                              // who may open the tool, and which tabs they see
  poolFolder: "CallAudit",                                    // folder in the site's Documents library for leads.json

  // Permanent admins: always see every tab (Settings, Users, Edit, Delete, Download), even if missing
  // from the Users list, so nobody can be locked out. Everyone else is managed on the Users tab.
  owners: ["simran.singh@dreamfolks.com"],
};

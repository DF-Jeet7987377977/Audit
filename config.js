// DreamFolks Call Audit: deployment settings. See IT-SETUP.md.
window.AUDIT_CONFIG = {
  // Microsoft Entra ID (Azure AD)
  tenantId: "6c120c14-40ec-4ef0-ab13-6e996c48c6a3",          // DreamFolks tenant
  clientId: "REPLACE-WITH-APP-CLIENT-ID",                     // from the app registration (IT-SETUP.md step 2)

  // SharePoint site that stores the audits
  siteHost: "itdreamfolks.sharepoint.com",
  sitePath: "/sites/CallAudit",                               // change if IT names the site differently
  auditsList: "Call Audits",
  settingsList: "Call Audit Settings",
  poolFolder: "CallAudit",                                    // folder in the site's Documents library for leads.json

  // People who see Settings, Edit, Delete and Download. SharePoint permissions enforce the same rule.
  owners: ["simran.singh@dreamfolks.com"],
};

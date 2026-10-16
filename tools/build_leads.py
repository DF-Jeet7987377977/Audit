"""Build leads.json offline from the source Excel files (same builder the server uses).

Normally not needed: admins upload the Excel files on the page (Settings > Lead pool).

Usage: python -I tools/build_leads.py <talk time bands.xlsx> [lead data.xlsx] [calling data.xlsx] [--out leads.json]
"""
import argparse, json, os, sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "api"))
import leadpool  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("leads")
ap.add_argument("leaddata", nargs="?")
ap.add_argument("calling", nargs="?")
ap.add_argument("--out", default="leads.json")
a = ap.parse_args()
payload, stats = leadpool.build(a.leads, a.leaddata, a.calling, progress=lambda m: print(m, flush=True))
with open(a.out, "w", encoding="utf-8") as f:
    json.dump(payload, f, ensure_ascii=False, separators=(",", ":"))
print(json.dumps(stats))

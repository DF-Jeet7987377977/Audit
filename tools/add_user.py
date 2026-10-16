"""Add or update a user in users.json from the command line (used to create the first admin).

Usage:  python tools/add_user.py <login id> "<display name>" [--admin] [--tabs new,all,auditors,coverage]
The password is asked for and never shown. users.json stores only a salted PBKDF2 hash.
"""
import argparse, base64, getpass, hashlib, json, os, secrets
from datetime import date

ITER = 200_000
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PATH = os.path.join(ROOT, "users.json")


def hash_password(pw):
    salt = secrets.token_bytes(16)
    h = hashlib.pbkdf2_hmac("sha256", pw.encode(), salt, ITER)
    return f"pbkdf2_sha256${ITER}${base64.b64encode(salt).decode()}${base64.b64encode(h).decode()}"


ap = argparse.ArgumentParser()
ap.add_argument("login")
ap.add_argument("name")
ap.add_argument("--admin", action="store_true")
ap.add_argument("--tabs", default="new,all,auditors,coverage")
a = ap.parse_args()

pw = getpass.getpass("Password for " + a.login + ": ")
if len(pw) < 8 or pw != getpass.getpass("Repeat password: "):
    raise SystemExit("Passwords must match and be at least 8 characters.")

data = json.load(open(PATH, encoding="utf-8")) if os.path.exists(PATH) else {"users": []}
login = a.login.strip().lower()
data["users"] = [u for u in data["users"] if u.get("loginId", "").lower() != login]
data["users"].append({"loginId": login, "name": a.name, "password": hash_password(pw),
                      "tabs": [t for t in a.tabs.split(",") if t], "admin": a.admin, "active": True})
data["generatedAt"] = date.today().isoformat()
json.dump(data, open(PATH, "w", encoding="utf-8"), indent=2)
print(f"Saved {login} to {PATH}. Commit and push users.json to deploy it.")

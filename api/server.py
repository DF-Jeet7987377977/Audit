"""DreamFolks Call Audit: /api helper (same pattern as the b2csales serve.py).

Stores audits, questionnaire settings and the lead pool in MySQL, and checks logins against
users.json (Login ID + hashed password + tab rights), which is managed on the page's Users tab
and deployed through git.

Run:  python api/server.py            (listens on 0.0.0.0:8770; nginx proxies /api/ to it)

Environment:
  CALL_AUDIT_HOST      address to listen on (default 0.0.0.0, so nginx can reach it from another
                       container or host; firewall port 8770 from the internet)
  CALL_AUDIT_PORT      port to listen on (default 8770)
  CALL_AUDIT_SECRET    long random string used to sign login tokens (required in production)
  CALL_AUDIT_USERS     path to users.json (default: users.json next to this folder)
  MYSQL_HOST / MYSQL_PORT / MYSQL_USER / MYSQL_PASS / MYSQL_DB   (MYSQL_DB default call_audit)
  CALL_AUDIT_UPLOADS   folder for uploaded Excel files (default: uploads/ next to this folder)
  CALL_AUDIT_SQLITE    path to a SQLite file instead of MySQL (local testing only)
  CALL_AUDIT_STATIC    folder to also serve the page from (local testing only)
"""
import base64, hashlib, hmac, json, os, re, secrets, sqlite3, sys, threading, time, uuid
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

HERE = os.path.dirname(os.path.abspath(__file__))
HOST = os.getenv("CALL_AUDIT_HOST", "0.0.0.0")
PORT = int(os.getenv("CALL_AUDIT_PORT", "8770"))
SECRET = os.getenv("CALL_AUDIT_SECRET") or secrets.token_hex(32)
USERS_FILE = os.getenv("CALL_AUDIT_USERS") or os.path.join(os.path.dirname(HERE), "users.json")
SQLITE = os.getenv("CALL_AUDIT_SQLITE")
STATIC = os.getenv("CALL_AUDIT_STATIC")
UPLOADS = os.getenv("CALL_AUDIT_UPLOADS") or os.path.join(os.path.dirname(HERE), "uploads")
EXCEL_KINDS = {"leads": "Audit leads (Talk Time Bands)", "leaddata": "Lead Data", "calling": "Calling Data"}
TOKEN_HOURS = 12
sys.path.insert(0, HERE)
WORK_TABS = ("new", "all", "auditors", "coverage", "report")
MAX_BODY = 20 * 1024 * 1024
if not os.getenv("CALL_AUDIT_SECRET"):
    print("WARNING: CALL_AUDIT_SECRET not set; logins end whenever the service restarts.", file=sys.stderr)


def log(msg):
    print(f"{datetime.now():%Y-%m-%d %H:%M:%S} {msg}", flush=True)


# ---------------------------------------------------------------- database
class DB:
    """Tiny wrapper so the same SQL runs on MySQL (production) and SQLite (local tests)."""

    def __init__(self):
        self.lock = threading.Lock()
        if SQLITE:
            self.kind = "sqlite"
            self.conn = sqlite3.connect(SQLITE, check_same_thread=False)
        else:
            import mysql.connector  # pip install mysql-connector-python
            self.kind = "mysql"
            self.cfg = dict(host=os.getenv("MYSQL_HOST", "localhost"), port=int(os.getenv("MYSQL_PORT", "3306")),
                            user=os.getenv("MYSQL_USER", ""), password=os.getenv("MYSQL_PASS", ""),
                            database=os.getenv("MYSQL_DB", "call_audit"), autocommit=True, charset="utf8mb4")
            self.mysql = mysql.connector
            self.conn = None
        self.init_schema()

    def _conn(self):
        if self.kind == "sqlite":
            return self.conn
        if self.conn is None or not self.conn.is_connected():
            self.conn = self.mysql.connect(**self.cfg, connection_timeout=10)
        return self.conn

    def run(self, sql, args=(), fetch=False):
        if self.kind == "sqlite":
            sql = sql.replace("%s", "?")
        with self.lock:
            for attempt in (1, 2):
                try:
                    c = self._conn()
                    cur = c.cursor()
                    cur.execute(sql, args)
                    rows = cur.fetchall() if fetch else None
                    cols = [d[0] for d in cur.description] if fetch and cur.description else []
                    last = cur.lastrowid
                    cur.close()
                    if self.kind == "sqlite":
                        c.commit()
                    return [dict(zip(cols, r)) for r in rows] if fetch else last
                except Exception as e:
                    if self.kind == "mysql" and attempt == 1 and ("Lost connection" in str(e) or "gone away" in str(e)):
                        self.conn = None
                        continue
                    raise

    def is_duplicate(self, e):
        return "UNIQUE" in str(e) or "Duplicate entry" in str(e) or getattr(e, "errno", None) == 1062

    def init_schema(self):
        text = "LONGTEXT" if self.kind == "mysql" else "TEXT"
        auto = "INT AUTO_INCREMENT PRIMARY KEY" if self.kind == "mysql" else "INTEGER PRIMARY KEY AUTOINCREMENT"
        tail = " ENGINE=InnoDB DEFAULT CHARSET=utf8mb4" if self.kind == "mysql" else ""
        self.run(f"""CREATE TABLE IF NOT EXISTS audits (
            id {auto}, phone VARCHAR(16) NOT NULL UNIQUE, auditor_login VARCHAR(255) NOT NULL, auditor_name VARCHAR(255),
            lead_id VARCHAR(64), agent VARCHAR(128), category VARCHAR(128), talk_band VARCHAR(32), source VARCHAR(128),
            submitted_at VARCHAR(32) NOT NULL, updated_at VARCHAR(32), updated_by VARCHAR(255), record {text} NOT NULL){tail}""")
        self.run(f"CREATE TABLE IF NOT EXISTS settings (k VARCHAR(64) PRIMARY KEY, v {text} NOT NULL, updated_at VARCHAR(32), updated_by VARCHAR(255)){tail}")
        self.run(f"CREATE TABLE IF NOT EXISTS lead_pool (id INT PRIMARY KEY, content {text} NOT NULL, rows_count INT, updated_at VARCHAR(32), updated_by VARCHAR(255)){tail}")
        self.run(f"CREATE TABLE IF NOT EXISTS app_users (id INT PRIMARY KEY, content {text} NOT NULL, updated_at VARCHAR(32), updated_by VARCHAR(255)){tail}")


def now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


# ---------------------------------------------------------------- users + tokens
# Users live in the database (table app_users) once an admin has saved them on the Users tab.
# Until then users.json is used, so the very first admin can sign in.
_users = {"loaded": 0.0, "doc": {"users": []}, "by_login": {}, "source": None}
USERS_TTL = 5  # seconds; a save on this server refreshes immediately


def users_doc():
    if time.time() - _users["loaded"] > USERS_TTL:
        doc, source = None, "database"
        try:
            rows = DBI.run("SELECT content FROM app_users WHERE id=1", fetch=True)
            doc = json.loads(rows[0]["content"]) if rows else None
        except Exception as e:
            log(f"users: database read failed ({e!r})")
            if _users["source"]:
                return _users["doc"]        # keep the last good list rather than locking everyone out
        if doc is None:
            source = USERS_FILE
            try:
                with open(USERS_FILE, encoding="utf-8") as f:
                    doc = json.load(f)
            except (OSError, ValueError):
                doc = {"users": []}
        by_login = {str(u.get("loginId", "")).strip().lower(): u for u in doc.get("users", []) if u.get("loginId")}
        if source != _users["source"] or len(by_login) != len(_users["by_login"]):
            log(f"users: {len(by_login)} from {source}")
        _users.update(loaded=time.time(), doc=doc, by_login=by_login, source=source)
    return _users["doc"]


def users():
    users_doc()
    return _users["by_login"]


def check_password(stored, password):
    # pbkdf2_sha256$<iterations>$<salt b64>$<hash b64>
    try:
        algo, it, salt, want = stored.split("$")
        if algo != "pbkdf2_sha256":
            return False
        got = hashlib.pbkdf2_hmac("sha256", password.encode(), base64.b64decode(salt), int(it))
        return hmac.compare_digest(got, base64.b64decode(want))
    except Exception:
        return False


def b64u(b):
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def unb64u(s):
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def make_token(login):
    body = b64u(json.dumps({"sub": login, "exp": int(time.time()) + TOKEN_HOURS * 3600}).encode())
    sig = b64u(hmac.new(SECRET.encode(), body.encode(), hashlib.sha256).digest())
    return body + "." + sig


def read_token(tok):
    try:
        body, sig = tok.split(".")
        if not hmac.compare_digest(sig, b64u(hmac.new(SECRET.encode(), body.encode(), hashlib.sha256).digest())):
            return None
        p = json.loads(unb64u(body))
        return p["sub"] if p.get("exp", 0) > time.time() else None
    except Exception:
        return None


def public_user(u):
    admin = bool(u.get("admin"))
    tabs = list(WORK_TABS) if admin else [t for t in u.get("tabs", []) if t in WORK_TABS]
    return {"loginId": u["loginId"].strip().lower(), "name": u.get("name") or u["loginId"], "admin": admin, "tabs": tabs}


# ---------------------------------------------------------------- lead pool storage + Excel builds
def store_pool(j, who):
    txt, ts = json.dumps(j, separators=(",", ":")), now_iso()
    if DBI.run("SELECT id FROM lead_pool WHERE id=1", fetch=True):
        DBI.run("UPDATE lead_pool SET content=%s, rows_count=%s, updated_at=%s, updated_by=%s WHERE id=1", (txt, len(j["rows"]), ts, who))
    else:
        DBI.run("INSERT INTO lead_pool (id, content, rows_count, updated_at, updated_by) VALUES (1,%s,%s,%s,%s)", (txt, len(j["rows"]), ts, who))
    log(f"lead pool replaced by {who}: {len(j['rows'])} rows")


_uploads = {}                      # upload id -> {kind, name, size, received, tmp, by}
_build = {"state": "idle"}         # state: idle | running | done | error
_build_lock = threading.Lock()


def excel_files():
    meta_path = os.path.join(UPLOADS, "files.json")
    try:
        with open(meta_path, encoding="utf-8") as f:
            meta = json.load(f)
    except (OSError, ValueError):
        meta = {}
    return {k: v for k, v in meta.items() if os.path.isfile(os.path.join(UPLOADS, k + ".xlsx"))}


def save_excel_meta(kind, info):
    meta = excel_files()
    meta[kind] = info
    with open(os.path.join(UPLOADS, "files.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=1)


def run_build(who):
    import leadpool
    files = excel_files()
    path = lambda k: os.path.join(UPLOADS, k + ".xlsx") if k in files else None

    def progress(msg):
        _build["message"] = msg

    try:
        payload, stats = leadpool.build(path("leads"), path("leaddata"), path("calling"), progress)
        progress("Saving the lead pool…")
        store_pool(payload, who)
        _build.update(state="done", message=f"Built the lead pool: {stats['leads']:,} leads.", stats=stats, finishedAt=now_iso())
    except Exception as e:
        log(f"build failed: {e!r}")
        _build.update(state="error", message=str(e) if isinstance(e, ValueError) else f"The build failed: {e}", finishedAt=now_iso())


# ---------------------------------------------------------------- HTTP
FIELD_RE = re.compile(r"^/api/audits/(\d+)$")
UPLOAD_RE = re.compile(r"^/api/excel/([0-9a-f]{32})(/finish)?$")
SETTING_RE = re.compile(r"^/api/settings/([a-z_]{1,64})$")
_fail = {}  # login -> [count, first_ts] for simple brute-force protection


class Handler(BaseHTTPRequestHandler):
    server_version = "CallAuditAPI/1.0"

    def log_message(self, fmt, *args):
        log(f"{self.address_string()} {fmt % args}")

    # ---- plumbing
    def send(self, status, body=None, headers=None):
        data = b"" if body is None else (body if isinstance(body, bytes) else json.dumps(body).encode())
        self.send_response(status)
        self.send_header("Content-Type", (headers or {}).pop("Content-Type", "application/json; charset=utf-8"))
        self.send_header("Cache-Control", "no-store")
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(data)

    def err(self, status, msg):
        self.send(status, {"error": msg})

    def body_json(self):
        n = int(self.headers.get("Content-Length") or 0)
        if n > MAX_BODY:
            raise ValueError("Request too large")
        raw = self.rfile.read(n) if n else b"{}"
        return json.loads(raw.decode("utf-8") or "{}")

    def me(self):
        auth = self.headers.get("Authorization", "")
        login = read_token(auth[7:]) if auth.startswith("Bearer ") else None
        u = users().get(login or "")
        if not u or u.get("active") is False:
            return None
        return public_user(u)

    def path_only(self):
        return urlparse(self.path).path.rstrip("/") or "/"

    # ---- routing
    def do_GET(self):
        self.route("GET")

    def do_POST(self):
        self.route("POST")

    def do_PUT(self):
        self.route("PUT")

    def do_DELETE(self):
        self.route("DELETE")

    def route(self, method):
        p = self.path_only()
        try:
            if not p.startswith("/api"):
                return self.static(p) if STATIC and method == "GET" else self.err(404, "Not found")
            if p == "/api/ping":
                return self.send(200, {"ok": True, "db": DBI.kind, "users": len(users()),
                                       "usersFrom": "database" if _users["source"] == "database" else "users.json"})
            if p == "/api/login" and method == "POST":
                return self.login()
            me = self.me()
            if not me:
                return self.err(401, "Sign in again.")
            if p == "/api/me":
                return self.send(200, {"user": me})
            if p == "/api/audits" and method == "GET":
                return self.list_audits(me)
            if p == "/api/audits" and method == "POST":
                return self.create_audit(me)
            m = FIELD_RE.match(p)
            if m and method in ("PUT", "DELETE"):
                if not me["admin"]:
                    return self.err(403, "Only admins can change or delete audits.")
                return self.update_audit(me, int(m.group(1))) if method == "PUT" else self.delete_audit(int(m.group(1)))
            if p == "/api/settings" and method == "GET":
                rows = DBI.run("SELECT k, v FROM settings", fetch=True)
                return self.send(200, {r["k"]: json.loads(r["v"]) for r in rows})
            m = SETTING_RE.match(p)
            if m and method == "PUT":
                if not me["admin"]:
                    return self.err(403, "Only admins can change settings.")
                return self.put_setting(me, m.group(1))
            if p == "/api/pool" and method == "GET":
                return self.get_pool()
            if p == "/api/pool" and method == "PUT":
                if not me["admin"]:
                    return self.err(403, "Only admins can replace the lead pool.")
                return self.put_pool(me)
            if p.startswith("/api/excel"):
                if not me["admin"]:
                    return self.err(403, "Only admins can upload lead files.")
                return self.excel(me, method, p)
            if p == "/api/users" and method in ("GET", "PUT"):
                if not me["admin"]:
                    return self.err(403, "Only admins can see or change users.")
                return self.send(200, users_doc()) if method == "GET" else self.put_users(me)
            return self.err(404, "Not found")
        except ValueError as e:
            return self.err(400, str(e))
        except Exception as e:
            log(f"ERROR {method} {p}: {e!r}")
            return self.err(500, "The audit service hit an error. Try again.")

    # ---- handlers
    def login(self):
        b = self.body_json()
        login = str(b.get("loginId", "")).strip().lower()
        f = _fail.get(login, [0, time.time()])
        if f[0] >= 8 and time.time() - f[1] < 900:
            return self.err(429, "Too many attempts. Wait 15 minutes and try again.")
        u = users().get(login)
        if not u or u.get("active") is False or not check_password(u.get("password", ""), str(b.get("password", ""))):
            _fail[login] = [f[0] + 1, f[1] if f[0] else time.time()]
            return self.err(401, "Incorrect login ID or password.")
        _fail.pop(login, None)
        pu = public_user(u)
        if not pu["admin"] and not pu["tabs"]:
            return self.err(403, "Your account has no tabs assigned. Ask an admin.")
        log(f"login {login}")
        return self.send(200, {"token": make_token(login), "user": pu})

    def list_audits(self, me):
        if not (me["admin"] or me["tabs"]):
            return self.err(403, "No access.")
        rows = DBI.run("SELECT id, phone, auditor_login, auditor_name, record FROM audits ORDER BY id", fetch=True)
        return self.send(200, {"audits": [{"id": r["id"], "phone": r["phone"], "auditorLogin": r["auditor_login"],
                                           "auditorName": r["auditor_name"], "record": json.loads(r["record"])} for r in rows]})

    def _cols(self, rec):
        L = rec.get("lead") or {}
        return (str(L.get("leadId") or "")[:64], str(L.get("agent") or "")[:128], str(L.get("category") or "")[:128],
                str(L.get("talkBand") or "")[:32], str(L.get("source") or "")[:128])

    def create_audit(self, me):
        if not (me["admin"] or "new" in me["tabs"]):
            return self.err(403, "You don't have the New Audit tab.")
        rec = self.body_json().get("record") or {}
        phone = re.sub(r"\D", "", str(rec.get("phone", "")))[-10:]
        if len(phone) != 10:
            return self.err(400, "The audit has no valid phone number.")
        rec["phone"], rec["auditorId"] = phone, me["loginId"]
        rec["submittedAt"] = rec.get("submittedAt") or now_iso()
        try:
            new_id = DBI.run("INSERT INTO audits (phone, auditor_login, auditor_name, lead_id, agent, category, talk_band, source, submitted_at, record) "
                             "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                             (phone, me["loginId"], me["name"], *self._cols(rec), rec["submittedAt"], json.dumps(rec)))
        except Exception as e:
            if DBI.is_duplicate(e):
                return self.err(409, "This lead has already been audited.")
            raise
        log(f"audit {phone} by {me['loginId']}")
        return self.send(201, {"id": new_id})

    def update_audit(self, me, aid):
        rec = self.body_json().get("record") or {}
        rows = DBI.run("SELECT phone, record FROM audits WHERE id=%s", (aid,), fetch=True)
        if not rows:
            return self.err(404, "That audit no longer exists.")
        old = json.loads(rows[0]["record"])
        rec["phone"], rec["auditorId"], rec["ts"], rec["submittedAt"] = rows[0]["phone"], old.get("auditorId"), old.get("ts"), old.get("submittedAt")
        rec["updatedAt"], rec["updatedBy"] = now_iso(), me["loginId"]
        DBI.run("UPDATE audits SET lead_id=%s, agent=%s, category=%s, talk_band=%s, source=%s, updated_at=%s, updated_by=%s, record=%s WHERE id=%s",
                (*self._cols(rec), rec["updatedAt"], me["loginId"], json.dumps(rec), aid))
        return self.send(200, {"ok": True, "record": rec})

    def delete_audit(self, aid):
        DBI.run("DELETE FROM audits WHERE id=%s", (aid,))
        return self.send(200, {"ok": True})

    def put_setting(self, me, key):
        val = self.body_json()
        val["updatedAt"] = now_iso()
        txt = json.dumps(val)
        if DBI.run("SELECT k FROM settings WHERE k=%s", (key,), fetch=True):
            DBI.run("UPDATE settings SET v=%s, updated_at=%s, updated_by=%s WHERE k=%s", (txt, val["updatedAt"], me["loginId"], key))
        else:
            DBI.run("INSERT INTO settings (k, v, updated_at, updated_by) VALUES (%s,%s,%s,%s)", (key, txt, val["updatedAt"], me["loginId"]))
        return self.send(200, val)

    def put_users(self, me):
        lst = self.body_json().get("users")
        if not isinstance(lst, list) or not lst:
            return self.err(400, "The user list is empty.")
        out, seen = [], set()
        for u in lst:
            lid = str(u.get("loginId", "")).strip().lower()
            if not lid:
                return self.err(400, "Every user needs a login ID.")
            if lid in seen:
                return self.err(400, f"{lid} is listed twice.")
            pw = str(u.get("password", ""))
            if not pw.startswith("pbkdf2_sha256$") or len(pw.split("$")) != 4:
                return self.err(400, f"Set a password for {lid}.")
            seen.add(lid)
            out.append({"loginId": lid, "name": str(u.get("name") or "")[:120], "password": pw,
                        "tabs": [t for t in (u.get("tabs") or []) if t in WORK_TABS],
                        "admin": bool(u.get("admin")), "active": u.get("active") is not False})
        mine = next((u for u in out if u["loginId"] == me["loginId"]), None)
        if not (mine and mine["admin"] and mine["active"]):
            return self.err(400, "You can't remove your own admin access.")
        ts = now_iso()
        txt = json.dumps({"generatedAt": ts[:10], "users": out})
        if DBI.run("SELECT id FROM app_users WHERE id=1", fetch=True):
            DBI.run("UPDATE app_users SET content=%s, updated_at=%s, updated_by=%s WHERE id=1", (txt, ts, me["loginId"]))
        else:
            DBI.run("INSERT INTO app_users (id, content, updated_at, updated_by) VALUES (1,%s,%s,%s)", (txt, ts, me["loginId"]))
        _users["loaded"] = 0.0
        log(f"users saved by {me['loginId']}: {len(out)} users")
        return self.send(200, {"ok": True, "users": len(out), "savedAt": ts})

    def get_pool(self):
        rows = DBI.run("SELECT content, updated_at FROM lead_pool WHERE id=1", fetch=True)
        if not rows:
            return self.err(404, "No lead pool uploaded yet.")
        tag = '"' + hashlib.sha1(rows[0]["updated_at"].encode()).hexdigest() + '"'
        if self.headers.get("If-None-Match") == tag:
            return self.send(304, None, {"ETag": tag})
        return self.send(200, rows[0]["content"].encode(), {"ETag": tag})

    def put_pool(self, me):
        j = self.body_json()
        if not (isinstance(j.get("rows"), list) and j["rows"] and all(f in (j.get("fields") or []) for f in ("ph", "lh", "le")) and j.get("mask")):
            return self.err(400, "This isn't a masked lead file (it needs ph, lh and le columns).")
        store_pool(j, me["loginId"])
        return self.send(200, {"ok": True, "rows": len(j["rows"])})

    def excel(self, me, method, p):
        """Excel files arrive in pieces (each under nginx's body limit), so file size is unlimited.
        POST /api/excel/start {kind,name,size} -> {id}; PUT /api/excel/<id>?offset=N <bytes>;
        POST /api/excel/<id>/finish; POST /api/excel/build; GET /api/excel/status"""
        if p == "/api/excel/status" and method == "GET":
            return self.send(200, {"files": excel_files(), "build": _build})
        if p == "/api/excel/start" and method == "POST":
            b = self.body_json()
            kind, size = b.get("kind"), int(b.get("size") or 0)
            if kind not in EXCEL_KINDS:
                return self.err(400, "Unknown file type.")
            if not str(b.get("name", "")).lower().endswith((".xlsx", ".xlsm")) or size <= 0:
                return self.err(400, "Choose an Excel .xlsx file.")
            os.makedirs(UPLOADS, exist_ok=True)
            for old in os.listdir(UPLOADS):   # clear abandoned partial uploads older than 6 hours
                fp = os.path.join(UPLOADS, old)
                if old.endswith(".part") and time.time() - os.path.getmtime(fp) > 6 * 3600:
                    os.remove(fp)
            uid = uuid.uuid4().hex
            tmp = os.path.join(UPLOADS, f".{uid}.part")
            open(tmp, "wb").close()
            _uploads[uid] = {"kind": kind, "name": os.path.basename(str(b["name"]))[:200], "size": size, "received": 0, "tmp": tmp, "by": me["loginId"]}
            return self.send(200, {"id": uid})
        if p == "/api/excel/build" and method == "POST":
            if "leads" not in excel_files():
                return self.err(400, "Upload the audit leads Excel (Talk Time Bands) first.")
            with _build_lock:
                if _build.get("state") == "running":
                    return self.err(409, "A build is already running.")
                _build.clear()
                _build.update(state="running", message="Starting…", startedAt=now_iso(), by=me["loginId"])
            threading.Thread(target=run_build, args=(me["loginId"],), daemon=True).start()
            return self.send(202, {"build": _build})
        m = UPLOAD_RE.match(p)
        up = _uploads.get(m.group(1)) if m else None
        if not up:
            return self.err(404, "That upload has expired. Start the upload again.")
        if method == "PUT" and not m.group(2):
            offset = int((urlparse(self.path).query.split("offset=") + ["0"])[1].split("&")[0] or 0)
            n = int(self.headers.get("Content-Length") or 0)
            if n <= 0 or n > MAX_BODY:
                return self.err(400, "That piece of the file doesn't fit.")
            piece = self.rfile.read(n)   # read it before answering, even when refusing it
            if offset != up["received"]:
                return self.send(409, {"error": "Out of order.", "received": up["received"]})
            if up["received"] + n > up["size"]:
                return self.err(400, "That piece of the file doesn't fit.")
            with open(up["tmp"], "ab") as f:
                f.write(piece)
            up["received"] += n
            return self.send(200, {"received": up["received"]})
        if method == "POST" and m.group(2):
            if up["received"] != up["size"]:
                return self.err(400, f"The upload is incomplete ({up['received']} of {up['size']} bytes).")
            os.replace(up["tmp"], os.path.join(UPLOADS, up["kind"] + ".xlsx"))
            save_excel_meta(up["kind"], {"name": up["name"], "size": up["size"], "uploadedAt": now_iso(), "uploadedBy": up["by"]})
            _uploads.pop(m.group(1), None)
            log(f"excel {up['kind']} uploaded by {up['by']}: {up['name']} ({up['size']} bytes)")
            return self.send(200, {"ok": True, "files": excel_files()})
        return self.err(404, "Not found")

    def static(self, p):
        rel = "index.html" if p == "/" else p.lstrip("/")
        full = os.path.realpath(os.path.join(STATIC, rel))
        if not full.startswith(os.path.realpath(STATIC)) or not os.path.isfile(full):
            return self.err(404, "Not found")
        ctype = {"html": "text/html; charset=utf-8", "js": "application/javascript", "json": "application/json"}.get(full.rsplit(".", 1)[-1], "application/octet-stream")
        with open(full, "rb") as f:
            return self.send(200, f.read(), {"Content-Type": ctype})


DBI = DB()

if __name__ == "__main__":
    users()
    log(f"Call Audit API on {HOST}:{PORT} (db={DBI.kind}, users file={USERS_FILE})")
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()

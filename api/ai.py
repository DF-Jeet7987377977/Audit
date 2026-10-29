"""AI categorisation of audit comments with Claude (Anthropic API).

An admin starts a run from the Report tab. Every free-text answer (call synopsis, Q1/Q3 "why",
Q12 "why not bought", and the comment under each issue) is given one theme from THEMES and a
segment. Results are stored in the ai_tags table and only new or edited comments are sent again.

Only the comment text is sent - never phone numbers, emails, Lead IDs or names; long digit runs
and emails inside a comment are masked first.

Needs ANTHROPIC_API_KEY in the service environment (/etc/callaudit.env).
Optional: CALL_AUDIT_AI_MODEL (default claude-opus-5-5).
"""
import hashlib
import json
import os
import re

MODEL = os.getenv("CALL_AUDIT_AI_MODEL", "claude-opus-5-5")
BATCH = 40

THEMES = [
    "Price too high / wants discount",
    "Already has lounge access through a bank card",
    "No travel plans / not a frequent traveller",
    "Just browsing / no real need",
    "Never enquired / wrong or junk lead",
    "Wants only one service, not the full membership",
    "Location or coverage gap (city, airport, outlets)",
    "Trust concern / doesn't know DreamFolks",
    "Product not pitched fully or explained poorly",
    "Agent behaviour or selling skill",
    "No follow-up / callback missed",
    "Busy now / will decide later",
    "Not the decision maker",
    "Payment or technical problem",
    "Language barrier",
    "No real conversation / call dropped",
    "Showed interest, could be re-worked",
    "Other",
]
SEGMENTS = ["Marketing", "Agent", "Product", "Customer", "Other"]

FIELDS = {"synopsis": "Call synopsis", "q1Why": "Why not interested at first (Q1)", "q3Why": "Why the full product wasn't pitched (Q3)",
          "q12": "Why the customer didn't buy (Q12)"}
ISSUE_KEYS = ["agent", "customer", "marketing", "product", "other"]

SYSTEM = f"""You categorise call-audit comments for DreamFolks Club, an Indian paid membership that bundles
airport and railway lounges, golf, private clubs, coffee, dining, salons, hotel perks, airport transfers and
entertainment. Auditors listened to sales calls with leads that did not buy and wrote short comments.

For each comment, choose exactly one theme from this list (copy it exactly):
{chr(10).join("- " + t for t in THEMES)}

and one segment: Marketing (lead quality, targeting, ad expectations), Agent (how the sales agent handled
the call), Product (price, coverage, features, restrictions), Customer (the customer's own situation or
needs), or Other.

Pick the theme that best explains why the sale didn't happen or what the comment is mainly about.
Comments may be in English, Hindi or Hinglish. Use "Other" only when nothing fits."""

SCHEMA = {
    "type": "object",
    "properties": {"items": {"type": "array", "items": {
        "type": "object",
        "properties": {"id": {"type": "string"}, "theme": {"type": "string", "enum": THEMES}, "segment": {"type": "string", "enum": SEGMENTS}},
        "required": ["id", "theme", "segment"], "additionalProperties": False}}},
    "required": ["items"], "additionalProperties": False,
}


def configured():
    return bool(os.getenv("ANTHROPIC_API_KEY"))


def mask(text):
    text = re.sub(r"[\w.+-]+@[\w-]+\.[\w.]+", "[email]", text)
    return re.sub(r"\d[\d\s-]{6,}\d", "[number]", text)


def text_items(audits):
    """(audit_id, field, label, text) for every non-empty free-text answer."""
    out = []
    for a in audits:
        ans = a["record"].get("answers") or {}
        for f, label in FIELDS.items():
            t = str(ans.get(f) or "").strip()
            if t:
                out.append((a["id"], f, label, t))
        for k in ISSUE_KEYS:
            x = (ans.get("issues") or {}).get(k) or {}
            t = str(x.get("comment") or "").strip()
            if t:
                out.append((a["id"], "issue:" + k, f"{k.title()} issue comment ({x.get('l2') or x.get('l1') or ''})", t))
    return out


def text_hash(t):
    return hashlib.sha1(t.encode("utf-8")).hexdigest()


def classify(batch):
    """batch: list of (key, label, text). Returns {key: (theme, segment)}. One Claude call."""
    import anthropic

    client = anthropic.Anthropic()
    lines = "\n".join(json.dumps({"id": k, "question": label, "comment": mask(t)[:1500]}, ensure_ascii=False) for k, label, t in batch)
    resp = client.beta.messages.create(
        model=MODEL,
        max_tokens=16000,
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
        system=SYSTEM,
        output_config={"effort": "low", "format": {"type": "json_schema", "schema": SCHEMA}},
        messages=[{"role": "user", "content": "Categorise each of these comments (one JSON object per line). "
                                              "Return one item per id.\n\n" + lines}],
    )
    if resp.stop_reason == "refusal":
        return {}
    text = next((b.text for b in resp.content if b.type == "text"), "{}")
    got = {}
    for it in json.loads(text).get("items", []):
        if it.get("theme") in THEMES and it.get("segment") in SEGMENTS:
            got[it["id"]] = (it["theme"], it["segment"])
    return got


def run(db, audits, who, status, now_iso, classify_fn=None):
    """Tag every comment that is new or changed since the last run. Updates `status` as it goes."""
    classify_fn = classify_fn or classify
    existing = {(r["audit_id"], r["field"]): r["text_hash"] for r in db.run("SELECT audit_id, field, text_hash FROM ai_tags", fetch=True)}
    items = text_items(audits)
    todo = [it for it in items if existing.get((it[0], it[1])) != text_hash(it[3])]
    status.update(total=len(todo), done=0, message=f"Categorising {len(todo):,} new or changed comments…" if todo else "Everything is already categorised.")
    failed = 0
    for i in range(0, len(todo), BATCH):
        chunk = todo[i:i + BATCH]
        keys = {f"c{j}": it for j, it in enumerate(chunk)}
        try:
            got = classify_fn([(k, it[2], it[3]) for k, it in keys.items()])
        except Exception as e:  # keep going; a later run retries what failed
            got = {}
            status["lastError"] = str(e)[:300]
        for k, it in keys.items():
            if k not in got:
                failed += 1
                continue
            theme, seg = got[k]
            db.run("DELETE FROM ai_tags WHERE audit_id=%s AND field=%s", (it[0], it[1]))
            db.run("INSERT INTO ai_tags (audit_id, field, text_hash, theme, segment, tagged_at) VALUES (%s,%s,%s,%s,%s,%s)",
                   (it[0], it[1], text_hash(it[3]), theme, seg, now_iso()))
        status.update(done=min(i + BATCH, len(todo)), message=f"Categorised {min(i + BATCH, len(todo)):,} of {len(todo):,} comments…")
    status.update(state="done", finishedAt=now_iso(), by=who, model=MODEL, failed=failed,
                  message=(f"Categorised {len(todo) - failed:,} comments." if todo else "Everything is already categorised.")
                  + (f" {failed:,} couldn't be categorised this time; run it again to retry them." if failed else ""))

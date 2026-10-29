"""Theme categorisation of audit comments, built in - no external service, no API key, no cost.

An admin starts a run from the Report tab. Every free-text answer (call synopsis, Q1/Q3 "why",
Q12 "why not bought", and the comment under each issue) is matched against the keyword rules
below (English, Hindi and Hinglish) and given one theme and a segment. Results are stored in the
ai_tags table, so a later run only looks at new or edited comments - or at everything again
after RULES_VERSION changes. Nothing leaves the server.

To improve the categories, add words to RULES and bump RULES_VERSION.
"""
import hashlib
import re

MODEL = "Built-in keyword rules"
RULES_VERSION = "1"
STEP = 200          # progress update every STEP comments

# theme -> (segment, patterns). Patterns are regular expressions matched on whole words,
# case-insensitive. The theme with the most matching patterns wins; a tie goes to the
# theme listed first.
RULES = {
    "Never enquired / wrong or junk lead": ("Marketing", [
        r"never (enquired|inquired|filled|applied|registered)", r"did ?n[o']?t (enquire|inquire|fill|apply|register)",
        r"no enquiry", r"wrong (number|lead|person)", r"junk", r"by mistake", r"galti se", r"not aware of (the )?(enquiry|form|lead)",
        r"fake lead", r"didn'?t (sign|ask)", r"kabhi (nahi|nhi) (kiya|bhara)"]),
    "Already has lounge access through a bank card": ("Product", [
        r"credit cards?", r"debit cards?", r"bank cards?", r"card (se|par|pe|benefit)", r"already (has|have|having|got) (free )?(lounge|access)",
        r"free lounge", r"complimentary (lounge|access)", r"card (gives|provides|offers)", r"through (his|her|their) (card|bank)"]),
    "Price too high / wants discount": ("Product", [
        r"price", r"pricing", r"costly", r"expensive", r"mehe?n?ga", r"discount", r"offer", r"budget", r"afford", r"too (much|high)",
        r"cheaper", r"paise?", r"fees?", r"charges?", r"amount", r"cost"]),
    "No travel plans / not a frequent traveller": ("Customer", [
        r"(no|not|any) travel", r"travel (nahi|nhi|less|rarely|plans?)", r"rarely (travel|fly)", r"doesn'?t (travel|fly)",
        r"don'?t (travel|fly)", r"not (a )?frequent", r"no (trip|plan|plans|journey)", r"trip (nahi|nhi)", r"not flying",
        r"once a year", r"occasional"]),
    "Just browsing / no real need": ("Customer", [
        r"just (checking|browsing|looking|exploring)", r"browsing", r"no (need|requirement|use)", r"not (needed|required|useful)",
        r"(zarurat|jarurat|zaroorat) (nahi|nhi)", r"no interest", r"not interested", r"curious", r"just (wanted|asked) to know"]),
    "Wants only one service, not the full membership": ("Product", [
        r"only (golf|lounge|spa|salon|coffee|dining|club|railway|transfer|meet)", r"just (the )?(lounge|golf|spa)",
        r"single (service|visit|use)", r"one[- ]time", r"pay per (use|visit)", r"(lounge|golf) only", r"individual service",
        r"not (the )?(whole|full|entire) (membership|package|bundle)"]),
    "Location or coverage gap (city, airport, outlets)": ("Product", [
        r"not available", r"no (outlet|lounge|partner|club)s? (in|at|near)", r"coverage", r"nearby", r"in (his|her|their) city",
        r"(city|airport) (not|isn'?t) (covered|available)", r"tier[- ]?(2|3|two|three)", r"small (city|town)", r"location",
        r"(nahi|nhi) (hai|milta) (yaha|wahan)"]),
    "Trust concern / doesn't know DreamFolks": ("Marketing", [
        r"trust", r"fraud", r"scam", r"fake", r"never heard", r"doubt", r"genuine", r"legit", r"suspicious", r"bharosa",
        r"reviews?", r"(don'?t|doesn'?t) know (about )?dream ?folks"]),
    "Product not pitched fully or explained poorly": ("Agent", [
        r"not (pitched|explained|mentioned|covered)", r"did ?n[o']?t (pitch|explain|mention|cover|tell)", r"incomplete", r"partial(ly)?",
        r"half (pitch|explained)", r"benefits? (not|were not|weren'?t)", r"only (told|explained|mentioned) about", r"missed (to )?(pitch|explain|mention)",
        r"poor(ly)? explain", r"no clarity", r"confus(ed|ion|ing)", r"unclear"]),
    "Agent behaviour or selling skill": ("Agent", [
        r"rude", r"pushy", r"interrupt(ed|ing|s)?", r"tone", r"rushed", r"hurr(y|ied)", r"objection", r"did ?n[o']?t (handle|probe|listen|ask)",
        r"probing", r"no probing", r"(poor|bad|weak) (communication|pitch|handling|selling)", r"lack of (confidence|knowledge|probing)",
        r"not confident", r"argu(ed|ing|ment)", r"script", r"greeting", r"closing", r"unprofessional", r"wrong information"]),
    "No follow-up / callback missed": ("Agent", [
        r"follow[- ]?ups?", r"call ?back", r"no follow", r"did ?n[o']?t call (again|back)", r"never called", r"missed (the )?call",
        r"call (nahi|nhi) (aaya|kiya)", r"was not contacted"]),
    "Busy now / will decide later": ("Customer", [
        r"busy", r"later", r"baad me(in)?", r"think (about|over)", r"will (decide|let|confirm|check|see|think)", r"next (month|week|time|year)",
        r"driving", r"in a meeting", r"call (me )?later", r"not now", r"abhi (nahi|nhi)", r"sochke", r"soch ke"]),
    "Not the decision maker": ("Customer", [
        r"husband", r"wife", r"father", r"mother", r"son", r"daughter", r"boss", r"family", r"decision maker", r"discuss with",
        r"consult", r"ask (his|her|their)", r"(papa|pati|patni|ghar)"]),
    "Payment or technical problem": ("Product", [
        r"payment", r"(payment )?link", r"otp", r"upi", r"website", r"app", r"error", r"technical", r"transaction", r"failed", r"refund",
        r"login", r"glitch"]),
    "Language barrier": ("Other", [
        r"language", r"tamil", r"telugu", r"kannada", r"malayalam", r"bengali", r"marathi", r"gujarati", r"odia", r"punjabi",
        r"(only|could only|can only) (speak|understand)", r"did ?n[o']?t understand (hindi|english)", r"bhasha"]),
    "No real conversation / call dropped": ("Other", [
        r"disconnect(ed|s)?", r"call (drop|dropped|cut)", r"cut the call", r"hung up", r"hang up", r"no (response|conversation|answer)",
        r"not (reachable|responding|answering)", r"switched off", r"silent", r"voice ?mail", r"ringing", r"network", r"wrap ?time ?out",
        r"(could ?n[o']?t|can'?t) hear", r"blank call"]),
    "Showed interest, could be re-worked": ("Customer", [
        r"(showed|shows|was|is|seemed|seems|sounded) (some )?interest(ed)?", r"positive", r"re-?work", r"re-?target", r"can be (converted|closed|pitched)",
        r"(send|share|shared|sent) (the )?(details|link|brochure)", r"whatsapp", r"warm lead", r"hot lead", r"good (lead|prospect)",
        r"interested in", r"wants? to (buy|know more|purchase)", r"potential"]),
}
THEMES = list(RULES) + ["Other"]
SEGMENTS = ["Marketing", "Agent", "Product", "Customer", "Other"]
_COMPILED = {t: [re.compile(r"(?<!\w)" + p + r"(?!\w)", re.I) for p in pats] for t, (_, pats) in RULES.items()}

FIELDS = ["synopsis", "q1Why", "q3Why", "q12"]
ISSUE_KEYS = ["agent", "customer", "marketing", "product", "other"]
SECTION_SEGMENT = {"agent": "Agent", "customer": "Customer", "marketing": "Marketing", "product": "Product", "other": "Other"}


def configured():
    return True


def text_items(audits):
    """(audit_id, field, issue_label, section, text) for every non-empty free-text answer."""
    out = []
    for a in audits:
        ans = a["record"].get("answers") or {}
        for f in FIELDS:
            t = str(ans.get(f) or "").strip()
            if t:
                out.append((a["id"], f, "", None, t))
        for k in ISSUE_KEYS:
            x = (ans.get("issues") or {}).get(k) or {}
            t = str(x.get("comment") or "").strip()
            if t:
                out.append((a["id"], "issue:" + k, " ".join(str(x.get(n) or "") for n in ("l1", "l2")), k, t))
    return out


def text_hash(t):
    return hashlib.sha1((RULES_VERSION + "|" + t).encode("utf-8")).hexdigest()


def classify(text, issue_label="", section=None):
    """One comment -> (theme, segment). The auditor's issue choice (Level 1/2) counts as part of the text."""
    hay = f"{text} {issue_label}"
    best, best_n = "Other", 0
    for theme, pats in _COMPILED.items():
        n = sum(1 for p in pats if p.search(hay))
        if n > best_n:
            best, best_n = theme, n
    if best == "Other":
        return best, SECTION_SEGMENT.get(section, "Other")
    return best, RULES[best][0]


def run(db, audits, who, status, now_iso):
    """Tag every comment that is new or changed since the last run. Updates `status` as it goes."""
    existing = {(r["audit_id"], r["field"]): r["text_hash"] for r in db.run("SELECT audit_id, field, text_hash FROM ai_tags", fetch=True)}
    todo = [it for it in text_items(audits) if existing.get((it[0], it[1])) != text_hash(it[4])]
    status.update(total=len(todo), done=0, message=f"Categorising {len(todo):,} new or changed comments…" if todo else "Everything is already categorised.")
    for i, (aid, field, label, section, t) in enumerate(todo, 1):
        theme, seg = classify(t, label, section)
        db.run("DELETE FROM ai_tags WHERE audit_id=%s AND field=%s", (aid, field))
        db.run("INSERT INTO ai_tags (audit_id, field, text_hash, theme, segment, tagged_at) VALUES (%s,%s,%s,%s,%s,%s)",
               (aid, field, text_hash(t), theme, seg, now_iso()))
        if i % STEP == 0:
            status.update(done=i, message=f"Categorised {i:,} of {len(todo):,} comments…")
    status.update(state="done", done=len(todo), finishedAt=now_iso(), by=who, model=MODEL, failed=0,
                  message=f"Categorised {len(todo):,} comments." if todo else "Everything is already categorised.")

import unicodedata
from collections import Counter
from datetime import date

FIELDS = "id batch analyte sampled ran version".split()

def parse_date(text):
    text = unicodedata.normalize("NFKC", str(text or "")).strip()
    if not text: return None
    try: return date.fromisoformat(text)
    except ValueError: return "INVALID"

def parse_version(text):
    try: value = int(unicodedata.normalize("NFKC", str(text)).strip())
    except ValueError: return None
    return value if value >= 1 else None

def decide(rows, state):
    periods, known = state["periods"], state["known"]
    out, seen = [], set()
    for r in rows:
        d = {"line": r["line"], "id": r["id"], "batch": r["batch"], "analyte": r["analyte"], "version": r["version"],
             "sampled": r["sampled"], "ran": r["ran"], "identity": None, "home_period": None, "posted_period": None,
             "decision": None, "basis": "", "reason": ""}
        out.append(d)
        if not r["id"] or not r["batch"] or not r["analyte"]:
            d.update(decision="REJECTED", reason="ID_REQUIRED"); continue
        version = parse_version(r["version"])
        if version is None:
            d.update(decision="REJECTED", reason="VERSION_INVALID"); continue
        d["version"] = version
        ident = f'{r["batch"]}|{r["analyte"]}|{r["id"]}|{version}'
        d["identity"] = ident
        sampled = parse_date(r["sampled"])
        if sampled is None:
            d.update(decision="REJECTED", reason="SAMPLED_REQUIRED"); continue
        if sampled == "INVALID":
            d.update(decision="REJECTED", reason="SAMPLED_INVALID"); continue
        home = sampled.isoformat()[:7]
        d["home_period"] = home
        d["basis"] = f"采样{sampled.isoformat()}→归属{home}"
        ran = parse_date(r["ran"])
        if ran == "INVALID":
            d.update(decision="REJECTED", reason="RAN_INVALID"); continue
        if ran is not None and ran < sampled:
            d.update(decision="REJECTED", reason="RAN_BEFORE_SAMPLED"); continue
        if ident in seen:
            d.update(decision="DUPLICATE", reason="IN_FILE"); continue
        seen.add(ident)
        prior = known.get(ident)
        if prior and prior["state"] in ("posted", "supplement"):
            d.update(decision="DUPLICATE", reason="ALREADY_POSTED", posted_period=prior["posted_period"]); continue
        if ran is None:
            d.update(decision="PENDING", reason="AWAITING_RUN"); continue
        if periods.get(home, {}).get("state") == "sealed":
            target = next((p for p in sorted(periods) if p > home and periods[p]["state"] == "open"), None)
            if target is None:
                d.update(decision="REJECTED", reason="NO_OPEN_PERIOD"); continue
            d.update(decision="SUPPLEMENT", posted_period=target, basis=d["basis"]+f"；{home}已封账，补记至{target}")
        else:
            d.update(decision="POSTED", posted_period=home)
    return out

def balance(decisions, malformed, blanks):
    counts = Counter(d["decision"] for d in decisions)
    return {"input": len(decisions)+len(malformed)+blanks,
            "posted": counts.get("POSTED", 0), "supplement": counts.get("SUPPLEMENT", 0),
            "pending": counts.get("PENDING", 0), "duplicate": counts.get("DUPLICATE", 0),
            "rejected": counts.get("REJECTED", 0), "malformed": len(malformed), "blank": blanks}

import sqlite3, json, hashlib
from datetime import datetime, timezone
from app.config import DATA_DIR, RULE_VERSION
from app.errors import BusinessError

STATE = {"POSTED": "posted", "SUPPLEMENT": "supplement", "PENDING": "pending", "REJECTED": "rejected"}

def connect():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(DATA_DIR/"ledger.sqlite", timeout=15)
    db.row_factory = sqlite3.Row
    db.execute("CREATE TABLE IF NOT EXISTS periods (period TEXT PRIMARY KEY, state TEXT NOT NULL DEFAULT 'open', revision INTEGER NOT NULL DEFAULT 0, sealed_at TEXT)")
    db.execute("CREATE TABLE IF NOT EXISTS samples (identity TEXT PRIMARY KEY, batch TEXT NOT NULL, analyte TEXT NOT NULL, sid TEXT NOT NULL, version INTEGER NOT NULL, sampled TEXT, ran TEXT, home_period TEXT, state TEXT NOT NULL, posted_period TEXT, basis TEXT, reason TEXT, run_id TEXT, updated TEXT NOT NULL)")
    db.execute("CREATE TABLE IF NOT EXISTS posting_runs (id TEXT PRIMARY KEY, digest TEXT NOT NULL, result TEXT NOT NULL, created TEXT NOT NULL)")
    db.execute("CREATE TABLE IF NOT EXISTS reports (period TEXT NOT NULL, version INTEGER NOT NULL, digest TEXT NOT NULL, snapshot TEXT NOT NULL, created TEXT NOT NULL, PRIMARY KEY (period, version))")
    return db

def load():
    with connect() as db:
        periods = {r["period"]: dict(r) for r in db.execute("SELECT * FROM periods")}
        known = {r["identity"]: {"state": r["state"], "posted_period": r["posted_period"]} for r in db.execute("SELECT identity,state,posted_period FROM samples")}
    return {"periods": periods, "known": known}

def get_run(ident):
    with connect() as db:
        row = db.execute("SELECT * FROM posting_runs WHERE id=?", (ident,)).fetchone()
    if row is None: raise BusinessError("NOT_FOUND", "入账批次不存在", 404)
    item = dict(row); item["result"] = json.loads(item["result"])
    return item

def save_run(text, decisions, quarantine, balance):
    digest = hashlib.sha256((RULE_VERSION+"\n"+text).encode()).hexdigest()
    ident = digest[:16]
    now = datetime.now(timezone.utc).isoformat()
    payload = {"decisions": decisions, "quarantine": quarantine, "balance": balance, "rule_version": RULE_VERSION}
    with connect() as db:
        replayed = db.execute("INSERT OR IGNORE INTO posting_runs(id,digest,result,created) VALUES(?,?,?,?)", (ident, digest, json.dumps(payload, ensure_ascii=False), now)).rowcount == 0
        if not replayed:
            for d in decisions:
                state = STATE.get(d["decision"])
                if state is None: continue
                db.execute("""INSERT INTO samples(identity,batch,analyte,sid,version,sampled,ran,home_period,state,posted_period,basis,reason,run_id,updated)
                    VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    ON CONFLICT(identity) DO UPDATE SET sampled=excluded.sampled,ran=excluded.ran,home_period=excluded.home_period,state=excluded.state,posted_period=excluded.posted_period,basis=excluded.basis,reason=excluded.reason,run_id=excluded.run_id,updated=excluded.updated
                    WHERE samples.state IN ('pending','rejected')""",
                    (d["identity"], d["batch"], d["analyte"], d["id"], d["version"], d["sampled"], d["ran"], d["home_period"], state, d["posted_period"], d["basis"], d["reason"], ident, now))
            for p in {d["home_period"] for d in decisions if d["home_period"]} | {d["posted_period"] for d in decisions if d["posted_period"]}:
                db.execute("INSERT OR IGNORE INTO periods(period) VALUES(?)", (p,))
    rec = get_run(ident)
    return {"id": rec["id"], "digest": rec["digest"], "created": rec["created"], "replayed": replayed, **rec["result"]}

def snapshot(db, period, version, now, state):
    rows = [dict(r) for r in db.execute("SELECT identity,batch,analyte,sid,version,sampled,ran,home_period,posted_period,state,basis FROM samples WHERE posted_period=? ORDER BY batch,sid,analyte,version", (period,))]
    pending = [dict(r) for r in db.execute("SELECT identity,batch,analyte,sid,version,sampled,home_period,basis,reason FROM samples WHERE home_period=? AND state='pending' ORDER BY batch,sid", (period,))]
    counts = {
        "posted": sum(1 for r in rows if r["state"] == "posted"),
        "supplement_in": sum(1 for r in rows if r["state"] == "supplement"),
        "supplement_out": db.execute("SELECT COUNT(*) c FROM samples WHERE home_period=? AND state='supplement'", (period,)).fetchone()["c"],
        "pending": len(pending),
        "rejected": db.execute("SELECT COUNT(*) c FROM samples WHERE home_period=? AND state='rejected'", (period,)).fetchone()["c"],
    }
    snap = {"period": period, "version": version, "state": state, "rule_version": RULE_VERSION, "generated_at": now, "counts": counts, "rows": rows, "pending": pending}
    snap["digest"] = hashlib.sha256(json.dumps(snap, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    return snap

def report(period):
    with connect() as db:
        prow = db.execute("SELECT * FROM periods WHERE period=?", (period,)).fetchone()
        if prow is None: raise BusinessError("PERIOD_NOT_FOUND", "报告期不存在", 404)
        versions = [r["version"] for r in db.execute("SELECT version FROM reports WHERE period=? ORDER BY version", (period,))]
        if prow["state"] == "sealed":
            snap = json.loads(db.execute("SELECT snapshot FROM reports WHERE period=? ORDER BY version DESC LIMIT 1", (period,)).fetchone()["snapshot"])
        else:
            snap = snapshot(db, period, prow["revision"], datetime.now(timezone.utc).isoformat(), "open")
        snap["versions"] = versions
        snap["revision"] = prow["revision"]
        return snap

def seal(period, revision):
    now = datetime.now(timezone.utc).isoformat()
    with connect() as db:
        prow = db.execute("SELECT * FROM periods WHERE period=?", (period,)).fetchone()
        if prow is None: raise BusinessError("PERIOD_NOT_FOUND", "报告期不存在", 404)
        if prow["state"] != "open": raise BusinessError("PERIOD_SEALED", "报告期已封账，旧版报告保持有效", 409)
        rejected = db.execute("SELECT COUNT(*) c FROM samples WHERE home_period=? AND state='rejected'", (period,)).fetchone()["c"]
        if rejected: raise BusinessError("UNRESOLVED_REJECTED", f"存在 {rejected} 条未处置异常记录，不能封账", 409)
        changed = db.execute("UPDATE periods SET state='sealed',revision=revision+1,sealed_at=? WHERE period=? AND state='open' AND revision=?", (now, period, revision)).rowcount
        if not changed: raise BusinessError("SEAL_CONFLICT", "期间状态已变化，请刷新", 409)
        snap = snapshot(db, period, revision+1, now, "sealed")
        db.execute("INSERT INTO reports(period,version,digest,snapshot,created) VALUES(?,?,?,?,?)", (period, revision+1, snap["digest"], json.dumps(snap, ensure_ascii=False), now))
    return report(period)

def overview():
    with connect() as db:
        periods = [dict(r) for r in db.execute("SELECT * FROM periods ORDER BY period")]
        samples = [dict(r) for r in db.execute("SELECT home_period,posted_period,state FROM samples")]
        versions = {r["period"]: r["v"] for r in db.execute("SELECT period,MAX(version) v FROM reports GROUP BY period")}
        runs = [dict(r) for r in db.execute("SELECT id,created FROM posting_runs ORDER BY created DESC LIMIT 20")]
    for p in periods:
        pp = p["period"]
        p["posted"] = sum(1 for s in samples if s["posted_period"] == pp and s["state"] == "posted")
        p["supplement_in"] = sum(1 for s in samples if s["posted_period"] == pp and s["state"] == "supplement")
        p["supplement_out"] = sum(1 for s in samples if s["home_period"] == pp and s["state"] == "supplement")
        p["pending"] = sum(1 for s in samples if s["home_period"] == pp and s["state"] == "pending")
        p["rejected"] = sum(1 for s in samples if s["home_period"] == pp and s["state"] == "rejected")
        p["report_version"] = versions.get(pp)
    totals = {
        "open_periods": sum(1 for p in periods if p["state"] == "open"),
        "sealed_periods": sum(1 for p in periods if p["state"] == "sealed"),
        "samples": len(samples),
        "posted": sum(1 for s in samples if s["state"] == "posted"),
        "supplement": sum(1 for s in samples if s["state"] == "supplement"),
        "pending": sum(1 for s in samples if s["state"] == "pending"),
        "rejected": sum(1 for s in samples if s["state"] == "rejected"),
    }
    return {"periods": periods, "totals": totals, "runs": runs}

def reset():
    with connect() as db:
        for table in ("samples", "periods", "posting_runs", "reports"):
            db.execute(f"DELETE FROM {table}")

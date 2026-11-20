import csv,io,json

def evidence_csv(run):
    out=io.StringIO();writer=csv.writer(out)
    writer.writerow(["run_id","sha256","rule_version","kind","line","reason","evidence"])
    writer.writerow([run["id"],run["digest"],run["rule_version"],"manifest","","",json.dumps({"balance":run["result"]["balance"],"decision":run["decision"],"revision":run["revision"]},ensure_ascii=False)])
    for row in run["result"].get("final",[]):
        writer.writerow([run["id"],run["digest"],run["rule_version"],"result",row.get("line",""),row.get("status",""),json.dumps(row,ensure_ascii=False)])
    for row in run["result"].get("quarantine",[]):
        writer.writerow([run["id"],run["digest"],run["rule_version"],"quarantine",row.get("line",""),row["reason"],json.dumps(row,ensure_ascii=False)])
    return "\ufeff"+out.getvalue()

def posting_csv(run):
    result=run["result"];version=result.get("rule_version","")
    out=io.StringIO();writer=csv.writer(out)
    writer.writerow(["run_id","sha256","rule_version","kind","line","id","batch","analyte","version","sampled","ran","home_period","posted_period","decision","basis","reason","evidence"])
    writer.writerow([run["id"],run["digest"],version,"manifest","","","","","","","","","","","","",json.dumps(result["balance"],ensure_ascii=False)])
    for d in result["decisions"]:
        writer.writerow([run["id"],run["digest"],version,"decision",d["line"],d["id"],d["batch"],d["analyte"],d["version"],d["sampled"],d["ran"],d["home_period"] or "",d["posted_period"] or "",d["decision"],d["basis"],d["reason"],d["identity"] or ""])
    for q in result["quarantine"]:
        writer.writerow([run["id"],run["digest"],version,"quarantine",q["line"],"","","","","","","","","","",q["reason"],json.dumps(q,ensure_ascii=False)])
    return "\ufeff"+out.getvalue()

def period_csv(rep):
    out=io.StringIO();writer=csv.writer(out)
    writer.writerow(["period","report_version","state","kind","identity","batch","analyte","id","version","sampled","ran","home_period","posted_period","basis","reason","evidence"])
    writer.writerow([rep["period"],rep["version"],rep["state"],"manifest","","","","","","","","","","","",json.dumps({"counts":rep["counts"],"digest":rep["digest"],"versions":rep["versions"]},ensure_ascii=False)])
    for r in rep["rows"]:
        writer.writerow([rep["period"],rep["version"],rep["state"],"supplement_in" if r["state"]=="supplement" else "posted",r["identity"],r["batch"],r["analyte"],r["sid"],r["version"],r["sampled"],r["ran"],r["home_period"],r["posted_period"],r["basis"],"",""])
    for r in rep["pending"]:
        writer.writerow([rep["period"],rep["version"],rep["state"],"pending_out",r["identity"],r["batch"],r["analyte"],r["sid"],r["version"],r["sampled"],"",r["home_period"],"",r["basis"],r["reason"],""])
    return "\ufeff"+out.getvalue()

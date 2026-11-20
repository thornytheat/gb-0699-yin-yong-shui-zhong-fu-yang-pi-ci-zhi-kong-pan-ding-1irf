# TRAP-27 上机跨月归属漂移 / TRAP-28 回填封账月 / TRAP-29 重跑重复入账 / TRAP-30 封账并发与异常
import pytest
from fastapi.testclient import TestClient
from app.main import app
from app import ledger
from app.errors import BusinessError
from app.exporter import posting_csv, period_csv
from app.modules.m8_posting.service import execute, sample_text
from app.modules.m8_posting.rules import decide, balance

client = TestClient(app, raise_server_exceptions=False)

@pytest.fixture(autouse=True)
def clean_ledger():
    ledger.reset()
    yield
    ledger.reset()

def csv(*rows):
    return "id,batch,analyte,sampled,ran,version\n" + "\n".join(rows)

def test_attribution_follows_sampled_not_ran():
    result = execute(csv("S1,B10,Pb,2026-10-31,2026-11-02,1"))
    d = result["decisions"][0]
    assert d["decision"] == "POSTED" and d["home_period"] == "2026-10" and d["posted_period"] == "2026-10"
    assert "2026-10-31" in d["basis"] and "2026-10" in d["basis"]

def test_balance_reconciles():
    result = execute(sample_text())
    b = result["balance"]
    assert b["input"] == b["posted"]+b["supplement"]+b["pending"]+b["duplicate"]+b["rejected"]+b["malformed"]+b["blank"]
    assert (b["posted"], b["pending"], b["rejected"], b["duplicate"]) == (6, 1, 2, 1)

def test_each_sample_lands_in_exactly_one_period():
    execute(csv("S1,B10,Pb,2026-10-31,2026-10-31,1", "S2,B10,Pb,2026-10-31,2026-11-02,1", "S3,B11,Pb,2026-11-03,2026-11-03,1"))
    execute(csv("S4,B10,Pb,2026-10-30,2026-11-05,1", "S5,B11,Pb,2026-11-04,2026-11-04,1"))
    ledger.seal("2026-10", 0)
    execute(csv("S6,B10,Pb,2026-10-29,2026-11-06,1"))
    with ledger.connect() as db:
        rows = db.execute("SELECT identity,posted_period FROM samples WHERE state IN ('posted','supplement')").fetchall()
        assert len(rows) == len({r["identity"] for r in rows})
        total = db.execute("SELECT COUNT(*) c FROM samples").fetchone()["c"]
        by_state = {r["state"]: r["c"] for r in db.execute("SELECT state,COUNT(*) c FROM samples GROUP BY state")}
        assert total == sum(by_state.values()) == 6

def test_late_sample_supplements_forward_and_sealed_report_untouched():
    execute(csv("S1,B10,Pb,2026-10-31,2026-10-31,1", "S2,B11,Pb,2026-11-02,2026-11-02,1"))
    sealed = ledger.seal("2026-10", 0)
    assert sealed["state"] == "sealed" and sealed["version"] == 1
    result = execute(csv("S3,B10,Pb,2026-10-31,2026-11-03,1", "S4,B11,Pb,2026-11-03,2026-11-03,1"))
    late = next(d for d in result["decisions"] if d["id"] == "S3")
    assert late["decision"] == "SUPPLEMENT" and late["home_period"] == "2026-10" and late["posted_period"] == "2026-11"
    assert "已封账" in late["basis"] and "2026-11" in late["basis"]
    after = ledger.report("2026-10")
    assert after["digest"] == sealed["digest"] and after["versions"] == [1]
    november = ledger.report("2026-11")
    assert november["counts"]["supplement_in"] == 1 and november["counts"]["posted"] == 2

def test_supplement_never_backfills_and_needs_open_period():
    execute(csv("S1,B10,Pb,2026-10-31,2026-10-31,1"))
    ledger.seal("2026-10", 0)
    result = execute(csv("S2,B10,Pb,2026-10-30,2026-11-01,1"))
    d = result["decisions"][0]
    assert d["decision"] == "REJECTED" and d["reason"] == "NO_OPEN_PERIOD" and d["posted_period"] is None

def test_seal_failure_keeps_old_report():
    execute(csv("S1,B10,Pb,2026-10-31,2026-10-31,1", "S2,B11,Pb,2026-11-02,2026-11-02,1"))
    sealed = ledger.seal("2026-10", 0)
    with pytest.raises(BusinessError, match="已封账"):
        ledger.seal("2026-10", 1)
    assert ledger.report("2026-10")["digest"] == sealed["digest"]
    with pytest.raises(BusinessError, match="已变化"):
        ledger.seal("2026-11", 5)
    draft = ledger.report("2026-11")
    assert draft["state"] == "open" and draft["versions"] == []

def test_seal_blocked_by_unresolved_rejected_then_fixed():
    execute(csv("S1,B10,Pb,2026-10-31,bad-date,1"))
    with pytest.raises(BusinessError, match="未处置"):
        ledger.seal("2026-10", 0)
    assert ledger.report("2026-10")["versions"] == []
    execute(csv("S1,B10,Pb,2026-10-31,2026-10-31,1"))
    assert ledger.seal("2026-10", 0)["version"] == 1

def test_pending_sample_does_not_block_sealing():
    execute(csv("S1,B10,Pb,2026-10-31,,1"))
    sealed = ledger.seal("2026-10", 0)
    assert sealed["counts"]["pending"] == 1 and sealed["pending"][0]["reason"] == "AWAITING_RUN"

def test_pending_later_posts_into_open_period():
    execute(csv("S1,B10,Pb,2026-10-31,,1"))
    ledger.seal("2026-10", 0)
    execute(csv("S2,B11,Pb,2026-11-02,2026-11-02,1"))
    result = execute(csv("S1,B10,Pb,2026-10-31,2026-11-03,1"))
    d = result["decisions"][0]
    assert d["decision"] == "SUPPLEMENT" and d["posted_period"] == "2026-11"
    with ledger.connect() as db:
        assert db.execute("SELECT COUNT(*) c FROM samples WHERE identity='B10|Pb|S1|1'").fetchone()["c"] == 1

def test_rerun_same_batch_adds_no_records():
    text = sample_text()
    first, second = execute(text), execute(text)
    assert first["id"] == second["id"] and second["replayed"] is True
    overview = ledger.overview()
    assert overview["totals"]["samples"] == 9
    assert len(overview["runs"]) == 1

def test_duplicate_in_file_and_across_files():
    row = "S1,B10,Pb,2026-10-31,2026-10-31,1"
    result = execute(csv(row, row))
    assert [d["decision"] for d in result["decisions"]] == ["POSTED", "DUPLICATE"]
    again = execute(csv("S2,B10,Pb,2026-10-30,2026-10-30,1", row))
    dup = next(d for d in again["decisions"] if d["id"] == "S1")
    assert dup["decision"] == "DUPLICATE" and dup["reason"] == "ALREADY_POSTED" and dup["posted_period"] == "2026-10"

def test_unposted_reasons_are_explicit():
    result = execute(csv(
        "S1,B10,Pb,,2026-10-31,1",
        "S2,B10,Pb,2026-10-32,2026-10-31,1",
        "S3,B10,Pb,2026-10-31,bad,1",
        "S4,B10,Pb,2026-10-31,2026-10-30,1",
        "S5,B10,Pb,2026-10-31,,0",
        ",B10,Pb,2026-10-31,2026-10-31,1",
        "S6,B10,Pb,2026-10-31,,1",
    ))
    reasons = {d["id"]: d["reason"] for d in result["decisions"]}
    assert reasons["S1"] == "SAMPLED_REQUIRED" and reasons["S2"] == "SAMPLED_INVALID"
    assert reasons["S3"] == "RAN_INVALID" and reasons["S4"] == "RAN_BEFORE_SAMPLED"
    assert reasons["S5"] == "VERSION_INVALID" and reasons[""] == "ID_REQUIRED"
    assert reasons["S6"] == "AWAITING_RUN"
    assert not any(d["decision"] == "POSTED" for d in result["decisions"])

def test_export_shows_basis_and_reason_per_sample():
    run = ledger.get_run(execute(sample_text())["id"])
    text = posting_csv(run)
    assert "basis" in text and "reason" in text and "AWAITING_RUN" in text and "SAMPLED_INVALID" in text
    assert "采样2026-10-31→归属2026-10" in text and run["digest"] in text

def test_period_export_carries_supplement_evidence():
    execute(csv("S1,B10,Pb,2026-10-31,2026-10-31,1", "S2,B11,Pb,2026-11-02,2026-11-02,1"))
    ledger.seal("2026-10", 0)
    execute(csv("S3,B10,Pb,2026-10-31,2026-11-03,1"))
    text = period_csv(ledger.report("2026-11"))
    assert "supplement_in" in text and "2026-10已封账，补记至2026-11" in text

def test_api_posting_flow_and_guards():
    assert client.post("/api/8", json=[]).status_code == 422
    assert client.post("/api/8", json={"text": 1}).status_code == 422
    run = client.post("/api/8", json={"text": csv("S1,B10,Pb,2026-10-31,2026-10-31,1")}).json()
    assert client.get("/api/8/runs/"+run["id"]).status_code == 200
    assert client.get("/api/8/runs/none").status_code == 404
    assert client.post("/api/8/periods/2026-10/seal", json={"revision": "0"}).status_code == 422
    assert client.post("/api/8/periods/2099-01/seal", json={"revision": 0}).status_code == 404
    assert client.post("/api/8/periods/2026-10/seal", json={"revision": 0}).json()["state"] == "sealed"
    assert client.post("/api/8/periods/2026-10/seal", json={"revision": 1}).status_code == 409
    assert client.get("/api/8/periods/2026-10/report").json()["version"] == 1
    assert client.get("/api/8/periods/2026-10/export").status_code == 200
    assert client.get("/api/8/export/"+run["id"]).status_code == 200
    page = client.get("/module/8?run_id="+run["id"])
    assert page.status_code == 200 and "归属依据" in page.text and "未入账原因" in page.text
    assert client.get("/module/9").status_code == 404

def test_overview_counts_by_period():
    execute(sample_text())
    overview = client.get("/api/8").json()
    october = next(p for p in overview["periods"] if p["period"] == "2026-10")
    assert october["posted"] == 2 and october["pending"] == 1 and october["rejected"] == 1
    assert overview["totals"]["samples"] == 9

def test_decide_is_pure_and_deterministic():
    rows = [{"line": 2, "id": "S1", "batch": "B10", "analyte": "Pb", "sampled": "2026-10-31", "ran": "2026-11-02", "version": "1"}]
    state = {"periods": {}, "known": {}}
    assert decide(rows, state) == decide(rows, state)
    assert balance(decide(rows, state), [], 0)["posted"] == 1

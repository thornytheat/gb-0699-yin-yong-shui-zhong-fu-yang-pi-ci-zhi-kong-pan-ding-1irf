from pathlib import Path
from app.reader import read_rows
from app import ledger
from app.modules.m8_posting import rules

def sample_text():
    return (Path(__file__).parent.parent.parent.parent/"sample_data"/"posting.csv").read_text(encoding="utf-8-sig")

def execute(text):
    rows, bad, blanks = read_rows(text, rules.FIELDS)
    decisions = rules.decide(rows, ledger.load())
    quarantine = [{"line": b["line"], "reason": b["reason"], "raw": b["raw"]} for b in bad]
    return ledger.save_run(text, decisions, quarantine, rules.balance(decisions, bad, blanks))

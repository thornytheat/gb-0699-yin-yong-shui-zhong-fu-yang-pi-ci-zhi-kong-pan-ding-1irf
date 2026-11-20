from fastapi import APIRouter, Body
from fastapi.responses import Response
from app.errors import BusinessError, object_payload
from app.modules.m8_posting.service import execute, sample_text
from app import ledger
from app.exporter import posting_csv, period_csv

router = APIRouter()

@router.post("/api/8")
def calculate(payload: object = Body(default=None)):
    payload = object_payload(payload)
    text = payload.get("text")
    if text is None: text = sample_text()
    if not isinstance(text, str): raise BusinessError("TEXT", "输入须为文本")
    return execute(text)

@router.get("/api/8")
def overview():
    return ledger.overview()

@router.get("/api/8/sample")
def sample():
    return {"text": sample_text()}

@router.get("/api/8/runs/{ident}")
def run_detail(ident: str):
    rec = ledger.get_run(ident)
    return {"id": rec["id"], "digest": rec["digest"], "created": rec["created"], **rec["result"]}

@router.get("/api/8/periods/{period}/report")
def period_report(period: str):
    return ledger.report(period)

@router.post("/api/8/periods/{period}/seal")
def seal(period: str, payload: object = Body(...)):
    payload = object_payload(payload)
    if type(payload.get("revision")) is not int: raise BusinessError("REVISION", "版本须为整数")
    return ledger.seal(period, payload["revision"])

@router.get("/api/8/export/{ident}")
def export_run(ident: str):
    return Response(posting_csv(ledger.get_run(ident)), media_type="text/csv", headers={"Content-Disposition": "attachment; filename=posting-evidence.csv"})

@router.get("/api/8/periods/{period}/export")
def export_period(period: str):
    return Response(period_csv(ledger.report(period)), media_type="text/csv", headers={"Content-Disposition": "attachment; filename=period-report.csv"})

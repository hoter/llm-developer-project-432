"""Взгляд в движок: состояние процесса и его результат.

Наружу клиент читает статус из базы (GET /jobs/{id}) — это предметное
состояние. Здесь — внутренняя кухня Temporal: run_status (RUNNING, COMPLETED,
FAILED) и значение query current_status. Полная история шагов видна в UI:
http://localhost:8233
"""
from fastapi import APIRouter, HTTPException
from temporalio.service import RPCError

from app.temporal.client import get_client

router = APIRouter(tags=["workflows"])


@router.get("/workflows/{wf_id}")
async def workflow_status(wf_id: str):
    client = await get_client()
    handle = client.get_workflow_handle(wf_id)
    try:
        desc = await handle.describe()
    except RPCError:
        raise HTTPException(404, "workflow not found")

    try:
        status_query = await handle.query("current_status")
    except RPCError:
        # Воркер не запущен: process state в движке есть, ответить на query некому.
        status_query = None

    return {
        "id": wf_id,
        "run_status": getattr(desc.status, "name", None) or str(desc.status),
        "status": status_query,
    }


@router.get("/workflows/{wf_id}/result")
async def workflow_result(wf_id: str):
    client = await get_client()
    handle = client.get_workflow_handle(wf_id)
    try:
        result = await handle.result()
    except RPCError as exc:
        raise HTTPException(409, f"not finished: {exc.message}")
    return {"id": wf_id, "result": result}

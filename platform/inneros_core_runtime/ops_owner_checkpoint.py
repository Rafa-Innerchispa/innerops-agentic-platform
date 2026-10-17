"""Entrega durable de checkpoint al owner (ChatGPT + WhatsApp).

ACK de inbox ≠ DONE de ops: los mensajes marcan fase de ejecución y evidencia
parcial; solo estados terminales certificados implican cierre.
"""

from __future__ import annotations

import os
import socket
from typing import Any

TERMINAL = frozenset({"completed", "failed", "blocked", "partial", "cancelled", "superseded"})
NOTIFY_CHECKPOINT = os.getenv("NOTIFY_OPS_OWNER_CHECKPOINT", "1") == "1"


def _host() -> str:
    return socket.gethostname().lower()


def _pid() -> int:
    return os.getpid()


def _format_body(
    task: dict[str, Any],
    *,
    phase: str,
    evidence: dict[str, Any],
    notes: str,
) -> str:
    tid = str(task.get("task_id") or "?")
    corr = str(task.get("correlation_id") or "")
    lane = str(task.get("execution_lane") or "")
    provider = str(task.get("preferred_provider") or task.get("assignee") or "")
    title = str(task.get("title") or "")[:200]
    sha = str(evidence.get("commit_sha") or evidence.get("sha") or "")[:40]
    tests = evidence.get("test_results") if isinstance(evidence.get("test_results"), dict) else {}
    test_exit = tests.get("exit_code")
    terminal = phase in TERMINAL
    ack_line = (
        "Estado terminal certificado por Temporal (no confundir con ACK de entrega)."
        if terminal
        else "Checkpoint de ejecución — ACK de entrega NO es DONE; la tarea sigue en carril Temporal."
    )
    lines = [
        f"task_id: {tid}",
        f"phase: {phase}",
        f"host: {_host()}",
        f"pid: {_pid()}",
        f"provider: {provider}",
        f"lane: {lane}",
        f"correlation_id: {corr}" if corr else "",
        f"title: {title}" if title else "",
        f"commit_sha: {sha}" if sha else "",
        f"tests.exit_code: {test_exit}" if test_exit is not None else "",
        ack_line,
    ]
    if notes.strip():
        lines.append(f"notes: {notes.strip()[:1200]}")
    if evidence.get("error"):
        lines.append(f"error: {str(evidence.get('error'))[:400]}")
    if evidence.get("mail_id"):
        lines.append(f"mail_id: {evidence.get('mail_id')}")
    return "\n".join(line for line in lines if line)


def publish_ops_owner_checkpoint(
    task: dict[str, Any],
    *,
    phase: str,
    evidence: dict[str, Any] | None = None,
    actor: str = "inneros",
    notes: str = "",
) -> dict[str, Any]:
    """Persist checkpoint for ChatGPT inbox and optional WhatsApp alert."""
    if not NOTIFY_CHECKPOINT:
        return {"ok": False, "skipped": "NOTIFY_OPS_OWNER_CHECKPOINT=0"}

    tid = str(task.get("task_id") or "").strip()
    if not tid:
        return {"ok": False, "error": "task_id_required"}

    status = str(phase or task.get("status") or "").strip().lower()
    ev = dict(evidence or {})
    body = _format_body(task, phase=status, evidence=ev, notes=notes)
    subject = f"[CHECKPOINT] {tid} · {status.upper()}"
    revision = int(task.get("revision") or 0)
    idempotency_key = f"owner_checkpoint:{tid}:{status}:r{revision}"

    from inneros_core_runtime import durable_coordination_spine as spine

    chatgpt = spine.create_durable_message(
        task_id=tid,
        workflow_id=str(task.get("workflow_id") or f"ops_task:{tid}"),
        run_id=str(ev.get("run_id") or task.get("temporal_run_id") or ""),
        correlation_id=str(task.get("correlation_id") or ""),
        sender=str(actor or "inneros").strip().lower(),
        recipient="chatgpt",
        subject=subject,
        content=body,
        metadata={
            "checkpoint": True,
            "execution_phase": status,
            "terminal": status in TERMINAL,
            "host": _host(),
            "pid": _pid(),
            "evidence_summary": {
                k: ev.get(k)
                for k in (
                    "commit_sha",
                    "mail_id",
                    "document_type",
                    "route_agent",
                    "test_results",
                    "error",
                )
                if k in ev
            },
        },
        idempotency_key=idempotency_key,
    )

    whatsapp: dict[str, Any] = {"ok": False, "skipped": "not_terminal_or_verification"}
    if status in TERMINAL or status == "verification":
        try:
            from inneros_core_runtime.notifications.ops_task_alerts import notify_ops_transition

            whatsapp = notify_ops_transition(
                {**task, "status": status},
                previous_status=str(task.get("_previous_status") or ""),
                actor=actor,
                evidence=ev,
            )
        except Exception as exc:
            whatsapp = {"ok": False, "error": str(exc)[:180]}

    ok = bool(chatgpt.get("ok")) or bool(chatgpt.get("duplicate"))
    return {
        "ok": ok,
        "task_id": tid,
        "phase": status,
        "chatgpt_message": chatgpt,
        "whatsapp": whatsapp,
        "idempotency_key": idempotency_key,
    }

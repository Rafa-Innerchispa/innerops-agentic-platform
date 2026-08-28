"""Unified WhatsApp entrypoint for executable Codex jobs and MCP coordination tasks.

Only explicit user requests naming an allowlisted agent are routed.  The parser
accepts the original compact syntax and a small, deterministic Spanish natural
language grammar; it never delegates interpretation to OCR, vision or an LLM.
"""
from __future__ import annotations
import hashlib, re
from typing import Any
from raphiia_openai import codex_whatsapp_jobs, coordination_live

TARGET_RE = re.compile(
    r"^(codex|cursor|antigravity|gemini|vscode)(?:\s*\[([a-z0-9_-]+)\]|\s+([a-z0-9_-]+))?\s*:\s*(.+)$",
    re.I | re.S,
)
TARGET_MAP = {"vscode":"cursor","codex":"codex","cursor":"cursor","antigravity":"antigravity","gemini":"gemini"}
_AGENT = r"codex|cursor|antigravity|gemini|vscode(?:\s+code)?|visual\s+studio\s+code"
_LEADING_ASSISTANT_RE = re.compile(r"^\s*(?:@?ralf(?:i|y)?ia)\s*[,;:\-]?\s*", re.I)
_NATURAL_PATTERNS = (
    re.compile(rf"^(?:por\s+favor\s+)?(?:p[ií]dele|dile|enc[aá]rgale)\s+a\s+({_AGENT})\s+(?:que\s+)?(.+)$", re.I | re.S),
    re.compile(rf"^(?:por\s+favor\s+)?(?:quiero|necesito)\s+que\s+({_AGENT})\s+(.+)$", re.I | re.S),
    re.compile(rf"^(?:por\s+favor\s+)?(?:usa|utiliza|trabaja\s+con)\s+({_AGENT})\s+(?:para\s+)?(.+)$", re.I | re.S),
    re.compile(rf"^({_AGENT})\s*[,;:\-]\s*(.+)$", re.I | re.S),
    re.compile(rf"^(?:haz|realiza|ejecuta)\s+(.+?)\s+con\s+({_AGENT})\s*$", re.I | re.S),
)
_PROJECT_ALIASES = (
    (re.compile(r"\b(?:quoteops|cotizaciones?|cotizaci[oó]n)\b", re.I), "quoteops"),
    (re.compile(r"\b(?:raphiia[- ]openai|ralf(?:i|y)?ia[- ]mcp|proyecto\s+(?:de\s+)?mcp)\b", re.I), "openai"),
)


def _canonical_agent(value: str) -> str:
    compact = re.sub(r"\s+", " ", value.strip().lower())
    return {"vscode code": "vscode", "visual studio code": "vscode"}.get(compact, compact)


def _infer_project(agent: str, prompt: str) -> str | None:
    if agent != "codex":
        return None
    return next((project for pattern, project in _PROJECT_ALIASES if pattern.search(prompt)), None)

def parse_request(message: str) -> tuple[str, str | None, str] | None:
    text = _LEADING_ASSISTANT_RE.sub("", (message or "").strip(), count=1)
    match = TARGET_RE.fullmatch(text)
    if match:
        requested = _canonical_agent(match.group(1))
        project = (match.group(2) or match.group(3) or "").lower() or None
        prompt = match.group(4).strip()
        return (requested, project, prompt) if prompt else None
    for index, pattern in enumerate(_NATURAL_PATTERNS):
        natural = pattern.fullmatch(text)
        if not natural:
            continue
        if index == len(_NATURAL_PATTERNS) - 1:
            prompt, raw_agent = natural.group(1), natural.group(2)
        else:
            raw_agent, prompt = natural.group(1), natural.group(2)
        requested = _canonical_agent(raw_agent)
        prompt = prompt.strip(" \t\r\n:,-")
        if len(prompt) < 4:
            return None
        return requested, _infer_project(requested, prompt), prompt
    return None

def route_request(message: str, sender: str, *, node: str="primary", trace: dict[str, Any]|None=None) -> dict[str, Any] | None:
    parsed=parse_request(message)
    if not parsed: return None
    requested,project,prompt=parsed; assignee=TARGET_MAP[requested]; trace=trace or {}
    if project and assignee!="codex": return {"ok":False,"route":"coordination_mcp","error":"project_selector_only_supported_for_codex"}
    if assignee=="codex":
        return {**codex_whatsapp_jobs.request_job(sender,prompt,target=project or "openai",node=node,trace=trace),"route":"codex_runner"}
    digest=hashlib.sha256(f"{sender}\n{requested}\n{prompt}".encode()).hexdigest()[:12]
    cid=str(trace.get("correlation_id") or f"whatsapp-{requested}-{digest}")
    task=coordination_live.create_ops_task(assignee=assignee,title=prompt[:160],checklist=[prompt],evidence_required=["PASS/PARTIAL/FAIL","resumen de cambios y pruebas"],priority="normal",from_agent="RAFAEL",correlation_id=cid,source_message_id=trace.get("message_id"),conversation_ref=str(trace.get("conversation_ref") or f"whatsapp:{sender[-6:]}"),related_project=str(trace.get("related_project") or "raphiia-openai"))
    if not task.get("ok"): return {"ok":False,"route":"coordination_mcp","error":task.get("error")}
    return {"ok":True,"route":"coordination_mcp","target":requested,"task_id":task.get("task_id"),"correlation_id":task.get("correlation_id"),"text":f"Tarea enviada a {requested}: {task.get('task_id')}. Quedó registrada en Coordinación MCP."}

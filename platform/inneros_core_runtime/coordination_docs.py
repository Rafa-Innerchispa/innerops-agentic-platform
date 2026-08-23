"""Lectura segura de documentación ai_coordination para MCP ChatGPT."""

from __future__ import annotations

import re
import textwrap
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from raphiia_openai.settings import COL_AGENT_MESSAGES

COORD_ROOT = Path("/home/rlopez/data/ai_coordination")

ALLOWED_EXTENSIONS = {".md", ".txt", ".json", ".yaml", ".yml", ".log"}
ALLOWED_PREFIXES = (
    "HUB/",
    "hub/",
    "LOG/",
    "log/",
    "cursor/",
    "codex/",
    "antigravity/",
    "notion/",
    "chatgpt/",
    "gemini/",
    "rafael/",
)
ALWAYS_ALLOWED = {
    "MAPA_CENTRAL.md",
    "TASKS.md",
    "DECISIONES.md",
    "OPEN_QUESTIONS.md",
    "ESTADO_ACTUAL.md",
    "PROJECTS_REGISTRY.md",
    "PORTS_CANONICAL.md",
    "MONGO_SCHEMA.md",
    "00_LEER_PRIMERO.md",
    "PROTOCOLO_LECTURA.md",
    "PROTOCOLO_ORQUESTACION.md",
    "SESSION_LOG.md",
    "CHATGPT_MCP.md",
    "HUB/ESTADO_VIVO.md",
    "HUB/RUNBOOK_COTIZACION_WHATSAPP.md",
    "PROTOCOLO_COMUNICACION_IAS_2026-07-11.md",
    "EDITORIAL_SOCIAL_FLOW.md",
    "ESPECIALIDADES_AGENTES.md",
    "ECOSISTEMA_COMPLETO.md",
    "MEMORIA_PERSISTENTE.md",
    "CHATS_Y_MEMORIA.md",
    "AUTOMACION_COORDINACION.md",
    "AG-25_ORCHESTRATOR_SPEC.md",
}
BLOCKED_NAMES = {
    ".env",
    ".env.example",
    "credentials.json",
    "secrets.json",
    "token.json",
    "tokens.json",
}
SECRET_PATTERN = re.compile(
    r"(api[_-]?key|secret|token|password|private[_-]?key|access[_-]?token|refresh[_-]?token|client[_-]?secret|mongo[_-]?uri|database[_-]?url)\s*[:=]",
    re.I,
)
TAG_PATTERN = re.compile(r"(?i)^(#+\s+)?(pendiente|idea(s)?|próximo|proximo|instruction(es)?|instrucción(es)?)\b")
WORKSPACE_SUBDIRS = ("notes", "ideas", "drafts", "handoff", "memory", "logs")
MAILBOX_AGENTS = ("cursor", "codex", "antigravity", "gemini", "chatgpt", "notion")
CHATGPT_ALIAS = "ChatGPT"


def _now_iso(path: Path) -> str:
    return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat()


def _safe_relative(relative_path: str) -> str:
    rel = (relative_path or "").strip().lstrip("/")
    if rel:
        parts = rel.split("/")
        first = parts[0].lower()
        if first in {"hub", "log"}:
            parts[0] = first.upper()
        elif first in {"cursor", "codex", "antigravity", "gemini", "chatgpt", "notion", "rafael"}:
            parts[0] = first
        rel = "/".join(parts)
    return rel or "MAPA_CENTRAL.md"


def _resolve(relative_path: str) -> Path:
    rel = _safe_relative(relative_path)
    parts = Path(rel).parts
    if ".." in parts:
        raise ValueError("path traversal not allowed")

    name = Path(rel).name
    if name in BLOCKED_NAMES or name.startswith("."):
        raise ValueError(f"file not allowed: {name}")

    suffix = Path(rel).suffix.lower()
    if suffix and suffix not in ALLOWED_EXTENSIONS:
        raise ValueError(f"extension not allowed: {suffix}")

    if rel not in ALWAYS_ALLOWED:
        if not any(rel == prefix.rstrip("/") or rel.startswith(prefix) for prefix in ALLOWED_PREFIXES):
            raise ValueError(f"path not in allowlist: {rel}")

    full = (COORD_ROOT / rel).resolve()
    if COORD_ROOT.resolve() not in full.parents and full != COORD_ROOT.resolve():
        raise ValueError("path outside coordination root")
    return full


def _scrub(text: str) -> str:
    lines: list[str] = []
    for line in text.splitlines():
        if SECRET_PATTERN.search(line):
            lines.append("[REDACTED]")
        else:
            lines.append(line)
    return "\n".join(lines)


def _entry_meta(path: Path) -> dict[str, Any]:
    stat = path.stat()
    rel = str(path.relative_to(COORD_ROOT))
    entry_type = "directory" if path.is_dir() else "file"
    return {
        "path": rel,
        "name": path.name,
        "type": entry_type,
        "size": None if path.is_dir() else stat.st_size,
        "modified_at": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
    }


def _iter_allowed_entries() -> list[Path]:
    entries: list[Path] = []
    if not COORD_ROOT.exists():
        return entries
    for path in sorted(COORD_ROOT.rglob("*")):
        if path.is_dir():
            rel = str(path.relative_to(COORD_ROOT))
            if rel == ".":
                continue
            try:
                _resolve(rel)
            except ValueError:
                continue
            entries.append(path)
            continue
        suffix = path.suffix.lower()
        if suffix and suffix not in ALLOWED_EXTENSIONS:
            continue
        rel = str(path.relative_to(COORD_ROOT))
        try:
            _resolve(rel)
        except ValueError:
            continue
        entries.append(path)
    return entries


def _ensure_workspace() -> Path:
    chatgpt = COORD_ROOT / "chatgpt"
    legacy = COORD_ROOT / CHATGPT_ALIAS
    for sub in ("", "notes", "ideas", "drafts", "handoff", "memory", "logs", "journal"):
        (chatgpt / sub).mkdir(parents=True, exist_ok=True)
        (legacy / sub).mkdir(parents=True, exist_ok=True)
    for filename, title in (
        ("README.md", "ChatGPT workspace"),
        ("INSTRUCTIONS.md", "ChatGPT instructions"),
        ("INBOX.md", "ChatGPT inbox"),
        ("OUTBOX.md", "ChatGPT outbox"),
    ):
        for base in (chatgpt, legacy):
            p = base / filename
            if not p.exists():
                p.write_text(f"# {title}\n\n", encoding="utf-8")
    return chatgpt


def _canonical_mailbox_map() -> dict[str, Any]:
    return {
        "root": str(COORD_ROOT),
        "primary_agent_dirs": {
            "chatgpt": "chatgpt/",
            "codex": "codex/",
            "cursor": "cursor/",
            "antigravity": "antigravity/",
            "gemini": "gemini/",
            "notion": "notion/",
            "rafael": "rafael/",
        },
        "chatgpt_canonical_inbox": "chatgpt/INBOX.md",
        "chatgpt_canonical_outbox": "chatgpt/OUTBOX.md",
        "chatgpt_alias_mirror": "ChatGPT/INBOX.md and ChatGPT/OUTBOX.md",
        "message_source_of_truth": "Mongo ralfia_agent_messages + canonical Markdown inbox",
        "desync_policy": "If file and Mongo diverge, treat Mongo as delivery truth and resync the Markdown inbox immediately.",
    }


def _fresh_chat_sequence() -> list[str]:
    return [
        "1. bootstrap_context()",
        "2. get_project_map()",
        "3. get_chatgpt_workspace()",
        "4. read_coordination_file('00_LEER_PRIMERO.md')",
        "5. read_coordination_file('PROTOCOLO_LECTURA.md')",
        "6. read_coordination_file('PROTOCOLO_ORQUESTACION.md')",
        "7. get_agent_mailboxes(agent='chatgpt')",
        "8. get_agent_mailboxes(agent='codex') / cursor / antigravity as needed",
        "9. Search Mongo coordination log only for the exact thread or project.",
    ]


def _coordination_protocol() -> dict[str, Any]:
    return {
        "root": str(COORD_ROOT),
        "reading_order": [
            "HUB/ESTADO_VIVO.md",
            "00_LEER_PRIMERO.md",
            "PROTOCOLO_COMUNICACION_IAS_2026-07-11.md",
            "MAPA_CENTRAL.md",
            "PROJECTS_REGISTRY.md",
            "Agent mailbox INBOX/OUTBOX",
        ],
        "canonical_mailboxes": _canonical_mailbox_map(),
        "fresh_chat_sequence": _fresh_chat_sequence(),
        "write_rules": [
            "Use lowercase canonical mailbox paths internally.",
            "Mirror ChatGPT writes to both chatgpt/ and ChatGPT/ for compatibility.",
            "Write progress to INBOX/OUTBOX plus Mongo coordination log.",
            "If a tool fails, capture the exact error before switching tools.",
        ],
    }


def _mirror_chatgpt_workspace_file(path: Path) -> None:
    try:
        rel = path.relative_to(COORD_ROOT / "chatgpt")
    except ValueError:
        return
    legacy = COORD_ROOT / CHATGPT_ALIAS / rel
    legacy.parent.mkdir(parents=True, exist_ok=True)
    legacy.write_text(path.read_text(encoding="utf-8", errors="replace"), encoding="utf-8")


def _recent_files(base: Path, limit: int = 5, pattern: str = "*.md") -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    if not base.is_dir():
        return items
    for path in sorted(base.glob(pattern), key=lambda p: p.stat().st_mtime, reverse=True)[:limit]:
        items.append(_entry_meta(path))
    return items


def _pending_lines(text: str) -> list[str]:
    pending: list[str] = []
    for line in text.splitlines():
        if line.strip().startswith(("- [ ]", "* [ ]")) or "pendiente" in line.lower() or "todo" in line.lower():
            cleaned = line.strip()
            if cleaned and cleaned not in pending:
                pending.append(cleaned)
    return pending[:10]


def _agent_path(agent: str) -> Path:
    agent_name = (agent or "").strip().lower()
    if agent_name not in MAILBOX_AGENTS:
        raise ValueError(f"invalid agent: {agent}")
    path = COORD_ROOT / agent_name
    path.mkdir(parents=True, exist_ok=True)
    for filename in ("INBOX.md", "OUTBOX.md"):
        p = path / filename
        if not p.exists():
            p.write_text(f"# {agent_name.title()} {filename[:-3]}\n\n", encoding="utf-8")
    return path


def _lines_with_query(text: str, query: str) -> list[dict[str, Any]]:
    q = query.lower().strip()
    if not q:
        return []
    matches: list[dict[str, Any]] = []
    lines = text.splitlines()
    for idx, line in enumerate(lines, start=1):
        if q in line.lower():
            start = max(1, idx - 1)
            end = min(len(lines), idx + 1)
            snippet = "\n".join(lines[start - 1 : end])
            matches.append({"line": idx, "snippet": _scrub(snippet)})
    return matches


def list_coordination_files(path: str | None = None) -> dict[str, Any]:
    """Lista archivos y carpetas permitidos dentro de ai_coordination."""
    items: list[dict[str, Any]] = []
    if path:
        root = _resolve(path)
        if root.is_file():
            items = [_entry_meta(root)]
        else:
            for child in sorted(root.rglob("*")):
                if child.is_dir() or child.suffix.lower() in ALLOWED_EXTENSIONS:
                    try:
                        _resolve(str(child.relative_to(COORD_ROOT)))
                    except ValueError:
                        continue
                    items.append(_entry_meta(child))
    else:
        items = [_entry_meta(path) for path in _iter_allowed_entries()]
    return {
        "ok": True,
        "root": str(COORD_ROOT),
        "count": len(items),
        "items": items[:500],
    }


def list_coordination_docs(category: str | None = None) -> dict[str, Any]:
    """Alias de compatibilidad para list_coordination_files."""
    items = list_coordination_files()["items"]
    if category:
        needle = category.strip().lower().rstrip("/")
        items = [item for item in items if needle in item["path"].lower()]
    return {"ok": True, "root": str(COORD_ROOT), "count": len(items), "docs": items}


def read_coordination_file(
    relative_path: str,
    max_chars: int = 12000,
    tail: bool = False,
) -> dict[str, Any]:
    """Lee un archivo de ai_coordination con allowlist estricta y filtrado de secretos."""
    path = _resolve(relative_path)
    if not path.is_file():
        return {"ok": False, "error": "not found", "path": relative_path}
    if path.suffix.lower() not in ALLOWED_EXTENSIONS:
        return {"ok": False, "error": "extension not allowed", "path": str(path.relative_to(COORD_ROOT))}

    raw = path.read_text(encoding="utf-8", errors="replace")
    text = _scrub(raw)
    truncated = len(text) > max_chars
    if truncated:
        if tail:
            text = "[... earlier content truncated ...]\n\n" + text[-max_chars:]
        else:
            text = text[:max_chars] + "\n\n[... later content truncated ...]"
    return {
        "ok": True,
        "path": str(path.relative_to(COORD_ROOT)),
        "type": "file",
        "size": path.stat().st_size,
        "modified_at": _now_iso(path),
        "chars": len(text),
        "truncated": truncated,
        "read_mode": "tail" if tail else "head",
        "content": text,
    }


def read_coordination_doc(relative_path: str, max_chars: int = 24000) -> dict[str, Any]:
    """Alias de compatibilidad para read_coordination_file."""
    return read_coordination_file(relative_path, max_chars=max_chars)


def search_coordination_docs(query: str, limit: int = 10) -> dict[str, Any]:
    """Busca texto en docs permitidos y devuelve líneas aproximadas y fragmentos."""
    q = query.strip().lower()
    if not q:
        return {"ok": False, "error": "empty query"}

    limit = max(1, min(int(limit), 50))
    hits: list[dict[str, Any]] = []
    for path in _iter_allowed_entries():
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        matches = _lines_with_query(text, q)
        if not matches:
            continue
        hits.append(
            {
                "file": str(path.relative_to(COORD_ROOT)),
                "modified_at": _now_iso(path),
                "matches": matches[:5],
            }
        )
        if len(hits) >= limit:
            break
    return {"ok": True, "query": query, "count": len(hits), "hits": hits}


def _extract_section_lines(text: str, wanted: tuple[str, ...]) -> list[str]:
    lines = text.splitlines()
    collected: list[str] = []
    active = False
    for line in lines:
        if line.startswith("#"):
            active = any(token.lower() in line.lower() for token in wanted)
        if active and line.strip():
            collected.append(line)
    return collected[:40]


def get_project_map() -> dict[str, Any]:
    """Mapa central compactado para abrir sesión rápido."""
    from raphiia_openai import mongo_store

    mapa = read_coordination_file("MAPA_CENTRAL.md", max_chars=11000)
    leer = read_coordination_file("00_LEER_PRIMERO.md", max_chars=7000)
    projects = read_coordination_file("PROJECTS_REGISTRY.md", max_chars=9000)
    mongo_schema = read_coordination_file("MONGO_SCHEMA.md", max_chars=8000)
    summary = mongo_store.get_coordination_summary(limit=12)
    active_services = _extract_section_lines(mapa.get("content", ""), ("live", "done", "in_progress"))
    active_projects = _extract_section_lines(projects.get("content", ""), ("activo", "activa", "live", "done"))
    dead_modules = _extract_section_lines(mapa.get("content", ""), ("blocked", "caid", "todo"))
    active_agents = [
        {
            "agent": mailbox.get("agent"),
            "last_modified": mailbox.get("last_modified"),
            "pending_count": len(mailbox.get("pending", [])),
            "pending": mailbox.get("pending", [])[:3],
        }
        for mailbox in get_agent_mailboxes().get("mailboxes", [])
    ]

    return {
        "ok": True,
        "read_protocol": "Empieza en 00_LEER_PRIMERO.md, luego MAPA_CENTRAL.md y consulta puntual.",
        "coordination_protocol": _coordination_protocol(),
        "central_map": mapa.get("content", ""),
        "start_here": leer.get("content", ""),
        "projects_registry": projects.get("content", ""),
        "mongo_schema": mongo_schema.get("content", ""),
        "recent_coordination_events": summary.get("recent_events", []),
        "active_agents": active_agents,
        "active_services": active_services[:20],
        "active_projects": active_projects[:20],
        "modules_down": dead_modules[:20],
        "pointers": {
            "hub_feed": "HUB/feed.md",
            "tasks": "TASKS.md",
            "decisions": "DECISIONES.md",
            "open_questions": "OPEN_QUESTIONS.md",
            "chatgpt_inbox": "chatgpt/INBOX.md",
            "chatgpt_outbox": "chatgpt/OUTBOX.md",
        },
    }


def get_chatgpt_workspace() -> dict[str, Any]:
    """Estado resumido del espacio de ChatGPT dentro de ai_coordination."""
    workspace = _ensure_workspace()
    inbox = read_coordination_file("chatgpt/INBOX.md", max_chars=10000)
    outbox = read_coordination_file("chatgpt/OUTBOX.md", max_chars=10000)
    readme = read_coordination_file("chatgpt/README.md", max_chars=4000)
    instructions = read_coordination_file("chatgpt/INSTRUCTIONS.md", max_chars=8000)
    journal_dir = workspace / "journal"
    notes_dir = workspace / "notes"
    ideas_dir = workspace / "ideas"
    drafts_dir = workspace / "drafts"
    handoff_dir = workspace / "handoff"
    memory_dir = workspace / "memory"
    logs_dir = workspace / "logs"

    recent_notes = [
        {**_entry_meta(path), "preview": _scrub(path.read_text(encoding="utf-8", errors="replace")[:500])}
        for path in sorted(notes_dir.glob("*.md"), key=lambda p: p.stat().st_mtime, reverse=True)[:10]
    ] if notes_dir.is_dir() else []
    recent_ideas = _recent_files(ideas_dir, limit=5)
    recent_drafts = _recent_files(drafts_dir, limit=5)
    recent_handoffs = _recent_files(handoff_dir, limit=5)
    journal_files = _recent_files(journal_dir, limit=5)
    recent_logs = _recent_files(logs_dir, limit=5, pattern="*")

    inbox_text = inbox.get("content", "")
    outbox_text = outbox.get("content", "")
    instruction_text = instructions.get("content", "")
    ideas_pending = _pending_lines(inbox_text + "\n" + outbox_text + "\n" + instruction_text)
    instructions_active = [
        line.strip()
        for line in _extract_section_lines(instruction_text + "\n" + readme.get("content", ""), ("instruction", "rol", "leer", "workflow"))
        if line.strip() and not line.lstrip().startswith("#")
    ][:20]

    return {
        "ok": True,
        "root": str(workspace),
        "canonical_mailboxes": _canonical_mailbox_map(),
        "operational_runbooks": get_operational_runbooks().get("runbooks", []),
        "primary_runbook": "HUB/RUNBOOK_COTIZACION_WHATSAPP.md",
        "quoter_mcp_profile": "quoter",
        "files": {
            "readme": readme.get("path"),
            "instructions": instructions.get("path"),
            "inbox": inbox.get("path"),
            "outbox": outbox.get("path"),
            "journal": [item["path"] for item in journal_files],
            "notes": [item["path"] for item in recent_notes],
            "ideas": [item["path"] for item in recent_ideas],
            "drafts": [item["path"] for item in recent_drafts],
            "handoff": [item["path"] for item in recent_handoffs],
            "memory": [item["path"] for item in _recent_files(memory_dir, limit=5, pattern="*")],
            "logs": [item["path"] for item in recent_logs],
        },
        "latest_notes": recent_notes,
        "latest_ideas": recent_ideas,
        "latest_drafts": recent_drafts,
        "latest_handoffs": recent_handoffs,
        "ideas_pending": ideas_pending,
        "instructions_active": instructions_active,
    }


def save_chatgpt_note(title: str, body: str, tags: list[str] | None = None) -> dict[str, Any]:
    """Guarda una nota de ChatGPT en chatgpt/notes/ y registra auditoría en Mongo."""
    from raphiia_openai import mongo_store

    notes_dir = _ensure_workspace() / "notes"

    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    slug = re.sub(r"[^a-zA-Z0-9_-]+", "-", title.strip())[:48].strip("-") or "note"
    path = notes_dir / f"{ts}_{slug}.md"
    tag_line = ", ".join(tags or [])
    content = f"# {title.strip()}\n\n**Tags:** {tag_line or '—'}\n\n{body.strip()}\n"
    path.write_text(content, encoding="utf-8")
    _mirror_chatgpt_workspace_file(path)

    mongo_store.log_coordination(
        agent="CHATGPT",
        summary=f"Nota: {title.strip()[:120]}",
        project="ralfia-coordination",
        tool_used="save_chatgpt_note",
        metadata={"path": str(path.relative_to(COORD_ROOT)), "tags": tags or []},
    )
    return {"ok": True, "path": str(path.relative_to(COORD_ROOT)), "saved_chars": len(content)}


def save_chatgpt_handoff(title: str, body: str, tags: list[str] | None = None) -> dict[str, Any]:
    from raphiia_openai import mongo_store

    workspace = _ensure_workspace()
    handoff_dir = workspace / "handoff"
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    slug = re.sub(r"[^a-zA-Z0-9_-]+", "-", title.strip())[:48].strip("-") or "handoff"
    path = handoff_dir / f"{ts}_{slug}.md"
    content = f"# {title.strip()}\n\n**Tags:** {', '.join(tags or []) or '—'}\n\n{body.strip()}\n"
    path.write_text(content, encoding="utf-8")
    _mirror_chatgpt_workspace_file(path)
    mongo_store.log_coordination(
        agent="CHATGPT",
        summary=f"Handoff: {title.strip()[:120]}",
        project="ralfia-coordination",
        tool_used="save_chatgpt_handoff",
        metadata={"path": str(path.relative_to(COORD_ROOT)), "tags": tags or []},
    )
    return {"ok": True, "path": str(path.relative_to(COORD_ROOT)), "saved_chars": len(content)}


def save_chatgpt_draft(title: str, body: str, channel: str | None = None, tags: list[str] | None = None) -> dict[str, Any]:
    from raphiia_openai import mongo_store

    workspace = _ensure_workspace()
    drafts_dir = workspace / "drafts"
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    slug = re.sub(r"[^a-zA-Z0-9_-]+", "-", title.strip())[:48].strip("-") or "draft"
    path = drafts_dir / f"{ts}_{slug}.md"
    content = (
        f"# {title.strip()}\n\n"
        f"**Channel:** {channel or 'general'}\n\n"
        f"**Tags:** {', '.join(tags or []) or '—'}\n\n"
        f"{body.strip()}\n"
    )
    path.write_text(content, encoding="utf-8")
    _mirror_chatgpt_workspace_file(path)
    mongo_store.log_coordination(
        agent="CHATGPT",
        summary=f"Draft: {title.strip()[:120]}",
        project="ralfia-coordination",
        tool_used="save_chatgpt_draft",
        metadata={"path": str(path.relative_to(COORD_ROOT)), "channel": channel or "general", "tags": tags or []},
    )
    return {"ok": True, "path": str(path.relative_to(COORD_ROOT)), "saved_chars": len(content)}


def get_agent_mailboxes(
    agent: str | None = None,
    limit: int = 20,
    include_files: bool = True,
) -> dict[str, Any]:
    """Return recent Mongo messages first, with Markdown tails as a human mirror."""
    from raphiia_openai.memory import agent_messages as _am

    agents = [agent] if agent else list(MAILBOX_AGENTS)
    if agent and (agent.strip().lower() not in MAILBOX_AGENTS):
        return {"ok": False, "error": f"invalid agent: {agent}"}

    limit = max(1, min(int(limit), 50))

    results: list[dict[str, Any]] = []
    for name in agents:
        base = _agent_path(name)
        inbox_path = base / "INBOX.md"
        outbox_path = base / "OUTBOX.md"
        recent = _am.list_agent_messages(agent=name, limit=limit, role="inbox")
        inbox = (
            read_coordination_file(f"{name}/INBOX.md", max_chars=6000, tail=True)
            if include_files
            else {"content": "", "truncated": False}
        )
        outbox = (
            read_coordination_file(f"{name}/OUTBOX.md", max_chars=6000, tail=True)
            if include_files
            else {"content": "", "truncated": False}
        )
        inbox_text = inbox.get("content", "")
        outbox_text = outbox.get("content", "")
        messages = recent.get("messages", [])
        results.append(
            {
                "agent": name.lower(),
                "source_of_truth": "Mongo ralfia_agent_messages",
                "messages": messages,
                "message_count": len(messages),
                "open_count": sum(1 for item in messages if item.get("status") == "open"),
                "inbox": inbox_text,
                "outbox": outbox_text,
                "inbox_truncated": bool(inbox.get("truncated")),
                "outbox_truncated": bool(outbox.get("truncated")),
                "last_modified": max(
                    datetime.fromtimestamp(inbox_path.stat().st_mtime, tz=timezone.utc).isoformat(),
                    datetime.fromtimestamp(outbox_path.stat().st_mtime, tz=timezone.utc).isoformat(),
                ),
                "pending": _pending_lines(inbox_text),
                "recent_messages": _extract_section_lines(inbox_text + "\n" + outbox_text, ("##",)),
            }
        )
    if agent:
        return {"ok": True, "mailbox": results[0]}
    return {"ok": True, "count": len(results), "mailboxes": results}


def write_agent_message(
    target_agent: str,
    title: str,
    body: str,
    priority: str | None = None,
    from_agent: str = "CHATGPT",
) -> dict[str, Any]:
    """Alias del canal único — delega a memory.agent_messages (schema v2)."""
    from raphiia_openai.memory.agent_messages import write_agent_message as _write

    return _write(
        target_agent=target_agent,
        title=title,
        body=body,
        priority=priority,
        from_agent=from_agent,
    )


def create_agent_message(
    from_agent: str,
    target_agent: str,
    title: str,
    body: str,
    priority: str = "normal",
) -> dict[str, Any]:
    """Canal único de mensajería entre agentes (Mongo + INBOX)."""
    from raphiia_openai.memory.agent_messages import create_agent_message as _create

    return _create(
        from_agent=from_agent,
        target_agent=target_agent,
        title=title,
        body=body,
        priority=priority,
    )


def list_agent_messages(
    agent: str | None = None,
    status: str | None = None,
    limit: int = 20,
    role: str = "inbox",
) -> dict[str, Any]:
    """Lista mensajes del canal único. role=inbox|sent|all."""
    from raphiia_openai.memory.agent_messages import list_agent_messages as _list

    return _list(agent=agent, status=status, limit=limit, role=role)


def bootstrap_context() -> dict[str, Any]:
    from raphiia_openai import coordination_live

    live = coordination_live.get_coordination_live()
    base = _bootstrap_context_legacy()
    runbook = read_coordination_file("HUB/RUNBOOK_COTIZACION_WHATSAPP.md", max_chars=8000)
    runbook_excerpt = (runbook.get("content") or "")[:7500]
    prefix = (
        f"# COORDINATION LIVE — revision {live.get('revision')}\n"
        f"OBLIGATORIO: leer {', '.join(live.get('mandatory_reads', [])[:4])} …\n"
        f"Órdenes ops abiertas: {live.get('open_ops_count', 0)}\n"
        f"Mensajes open: {live.get('unread_messages', {})}\n"
        f"COTIZAR: list_mcp_tool_profiles() → perfil `quoter` · RUNBOOK HUB/RUNBOOK_COTIZACION_WHATSAPP.md\n"
        f"AGENTES (lenguaje natural): ralfia_dispatch(mensaje, auto_execute=true) · dispatch_local_agent(ejecuta por defecto) · get_agent_catalog()\n"
        f"CHATGPT ORQUESTADOR: read_coordination_file('HUB/CHATGPT_ORQUESTADOR.md') · get_dev_backlog_summary() · generate_agent_activity_report()\n"
        f"Al cerrar sesión: ack_coordination_revision(agent, {live.get('revision')})\n\n"
        f"## RUNBOOK COT + WhatsApp (extracto)\n{runbook_excerpt}\n\n"
    )
    content = prefix + base.get("content", "")
    if len(content) > 18000:
        content = content[:18000] + "\n[truncated]"
    return {
        **base,
        "content": content,
        "coordination_live": live,
        "operational_runbooks": get_operational_runbooks().get("runbooks", []),
    }


def get_operational_runbooks() -> dict[str, Any]:
    """Runbooks canónicos — rutas que TODOS los agentes deben conocer."""
    items = [
        {
            "id": "cot_whatsapp",
            "path": "HUB/RUNBOOK_COTIZACION_WHATSAPP.md",
            "title": "Cotización + WhatsApp",
            "audience": ["chatgpt", "cursor", "codex", "antigravity", "notion", "rafael"],
            "mcp_profile": "quoter",
            "read_with": "read_coordination_file('HUB/RUNBOOK_COTIZACION_WHATSAPP.md')",
        },
        {
            "id": "cot_spec",
            "path": "docs/COT_QUOTER_SPEC.md",
            "title": "Spec técnica COT (repo raphiia-openai)",
            "audience": ["cursor", "codex"],
            "read_with": "read_coordination_file via sync o repo",
        },
        {
            "id": "whatsapp_agent",
            "path": "cursor/specs/WHATSAPP_EVOLUTION_AGENT.md",
            "title": "Evolution dual-nodo",
            "audience": ["cursor", "codex", "chatgpt"],
        },
    ]
    primary = read_coordination_file("HUB/RUNBOOK_COTIZACION_WHATSAPP.md", max_chars=1200)
    excerpt = (primary.get("content") or "")[:1200]
    return {"ok": True, "runbooks": items, "primary_runbook_excerpt": excerpt}


def _bootstrap_context_legacy() -> dict[str, Any]:
    from raphiia_openai import editorial_store, mongo_store

    workspace = get_chatgpt_workspace()
    project_map = get_project_map()
    coord = mongo_store.get_coordination_summary(limit=10)
    drafts = editorial_store.list_drafts(limit=5)
    protocol = _coordination_protocol()
    health = {
        "coordination_root": str(COORD_ROOT),
        "workspace_ok": workspace.get("ok", False),
        "recent_events": len(coord.get("recent_events", [])),
        "recent_drafts": len(drafts),
    }
    chunks = [
        "# Bootstrap context",
        "## Project map",
        project_map.get("central_map", "")[:3000],
        project_map.get("start_here", "")[:2000],
        "## Coordination protocol",
        textwrap.shorten(str(protocol), width=3500, placeholder=" ..."),
        "## ChatGPT workspace",
        textwrap.shorten(str(workspace), width=4000, placeholder=" ..."),
        "## Recent coordination events",
        textwrap.shorten(str(coord.get("recent_events", [])), width=2500, placeholder=" ..."),
        "## Recent drafts",
        textwrap.shorten(str(drafts), width=2000, placeholder=" ..."),
        "## Health",
        textwrap.shorten(str(health), width=1000, placeholder=" ..."),
    ]
    content = "\n\n".join(chunks)
    if len(content) > 12000:
        content = content[:12000] + "\n\n[... truncated ...]"
    return {"ok": True, "chars": len(content), "content": content, "workspace": workspace, "project_map": project_map, "health": health}


def classify_knowledge_seed(title: str, body: str) -> dict[str, Any]:
    text = f"{title}\n{body}".lower()
    category = "technical"
    intent = "remember"
    visibility = "INTERNAL"
    project = None
    reason = "defaulted to technical/internal"
    rules = [
        (("linkedin", "publish", "post", "publicar", "publicación", "publicacion"), ("publication", "publish", "PUBLIC"), "looks like editorial/publication"),
        (("roadmap", "plan", "fase", "next", "próximo", "proximo"), ("roadmap", "plan", "TEAM"), "planning / roadmap"),
        (("architecture", "arquitect", "mcp", "oauth", "gateway"), ("architecture", "develop", "INTERNAL"), "architecture / integration"),
        (("hackathon", "funding", "grant", "opportunity"), ("hackathon", "plan", "TEAM"), "hackathon / funding"),
        (("client", "cliente", "business", "negocio"), ("client", "remember", "INTERNAL"), "client / business"),
        (("travel", "viaje", "trip"), ("travel", "remember", "PRIVATE"), "travel / private"),
    ]
    project_rules = [
        (("funding-hub", "funding", "opportunity", "grant", "hackathon"), "hackathon-funding-hub"),
        (("linkedin", "post", "publish", "editorial"), "editorial"),
        (("portal", "8800", "control center", "control plane"), "innerspark-swarm-os"),
        (("oauth", "mcp", "connector"), "raphiia-openai"),
        (("gemini", "imagen", "google image"), "gemini"),
        (("notion",), "notion"),
        (("cursor",), "cursor"),
        (("antigravity",), "antigravity"),
    ]
    for needles, values, why in rules:
        if any(n in text for n in needles):
            category, intent, visibility = values
            reason = why
            break
    for needles, proj in project_rules:
        if any(n in text for n in needles):
            project = proj
            break
    if category == "publication":
        intent = "publish"
        visibility = "PUBLIC"
    return {
        "ok": True,
        "category": category,
        "intent": intent,
        "visibility": visibility,
        "project": project,
        "confidence": 0.72,
        "reason": reason,
    }


def save_knowledge_seed(
    title: str,
    body: str,
    category: str,
    intent: str,
    visibility: str,
    project: str | None = None,
    tags: list[str] | None = None,
) -> dict[str, Any]:
    from raphiia_openai import mongo_store

    classified = classify_knowledge_seed(title, body)
    payload = mongo_store.save_knowledge_seed(
        title=title,
        body=body,
        category=category or classified["category"],
        intent=intent or classified["intent"],
        visibility=visibility or classified["visibility"],
        project=project or classified.get("project"),
        tags=tags or [],
        metadata={"classified": classified},
    )
    return {"ok": True, "seed": payload, "classification": classified}

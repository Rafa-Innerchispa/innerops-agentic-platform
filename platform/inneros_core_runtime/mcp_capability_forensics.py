"""Forensic MCP capability snapshots and release gates.

This module is intentionally read-only by default. It lets deployment and
coordination code compare historical catalog surfaces before promoting a MCP
runtime, so a missing tool or declared-but-unavailable backend becomes visible
as a blocking regression instead of being normalized as a new baseline.
"""

from __future__ import annotations

import ast
import hashlib
import json
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from raphiia_openai.mcp_catalog import tool_catalog

CATALOG_PATH = "platform/inneros_core_runtime/mcp_catalog/tool_catalog.py"
SERVER_PATH = "platform/inneros_core_runtime/mcp_server.py"
RETIREMENT_PHASES = ("DEPRECATED", "RETIREMENT_PENDING", "OWNER_APPROVED_REMOVAL")


@dataclass(frozen=True)
class CatalogSnapshot:
    label: str
    tool_names: tuple[str, ...]
    server_symbols: tuple[str, ...]
    catalog_version: str | None = None

    def as_dict(self) -> dict[str, Any]:
        tool_names = sorted(set(self.tool_names))
        server_symbols = sorted(set(self.server_symbols))
        missing_backends = sorted(set(tool_names) - set(server_symbols))
        names_hash = _hash_list(tool_names)
        backend_hash = _hash_list(server_symbols)
        return {
            "ok": True,
            "label": self.label,
            "catalog_version": self.catalog_version,
            "tool_count": len(tool_names),
            "tool_names": tool_names,
            "tool_names_hash": names_hash,
            "tool_names_hash_short": names_hash[:16],
            "server_symbol_count": len(server_symbols),
            "server_symbols_hash": backend_hash,
            "backend_unavailable": missing_backends,
            "backend_unavailable_count": len(missing_backends),
        }


def _hash_list(items: Iterable[str]) -> str:
    raw = json.dumps(sorted(set(items)), separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _literal_assignment(source: str, name: str) -> Any:
    tree = ast.parse(source)
    value: Any = None
    found = False
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == name:
                    value = ast.literal_eval(node.value)
                    found = True
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.target.id == name:
            value = ast.literal_eval(node.value)
            found = True
    if not found:
        raise ValueError(f"{name} not found as literal assignment")
    if name == "ALL_MCP_TOOL_NAMES" and isinstance(value, list):
        for node in ast.walk(tree):
            if not isinstance(node, ast.Expr) or not isinstance(node.value, ast.Call):
                continue
            call = node.value
            if not isinstance(call.func, ast.Attribute) or call.func.attr != "extend":
                continue
            target = call.func.value
            if isinstance(target, ast.Name) and target.id == name and call.args:
                try:
                    extra = ast.literal_eval(call.args[0])
                except Exception:
                    continue
                if isinstance(extra, list):
                    value.extend(extra)
    return value


def _literal_mcp_version(source: str) -> str | None:
    try:
        value = _literal_assignment(source, "MCP_VERSION")
    except Exception:
        return None
    return str(value) if value is not None else None


def _function_symbols(source: str) -> list[str]:
    tree = ast.parse(source)
    return sorted(
        node.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    )


def snapshot_from_sources(*, label: str, catalog_source: str, server_source: str) -> dict[str, Any]:
    names = [str(item) for item in _literal_assignment(catalog_source, "ALL_MCP_TOOL_NAMES")]
    snap = CatalogSnapshot(
        label=label,
        tool_names=tuple(names),
        server_symbols=tuple(_function_symbols(server_source)),
        catalog_version=_literal_mcp_version(catalog_source),
    )
    return snap.as_dict()


def current_snapshot(label: str = "current-runtime") -> dict[str, Any]:
    names = sorted(tool_catalog.ALL_MCP_TOOL_NAMES)
    try:
        root = Path(__file__).resolve().parents[1]
        server_source = (root / "inneros_core_runtime" / "mcp_server.py").read_text(encoding="utf-8")
        server_symbols = _function_symbols(server_source)
    except Exception:
        server_symbols = []
    snap = CatalogSnapshot(
        label=label,
        tool_names=tuple(names),
        server_symbols=tuple(server_symbols),
        catalog_version=tool_catalog.MCP_VERSION,
    )
    return snap.as_dict()


def compare_snapshots(
    previous: dict[str, Any],
    current: dict[str, Any],
    *,
    owner_approved_removals: list[str] | None = None,
) -> dict[str, Any]:
    approved = set(owner_approved_removals or [])
    previous_tools = set(previous.get("tool_names") or [])
    current_tools = set(current.get("tool_names") or [])
    removed = sorted(previous_tools - current_tools)
    added = sorted(current_tools - previous_tools)
    unapproved_removed = [name for name in removed if name not in approved]
    backend_unavailable = sorted(current.get("backend_unavailable") or [])
    issues: list[dict[str, Any]] = []
    for name in unapproved_removed:
        issues.append(
            {
                "code": "CAPABILITY_REMOVAL_REQUIRES_OWNER_APPROVAL",
                "tool_name": name,
                "required_phase": "RETIREMENT_PENDING -> explicit owner approval",
            }
        )
    for name in backend_unavailable:
        issues.append(
            {
                "code": "CATALOG_BACKEND_REGRESSION",
                "tool_name": name,
                "meaning": "tool_name_present=true backend_available=false",
            }
        )
    status = "BLOCKED" if issues else "PASS"
    return {
        "ok": not issues,
        "status": status,
        "previous_label": previous.get("label"),
        "current_label": current.get("label"),
        "previous_tool_count": len(previous_tools),
        "current_tool_count": len(current_tools),
        "removed_tools": removed,
        "added_tools": added,
        "approved_removed_tools": sorted(set(removed) & approved),
        "backend_unavailable": backend_unavailable,
        "issues": issues,
        "policy": {
            "baseline_update": "never_auto_update_to_silence_alarm",
            "retirement_flow": list(RETIREMENT_PHASES),
            "backend_rule": "tool_name_present=true + backend_available=false is a regression",
        },
    }


def _repo_root() -> Path:
    here = Path(__file__).resolve()
    # file = <repo>/platform/inneros_core_runtime/mcp_capability_forensics.py
    return here.parents[2]


def _git_show(repo: Path, ref: str, path: str) -> str:
    cmd = ["git", "-C", str(repo), "show", f"{ref}:{path}"]
    completed = subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    return completed.stdout


def snapshot_git_ref(ref: str, *, repo_path: str | None = None) -> dict[str, Any]:
    repo = Path(repo_path).expanduser().resolve() if repo_path else _repo_root()
    catalog_source = _git_show(repo, ref, CATALOG_PATH)
    server_source = _git_show(repo, ref, SERVER_PATH)
    snapshot = snapshot_from_sources(label=ref, catalog_source=catalog_source, server_source=server_source)
    snapshot["repo_path"] = str(repo)
    return snapshot


def diff_git_refs(
    previous_ref: str,
    current_ref: str = "HEAD",
    *,
    repo_path: str | None = None,
    owner_approved_removals: list[str] | None = None,
) -> dict[str, Any]:
    previous = snapshot_git_ref(previous_ref, repo_path=repo_path)
    current = snapshot_git_ref(current_ref, repo_path=repo_path)
    return compare_snapshots(previous, current, owner_approved_removals=owner_approved_removals)


def release_gate(
    *,
    previous_ref: str | None = None,
    previous_snapshot: dict[str, Any] | None = None,
    current_snapshot_payload: dict[str, Any] | None = None,
    repo_path: str | None = None,
    owner_approved_removals: list[str] | None = None,
) -> dict[str, Any]:
    current = current_snapshot_payload or current_snapshot("current-runtime")
    if previous_snapshot is not None:
        previous = previous_snapshot
    elif previous_ref:
        previous = snapshot_git_ref(previous_ref, repo_path=repo_path)
    else:
        previous = current
    result = compare_snapshots(previous, current, owner_approved_removals=owner_approved_removals)
    result["gate"] = "mcp_capability_release_gate"
    result["repo_path"] = repo_path or str(_repo_root())
    return result


def history_union(refs: list[str], *, repo_path: str | None = None) -> dict[str, Any]:
    snapshots = []
    union: set[str] = set()
    failures: list[dict[str, str]] = []
    for ref in refs:
        try:
            snap = snapshot_git_ref(ref, repo_path=repo_path)
        except Exception as exc:
            failures.append({"ref": ref, "error": str(exc)[:500]})
            continue
        snapshots.append({k: snap[k] for k in ("label", "catalog_version", "tool_count", "tool_names_hash_short") if k in snap})
        union.update(snap.get("tool_names") or [])
    current = current_snapshot("current-runtime")
    return {
        "ok": not failures,
        "refs_checked": refs,
        "snapshots": snapshots,
        "failures": failures,
        "historical_union_count": len(union),
        "historical_union_hash": _hash_list(union),
        "missing_from_current": sorted(union - set(current.get("tool_names") or [])),
        "current_tool_count": current.get("tool_count"),
        "current_tool_names_hash_short": current.get("tool_names_hash_short"),
        "policy": "missing_from_current must be DEPRECATED/RETIREMENT_PENDING/OWNER_APPROVED_REMOVAL before deploy promotion",
    }

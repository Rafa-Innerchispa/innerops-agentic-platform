from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class SandboxPolicy:
    allowed_roots: tuple[str, ...] = ("/workspace",)
    read_only_required_for_prefixes: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ToolProfile:
    name: str
    description: str = ""
    backends: tuple[str, ...] = ()
    default_backend: str = ""
    allow_all: bool = False
    prefixes: tuple[str, ...] = ()
    whitelist: frozenset[str] = field(default_factory=frozenset)
    max_tools: int | None = 25
    sandbox: SandboxPolicy = field(default_factory=SandboxPolicy)

    def allows_name(self, tool_name: str) -> bool:
        if self.allow_all:
            return True
        if tool_name in self.whitelist:
            return True
        return any(tool_name.startswith(prefix) for prefix in self.prefixes)


@dataclass(frozen=True, slots=True)
class BackendTarget:
    name: str
    url: str
    description: str = ""
    enabled: bool = True


@dataclass(frozen=True, slots=True)
class RouterConfig:
    host: str
    port: int
    active_profile: str
    default_backend: str
    backends: dict[str, BackendTarget]
    profiles: dict[str, ToolProfile]
    public_url: str = ""
    bearer_token: str = ""
    auth_mode: str = "oauth_passthrough"
    oauth_resource: str = "https://mcp.pcdoctor.ai/mcp"
    oauth_authorization_server: str = "https://auth.pcdoctor.ai"

    @property
    def profile(self) -> ToolProfile:
        try:
            return self.profiles[self.active_profile]
        except KeyError as exc:
            raise ValueError(f"unknown profile: {self.active_profile}") from exc


def _tuple(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list):
        raise ValueError("expected a list")
    return tuple(str(item) for item in value)


def load_profiles(path: Path) -> tuple[str, str, dict[str, BackendTarget], dict[str, ToolProfile]]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    default_profile = str(raw.get("default_profile") or "profile_minimal")
    default_backend = str(raw.get("default_backend") or "default")
    backends_raw = raw.get("backends") or {}
    backends: dict[str, BackendTarget] = {}
    for name, item in backends_raw.items():
        if not isinstance(item, dict):
            continue
        url = str(item.get("url") or "").strip()
        if not url:
            continue
        backends[str(name)] = BackendTarget(
            name=str(name),
            url=url.rstrip("/"),
            description=str(item.get("description") or ""),
            enabled=bool(item.get("enabled", True)),
        )
    profiles: dict[str, ToolProfile] = {}
    for name, item in (raw.get("profiles") or {}).items():
        sandbox_raw = item.get("sandbox") or {}
        sandbox = SandboxPolicy(
            allowed_roots=_tuple(sandbox_raw.get("allowed_roots") or ["/workspace"]),
            read_only_required_for_prefixes=_tuple(sandbox_raw.get("read_only_required_for_prefixes")),
        )
        max_tools_raw = item.get("max_tools", 25)
        max_tools = None if max_tools_raw is None else int(max_tools_raw)
        profile_backends = _tuple(item.get("backends"))
        profile_default_backend = str(item.get("default_backend") or (profile_backends[0] if profile_backends else default_backend))
        profiles[str(name)] = ToolProfile(
            name=str(name),
            description=str(item.get("description") or ""),
            backends=profile_backends,
            default_backend=profile_default_backend,
            allow_all=bool(item.get("allow_all", False)),
            prefixes=_tuple(item.get("prefixes")),
            whitelist=frozenset(_tuple(item.get("whitelist"))),
            max_tools=max_tools,
            sandbox=sandbox,
        )
    if not profiles:
        raise ValueError("profiles.json must define at least one profile")
    if not backends:
        legacy_backend_url = str(raw.get("backend_url") or "").strip()
        if legacy_backend_url:
            backends[default_backend] = BackendTarget(name=default_backend, url=legacy_backend_url.rstrip("/"))
    return default_profile, default_backend, backends, profiles


def load_config() -> RouterConfig:
    root = Path(os.environ.get("MCP_ROUTER_CONFIG_DIR", ".")).resolve()
    profiles_path = Path(os.environ.get("MCP_ROUTER_PROFILES", root / "profiles.json")).resolve()
    default_profile, default_backend, backends, profiles = load_profiles(profiles_path)
    legacy_backend_url = os.environ.get("MCP_ROUTER_BACKEND_URL", "").strip()
    if legacy_backend_url and default_backend not in backends:
        backends = {
            **backends,
            default_backend: BackendTarget(name=default_backend, url=legacy_backend_url.rstrip("/")),
        }
    return RouterConfig(
        host=os.environ.get("MCP_ROUTER_HOST", "127.0.0.1"),
        port=int(os.environ.get("MCP_ROUTER_PORT", "8001")),
        active_profile=os.environ.get("MCP_ROUTER_PROFILE", default_profile),
        default_backend=default_backend,
        backends=backends,
        profiles=profiles,
        public_url=os.environ.get("MCP_ROUTER_PUBLIC_URL", "").rstrip("/"),
        bearer_token=os.environ.get("MCP_ROUTER_BEARER_TOKEN", "").strip(),
        auth_mode=os.environ.get("MCP_ROUTER_AUTH_MODE", "oauth_passthrough").strip().lower(),
        oauth_resource=os.environ.get("MCP_ROUTER_OAUTH_RESOURCE", "https://mcp.pcdoctor.ai/mcp").rstrip("/"),
        oauth_authorization_server=os.environ.get("MCP_ROUTER_OAUTH_AUTHORIZATION_SERVER", "https://auth.pcdoctor.ai").rstrip("/"),
    )

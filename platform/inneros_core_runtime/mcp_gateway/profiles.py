"""MCP Gateway Profile Manager and Strict Tool Filtering Engine."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

DEFAULT_CONFIG_PATH = Path(__file__).parent / "profiles.json"


class UnauthorizedProfileError(Exception):
    """Raised when an unauthorized client attempts to activate a privileged profile."""

    def __init__(self, profile: str, reason: str = "Elevated profile access denied.") -> None:
        self.profile = profile
        self.error_code = -32003
        self.message = f"UnauthorizedProfileError: Access to profile '{profile}' is restricted. {reason}"
        super().__init__(self.message)


class ProfileManager:
    def __init__(
        self,
        config_path: Path | str | None = None,
        inline_config: dict[str, Any] | None = None,
        allow_admin_profile: bool | None = None,
        admin_secret: str | None = None,
    ) -> None:
        if inline_config is not None:
            self.config = inline_config
        else:
            p = Path(config_path) if config_path else DEFAULT_CONFIG_PATH
            if p.exists():
                with open(p, "r", encoding="utf-8") as f:
                    self.config = json.load(f)
            else:
                self.config = self._default_fallback_config()

        self.profiles: dict[str, dict[str, Any]] = self.config.get("profiles", {})
        self.default_profile: str = self.config.get("default_profile", "profile_minimal")
        
        # Admin elevation settings
        env_allow_admin = os.environ.get("ALLOW_ADMIN_PROFILE", "").strip().lower() in ("true", "1", "yes")
        self.allow_admin_profile: bool = (
            allow_admin_profile
            if allow_admin_profile is not None
            else (env_allow_admin or self.config.get("allow_admin_profile", False))
        )
        self.admin_secret: str = admin_secret or os.environ.get("MCP_ADMIN_SECRET", "")

    def _default_fallback_config(self) -> dict[str, Any]:
        return {
            "default_profile": "profile_minimal",
            "allow_admin_profile": False,
            "profiles": {
                "profile_coding": {
                    "label": "Coding",
                    "allow_all": False,
                    "max_tools": 25,
                    "tools": [
                        "local_exec_inspect_repo",
                        "local_exec_inspect_remotes",
                        "local_exec_prepare_repo",
                        "local_exec_acquire_lock",
                        "local_exec_release_lock",
                        "local_exec_create_worktree",
                        "local_exec_write_file",
                        "local_exec_apply_patch",
                        "local_exec_run_command_allowlisted",
                        "local_exec_commit_branch",
                        "local_exec_report_evidence",
                        "local_fs_list",
                        "local_fs_read_file",
                        "local_model_router_status",
                        "mcp_version",
                        "diagnose_mcp_session",
                        "list_ops_tasks",
                    ],
                },
                "profile_minimal": {
                    "label": "Minimal",
                    "allow_all": False,
                    "max_tools": 15,
                    "tools": [
                        "mcp_version",
                        "diagnose_mcp_session",
                        "list_mcp_tool_profiles",
                        "route_mcp_tools",
                        "bootstrap_context",
                        "get_coordination_live",
                        "poll_agent_inbox",
                        "list_ops_tasks",
                        "create_agent_message",
                        "a2a_status",
                        "a2a_agent_cards",
                        "project_runtime_bootstrap",
                        "dev_swarm_scope_status",
                        "dev_swarm_launch_task",
                        "dev_swarm_scheduler_status",
                    ],
                },
                "profile_admin": {
                    "label": "Admin Full",
                    "allow_all": True,
                    "max_tools": 1000,
                    "requires_auth": True,
                    "tools": [],
                },
            },
        }

    def validate_profile_access(self, profile_name: str | None, client_secret: str | None = None) -> str:
        """Validate if the requested profile is permitted. Returns the validated profile name or raises UnauthorizedProfileError."""
        name = profile_name or self.default_profile
        prof = self.profiles.get(name)
        if not prof:
            return self.default_profile

        if prof.get("requires_auth", False) or name == "profile_admin":
            if not self.allow_admin_profile:
                raise UnauthorizedProfileError(
                    name,
                    "profile_admin is disabled by server security policy (ALLOW_ADMIN_PROFILE=false).",
                )
            if self.admin_secret:
                if not client_secret or client_secret != self.admin_secret:
                    raise UnauthorizedProfileError(
                        name,
                        "Invalid or missing admin authorization secret.",
                    )

        return name

    def list_profiles(self) -> dict[str, dict[str, Any]]:
        return {
            name: {
                "label": p.get("label", name),
                "description": p.get("description", ""),
                "max_tools": p.get("max_tools", 25),
                "allow_all": p.get("allow_all", False),
                "requires_auth": p.get("requires_auth", False),
                "tools_count": len(p.get("tools", [])),
            }
            for name, p in self.profiles.items()
        }

    def get_profile(self, profile_name: str | None) -> dict[str, Any]:
        name = profile_name or self.default_profile
        if name in self.profiles:
            return self.profiles[name]
        return self.profiles.get(self.default_profile, self._default_fallback_config()["profiles"]["profile_minimal"])

    def is_tool_allowed(self, tool_name: str, profile_name: str | None) -> bool:
        prof = self.get_profile(profile_name)
        if prof.get("allow_all", False):
            return True

        # Strict explicit tool allowlist only (no loose text matching)
        explicit_tools = set(prof.get("tools", []))
        return tool_name in explicit_tools

    def filter_tools(self, tools_list: list[dict[str, Any]], profile_name: str | None) -> list[dict[str, Any]]:
        prof = self.get_profile(profile_name)
        if prof.get("allow_all", False):
            max_limit = prof.get("max_tools", 1000)
            return tools_list[:max_limit]

        allowed: list[dict[str, Any]] = []
        max_tools = prof.get("max_tools", 25)
        allowed_set = set(prof.get("tools", []))

        for t in tools_list:
            t_name = t.get("name")
            if not t_name:
                continue
            if t_name in allowed_set:
                allowed.append(t)
                if len(allowed) >= max_tools:
                    break

        return allowed

"""Canonical policy adapter and deny-only security for the shadow MCP router."""
from __future__ import annotations
import asyncio
import json
import time
from contextlib import asynccontextmanager
from pathlib import Path
from inneros_core_runtime import mcp_profiles, capability_router
from inneros_core_runtime.mcp_catalog import tool_catalog

class Denied(Exception):
    def __init__(self, kind, code=-32001):
        self.kind, self.code = kind, code
        super().__init__(kind)

# Exact reviewed subset of owner_dev; never prefix-derived permissions.
CODING = (
    "local_fs_list", "local_fs_read_file", "local_exec_inspect_repo",
    "local_exec_inspect_remotes", "local_exec_verified_git_author_status",
    "local_exec_repo_policy_status", "local_exec_prepare_repo",
    "local_exec_acquire_lock", "local_exec_release_lock", "local_exec_create_worktree",
    "local_exec_apply_patch", "local_exec_write_file", "local_exec_run_command_allowlisted",
    "local_exec_commit_branch", "local_exec_report_evidence",
)
PATH_KEYS = {"path", "file_path", "filepath", "target_path", "source_path", "dest_path",
             "destination_path", "cwd", "directory", "dir_path", "folder", "repo_path",
             "workspace_path", "root_dir"}

def profile_tools(profile, scopes, *, admin_enabled=False, admin_authorized=False):
    if profile == "profile_admin":
        if not (admin_enabled and admin_authorized and "ralfia:admin" in scopes):
            raise Denied("UnauthorizedProfileError", -32003)
        return tuple(tool_catalog.ALL_MCP_TOOL_NAMES)
    aliases = {"profile_minimal": ("chatgpt_compact", "low", 15),
               "profile_coding": ("owner_dev", "medium", 25)}
    if profile not in aliases:
        raise Denied("UnknownProfileError", -32003)
    source, risk, cap = aliases[profile]
    result = capability_router.route_tools(title="shadow MCP router", requested_profile=source,
                                           granted_scopes=list(scopes), max_risk=risk)
    if not result.get("ok"):
        raise Denied("CanonicalProfileInvalid", -32005)
    candidates = result["tools"]
    if profile == "profile_coding":
        if not set(CODING).issubset(mcp_profiles.PROFILES[source]["tools"]):
            raise Denied("CanonicalProfileMismatch", -32005)
        candidates = [n for n in CODING if n in candidates]
    else:
        candidates = [n for n in candidates
                      if not tool_catalog.TOOL_DEFINITIONS.get(n, {}).get("writes_to")]
    if len(candidates) > cap or len(set(candidates)) != len(candidates):
        raise Denied("CanonicalProfileMismatch", -32005)
    return tuple(candidates)

def validate_paths(tool, args, roots=("/workspace",)):
    if not isinstance(args, dict):
        raise Denied("InvalidArguments", -32602)
    canonical_roots = tuple(Path(r).resolve() for r in roots)
    if not canonical_roots or any(str(r) in ("/", "/home", "/home/rlopez") for r in canonical_roots):
        raise Denied("UnsafeRootConfiguration", -32002)
    def walk(value, key="", depth=0):
        if depth > 24:
            raise Denied("ArgumentDepthExceeded", -32602)
        if isinstance(value, dict):
            for k, v in value.items():
                walk(v, str(k).lower(), depth+1)
        elif isinstance(value, list):
            for v in value:
                walk(v, key, depth+1)
        elif isinstance(value, str):
            if "\x00" in value:
                raise Denied("SandboxPathViolation", -32002)
            if key in PATH_KEYS:
                path = Path(value)
                if ".." in path.parts:
                    raise Denied("SandboxPathViolation", -32002)
                # Worktree-relative paths are resolved and checked downstream by Local Execution Plane.
                if not path.is_absolute() and tool.startswith("local_exec_"):
                    return
                if not path.is_absolute():
                    raise Denied("SandboxPathViolation", -32002)
                resolved = path.resolve()
                if not any(resolved == r or r in resolved.parents for r in canonical_roots):
                    raise Denied("SandboxPathViolation", -32002)
    walk(args)
    if tool == "local_exec_run_command_allowlisted":
        command = args.get("command")
        if not isinstance(command, list) or not command or not all(isinstance(v, str) for v in command):
            raise Denied("UnsafeCommandSurface", -32002)
        if Path(command[0]).name in {"sh","bash","dash","zsh","cmd","powershell","pwsh","docker","sudo"}:
            raise Denied("UnsafeCommandSurface", -32002)
        if any(v in {"-c","-Command","--eval"} for v in command[1:]):
            raise Denied("UnsafeCommandSurface", -32002)
        if not all(isinstance(args.get(k), str) and args[k] for k in
                   ("repo","actor","task_id","correlation_id","work_branch")):
            raise Denied("MissingDownstreamScope", -32002)

class Throttle:
    """Per authenticated client/profile token bucket and bounded concurrency."""
    def __init__(self, rate=5., burst=10, concurrency=3, max_clients=1024, clock=time.monotonic):
        if min(rate, burst, concurrency, max_clients) <= 0:
            raise ValueError("positive throttle limits required")
        self.rate, self.burst, self.concurrency = rate, burst, concurrency
        self.max_clients, self.clock, self.states = max_clients, clock, {}
        self.lock = asyncio.Lock()

    @asynccontextmanager
    async def acquire(self, client, profile):
        key, now = (client, profile), self.clock()
        async with self.lock:
            if key not in self.states:
                if len(self.states) >= self.max_clients:
                    for old, state in list(self.states.items()):
                        if state[2] == 0 and now-state[1] >= max(60, self.burst/self.rate):
                            del self.states[old]
                    if len(self.states) >= self.max_clients:
                        raise Denied("ToolThrottledError", -32004)
                self.states[key] = [float(self.burst), now, 0]
            state = self.states[key]
            state[0] = min(self.burst, state[0] + max(0, now-state[1])*self.rate)
            state[1] = now
            if state[0] < 1 or state[2] >= self.concurrency:
                raise Denied("ToolThrottledError", -32004)
            state[0] -= 1
            state[2] += 1
        try:
            yield
        finally:
            async with self.lock:
                state[2] -= 1

class Federation:
    """Disabled candidates still undergo ownership collision validation."""
    def __init__(self, backends):
        self.backends = backends
        self.exact, self.prefixes = {}, {}
        defaults = [k for k,v in backends.items() if v.get("default") and v.get("enabled")]
        if len(defaults) != 1:
            raise ValueError("one enabled default backend required")
        self.default = defaults[0]
        for owner, conf in backends.items():
            for tool in conf.get("tools", []):
                if tool in self.exact:
                    raise ValueError("tool ownership collision")
                self.exact[tool] = owner
            for prefix in conf.get("prefixes", []):
                if not prefix or any(prefix.startswith(p) or p.startswith(prefix) for p in self.prefixes):
                    raise ValueError("prefix ownership collision")
                self.prefixes[prefix] = owner
            if owner != self.default and conf.get("enabled") and not conf.get("parity_verified"):
                raise ValueError("federation parity gate")
    def resolve(self, tool):
        owner = self.exact.get(tool)
        if owner is None:
            owner = next((v for p,v in self.prefixes.items() if tool.startswith(p)), self.default)
        return owner if self.backends[owner].get("enabled") else self.default

def validate_projection():
    config = json.loads((Path(__file__).parent/"profiles.json").read_text())
    if config["profile_minimal"]["source"] != "chatgpt_compact" or config["profile_coding"]["source"] != "owner_dev":
        raise Denied("ProjectionMismatch", -32005)
    if tuple(config["profile_coding"]["exact_subset"]) != CODING:
        raise Denied("ProjectionMismatch", -32005)
    for alias in ("profile_minimal","profile_coding"):
        conf = config[alias]
        names = profile_tools(alias, conf["scopes"])
        if len(names) > conf["max_tools"]:
            raise Denied("ProjectionMismatch", -32005)
    return True

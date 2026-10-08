"""Safe local repository execution plane for Ralphi IA.

This module is intentionally boring: no shell strings, no privileged commands,
no production deploys, no secrets, and no edits outside isolated worktrees.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import stat
import subprocess
import tempfile
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator

from raphiia_openai import execution_policy

CAPABILITY = "local_execution_plane"
DEFAULT_INNEROS_CORE_ROOT = Path("/home/rlopez/inneros/inneros_core")
DEFAULT_ROOT = DEFAULT_INNEROS_CORE_ROOT / "var" / "local_execution"
MAX_OUTPUT_BYTES_DEFAULT = 60000
MAX_TIMEOUT_SECONDS = 1200
DEV_SWARM_GIT_USER_NAME = "RalfIA Dev Swarm"
DEV_SWARM_GIT_USER_EMAIL = "dev-swarm@inneros.local"
HOST_APPROVALS_COL = "ralfia_host_approvals"

REPO_PATTERN = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
NESTED_REPO_PATTERN = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
BRANCH_PATTERN = re.compile(r"^(codex|chatgpt|cursor|antigravity|gemini|local-agent|dev-swarm)/[A-Za-z0-9._/-]+$")
PROTECTED_BRANCHES = {"main", "master", "production", "prod", "develop"}
OWNER_APPROVED_GITHUB_OWNERS = {"Rafa-Innerchispa", "rafagye"}
OWNER_APPROVED_NESTED_REPOS = {
    "gitlab-community/gitlab-org/gitlab-runner",
    "gitlab-community/gitlab-org/gitlab",
}
OWNER_APPROVED_ALLOWED_PATHS = [
    "app",
    "components",
    "docs",
    "infra",
    "lib",
    "modules",
    "public",
    "scripts",
    "src",
    "tests",
    "AGENT_CONTRACT.md",
    "BASELINE_PROVENANCE.md",
    "DEPLOYMENT.md",
    "README.md",
    "package.json",
    "package-lock.json",
    "pnpm-lock.yaml",
    "pyproject.toml",
    "requirements.txt",
    "tsconfig.json",
    "next.config.js",
    "next.config.mjs",
    "vite.config.ts",
]
OWNER_APPROVED_REMOTE_POLICIES: dict[str, dict[str, str]] = {
    "Rafa-Innerchispa/gitlab-community-contrib": {
        "origin": "https://gitlab.com/gitlab-community/gitlab-org/gitlab.git",
    },
    "Rafa-Innerchispa/hyperloom-r9700-experimental": {
        "origin": "https://github.com/Rafa-Innerchispa/hyperloom-r9700-experimental.git",
        "upstream": "https://github.com/AMD-AGI/Hyperloom.git",
    },
    "gitlab-community/gitlab-org/gitlab-runner": {
        "origin": "https://gitlab.com/rafagye/gitlab-runner.git",
        "community": "https://gitlab.com/gitlab-community/gitlab-org/gitlab-runner.git",
    },
    "gitlab-community/gitlab-org/gitlab": {
        "origin": "https://gitlab.com/gitlab-community/gitlab-org/gitlab.git",
        "upstream": "https://gitlab.com/gitlab-org/gitlab.git",
    },
    "gitlab-org/gitlab": {
        "origin": "https://gitlab.com/gitlab-community/gitlab-org/gitlab.git",
        "upstream": "https://gitlab.com/gitlab-org/gitlab.git",
    },
}
VERIFIED_GIT_AUTHORS_ENV = "RALFIA_VERIFIED_GIT_AUTHORS_JSON"
DENIED_PATH_PARTS = {
    ".env",
    ".ssh",
    ".gnupg",
    "secrets",
    "secret",
    "backup",
    "backups",
    "dump",
    "dumps",
    "private",
    "credentials",
    "node_modules",
    "venv",
    ".venv",
    "__pycache__",
}
SECRET_PATTERNS = [
    re.compile(r"(?i)(api[_-]?key|token|secret|password|passwd|private[_-]?key)\s*[:=]\s*[^\s]+"),
    re.compile(r"sk-[A-Za-z0-9_-]{20,}"),
    re.compile(r"gh[opsu]_[A-Za-z0-9_]{20,}"),
    re.compile(r"glpat-[A-Za-z0-9_.-]{10,}"),
]

ALLOWLISTED_COMMANDS: dict[str, list[tuple[str, ...]]] = {
    "ecosystem-core-docs": [
        ("git", "status", "--short", "--branch"),
        ("git", "diff", "--check"),
        ("git", "diff", "--stat"),
        ("git", "diff", "--name-only"),
        ("git", "log", "--oneline", "-n"),
        ("python", "-m", "json.tool"),
        ("python3", "-m", "json.tool"),
    ],
    "docs_git_markdown": [
        ("git", "status", "--short", "--branch"),
        ("git", "diff", "--check"),
        ("git", "diff", "--stat"),
        ("git", "diff", "--name-only"),
        ("git", "log", "--oneline", "-n"),
    ],
    "go_gitlab_runner": [
        ("git", "status", "--short", "--branch"),
        ("git", "diff", "--check"),
        ("git", "diff", "--stat"),
        ("git", "diff", "--name-only"),
        ("git", "log", "--oneline", "-n"),
        ("git", "log", "--format=fuller", "-1"),
        ("git", "commit", "--amend", "-m"),
        ("go", "version"),
        ("go", "test"),
        ("go", "build"),
        ("go", "vet"),
        ("make", "tools"),
        ("make", "development_setup"),
        ("make", "lint"),
        ("gofmt", "-l"),
        ("gofmt", "-d"),
        ("gofmt", "-w"),
        ("scripts/lint-docs",),
        ("scripts/lint-i18n-docs",),
        ("glab", "issue", "view"),
        ("glab", "issue", "list"),
        ("glab", "mr", "view"),
        ("glab", "mr", "list"),
    ],
    "python-tests": [
        ("python", "-m", "pytest"),
        ("python3", "-m", "pytest"),
        ("pytest",),
        ("python", "-m", "unittest"),
        ("python3", "-m", "unittest"),
        ("python", "-m", "compileall"),
        ("python3", "-m", "compileall"),
        ("git", "status", "--short", "--branch"),
        ("git", "diff", "--check"),
        ("git", "diff", "--stat"),
        ("git", "diff", "--name-only"),
        ("agy", "--help"),
        ("agy", "--status"),
        ("agy", "--inbox"),
        ("agy", "--version"),
        ("scripts/agy", "--help"),
        ("scripts/agy", "--status"),
        ("scripts/agy", "--inbox"),
        ("scripts/agy", "--version"),
        ("/home/rlopez/.local/bin/agy", "--status"),
    ],
    "node-tests": [
        ("npm", "test"),
        ("npm", "run", "test"),
        ("npm", "run", "lint"),
        ("npm", "run", "build"),
        ("git", "status", "--short", "--branch"),
        ("git", "diff", "--check"),
        ("git", "diff", "--stat"),
        ("git", "diff", "--name-only"),
    ],
}

DEFAULT_REPO_PROFILES = {
    "Rafa-Innerchispa/inneros": {
        "profile": "python-tests",
        "source_path": "/home/rlopez/inneros/inneros_core/workspaces/innerops-agentic-platform",
        "allowed_paths": [
            "agents_pool",
            "config",
            "docs",
            "infra",
            "modules",
            "platform",
            "scripts",
            "services",
            "tenants",
        ],
    },
    "Rafa-Innerchispa/ralphiia-ecosystem-core": {
        "profile": "ecosystem-core-docs",
        "allowed_paths": ["bootstrap", "contracts", "docs", "ops", "registry", "runbooks"],
    },
    "Rafa-Innerchispa/ralfi-ia-platform": {
        "profile": "ecosystem-core-docs",
        "allowed_paths": ["companies", "docs"],
    },
    "Rafa-Innerchispa/innerspark-workforce-ai": {
        "profile": "node-tests",
        "source_path": "/home/rlopez/inneros/inneros_core/workspaces/innerspark-workforce-ai",
        "package_roots": ["services/femar-mvp-core"],
        "allowed_paths": [
            "app",
            "components",
            "docs",
            "lib",
            "public",
            "scripts",
            "services",
            "src",
            "tests",
            "README.md",
            "package.json",
            "package-lock.json",
            "pnpm-lock.yaml",
            "tsconfig.json",
            "next.config.js",
            "next.config.mjs",
            "vite.config.ts",
        ],
    },
    "Rafa-Innerchispa/innerops-service-ops": {
        "profile": "node-tests",
        "source_path": "/home/rlopez/inneros/inneros_core/workspaces/innerops-service-ops",
        "package_roots": ["."],
        "allowed_paths": [
            "app",
            "components",
            "docs",
            "lib",
            "public",
            "scripts",
            "src",
            "tests",
            "AGENT_CONTRACT.md",
            "BASELINE_PROVENANCE.md",
            "DEPLOYMENT.md",
            "README.md",
            "package.json",
            "package-lock.json",
            "pnpm-lock.yaml",
            "tsconfig.json",
            "next.config.js",
            "next.config.mjs",
            "vite.config.ts",
        ],
    },
    "Rafa-Innerchispa/inneros-forensic-replay": {
        "profile": "python-tests",
        "source_path": "/home/rlopez/inneros/inneros_core/workspaces/inneros-forensic-replay",
        "package_roots": ["."],
        "allowed_paths": [
            "docs",
            "examples",
            "inneros_forensic_replay",
            "scripts",
            "src",
            "tests",
            "README.md",
            "pyproject.toml",
            "requirements.txt",
            "setup.py",
        ],
    },
    "Rafa-Innerchispa/innerops-agentic-platform": {
        "profile": "python-tests",
        "source_path": "/home/rlopez/inneros/inneros_core/workspaces/innerops-agentic-platform",
        "package_roots": ["platform", "."],
        "allowed_paths": [
            "app",
            "components",
            "docs",
            "lib",
            "public",
            "scripts",
            "src",
            "tests",
            "platform/inneros_core_runtime",
            "platform/raphiia_openai",
            "platform/tests",
            "platform/pyproject.toml",
            "BASELINE_PROVENANCE.md",
            "AGENT_CONTRACT.md",
            "DEPLOYMENT.md",
            "README.md",
            "platform/package.json",
            "package.json",
            "package-lock.json",
            "pnpm-lock.yaml",
            "tsconfig.json",
            "next.config.js",
            "next.config.mjs",
            "vite.config.ts",
        ],
    },
    "Rafa-Innerchispa/amd-ralfiia-hybrid-ops-copilot": {
        "profile": "python-tests",
        "source_path": "/home/rlopez/inneros/inneros_core/workspaces/amd-ralfiia-hybrid-ops-copilot",
        "package_roots": ["."],
        "allowed_paths": [
            "agent_smart_quoter",
            "agent_watchdog",
            "backend",
            "docs",
            "scripts",
            "shared",
            "src",
            "tests",
            "track1_agent",
            "track2_agent",
            "ui",
            "README.md",
            "docker-compose.yml",
            "requirements.txt",
            "pyproject.toml",
        ],
    },
    "Rafa-Innerchispa/hyperloom-r9700-experimental": {
        "profile": "python-tests",
        "source_path": "/home/rlopez/inneros/inneros_core/workspaces/hyperloom-r9700-experimental",
        "package_roots": ["."],
        "allowed_paths": [
            "backend",
            "docs",
            "examples",
            "hyperloom",
            "scripts",
            "src",
            "tests",
            "README.md",
            "pyproject.toml",
            "requirements.txt",
            "setup.py",
        ],
    },
    "Rafa-Innerchispa/infralens-ocr-amd": {
        "profile": "python-tests",
        "source_path": "/home/rlopez/inneros/inneros_core/workspaces/infralens-ocr-amd",
        "package_roots": ["app", "demo", "."],
        "allowed_paths": [
            "app",
            "demo",
            "docs",
            "scripts",
            "tests",
            "README.md",
            "pyproject.toml",
            "requirements.txt",
            "Dockerfile",
            "Dockerfile.presentation",
            "docker-compose.presentation.yml",
        ],
    },
    "Rafa-Innerchispa/inneros-dmx-engine": {
        "profile": "python-tests",
        "source_path": "/home/rlopez/inneros/inneros_core/workspaces/inneros-dmx-engine",
        "package_roots": ["."],
        "allowed_paths": [
            "src",
            "tests",
            "docs",
            "scripts",
            "config",
            "systemd",
            "README.md",
            "pyproject.toml",
            "requirements.txt",
            "docker-compose.yml",
        ],
    },
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_dt(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if not value:
        return None
    try:
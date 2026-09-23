#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from inneros_core_runtime import local_github_plane as ghp
from inneros_core_runtime import local_gitlab_plane as glp

OWNER = "Rafa-Innerchispa"
STATE = Path("/home/rlopez/inneros/inneros_core/var/repo_sovereignty/portfolio-metadata.json")

BASE_TOPICS = ["inneros", "agentic-ai", "local-first", "governed-ai"]

PORTFOLIO = {
    "innerops-agentic-platform": {
        "description": "Core InnerOS platform for governed multi-agent coordination, local/cloud routing, bounded execution, recovery, and evidence.",
        "topics": BASE_TOPICS + ["multi-agent", "mcp", "a2a", "orchestration"],
    },
    "inneros-personal-brain": {
        "description": "InnerOS cognitive and memory layer: sovereign long-term context, live perception, governed reasoning, and cross-agent memory.",
        "topics": BASE_TOPICS + ["memory", "cognee", "strands-agents", "bright-data"],
    },
    "inneros-physical-guardian-ai-infra-2026": {
        "description": "AI Infra Summit validation of InnerOS Physical Guardian: perception, policy, approval, action, verification, and evidence.",
        "topics": BASE_TOPICS + ["physical-ai", "edge-ai", "computer-vision", "hackathon"],
    },
    "inneros-voiceops-assemblyai": {
        "description": "AssemblyAI validation of InnerOS VoiceOps: realtime speech as an interface to governed execution, approval, and evidence.",
        "topics": BASE_TOPICS + ["voice-ai", "assemblyai", "speech-to-text", "hackathon"],
    },
    "innerspark-workforce-ai": {
        "description": "Workforce operations product for attendance, incidents, reporting, and deterministic pre-payroll automation.",
        "topics": BASE_TOPICS + ["workforce", "payroll", "operations", "automation"],
    },
    "inneros-executable-world-2026": {
        "description": "Executable World validation of provider-agnostic InnerOS execution, permits, approvals, evidence, and optional adapters.",
        "topics": BASE_TOPICS + ["execution", "human-in-the-loop", "evidence", "hackathon"],
    },
    "inneros-amd-act-iii": {
        "description": "AMD/ROCm R&D track for sovereign local inference, capability routing, execution evidence, and replay in InnerOS.",
        "topics": BASE_TOPICS + ["amd", "rocm", "vllm", "local-llm"],
    },
    "inneros-fieldops-agents-for-humans": {
        "description": "AWS hackathon validation of governed physical-world workflows with approval, execution, verification, and evidence receipts.",
        "topics": BASE_TOPICS + ["aws", "field-operations", "human-in-the-loop", "hackathon"],
    },
    "inneros-webmcp": {
        "description": "Public-safe browser control surface for InnerOS local AI, project workspaces, execution lanes, evidence, and bounded physical control.",
        "topics": BASE_TOPICS + ["webmcp", "browser-agents", "mcp", "developer-tools"],
    },
    "inneros-forensic-replay": {
        "description": "Forensic evidence, deterministic replay, and counterfactual analysis for governed AI agents and operational decisions.",
        "topics": BASE_TOPICS + ["forensic-replay", "audit", "evidence", "observability"],
    },
    "inneros-engineering-journal": {
        "description": "Public engineering record of InnerOS architecture, failures, experiments, measurements, and lessons learned.",
        "topics": ["inneros", "engineering", "local-first", "agentic-ai", "architecture", "research-notes"],
    },
    "Rafa-Innerchispa": {
        "description": "Rafael Lopez / InnerChispa: InnerOS, sovereign local-first agentic infrastructure, operational AI products, and applied R&D.",
        "topics": ["inneros", "agentic-ai", "local-first", "ai-infrastructure", "portfolio"],
    },
    "ralphiia-founderos-openai": {
        "description": "FounderOS: an InnerOS operational layer connecting conversation, memory, infrastructure, software delivery and business workflows from anywhere.",
        "topics": ["inneros", "founderos", "agentic-ai", "mcp", "local-first", "memory", "developer-tools", "operations"],
    },
    "aegis-forkguard": {
        "description": "AEGIS ForkGuard: counterfactual pre-execution firewall for autonomous agents, evaluating safer futures before irreversible action.",
        "topics": ["inneros", "agent-safety", "counterfactual", "governed-ai", "jaclang", "audit", "human-in-the-loop", "security"],
    },
}

HYPERLOOM = {
    "hyperloom-r9700-experimental": "HyperLoom R9700 R&D hub for reproducible AMD/ROCm agentic-infrastructure experiments with explicit evidence and truth boundaries.",
    "hyperloom-r9700-container-baseline": "HyperLoom R9700 experiment: minimal container/runtime baseline for reproducible AMD/ROCm validation. Not a standalone product.",
    "hyperloom-r9700-live-ab": "HyperLoom R9700 experiment: live A/B validation path for AMD local inference. Not a standalone product.",
    "hyperloom-r9700-bridge-smoke": "HyperLoom R9700 probe: bounded bridge smoke test for the AMD/local execution fabric. Not a standalone product.",
    "hyperloom-r9700-tool-probe": "HyperLoom R9700 probe: isolated tool-contract validation for the InnerOS AMD research line. Not a standalone product.",
    "hyperloom-r9700-json-agent-smoke": "HyperLoom R9700 probe: JSON agent-output smoke test for deterministic local-agent integration. Not a standalone product.",
    "hyperloom-r9700-agent-smoke": "HyperLoom R9700 probe: minimal agent execution smoke test on the AMD/local runtime. Not a standalone product.",
    "hyperloom-r9700-autonomous-loop": "HyperLoom R9700 experiment: bounded autonomous-loop validation with evidence and failure boundaries. Not a standalone product.",
    "hyperloom-r9700-anthropic-bridge": "HyperLoom R9700 experiment: provider bridge validation against the local AMD execution fabric. Not a standalone product.",
    "hyperloom-r9700-live-runner": "HyperLoom R9700 experiment: live runner validation for local AMD workloads and evidence capture. Not a standalone product.",
    "hyperloom-r9700-evidence-reader": "HyperLoom R9700 probe: evidence-reader validation for auditable AMD/local executions. Not a standalone product.",
}

for name, description in HYPERLOOM.items():
    PORTFOLIO[name] = {
        "description": description,
        "topics": ["inneros", "hyperloom", "amd", "rocm", "r9700", "experiment"],
    }


def run(argv: list[str], timeout: int = 120) -> dict:
    proc = subprocess.run(argv, capture_output=True, text=True, timeout=timeout, check=False)
    return {
        "ok": proc.returncode == 0,
        "returncode": proc.returncode,
        "stdout": proc.stdout[-4000:],
        "stderr": proc.stderr[-4000:],
    }


def main() -> int:
    gh = ghp.shutil_which("gh")
    if not gh:
        STATE.parent.mkdir(parents=True, exist_ok=True)
        STATE.write_text(json.dumps({"ok": False, "error": "gh_unavailable"}, indent=2), encoding="utf-8")
        return 2

    rows = []
    failures = []
    for name, cfg in PORTFOLIO.items():
        full = f"{OWNER}/{name}"
        desc = cfg["description"]
        topics = list(dict.fromkeys(cfg["topics"]))[:20]

        edit = run([gh, "repo", "edit", full, "--description", desc], timeout=120)

        topic_args = [gh, "api", "--method", "PUT", f"repos/{full}/topics"]
        for topic in topics:
            topic_args += ["-f", f"names[]={topic}"]
        topic_result = run(topic_args, timeout=120)

        target_name = "VigilOS_Cursor-Antigravity" if name == "VigilOS_Cursor---Antigravity" else name
        target = f"rafagye/{target_name}"
        gl_project = glp.project_summary(target)
        gl_ok = False
        if gl_project.get("ok"):
            gl_edit = glp._request(
                "PUT",
                f"/projects/{glp.project_api_path(target)}",
                payload={"description": desc},
                timeout=30,
            )
            gl_ok = bool(gl_edit.get("ok"))
        else:
            gl_edit = {"ok": False, "error": "gitlab_project_missing"}

        row = {
            "repo": full,
            "github_description_ok": bool(edit.get("ok")),
            "github_topics_ok": bool(topic_result.get("ok")),
            "gitlab_description_ok": gl_ok,
            "topics": topics,
        }
        row["ok"] = row["github_description_ok"] and row["github_topics_ok"] and row["gitlab_description_ok"]
        rows.append(row)
        if not row["ok"]:
            failures.append({"repo": full, "github_edit": edit, "github_topics": topic_result, "gitlab": gl_edit})

    payload = {
        "ok": not failures,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "count": len(rows),
        "rows": rows,
        "failures": failures,
        "policy": "Portfolio metadata is concise, role-based, and consistent across GitHub/GitLab. HyperLoom child repositories are explicitly labeled experiments/probes.",
    }
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return 0 if payload["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

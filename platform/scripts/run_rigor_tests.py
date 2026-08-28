#!/usr/bin/env python3
"""Pruebas de rigor — WhatsApp NL, AG-05/07/17/20, dashboard, integración."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

EVIDENCE = os.path.expanduser(
    f"~/data/ai_coordination/evidence/rigor_tests_{time.strftime('%Y%m%d_%H%M%S')}.json"
)


def _run(name: str, fn) -> dict:
    t0 = time.time()
    try:
        r = fn()
        ok = bool(r.get("ok", True)) if isinstance(r, dict) else bool(r)
        err = r.get("error") if isinstance(r, dict) else None
    except Exception as exc:
        ok, r, err = False, {}, str(exc)
    return {"name": name, "ok": ok, "elapsed_s": round(time.time() - t0, 2), "error": err, "result": r}


def main() -> int:
    cases: list[dict] = []

    # Suite base
    proc = subprocess.run(
        [sys.executable, os.path.join(ROOT, "scripts/run_agent_integration_tests.py")],
        capture_output=True,
        text=True,
        env={**os.environ, "PYTHONPATH": ROOT},
        timeout=180,
    )
    cases.append({
        "name": "integration_suite",
        "ok": proc.returncode == 0,
        "stdout": proc.stdout[-500:],
        "stderr": proc.stderr[-300:] if proc.stderr else "",
    })

    cases.append(_run("whatsapp_ralfia_should_dispatch", lambda: {
        "ok": __import__("raphiia_openai.whatsapp_ralfia_bridge", fromlist=["should_ralfia_dispatch"]).should_ralfia_dispatch(
            "cómo va mi salud hoy",
            identity={"authenticated": True, "roles": ["owner"]},
        )
    }))

    cases.append(_run("whatsapp_ralfia_format", lambda: {
        "ok": True,
        **__import__("raphiia_openai.whatsapp_ralfia_bridge", fromlist=["dispatch_and_format"]).dispatch_and_format(
            "estado guardian", dry_run=True
        ),
    }))

    cases.append(_run("ag05_inbox", lambda: {
        "ok": True,
        **__import__("raphiia_openai.agents.pool_agent_runners", fromlist=["invoke_agent"]).invoke_agent("AG-05", "inbox", dry_run=False),
    }))

    cases.append(_run("ag07_notion", lambda: {
        "ok": True,
        **__import__("raphiia_openai.agents.pool_agent_runners", fromlist=["invoke_agent"]).invoke_agent("AG-07", "status", dry_run=False),
    }))

    cases.append(_run("ag17_ruc_validate", lambda: {
        "ok": True,
        "invalid": __import__(
            "raphiia_openai.agents.ag17_contifico_bridge_agent", fromlist=["validate_ecuador_tax_id"]
        ).validate_ecuador_tax_id("123"),
    }))

    cases.append(_run("ag20_dashboard", lambda: {
        "ok": True,
        **__import__("raphiia_openai.agents.pool_agent_runners", fromlist=["invoke_agent"]).invoke_agent("AG-20", "", dry_run=False),
    }))

    proc2 = subprocess.run(
        [sys.executable, os.path.join(ROOT, "scripts/generate_hub_fleet_dashboard.py")],
        capture_output=True,
        text=True,
        env={**os.environ, "PYTHONPATH": ROOT},
        timeout=120,
    )
    cases.append({"name": "hub_fleet_dashboard", "ok": proc2.returncode == 0, "stdout": proc2.stdout.strip()})

    cases.append(_run("preview_whatsapp_ralfia", lambda: {
        "ok": True,
        **__import__("raphiia_openai.whatsapp_ralfia_bridge", fromlist=["dispatch_and_format"]).dispatch_and_format(
            "estado guardian servicios", dry_run=True
        ),
    }))

    failed = [c["name"] for c in cases if not c.get("ok")]
    report = {"ok": not failed, "passed": sum(1 for c in cases if c.get("ok")), "total": len(cases), "failed": failed, "cases": cases}
    os.makedirs(os.path.dirname(EVIDENCE), exist_ok=True)
    with open(EVIDENCE, "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2, ensure_ascii=False, default=str)
    print(f"rigor: {report['passed']}/{report['total']} failed={failed or 'none'}")
    print(f"evidence: {EVIDENCE}")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

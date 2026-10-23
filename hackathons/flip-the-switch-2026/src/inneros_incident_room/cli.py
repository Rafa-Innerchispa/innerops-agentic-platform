"""Offline demonstration of generic reusable primitives, not a Switch demo."""
from __future__ import annotations

import argparse
from dataclasses import asdict
import json
from pathlib import Path

from .core import HumanApproval, PolicyDenied, execute_fixture, load_incident_dict, propose_actions


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Offline-only, synthetic incident fixture")
    parser.add_argument("--fixture", default=str(Path(__file__).resolve().parents[2] / "fixtures" / "synthetic_incident.json"))
    parser.add_argument("--decision", choices=("approve", "deny", "none"), default="none")
    args = parser.parse_args(argv)

    data = json.loads(Path(args.fixture).read_text(encoding="utf-8"))
    incident = load_incident_dict(data["incident"])
    state = dict(data["state"])
    actions = propose_actions(incident)
    observations = execute_fixture(actions[0], incident, state)
    approval = None
    if args.decision != "none":
        approval = HumanApproval(actions[1].action_id, incident.device_alias,
                                 "synthetic-human-reviewer", args.decision == "approve")
    try:
        remediation = asdict(execute_fixture(actions[1], incident, state, approval))
    except PolicyDenied as exc:
        remediation = {"outcome": "blocked_by_policy", "reason": str(exc)}
    print(json.dumps({"fixture_only": True, "switch_connected": False, "incident": asdict(incident),
                      "actions": [asdict(a) for a in actions],
                      "observation": asdict(observations), "remediation": remediation,
                      "final_state": state}, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Apply the bounded Dev Swarm repo-policy path fix to the scheduler.

The patch is deliberately source-drift sensitive. It changes only known
scheduler fragments and refuses to write when any expected fragment no longer
matches. Run with --check to validate applicability without changing the file.
"""

from __future__ import annotations

import argparse
from pathlib import Path

DEFAULT_TARGET = Path("platform/inneros_core_runtime/dev_swarm_scheduler.py")


def _replace_once(source: str, old: str, new: str, label: str) -> str:
    count = source.count(old)
    if count != 1:
        raise RuntimeError(f"source_drift:{label}:expected_once:found_{count}")
    return source.replace(old, new, 1)


def patch_scheduler_source(source: str) -> tuple[str, bool]:
    if "def _policy_product_path_instruction(" in source and "dev_swarm_path_guidance" in source:
        return source, False

    old_import = (
        "from raphiia_openai import capacity_governor_vnext, coordination_live, "
        "dev_swarm_watchdog, durable_coordination_spine, local_execution_plane, "
        "local_model_router, mongo_store, project_runtime_registry\n"
    )
    new_import = (
        "from raphiia_openai import capacity_governor_vnext, coordination_live, "
        "dev_swarm_path_guidance, dev_swarm_watchdog, durable_coordination_spine, "
        "local_execution_plane, local_model_router, mongo_store, project_runtime_registry\n"
    )
    source = _replace_once(source, old_import, new_import, "import")

    old_normalize = """        try:\n            local_execution_plane._validate_relative_path(normalized, [product_root])\n        except Exception as exc:\n"""
    new_normalize = """        try:\n            allowed_paths = _repo_allowed_paths(repo) or [product_root]\n            local_execution_plane._validate_relative_path(normalized, allowed_paths)\n        except Exception as exc:\n"""
    source = _replace_once(source, old_normalize, new_normalize, "normalize_policy")

    quality_marker = "\ndef _quality_gate_guidance(\n"
    helpers = """
def _repo_allowed_paths(repo: str) -> list[str]:
    try:
        return list(local_execution_plane._repo_config(repo).get("allowed_paths") or [])
    except Exception:
        return []


def _policy_product_path_instruction(repo: str, product_root: str) -> str:
    return dev_swarm_path_guidance.product_path_instruction(
        product_root,
        _repo_allowed_paths(repo),
    )


def _quality_gate_guidance(
"""
    source = _replace_once(source, quality_marker, helpers, "policy_helpers")

    old_guidance = """    if any(reason in reasons for reason in ("path_not_allowed_for_repo_profile", "path_outside_product_root", "path_traversal_denied")):\n        if product_root:\n            instructions.append(f"Use paths under {product_root}/src, {product_root}/app, {product_root}/lib, {product_root}/components, {product_root}/infra, or {product_root}/tests.")\n        else:\n            instructions.append("Use repo-relative paths under src, app, lib, components, infra, modules, or tests.")\n"""
    new_guidance = """    if any(reason in reasons for reason in ("path_not_allowed_for_repo_profile", "path_outside_product_root", "path_traversal_denied")):\n        instructions.append(_policy_product_path_instruction(repo, product_root))\n"""
    source = _replace_once(source, old_guidance, new_guidance, "quality_guidance")

    old_contract = """    path_contract = (\n        f"Product root is {product_root}. Return file paths either under {product_root}/... "\n        f"or relative to that product root such as src/..., components/... or tests/.... "\n        f"The executor will normalize product-relative paths to {product_root}/.... "\n        "Absolute paths, traversal, sibling services and repo-root writes outside the product root are denied."\n        if product_root\n        else "Return repo-relative file paths under src/, modules/, app/, lib/, components/, infra/ or tests/. Absolute paths and traversal are denied."\n    )\n"""
    new_contract = """    policy_path_instruction = _policy_product_path_instruction(repo, product_root)\n    path_contract = (\n        f"Product root is {product_root}. {policy_path_instruction} "\n        f"The executor normalizes product-relative paths to {product_root}/ only when repo policy permits them. "\n        "Absolute paths, traversal, sibling services and repo-root writes outside the product root are denied."\n        if product_root\n        else policy_path_instruction + " Absolute paths and traversal are denied."\n    )\n"""
    source = _replace_once(source, old_contract, new_contract, "prompt_path_contract")

    source = _replace_once(
        source,
        '            "At least one file must be product code under src/, modules/, app/, lib/, components/ or infra/ inside the product scope. "\n',
        '            "At least one file must be product code under a repo-policy product root listed above. "\n',
        "prompt_product_root",
    )

    source = _replace_once(
        source,
        '                "path_contract": {"product_root": product_root, "allowed_paths": [product_root] if product_root else list(local_execution_plane._repo_config(repo).get("allowed_paths") or [])},\n',
        '                "path_contract": {"product_root": product_root, "allowed_paths": _repo_allowed_paths(repo)},\n',
        "diagnostic_allowed_paths",
    )
    return source, True


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--path", type=Path, default=DEFAULT_TARGET)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    source = args.path.read_text(encoding="utf-8")
    patched, changed = patch_scheduler_source(source)
    if args.check:
        print("PATCH_APPLICABLE" if changed else "ALREADY_PATCHED")
        return 0
    if changed:
        args.path.write_text(patched, encoding="utf-8")
        print(f"PATCHED {args.path}")
    else:
        print(f"ALREADY_PATCHED {args.path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

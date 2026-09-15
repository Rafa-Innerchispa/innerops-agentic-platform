"""Repo-policy-derived path guidance for the local Dev Swarm.

Keep model repair prompts aligned with Local Execution Plane policy. This module
never broadens write access; it only projects already-allowed product roots into
human/model-readable guidance.
"""

from __future__ import annotations

from collections.abc import Iterable

PRODUCT_CODE_DIRS = frozenset(
    {
        "src",
        "modules",
        "app",
        "lib",
        "components",
        "infra",
        "commands",
        "backend",
        "inneros_core_runtime",
        "raphiia_openai",
    }
)


def allowed_product_code_roots(product_root: str, allowed_paths: Iterable[str]) -> list[str]:
    """Return policy-allowed roots that can contain real product code.

    Test/docs/config-only paths are intentionally excluded. A parent package
    root by itself is not expanded into imaginary subdirectories.
    """
    root = str(product_root or "").strip().replace("\\", "/").strip("/")
    prefix = f"{root}/" if root else ""
    result: list[str] = []

    for raw in allowed_paths:
        path = str(raw or "").strip().replace("\\", "/").strip("/")
        if not path or path == ".":
            continue
        if root:
            if path == root or not path.startswith(prefix):
                continue
            relative = path[len(prefix) :]
        else:
            relative = path
        head = relative.split("/", 1)[0]
        if head not in PRODUCT_CODE_DIRS:
            continue
        if path not in result:
            result.append(path)

    return result


def product_path_instruction(product_root: str, allowed_paths: Iterable[str]) -> str:
    """Build compact repair guidance without granting new filesystem scope."""
    roots = allowed_product_code_roots(product_root, allowed_paths)
    if roots:
        return "Use product-code paths only under these repo-policy roots: " + ", ".join(roots) + "."
    if product_root:
        return f"Use an existing product-code path already allowed under {product_root}/; do not invent a new root."
    return "Use an existing repo-policy product-code path; do not invent or broaden writable roots."

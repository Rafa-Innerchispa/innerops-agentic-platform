"""Repo-policy-derived path guidance for the local Dev Swarm.

Keep model repair prompts aligned with Local Execution Plane policy. This module
never broadens write access; it only projects already-allowed product roots into
human/model-readable guidance.
"""

from __future__ import annotations

from collections.abc import Iterable

CONVENTIONAL_PRODUCT_DIRS = (
    "src",
    "modules",
    "app",
    "lib",
    "components",
    "infra",
    "commands",
    "backend",
)
PRODUCT_CODE_DIRS = frozenset(
    (*CONVENTIONAL_PRODUCT_DIRS, "inneros_core_runtime", "raphiia_openai")
)


def _clean_paths(paths: Iterable[str]) -> list[str]:
    result: list[str] = []
    for raw in paths:
        path = str(raw or "").strip().replace("\\", "/").strip("/")
        if path and path not in result:
            result.append(path)
    return result


def _ancestor_scope_covers_root(product_root: str, allowed_paths: Iterable[str]) -> bool:
    """Return True when policy already grants the package root or an ancestor."""
    root = str(product_root or "").strip().replace("\\", "/").strip("/")
    if not root:
        return "." in _clean_paths(allowed_paths)
    for path in _clean_paths(allowed_paths):
        if path == "." or path == root or root.startswith(path + "/"):
            return True
    return False


def allowed_product_code_roots(product_root: str, allowed_paths: Iterable[str]) -> list[str]:
    """Return policy-allowed roots that can contain real product code.

    When policy grants the package root (or an ancestor), conventional product
    directories underneath it are valid. Otherwise only explicitly allowlisted
    descendant product-code roots are returned. Test/docs/config paths are never
    presented as product code.
    """
    root = str(product_root or "").strip().replace("\\", "/").strip("/")
    paths = _clean_paths(allowed_paths)
    prefix = f"{root}/" if root else ""

    if root and _ancestor_scope_covers_root(root, paths):
        return [f"{root}/{name}" for name in CONVENTIONAL_PRODUCT_DIRS]

    result: list[str] = []
    for path in paths:
        if not path or path == ".":
            continue
        if root:
            if not path.startswith(prefix):
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

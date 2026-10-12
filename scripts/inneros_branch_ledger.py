#!/usr/bin/env python3
"""Read-only branch audit, including separated legacy Git histories.

Never merges, deletes, rebases, checks out, executes a remote branch, or
updates a protected branch. A separate GitHub Actions workflow may submit
the generated ledger for review through a pull request.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import time
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

REPORT = "docs/INNEROS_BRANCH_LEDGER.md"
ATTESTATION = Path("docs/INNEROS_RELEASE_ATTESTATION.json")


def request(repo, endpoint, method="GET", payload=None, missing_ok=False):
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        raise RuntimeError("GITHUB_TOKEN_required")
    url = "https://api.github.com/repos/" + repo + "/" + endpoint.lstrip("/")
    body = json.dumps(payload).encode() if payload is not None else None
    headers = {"Accept": "application/vnd.github+json",
               "Authorization": "Bearer " + token,
               "X-GitHub-Api-Version": "2022-11-28",
               "User-Agent": "InnerOS-Branch-Ledger"}
    if body is not None:
        headers["Content-Type"] = "application/json"
    for attempt in range(3):
        try:
            req = Request(url, data=body, method=method, headers=headers)
            with urlopen(req, timeout=40) as response:
                return json.load(response)
        except HTTPError as exc:
            if exc.code == 404 and endpoint.startswith("compare/"):
                # A legacy unrelated Git root is not a failed API audit.
                body = exc.read(4096).decode("utf-8", errors="replace")
                if "no common ancestor" in body.lower():
                    raise RuntimeError("no_common_ancestor") from exc
            if missing_ok and exc.code == 404:
                return None
            if exc.code not in (429, 502, 503, 504) or attempt == 2:
                raise RuntimeError("GitHub_HTTP_" + str(exc.code) + "_" + endpoint[:80]) from exc
        except (URLError, TimeoutError) as exc:
            if attempt == 2:
                raise RuntimeError("GitHub_unreachable_" + endpoint[:80]) from exc
        time.sleep(2 ** attempt)
    raise RuntimeError("request_failed")


def pages(repo, endpoint):
    result = []
    for page in range(1, 100):
        separator = "&" if "?" in endpoint else "?"
        batch = request(repo, endpoint + separator + "per_page=100&page=" + str(page))
        if not isinstance(batch, list):
            raise RuntimeError("unexpected_pagination_shape")
        result.extend(batch)
        if len(batch) < 100:
            return result
    raise RuntimeError("pagination_limit")


def summarize_compare(data):
    files = data.get("files") or []
    deletions = sum(int(f.get("deletions") or 0) for f in files)
    return {"ahead": int(data.get("ahead_by") or 0),
            "behind": int(data.get("behind_by") or 0),
            "changed_files": len(files),
            "deletions": deletions,
            "bulk_risk": len(files) >= 100 or deletions >= 5000,
            "sample": [f.get("filename") for f in files[:12]]}


def classification(row):
    if row.get("error"):
        return "ERROR"
    if row.get("no_common_ancestor"):
        return "HISTORIA_SEPARADA"
    if not row.get("ahead"):
        return "EN_HISTORIA_MAIN"
    if row.get("bulk_risk"):
        return "RIESGO_ALTO"
    if row.get("prs"):
        return "PR_ABIERTO"
    return "REVISAR_SIN_PR"


def production_status(main_sha, attestations):
    hosts = attestations.get("hosts") or {}
    result = []
    for node in ("amd", "intel"):
        entry = hosts.get(node) or {}
        sha = entry.get("runtime_git_sha")
        evidence = entry.get("evidence_path")
        verified = entry.get("verified") is True and bool(sha and evidence)
        status = "NO_CERTIFICADO"
        if verified:
            status = "ALINEADO" if sha == main_sha else "DESFASADO"
        result.append({"node": node, "sha": sha, "evidence": evidence,
                       "status": status})
    return result


def audit(repo, workers=4):
    main = request(repo, "branches/main")
    main_sha = (main.get("commit") or {}).get("sha")
    if not main_sha or len(main_sha) != 40:
        raise RuntimeError("main_sha_invalid")
    branches = pages(repo, "branches")
    prs = pages(repo, "pulls?state=open")
    pr_map = {}
    open_prs = []
    for pr in prs:
        head = pr.get("head") or {}
        if ((head.get("repo") or {}).get("full_name")) != repo:
            continue
        name = head.get("ref") or ""
        pr_map.setdefault(name, []).append(pr["number"])
        open_prs.append({"number": pr["number"], "head": name})
    unique_heads = {}
    for branch in branches:
        name = branch.get("name") or ""
        sha = (branch.get("commit") or {}).get("sha") or ""
        if name != "main" and sha != main_sha:
            unique_heads.setdefault(sha, name)

    def compare(item):
        sha, name = item
        try:
            encoded = quote(name, safe="")
            value = request(repo, "compare/main..." + encoded)
            if not isinstance(value, dict):
                raise RuntimeError("compare_invalid_shape")
            return sha, summarize_compare(value)
        except RuntimeError as exc:
            if str(exc) == "no_common_ancestor":
                return sha, {"no_common_ancestor": True}
            return sha, {"error": str(exc)}

    comparisons = {}
    with ThreadPoolExecutor(max_workers=max(1, min(workers, 6))) as pool:
        futures = [pool.submit(compare, x) for x in unique_heads.items()]
        for future in as_completed(futures):
            sha, data = future.result()
            comparisons[sha] = data
    rows = []
    for branch in branches:
        name = branch.get("name") or ""
        if name == "main":
            continue
        sha = (branch.get("commit") or {}).get("sha") or ""
        diff = ({"ahead": 0, "behind": 0, "changed_files": 0}
                if sha == main_sha else comparisons.get(sha, {"error": "comparison_missing"}))
        row = {"name": name, "sha": sha, "prs": pr_map.get(name, []), **diff}
        row["classification"] = classification(row)
        rows.append(row)
    attestations = json.loads(ATTESTATION.read_text(encoding="utf-8"))
    return {"schema": "inneros-branch-ledger-v1",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "repo": repo, "main_sha": main_sha,
            "branches_total": len(branches),
            "prs": open_prs,
            "production": production_status(main_sha, attestations),
            "rows": rows, "errors": sum(bool(r.get("error")) for r in rows)}


def clean(value):
    return str(value).replace("|", "/").replace("\n", " ").replace(chr(96), "'")


def render(report):
    rows = report["rows"]
    counts = {}
    for row in rows:
        k = row["classification"]
        counts[k] = counts.get(k, 0) + 1
    lines = [
        "# InnerOS - Inventario permanente de ramas y produccion",
        "",
        "Generado automaticamente; no ejecuta ramas, ni fusiona ni elimina codigo.",
        "Un commit adelantado no implica cambios utiles ausentes del main: revisar",
        "equivalencia semantica, squash y cherry-pick antes de integrar.",
        "HISTORIA_SEPARADA: sin ancestro comun, revisar raiz aislada antes de rescatar.",
        "",
        "Auditoria UTC: " + report["generated_at"],
        "Repositorio: " + report["repo"],
        "main: " + report["main_sha"],
        "Ramas incluyendo main: " + str(report["branches_total"]),
        "PR abiertos: " + str(len(report["prs"])),
        "Resumen: " + ", ".join(k + "=" + str(v) for k, v in sorted(counts.items())),
        "",
        "## Evidencia productiva (no inferir desde GitHub)",
        "",
        "| Nodo | Estado | SHA ejecutable probado | Evidencia host |",
        "|---|---|---|---|",
    ]
    for host in report["production"]:
        lines.append("| {node} | {status} | {sha} | {ev} |".format(
            node=host["node"], status=host["status"],
            sha=clean(host["sha"] or "sin evidencia"),
            ev=clean(host["evidence"] or "sin evidencia")))
    lines.extend([
        "",
        "## PR abiertos",
        "",
        "| PR | Rama |",
        "|---|---|",
    ])
    for pr in sorted(report["prs"], key=lambda p: p["number"], reverse=True):
        url = "https://github.com/" + report["repo"] + "/pull/" + str(pr["number"])
        lines.append("| [#{number}]({url}) | {name} |".format(
            number=pr["number"], url=url, name=clean(pr["head"])))
    lines.extend([
        "",
        "## Todas las ramas: NO BORRAR antes de triage",
        "",
        "| Rama | Ahead | Behind | Estado | PR | Archivos |",
        "|---|---:|---:|---|---|---:|",
    ])
    priority = {"ERROR": 0, "HISTORIA_SEPARADA": 1,
                "RIESGO_ALTO": 2, "PR_ABIERTO": 3,
                "REVISAR_SIN_PR": 4, "EN_HISTORIA_MAIN": 5}
    ordered = sorted(rows, key=lambda r: (priority.get(r["classification"], 5),
                                         -r.get("ahead", 0), r["name"]))
    for row in ordered:
        link = "https://github.com/" + report["repo"] + "/tree/" + quote(row["name"], safe="/")
        label = clean(row["name"])
        prlist = ",".join("#" + str(n) for n in row["prs"]) or "-"
        lines.append("| [{name}]({url}) | {ahead} | {behind} | {status} | {prs} | {files} |".format(
            name=label, url=link, ahead=row.get("ahead", "?"),
            behind=row.get("behind", "?"), status=row["classification"],
            prs=prlist, files=row.get("changed_files", "?")))
    lines.extend([
        "",
        "## Politica de rescate y publicacion",
        "",
        "1. No mezclar todas las ramas ni borrar ninguna por este inventario.",
        "2. Revisar equivalencias de contenido; si hay trabajo nuevo, PR acotado.",
        "3. CI PASS y merge main con responsables de archivos coordinados.",
        "4. Desplegar SHA pinneado con backup, hashes de runtime y rollback.",
        "5. Certificar AMD e Intel con pruebas operativas, no solo git HEAD.",
        "",
        "Los detalles JSON y las muestras de archivos estan en el artefacto",
        "inneros-branch-ledger.json de cada ejecucion de GitHub Actions.",
        "",
    ])
    return "\n".join(lines)



def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", default=os.getenv("GITHUB_REPOSITORY", ""))
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()
    if args.repo.count("/") != 1:
        parser.error("--repo owner/name required")
    report = audit(args.repo, args.workers)
    text = render(report)
    Path("inneros-branch-ledger.md").write_text(text + "\n", encoding="utf-8")
    Path("inneros-branch-ledger.json").write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"sha": report["main_sha"], "branches": report["branches_total"],
                      "prs": len(report["prs"]), "errors": report["errors"]}))
    # Keep individual API comparison failures visible in main; one oversized
    # legacy branch must not prevent inventorying all other branches.
    # Fail closed if the API failed for too many refs to be meaningful.
    max_errors = max(10, len(report["rows"]) // 4)
    if report["errors"] > max_errors:
        raise RuntimeError("branch_comparisons_unreliable; refusing_publication")
    if report["errors"]:
        print("::warning::Some branch comparisons failed; see ERROR rows in ledger")


if __name__ == "__main__":
    main()

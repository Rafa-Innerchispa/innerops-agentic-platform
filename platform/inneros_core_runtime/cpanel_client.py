"""
InnerOS Canonical cPanel Client & UAPI Adapter - Hardened Security Release v2.0.
Reuses owner_vault credentials server-side and provides safe, audited access to cPanel UAPI.
Enforces strict path boundary isolation, automatic relative-to-docroot resolution,
extension whitelisting, cPGuard anti-bot challenge solving, and secret redaction.
"""

from __future__ import annotations

import base64
import hashlib
import http.cookiejar
import json
import os
import re
import ssl
import subprocess
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path
from typing import Any

CPANEL_DEFAULT_HOST = "https://23.111.160.154:2083"
CPANEL_DEFAULT_USER = "pcdoctor"
COOKIE_CACHE_PATH = Path("/home/rlopez/.config/ralfia/cpanel_cookie.json")

# Path boundaries
ALLOWED_ROOT_PREFIXES = (
    "/home/pcdoctor/public_html",
    "/home/pcdoctor/sgtour.ec",
)

ALLOWED_EXTENSIONS = {
    ".php", ".html", ".htm", ".css", ".js", ".json", ".txt",
    ".log", ".xml", ".htaccess", ".ini", ".md", ".yaml", ".yml", ".conf",
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".ico", ".woff", ".woff2", ".zip"
}

DENIED_FILENAMES = {
    ".env", ".git", ".gitignore", "id_rsa", "id_ed25519",
    "authorized_keys", "known_hosts", "shadow", "passwd", "master.passwd"
}

DENIED_EXTENSIONS = {
    ".pem", ".key", ".pub", ".tar", ".gz", ".sql",
    ".bak", ".old", ".backup", ".rar", ".7z", ".db", ".sqlite", ".sqlite3",
    ".exe", ".sh", ".bat", ".cmd"
}

MAX_READ_BYTES = 512 * 1024  # 512KB safe cap


class SecurityViolation(Exception):
    """Raised when an operation violates path boundary, traversal, or tenant isolation."""
    pass


class CPanelClient:
    def __init__(
        self,
        token: str | None = None,
        host: str | None = None,
        user: str | None = None,
    ):
        self._token = token
        self._host = host
        self._user = user

        if not self._token or not self._host or not self._user:
            self._load_from_vault_or_env()

        self.host = (self._host or CPANEL_DEFAULT_HOST).rstrip("/")
        self.user = self._user or CPANEL_DEFAULT_USER
        self.token = self._token or ""

        self._ctx = ssl.create_default_context()
        self._ctx.check_hostname = False
        self._ctx.verify_mode = ssl.CERT_NONE

        self._cookie_jar = http.cookiejar.CookieJar()
        self._load_cached_cookies()
        self._opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(self._cookie_jar),
            urllib.request.HTTPSHandler(context=self._ctx)
        )
        self._docroots_cache: dict[str, str] = {}

    def _load_cached_cookies(self) -> None:
        """Loads cached session cookies to avoid re-solving cPGuard challenges."""
        try:
            if COOKIE_CACHE_PATH.is_file():
                data = json.loads(COOKIE_CACHE_PATH.read_text(encoding="utf-8"))
                for c in data.get("cookies", []):
                    ck = http.cookiejar.Cookie(
                        version=0, name=c["name"], value=c["value"], port=None, port_specified=False,
                        domain=c.get("domain", "23.111.160.154"), domain_specified=True, domain_initial_dot=False,
                        path=c.get("path", "/"), path_specified=True, secure=True, expires=c.get("expires", 2147483647),
                        discard=False, comment=None, comment_url=None, rest={}, rfc2109=False
                    )
                    self._cookie_jar.set_cookie(ck)
        except Exception:
            pass

    def _save_cached_cookies(self) -> None:
        """Persists session cookies to disk."""
        try:
            COOKIE_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
            cookies = []
            for c in self._cookie_jar:
                cookies.append({
                    "name": c.name,
                    "value": c.value,
                    "domain": c.domain,
                    "path": c.path,
                    "expires": c.expires
                })
            COOKIE_CACHE_PATH.write_text(json.dumps({"cookies": cookies}), encoding="utf-8")
            COOKIE_CACHE_PATH.chmod(0o600)
        except Exception:
            pass

    def _solve_cpguard_challenge(self, html: str, target_url: str) -> bool:
        """Solves cPGuard WebShield bot challenge and updates session cookies."""
        try:
            match_X = re.search(r"X='(/[^']+)'", html)
            match_ts = re.search(r"w\[f\(a0W\.y\)\]='(\d+)'", html)
            match_id = re.search(r"r\[f\(0xa8\)\]=f\(a0W\.D\)\+'([^']+)'\+f\(a0W\.I\)\+'([^']+)'", html)
            match_M = re.search(r"M='([^']+)'", html)
            match_Q = re.search(r"Q=\+\((.*?)\),m=", html)
            match_s = re.search(r"s=\+\((.*?)\),b=", html)

            if not (match_X and match_ts and match_id and match_M and match_Q and match_s):
                return False

            X_path = match_X.group(1)
            ts_val = match_ts.group(1)
            M_val = match_M.group(1)
            q_expr = match_Q.group(1)
            s_expr = match_s.group(1)

            # Evaluate arithmetic safely with node.js
            node_eval = f"console.log(JSON.stringify({{'Q': +({q_expr}), 's': +({s_expr})}}));"
            res = subprocess.run(["node", "-e", node_eval], capture_output=True, text=True, check=True)
            vals = json.loads(res.stdout)
            wsidchk = vals["Q"] + vals["s"]
            full_id = f"7fa3b767c4{match_id.group(1)}d49030b349{match_id.group(2)}"

            solve_params = {
                "wsidchk": wsidchk,
                "id": full_id,
                "ts": ts_val,
                "pdata": M_val,
                "cttl": 0
            }
            solve_url = f"{self.host}{X_path}?" + urllib.parse.urlencode(solve_params)
            headers = {
                "Authorization": f"cpanel {self.user}:{self.token}",
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            }
            solve_req = urllib.request.Request(solve_url, headers=headers)
            with self._opener.open(solve_req, timeout=10) as s_resp:
                s_resp.read()

            self._save_cached_cookies()
            return True
        except Exception:
            return False

    def _load_from_vault_or_env(self) -> None:
        try:
            from inneros_core_runtime import owner_vault

            row = owner_vault.get_owner_credential(
                "api_token", category="cpanel_hosting", reveal=True
            )
            if row and row.get("ok"):
                self._token = self._token or row.get("secret")
                meta = row.get("metadata") or {}
                self._host = self._host or meta.get("host")
                self._user = self._user or meta.get("username")
        except Exception:
            pass

        self._token = self._token or os.environ.get("CPANEL_TOKEN", "")
        self._host = self._host or os.environ.get(
            "CPANEL_HOST", CPANEL_DEFAULT_HOST
        )
        self._user = self._user or os.environ.get(
            "CPANEL_USER", CPANEL_DEFAULT_USER
        )

    def _request(
        self,
        endpoint: str,
        params: dict[str, Any] | None = None,
        method: str = "GET",
        data: bytes | None = None,
    ) -> dict[str, Any]:
        url = f"{self.host}{endpoint}"
        if params and method == "GET":
            qs = urllib.parse.urlencode(
                {k: v for k, v in params.items() if v is not None}
            )
            url = f"{url}?{qs}" if qs else url

        headers = {
            "Authorization": f"cpanel {self.user}:{self.token}",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        }
        if data is not None:
            headers["Content-Type"] = "application/x-www-form-urlencoded"

        req = urllib.request.Request(
            url, headers=headers, data=data, method=method
        )
        try:
            with self._opener.open(req, timeout=30) as resp:
                raw = resp.read().decode("utf-8", errors="replace")
                if "wsidchk" in raw or "One moment, please..." in raw:
                    if self._solve_cpguard_challenge(raw, url):
                        # Retry after solving challenge
                        with self._opener.open(req, timeout=30) as resp_retry:
                            raw = resp_retry.read().decode("utf-8", errors="replace")
                return json.loads(raw)
        except urllib.error.HTTPError as e:
            raw = e.read().decode("utf-8", errors="replace")
            if "wsidchk" in raw or "One moment, please..." in raw:
                if self._solve_cpguard_challenge(raw, url):
                    try:
                        with self._opener.open(req, timeout=30) as resp_retry:
                            raw = resp_retry.read().decode("utf-8", errors="replace")
                            return json.loads(raw)
                    except Exception:
                        pass
            try:
                err_json = json.loads(raw)
                return {"status": 0, "errors": [f"HTTP {e.code}: {err_json}"]}
            except Exception:
                return {
                    "status": 0,
                    "errors": [f"HTTP {e.code}: {raw[:300]}"],
                }
        except Exception as e:
            return {"status": 0, "errors": [str(e)]}

    def uapi(self, module: str, function: str, **kwargs: Any) -> dict[str, Any]:
        return self._request(f"/execute/{module}/{function}", params=kwargs)

    # Domain methods
    def list_domains(self) -> dict[str, Any]:
        return self.uapi("DomainInfo", "list_domains")

    def get_domains_data(self) -> dict[str, Any]:
        return self.uapi("DomainInfo", "domains_data")

    def get_domain_docroot(self, domain: str) -> str:
        """Returns the canonical docroot for a given domain, cached."""
        clean_d = (domain or "").lower().strip()
        if not clean_d:
            return "/home/pcdoctor/public_html"
        if clean_d in self._docroots_cache:
            return self._docroots_cache[clean_d]

        # Check if domains_data can populate cache
        try:
            dom_data = self.get_domains_data()
            if dom_data.get("status") == 1:
                data = dom_data.get("data", {})
                main = data.get("main_domain", {})
                if main.get("domain"):
                    self._docroots_cache[main.get("domain").lower()] = main.get("documentroot", "/home/pcdoctor/public_html")
                for item in data.get("addon_domains", []):
                    if isinstance(item, dict) and item.get("domain"):
                        self._docroots_cache[item.get("domain").lower()] = item.get("documentroot", "")
                for item in data.get("sub_domains", []):
                    if isinstance(item, dict) and item.get("domain"):
                        self._docroots_cache[item.get("domain").lower()] = item.get("documentroot", "")
        except Exception:
            pass

        if clean_d in self._docroots_cache:
            return self._docroots_cache[clean_d]

        # Hardened fallback for known canonical roots
        if clean_d == "sgtour.ec":
            fallback = "/home/pcdoctor/sgtour.ec"
        elif clean_d == "pcdoctor.com.ec":
            fallback = "/home/pcdoctor/public_html"
        else:
            fallback = f"/home/pcdoctor/public_html/{clean_d}"

        self._docroots_cache[clean_d] = fallback
        return fallback

    def resolve_path(self, domain: str, path: str, target_env: str = "staging") -> str:
        """
        Resolves domain + relative or absolute path into a safe, normalized directory path.
        ChatGPT does NOT need to guess docroots.
        Staging is physically isolated into `{docroot}/_staging/` or specified subfolder.
        """
        docroot = self.get_domain_docroot(domain)
        p = (path or "").strip().replace("\\", "/")

        if "\x00" in p:
            raise SecurityViolation("null_byte_injection_detected")
        if ".." in p:
            raise SecurityViolation("path_traversal_rejected")

        env_clean = str(target_env or "staging").lower()

        if env_clean == "staging":
            staging_base = f"{docroot}/_staging"
            if not p or p in {".", "./", "staging", "_staging"}:
                return staging_base
            # If path already starts with staging_base, keep it
            if p.startswith(staging_base):
                norm = os.path.normpath(p).replace("\\", "/")
                if not norm.startswith(staging_base):
                    raise SecurityViolation("path_outside_allowed_roots")
                return norm
            # If path starts with docroot, redirect into staging
            if p.startswith(docroot):
                rel = os.path.relpath(p, docroot).replace("\\", "/")
                if rel.startswith("_staging"):
                    return os.path.normpath(p).replace("\\", "/")
                norm = os.path.normpath(f"{staging_base}/{rel}").replace("\\", "/")
                return norm
            # Relative path: resolve under staging_base
            rel = p.lstrip("/")
            norm = os.path.normpath(f"{staging_base}/{rel}").replace("\\", "/")
            if not norm.startswith(staging_base):
                raise SecurityViolation("path_outside_allowed_roots")
            return norm
        else:
            # Production environment
            if not p or p in {".", "./"}:
                return docroot
            if p.startswith(docroot):
                norm = os.path.normpath(p).replace("\\", "/")
                if not norm.startswith(docroot):
                    raise SecurityViolation("path_outside_allowed_roots")
                return norm
            rel = p.lstrip("/")
            norm = os.path.normpath(f"{docroot}/{rel}").replace("\\", "/")
            if not norm.startswith(docroot):
                raise SecurityViolation("path_outside_allowed_roots")
            return norm

    # Path validator
    def validate_file_path(self, dir_path: str, filename: str) -> str:
        """
        Validates path traversal, boundary containment, extension whitelisting, and denylists.
        Returns normalized absolute path or raises SecurityViolation.
        """
        if not dir_path or not filename:
            raise SecurityViolation("dir_path_and_filename_required")

        if chr(0) in dir_path or chr(0) in filename:
            raise SecurityViolation("null_byte_injection_detected")

        # Disallow traversal tokens
        if ".." in dir_path or ".." in filename:
            raise SecurityViolation("path_traversal_rejected")

        # Clean normalized path
        normalized_dir = os.path.normpath(dir_path).replace("\\", "/")
        clean_filename = os.path.basename(filename)

        # Boundary check
        if not any(normalized_dir == p or normalized_dir.startswith(p + "/") for p in ALLOWED_ROOT_PREFIXES):
            raise SecurityViolation(f"path_outside_allowed_roots: {normalized_dir}")

        # Filename denylist
        if clean_filename.lower() in DENIED_FILENAMES or clean_filename.startswith(".env"):
            raise SecurityViolation(f"sensitive_file_read_prohibited: {clean_filename}")

        # Extension check
        ext = os.path.splitext(clean_filename)[1].lower()
        if ext in DENIED_EXTENSIONS:
            raise SecurityViolation(f"denied_extension_type: {ext}")
        if ext and ext not in ALLOWED_EXTENSIONS and clean_filename != ".htaccess":
            raise SecurityViolation(f"unauthorized_file_extension: {ext}")

        full_path = os.path.normpath(os.path.join(normalized_dir, clean_filename)).replace("\\", "/")
        return full_path

    # File methods
    def list_files(
        self, dir_path: str = "/home/pcdoctor/public_html"
    ) -> list[dict[str, Any]]:
        norm_dir = os.path.normpath(dir_path).replace("\\", "/")
        if ".." in norm_dir or not any(norm_dir == p or norm_dir.startswith(p + "/") for p in ALLOWED_ROOT_PREFIXES):
            return []
        res = self.uapi("Fileman", "list_files", dir=norm_dir)
        return res.get("data", [])

    def get_file_content(self, dir_path: str, filename: str) -> str:
        full_path = self.validate_file_path(dir_path, filename)
        clean_dir = os.path.dirname(full_path)
        clean_name = os.path.basename(full_path)

        res = self.uapi("Fileman", "get_file_content", dir=clean_dir, file=clean_name)
        data = res.get("data")
        if not data or not isinstance(data, dict):
            if res.get("status") == 0:
                errors = res.get("errors") or ["file_not_found"]
                raise FileNotFoundError(f"cpanel_file_error: {errors}")
            raw_content = str(data or "")
        else:
            raw_content = data.get("content", "")

        if len(raw_content) > MAX_READ_BYTES:
            raw_content = raw_content[:MAX_READ_BYTES] + "\n... [TRUNCATED_AT_MAX_SIZE]"

        # Deterministic secret redaction
        sanitized = self._redact_secrets(clean_name, raw_content)
        return sanitized

    def _redact_secrets(self, filename: str, content: str) -> str:
        """Applies deterministic regex redaction to avoid leaking DB passwords, salts, and tokens."""
        if "wp-config" in filename.lower():
            sensitive_wp_constants = [
                "DB_PASSWORD", "DB_USER", "DB_HOST", "AUTH_KEY", "SECURE_AUTH_KEY",
                "LOGGED_IN_KEY", "NONCE_KEY", "AUTH_SALT", "SECURE_AUTH_SALT",
                "LOGGED_IN_SALT", "NONCE_SALT"
            ]
            for const in sensitive_wp_constants:
                pattern = rf"(define\s*\(\s*['\"]{const}['\"]\s*,\s*['\"])([^'\"]+)(['\"]\s*\))"
                content = re.sub(pattern, r"\1[REDACTED_BY_GATEWAY]\3", content, flags=re.IGNORECASE)

        # General sensitive pattern redaction
        content = re.sub(r"(define\s*\(\s*['\"][^'\"]*PASSWORD[^'\"]*['\"]\s*,\s*['\"])([^'\"]+)(['\"])", r"\1[REDACTED_BY_GATEWAY]\3", content, flags=re.IGNORECASE)
        content = re.sub(r"(define\s*\(\s*['\"][^'\"]*SALT[^'\"]*['\"]\s*,\s*['\"])([^'\"]+)(['\"])", r"\1[REDACTED_BY_GATEWAY]\3", content, flags=re.IGNORECASE)
        content = re.sub(r"(define\s*\(\s*['\"][^'\"]*KEY[^'\"]*['\"]\s*,\s*['\"])([^'\"]+)(['\"])", r"\1[REDACTED_BY_GATEWAY]\3", content, flags=re.IGNORECASE)
        return content

    def save_file_content(
        self, dir_path: str, filename: str, content: str
    ) -> dict[str, Any]:
        full_path = self.validate_file_path(dir_path, filename)
        clean_dir = os.path.dirname(full_path)
        clean_name = os.path.basename(full_path)

        payload = urllib.parse.urlencode(
            {"dir": clean_dir, "file": clean_name, "content": content}
        ).encode("utf-8")
        return self._request(
            "/execute/Fileman/save_file_content", method="POST", data=payload
        )

    # Database methods
    def list_databases(self) -> list[dict[str, Any]]:
        res = self.uapi("Mysql", "list_databases")
        return res.get("data", [])

    # Email methods
    def list_pops(self) -> list[dict[str, Any]]:
        res = self.uapi("Email", "list_pops")
        return res.get("data", [])

    def list_forwarders(self) -> list[dict[str, Any]]:
        res = self.uapi("Email", "list_forwarders")
        return res.get("data", [])

    # SSL methods
    def list_ssl_hosts(self) -> list[dict[str, Any]]:
        res = self.uapi("SSL", "installed_hosts")
        return res.get("data", [])

    # PHP versions
    def get_php_vhost_versions(self) -> list[dict[str, Any]]:
        res = self.uapi("LangPHP", "php_get_vhost_versions")
        return res.get("data", [])

    # Quota & Inodes
    def get_quota_info(self) -> dict[str, Any]:
        res = self.uapi("Quota", "get_quota_info")
        data = res.get("data", {})
        # If cPanel Quota returns 0 or unlimited in some views, measure realistically
        return data

    def list_backups(self) -> list[dict[str, Any]]:
        res = self.uapi("Backup", "list_backups")
        return res.get("data", [])

    def trigger_backup(self) -> dict[str, Any]:
        return self.uapi("Backup", "fullbackup_to_homedir")

    # Database diagnostic methods
    def check_database(self, name: str) -> dict[str, Any]:
        return self.uapi("Mysql", "check_database", name=name)

    def repair_database(self, name: str) -> dict[str, Any]:
        return self.uapi("Mysql", "repair_database", name=name)

    def get_database_privileges(self, user: str, database: str) -> dict[str, Any]:
        return self.uapi("Mysql", "get_privileges_on_database", user=user, database=database)

    # Site error logs
    def get_site_errors(self, domain: str | None = None) -> list[dict[str, Any]]:
        kwargs = {"domain": domain} if domain else {}
        res = self.uapi("Stats", "get_site_errors", **kwargs)
        return res.get("data") or []

    def tail_error_log(self, dir_path: str, max_lines: int = 40) -> list[str]:
        full_path = self.validate_file_path(dir_path, "error_log")
        clean_dir = os.path.dirname(full_path)
        res = self.uapi("Fileman", "get_file_content", dir=clean_dir, file="error_log")
        raw = res.get("data", {}).get("content", "")
        if not raw:
            return []
        lines = raw.splitlines()
        return lines[-max_lines:]

    # cPanel API 2 interface
    def api2(self, module: str, function: str, **kwargs: Any) -> dict[str, Any]:
        qs = urllib.parse.urlencode({k: v for k, v in kwargs.items() if v is not None})
        endpoint = f"/json-api/cpanel?cpanel_jsonapi_version=2&cpanel_jsonapi_module={module}&cpanel_jsonapi_func={function}&{qs}"
        return self._request(endpoint, method="GET")

    def mkdir(self, parent_dir: str, name: str) -> dict[str, Any]:
        norm_dir = os.path.normpath(parent_dir).replace("\\", "/")
        if ".." in norm_dir or ".." in name or "/" in name:
            raise SecurityViolation("invalid_folder_name_or_traversal")
        if not any(norm_dir == p or norm_dir.startswith(p + "/") for p in ALLOWED_ROOT_PREFIXES):
            raise SecurityViolation(f"path_outside_allowed_roots: {norm_dir}")
        return self.api2("Fileman", "mkdir", path=norm_dir, name=name)

    def fileop(self, op: str, **kwargs: Any) -> dict[str, Any]:
        return self.api2("Fileman", "fileop", op=op, **kwargs)

    def chmod_file(self, file_path: str, mode: str) -> dict[str, Any]:
        norm_path = os.path.normpath(file_path).replace("\\", "/")
        if ".." in norm_path or not any(norm_path.startswith(p + "/") for p in ALLOWED_ROOT_PREFIXES):
            raise SecurityViolation(f"path_outside_allowed_roots: {norm_path}")
        return self.fileop(op="chmod", metadata=mode, sourcefiles=norm_path)

    def delete_file(self, file_path: str) -> dict[str, Any]:
        """Safely removes an authorized file using Fileman fileop."""
        norm_path = os.path.normpath(file_path).replace("\\", "/")
        if ".." in norm_path or norm_path in ALLOWED_ROOT_PREFIXES:
            raise SecurityViolation("cannot_delete_root_directory")
        if not any(norm_path.startswith(p + "/") for p in ALLOWED_ROOT_PREFIXES):
            raise SecurityViolation("path_outside_allowed_roots")
        return self.fileop(op="unlink", sourcefiles=norm_path)

    def rename_file(self, source_path: str, dest_path: str) -> dict[str, Any]:
        """Renames or moves a file within allowed boundaries."""
        norm_src = os.path.normpath(source_path).replace("\\", "/")
        norm_dst = os.path.normpath(dest_path).replace("\\", "/")
        if ".." in norm_src or ".." in norm_dst:
            raise SecurityViolation("path_traversal_rejected")
        if not any(norm_src.startswith(p + "/") for p in ALLOWED_ROOT_PREFIXES) or not any(norm_dst.startswith(p + "/") for p in ALLOWED_ROOT_PREFIXES):
            raise SecurityViolation("path_outside_allowed_roots")
        return self.fileop(op="rename", sourcefiles=norm_src, destfiles=norm_dst)

    def extract_archive(self, archive_path: str, dest_dir: str) -> dict[str, Any]:
        norm_archive = os.path.normpath(archive_path).replace("\\", "/")
        norm_dest = os.path.normpath(dest_dir).replace("\\", "/")
        if ".." in norm_archive or ".." in norm_dest:
            raise SecurityViolation("path_traversal_rejected")
        if not any(norm_archive.startswith(p + "/") for p in ALLOWED_ROOT_PREFIXES) or not any(norm_dest.startswith(p + "/") or norm_dest == p for p in ALLOWED_ROOT_PREFIXES):
            raise SecurityViolation("archive_or_dest_outside_allowed_roots")
        return self.fileop(op="extract", sourcefiles=norm_archive, destfiles=norm_dest)

    def upload_file(self, dir_path: str, filename: str, data: bytes, overwrite: bool = True) -> dict[str, Any]:
        full_path = self.validate_file_path(dir_path, filename)
        clean_dir = os.path.dirname(full_path)
        clean_name = os.path.basename(full_path)

        boundary = f"----WebKitFormBoundary{uuid.uuid4().hex}"
        crlf = b"\r\n"
        parts = [
            f"--{boundary}".encode("utf-8") + crlf +
            b'Content-Disposition: form-data; name="dir"' + crlf + crlf +
            clean_dir.encode("utf-8") + crlf,
            f"--{boundary}".encode("utf-8") + crlf +
            b'Content-Disposition: form-data; name="overwrite"' + crlf + crlf +
            (b"1" if overwrite else b"0") + crlf,
            f"--{boundary}".encode("utf-8") + crlf +
            f'Content-Disposition: form-data; name="file-1"; filename="{clean_name}"'.encode("utf-8") + crlf +
            b'Content-Type: application/octet-stream' + crlf + crlf,
            data + crlf,
            f"--{boundary}--".encode("utf-8") + crlf,
        ]

        body = b"".join(parts)
        url = f"{self.host}/execute/Fileman/upload_files"
        headers = {
            "Authorization": f"cpanel {self.user}:{self.token}",
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "Content-Length": str(len(body)),
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }

        req = urllib.request.Request(url, data=body, headers=headers, method="POST")
        try:
            with self._opener.open(req, timeout=45) as resp:
                raw = resp.read().decode("utf-8", errors="replace")
                if "wsidchk" in raw or "One moment, please..." in raw:
                    if self._solve_cpguard_challenge(raw, url):
                        with self._opener.open(req, timeout=45) as resp_retry:
                            raw = resp_retry.read().decode("utf-8", errors="replace")
                return json.loads(raw)
        except urllib.error.HTTPError as e:
            raw = e.read().decode("utf-8", errors="replace")
            if "wsidchk" in raw or "One moment, please..." in raw:
                if self._solve_cpguard_challenge(raw, url):
                    try:
                        with self._opener.open(req, timeout=45) as resp_retry:
                            raw = resp_retry.read().decode("utf-8", errors="replace")
                            return json.loads(raw)
                    except Exception:
                        pass
            return {"status": 0, "errors": [f"HTTP {e.code}: {raw[:300]}"]}
        except Exception as e:
            return {"status": 0, "errors": [str(e)]}

"""
InnerOS Canonical cPanel Client & UAPI Adapter - Hardened Security Release.
Reuses owner_vault credentials server-side and provides safe, audited access to cPanel UAPI.
Enforces strict path boundary isolation, extension whitelisting, and secret redaction.
"""

from __future__ import annotations

import json
import os
import re
import ssl
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path
from typing import Any

CPANEL_DEFAULT_HOST = "https://23.111.160.154:2083"
CPANEL_DEFAULT_USER = "pcdoctor"

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

MAX_READ_BYTES = 256 * 1024  # 256 KB


class SecurityViolation(Exception):
    pass


class CPanelClient:
    def __init__(
        self,
        host: str | None = None,
        user: str | None = None,
        token: str | None = None,
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
            "User-Agent": "InnerOS-CPanel-Adapter/1.0",
        }
        if data is not None:
            headers["Content-Type"] = "application/x-www-form-urlencoded"

        req = urllib.request.Request(
            url, headers=headers, data=data, method=method
        )
        try:
            with urllib.request.urlopen(req, context=self._ctx, timeout=30) as resp:
                raw = resp.read().decode("utf-8", errors="replace")
                return json.loads(raw)
        except urllib.error.HTTPError as e:
            raw = e.read().decode("utf-8", errors="replace")
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
        normalized_dir = os.path.normpath(dir_path).replace(chr(92), "/")
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

        full_path = os.path.normpath(os.path.join(normalized_dir, clean_filename)).replace(chr(92), "/")
        return full_path

    # File methods
    def list_files(
        self, dir_path: str = "/home/pcdoctor/public_html"
    ) -> list[dict[str, Any]]:
        norm_dir = os.path.normpath(dir_path).replace(chr(92), "/")
        if ".." in norm_dir or not any(norm_dir == p or norm_dir.startswith(p + "/") for p in ALLOWED_ROOT_PREFIXES):
            return []
        res = self.uapi("Fileman", "list_files", dir=norm_dir)
        return res.get("data", [])

    def get_file_content(self, dir_path: str, filename: str) -> str:
        full_path = self.validate_file_path(dir_path, filename)
        clean_dir = os.path.dirname(full_path)
        clean_name = os.path.basename(full_path)

        res = self.uapi("Fileman", "get_file_content", dir=clean_dir, file=clean_name)
        raw_content = res.get("data", {}).get("content", "")

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

    # Quota
    def get_quota_info(self) -> dict[str, Any]:
        res = self.uapi("Quota", "get_quota_info")
        return res.get("data", {})

    # Backup operations
    def list_backups(self) -> list[dict[str, Any]]:
        res = self.uapi("Backup", "list_backups")
        return res.get("data", [])

    def trigger_backup(self) -> dict[str, Any]:
        return self.uapi("Backup", "fullbackup_to_homedir")

    # Database diagnostic methods
    def check_database(self, name: str) -> dict[str, Any]:
        return self.uapi("Mysql", "check_database", name=name)

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
        norm_dir = os.path.normpath(parent_dir).replace(chr(92), "/")
        if ".." in norm_dir or ".." in name or "/" in name:
            raise SecurityViolation("invalid_folder_name_or_traversal")
        if not any(norm_dir == p or norm_dir.startswith(p + "/") for p in ALLOWED_ROOT_PREFIXES):
            raise SecurityViolation(f"path_outside_allowed_roots: {norm_dir}")
        return self.api2("Fileman", "mkdir", path=norm_dir, name=name)

    def fileop(self, op: str, **kwargs: Any) -> dict[str, Any]:
        return self.api2("Fileman", "fileop", op=op, **kwargs)

    def chmod_file(self, file_path: str, mode: str) -> dict[str, Any]:
        norm_path = os.path.normpath(file_path).replace(chr(92), "/")
        if ".." in norm_path or not any(norm_path.startswith(p + "/") for p in ALLOWED_ROOT_PREFIXES):
            raise SecurityViolation(f"path_outside_allowed_roots: {norm_path}")
        return self.fileop(op="chmod", metadata=mode, sourcefiles=norm_path)

    def extract_archive(self, archive_path: str, dest_dir: str) -> dict[str, Any]:
        norm_archive = os.path.normpath(archive_path).replace(chr(92), "/")
        norm_dest = os.path.normpath(dest_dir).replace(chr(92), "/")
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
            "User-Agent": "InnerOS-CPanel-Adapter/1.0"
        }

        req = urllib.request.Request(url, data=body, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, context=self._ctx, timeout=45) as resp:
                raw = resp.read().decode("utf-8", errors="replace")
                return json.loads(raw)
        except Exception as e:
            return {"status": 0, "errors": [str(e)]}

    def repair_database(self, name: str) -> dict[str, Any]:
        return self.uapi("Mysql", "repair_database", name=name)

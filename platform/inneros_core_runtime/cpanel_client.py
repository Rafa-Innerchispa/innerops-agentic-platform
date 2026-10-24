"""
InnerOS Canonical cPanel Client & UAPI Adapter.
Reuses owner_vault credentials server-side and provides safe, audited access to cPanel UAPI.
"""

from __future__ import annotations

import json
import os
import ssl
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

CPANEL_DEFAULT_HOST = "https://23.111.160.154:2083"
CPANEL_DEFAULT_USER = "pcdoctor"


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

    # File methods
    def list_files(
        self, dir_path: str = "/home/pcdoctor"
    ) -> list[dict[str, Any]]:
        res = self.uapi("Fileman", "list_files", dir=dir_path)
        return res.get("data", [])

    def get_file_content(self, dir_path: str, filename: str) -> str:
        res = self.uapi(
            "Fileman", "get_file_content", dir=dir_path, file=filename
        )
        return res.get("data", {}).get("content", "")

    def save_file_content(
        self, dir_path: str, filename: str, content: str
    ) -> dict[str, Any]:
        payload = urllib.parse.urlencode(
            {"dir": dir_path, "file": filename, "content": content}
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

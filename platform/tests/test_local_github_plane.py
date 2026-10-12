from __future__ import annotations

import os
import json
import tempfile
import unittest
from pathlib import Path

from raphiia_openai import local_github_plane


class LocalGithubPlaneTests(unittest.TestCase):
    def test_rejects_non_allowlisted_owner(self) -> None:
        result = local_github_plane.create_github_repo(
            owner="OtherOrg",
            name="example",
            actor="chatgpt",
            task_id="ops_test",
            correlation_id="corr_test",
        )

        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "github_owner_not_allowlisted")

    def test_rejects_invalid_repo_name(self) -> None:
        result = local_github_plane.create_github_repo(
            owner="Rafa-Innerchispa",
            name="../bad",
            actor="chatgpt",
            task_id="ops_test",
            correlation_id="corr_test",
        )

        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "invalid_repo_name")

    def test_bootstrap_project_without_remote_creates_git_repo(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            old_roots = os.environ.get("RALFIA_FS_ROOTS_JSON")
            old_audit = os.environ.get("RALFIA_FS_DISABLE_AUDIT")
            os.environ["RALFIA_FS_ROOTS_JSON"] = json.dumps([str(root)])
            os.environ["RALFIA_FS_DISABLE_AUDIT"] = "1"
            try:
                result = local_github_plane.bootstrap_project(
                    path=str(root),
                    project_name="innerops-example",
                    actor="chatgpt",
                    task_id="ops_test",
                    correlation_id="corr_test",
                    description="Example project.",
                    create_remote=False,
                )
            finally:
                if old_roots is None:
                    os.environ.pop("RALFIA_FS_ROOTS_JSON", None)
                else:
                    os.environ["RALFIA_FS_ROOTS_JSON"] = old_roots
                if old_audit is None:
                    os.environ.pop("RALFIA_FS_DISABLE_AUDIT", None)
                else:
                    os.environ["RALFIA_FS_DISABLE_AUDIT"] = old_audit

            self.assertTrue(result["ok"], result)
            project_dir = root / "innerops-example"
            self.assertTrue((project_dir / "README.md").exists())
            self.assertTrue((project_dir / ".git").exists())
            self.assertIsNone(result["remote"])

    def test_create_cli_does_not_disable_issues(self) -> None:
        from unittest.mock import patch
        with patch.object(local_github_plane, "shutil_which", return_value="/usr/bin/gh"):
            with patch.object(local_github_plane, "_run") as execute:
                execute.side_effect = [
                    {"ok": False, "stdout": "", "stderr": "", "returncode": 1},
                    {"ok": True, "stdout": "", "stderr": "", "returncode": 0},
                ]
                with patch.object(local_github_plane.local_filesystem_plane, "_audit"):
                    result = local_github_plane.create_github_repo(
                        owner="Rafa-Innerchispa", name="issues-enabled-probe",
                        actor="chatgpt", task_id="ops_test", correlation_id="corr_test"
                    )
        self.assertTrue(result["ok"], result)
        argv = execute.call_args_list[1].args[0]
        self.assertNotIn("--disable-issues", argv)
        self.assertEqual(argv[:4], ["/usr/bin/gh", "repo", "create", "Rafa-Innerchispa/issues-enabled-probe"])

    def test_api_creation_payload_enables_issues_for_owner(self) -> None:
        from unittest.mock import patch
        from urllib.error import HTTPError
        from io import BytesIO

        class Resp:
            def __init__(self, content):
                self.content = json.dumps(content).encode()
            def __enter__(self):
                return self
            def __exit__(self, *args):
                return False
            def read(self):
                return self.content

        calls = []
        def fake_open(request, timeout=30):
            calls.append(request)
            if request.full_url.endswith("/repos/issue-probe"):
                raise HTTPError(request.full_url, 404, "Not found", {}, BytesIO(b""))
            if request.full_url.endswith("/user"):
                return Resp({"login": "Rafa-Innerchispa"})
            if request.full_url.endswith("/user/repos"):
                data = json.loads(request.data)
                self.assertIs(data["has_issues"], True)
                self.assertEqual(data["private"], True)
                return Resp({"full_name": "Rafa-Innerchispa/issue-probe",
                             "html_url": "https://github.com/Rafa-Innerchispa/issue-probe",
                             "private": True})
            raise AssertionError(request.full_url)
        with patch.dict(os.environ, {"GITHUB_TOKEN": "test-local-never-reveal"}):
            with patch.object(local_github_plane.urllib.request, "urlopen", side_effect=fake_open):
                with patch.object(local_github_plane.local_filesystem_plane, "_audit"):
                    result = local_github_plane._create_github_repo_api(
                        "Rafa-Innerchispa", "issue-probe", "", True, None,
                        "chatgpt", "ops_test", "corr_test")
        self.assertTrue(result["ok"], result)
        self.assertEqual(calls[-1].full_url, "https://api.github.com/user/repos")

    def test_status_is_redacted_and_non_mutating(self) -> None:
        old_token = os.environ.get("GITHUB_TOKEN")
        os.environ["GITHUB_TOKEN"] = "github_pat_sensitive"
        try:
            status = local_github_plane.github_status()
        finally:
            if old_token is None:
                os.environ.pop("GITHUB_TOKEN", None)
            else:
                os.environ["GITHUB_TOKEN"] = old_token

        self.assertTrue(status["ok"])
        self.assertTrue(status["env_token_present"])
        self.assertNotIn("github_pat_sensitive", str(status))


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import io
from unittest import mock

from raphiia_openai import local_gitlab_plane as gl
from raphiia_openai import tool_catalog
from raphiia_openai.mcp_catalog import tool_catalog as canonical_tool_catalog


class FakeResponse:
    def __init__(self, body: bytes, status: int = 200):
        self._stream = io.BytesIO(body)
        self.status = status

    def read(self, size: int = -1) -> bytes:
        return self._stream.read(size)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


def test_get_job_trace_returns_bounded_redacted_tail() -> None:
    body = (
        b"A" * 2000
        + b"\nPRIVATE-TOKEN: glpat-abcdefghijklmnop\n"
        + b"Offenses: formatting failure at end\n"
    )
    response = FakeResponse(body)

    with (
        mock.patch.object(gl, "_token", return_value=("server-side-token", "owner_vault:test")),
        mock.patch.object(gl.urllib.request, "urlopen", return_value=response) as urlopen,
    ):
        result = gl.get_job_trace("gitlab-community/gitlab-org/gitlab", 16638944079, max_bytes=1024)

    assert result["ok"] is True
    assert result["job_id"] == 16638944079
    assert result["truncated"] is True
    assert result["returned_bytes"] <= 1024
    assert "formatting failure at end" in result["trace"]
    assert "glpat-" not in result["trace"]
    assert "[REDACTED]" in result["trace"]

    request = urlopen.call_args.args[0]
    assert "gitlab-community%2Fgitlab-org%2Fgitlab" in request.full_url
    assert request.full_url.endswith("/jobs/16638944079/trace")


def test_get_job_trace_rejects_invalid_job_id() -> None:
    assert gl.get_job_trace("gitlab-org/gitlab", 0)["error"] == "job_id_invalid"


def test_job_trace_tool_is_in_both_mcp_catalogs() -> None:
    for catalog in (tool_catalog, canonical_tool_catalog):
        assert "local_gitlab_get_job_trace" in catalog.ALL_MCP_TOOL_NAMES
        described = catalog.describe_tool("local_gitlab_get_job_trace")
        assert described["ok"] is True
        assert described["required_scopes"] == ["ralfia:read"]
        assert "job_id" in described["input_schema"]

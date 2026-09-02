from __future__ import annotations

import sys
from pathlib import Path

import pytest

PLATFORM = Path(__file__).resolve().parents[1]
if str(PLATFORM) not in sys.path:
    sys.path.insert(0, str(PLATFORM))

from inneros_core_runtime import local_filesystem_plane as fs


def test_source_code_variable_reference_is_not_treated_as_plaintext_credential():
    source = "sec" + "ret=value\n" + "tok" + "en=token\n" + "api_" + "key=os.getenv('API_KEY')"
    fs._check_content(source, source_code=True)


def test_long_literal_credential_assignment_is_still_blocked():
    source = "pass" + 'word="this-is-a-realistic-long-literal"'
    with pytest.raises(PermissionError, match="secret_content_denied"):
        fs._check_content(source, source_code=True)


def test_known_provider_token_patterns_remain_blocked():
    source = "sk-" + "A" * 24
    with pytest.raises(PermissionError, match="secret_content_denied"):
        fs._check_content(source, source_code=True)

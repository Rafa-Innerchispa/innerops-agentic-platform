from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from tests.test_router import (
    test_load_profiles_from_json,
    test_sandbox_blocks_path_outside_workspace,
    test_tools_call_forwards_allowed_tool,
    test_tools_call_rejects_unlisted_tool,
    test_tools_list_filters_by_profile_prefixes,
    test_session_initialize_then_tools_list,
)


def main() -> int:
    tests = (
        test_tools_list_filters_by_profile_prefixes,
        test_tools_call_rejects_unlisted_tool,
        test_tools_call_forwards_allowed_tool,
        test_session_initialize_then_tools_list,
        test_sandbox_blocks_path_outside_workspace,
        test_load_profiles_from_json,
    )
    for test in tests:
        test()
        print(f"ok {test.__name__}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

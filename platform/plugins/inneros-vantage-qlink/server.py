"""Launch local MCP tool plane from the checked-out InnerOS platform tree.
This plugin is intentionally local: it cannot see USB ports on AMD/Intel from the cloud.
"""
import sys
from pathlib import Path

platform_root = Path(__file__).resolve().parents[2]
if not (platform_root / "inneros_core_runtime" / "vantage_qlink_mcp.py").is_file():
    raise RuntimeError(
        "Requires the full canonical InnerOS platform checkout. "
        "Do not install this package alone."
    )
sys.path.insert(0, str(platform_root))

from inneros_core_runtime.vantage_qlink_mcp import main

if __name__ == "__main__":
    main()

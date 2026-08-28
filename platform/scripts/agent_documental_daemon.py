#!/usr/bin/env python3
from pathlib import Path
import sys

ROOT = Path("/home/rlopez/projects/raphiia-openai")
sys.path.insert(0, str(ROOT))

from raphiia_openai.documentary_daemon import main


if __name__ == "__main__":
    main()

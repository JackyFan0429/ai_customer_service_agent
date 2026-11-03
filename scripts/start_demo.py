#!/usr/bin/env python3
"""Launch the portal with temporary terminal settings, a free port, and a browser."""

import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))


def main(argv=None):
    if sys.version_info < (3, 11):
        raise SystemExit("需要 Python 3.11 或更新版本")
    from support_agent.portal import main as portal_main
    portal_main(argv, root=PROJECT, launcher=True)


if __name__ == "__main__":
    main()

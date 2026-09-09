"""CLI de capture des publications Facebook publiques retenues dans ``data/fb.txt``."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.services.facebook_retained_links_service import REGISTRY_PATH
from backend.services.facebook_screenshot_service import capture_retained_facebook_posts


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Capturer les publications Facebook publiques retenues dans les deux POC."
    )
    parser.add_argument("--links", type=Path, default=REGISTRY_PATH)
    parser.add_argument("--output", type=Path, default=PROJECT_ROOT / "data" / "facebook_screenshots")
    parser.add_argument("--scrolls", type=int, default=None)
    parser.add_argument("--pause", type=float, default=None)
    parser.add_argument("--max-links", type=int, default=None)
    parser.add_argument("--visible", action="store_true")
    args = parser.parse_args()

    result = capture_retained_facebook_posts(
        links_path=args.links,
        output_root=args.output,
        visible=args.visible,
        scrolls=args.scrolls,
        pause=args.pause,
        max_links=args.max_links,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("status") in {"completed", "partial", "no_links", "disabled"} else 1


if __name__ == "__main__":
    raise SystemExit(main())

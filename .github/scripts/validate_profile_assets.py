#!/usr/bin/env python3

from pathlib import Path
import sys
import xml.etree.ElementTree as ET


EXPECTED_FILES = (
    "github-user-stats.svg",
    "github-contribution-grid-snake.svg",
    "github-contribution-grid-snake-dark.svg",
)

ERROR_MARKERS = (
    "resource limits for this query exceeded",
    "rate limit exceeded",
    "something went wrong",
    "unexpected error",
    "error occurred while generating",
)


def validate_svg(path: Path) -> list[str]:
    errors: list[str] = []

    if not path.is_file():
        return [f"Missing expected asset: {path}"]

    if path.stat().st_size == 0:
        return [f"Generated asset is empty: {path}"]

    try:
        content = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return [f"Generated asset is not UTF-8 text: {path}"]

    try:
        root = ET.fromstring(content)
    except ET.ParseError as error:
        return [f"Generated asset is not valid XML: {path}: {error}"]

    if root.tag.rsplit("}", 1)[-1] != "svg":
        errors.append(f"Generated asset root element is not SVG: {path}")

    normalized = content.casefold()
    for marker in ERROR_MARKERS:
        if marker in normalized:
            errors.append(f"Generated asset contains error marker {marker!r}: {path}")

    return errors


def main() -> int:
    if len(sys.argv) != 2:
        print(f"Usage: {Path(sys.argv[0]).name} ASSET_DIRECTORY", file=sys.stderr)
        return 2

    asset_directory = Path(sys.argv[1])
    errors = [
        error
        for filename in EXPECTED_FILES
        for error in validate_svg(asset_directory / filename)
    ]

    if errors:
        for error in errors:
            print(f"::error::{error}")
        return 1

    print(f"Validated {len(EXPECTED_FILES)} profile SVG assets.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

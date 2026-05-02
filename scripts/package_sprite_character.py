#!/usr/bin/env python3
"""Package a validated configurable character spritesheet with metadata."""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path
from typing import Any


def load_request(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise SystemExit(f"request file not found: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def slugify(value: str) -> str:
    import re
    value = value.strip().lower()
    value = re.sub(r"[^a-z0-9]+", "-", value)
    value = re.sub(r"-{2,}", "-", value)
    return value.strip("-")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", required=True)
    parser.add_argument("--spritesheet", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    request = load_request(Path(args.request).expanduser().resolve())
    spritesheet = Path(args.spritesheet).expanduser().resolve()
    if not spritesheet.is_file():
        raise SystemExit(f"spritesheet not found: {spritesheet}")
    character_id = str(request.get("character_id") or slugify(str(request.get("display_name") or "character")))
    display_name = str(request.get("display_name") or character_id)
    target_dir = Path(args.output_dir).expanduser().resolve()
    if target_dir.exists() and any(target_dir.iterdir()) and not args.force:
        raise SystemExit(f"{target_dir} already contains files; pass --force to overwrite")
    target_dir.mkdir(parents=True, exist_ok=True)
    sheet_name = f"{character_id}{spritesheet.suffix.lower() or '.webp'}"
    target_sheet = target_dir / sheet_name
    shutil.copy2(spritesheet, target_sheet)
    metadata: dict[str, Any] = {
        "schema_version": 1,
        "id": character_id,
        "display_name": display_name,
        "description": request.get("description", ""),
        "spritesheet": target_sheet.name,
        "atlas": request.get("atlas"),
        "animations": request.get("animations"),
        "style_preset": request.get("style_preset"),
        "style_notes": request.get("style_notes"),
        "view": request.get("view"),
        "chroma_key": request.get("chroma_key"),
        "notes": request.get("character_notes"),
    }
    manifest_path = target_dir / "character.json"
    manifest_path.write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"ok": True, "character_dir": str(target_dir), "manifest": str(manifest_path), "spritesheet": str(target_sheet)}, indent=2))


if __name__ == "__main__":
    main()

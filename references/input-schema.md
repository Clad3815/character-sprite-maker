# Character Sprite Maker input schema

The skill accepts either CLI flags or a JSON config passed to:

```bash
python scripts/prepare_character_run.py --config config.json --force
```

## JSON fields

```json
{
  "character_name": "Milo",
  "character_id": "milo",
  "display_name": "Milo",
  "description": "An original 2D platformer hero.",
  "character_notes": "An original cheerful plumber-like platformer hero with a cap and overalls; not a copyrighted character.",
  "style_preset": "mario-like",
  "style_notes": "Bold readable shapes, bright palette, clean outline.",
  "view": "side-view",
  "cell_width": 128,
  "cell_height": 128,
  "columns": 8,
  "fps": 12,
  "chroma_key": "auto",
  "output_dir": "./output/milo-run",
  "references": ["/absolute/path/to/ref.png"],
  "animations": [
    {"name": "idle", "frames": 6, "action": "breathing and blink loop"},
    {"name": "walk-right", "frames": 8, "action": "rightward walk cycle"},
    {"name": "walk-left", "frames": 8, "action": "leftward walk cycle"},
    {"name": "jump", "frames": 6, "action": "anticipation, airborne jump, landing settle"}
  ],
  "mirror_pairs": {
    "walk-left": "walk-right"
  }
}
```

## Notes

- `columns` defaults to the maximum frame count across animations.
- `rows` is inferred from the animation count.
- `width = columns * cell_width` and `height = rows * cell_height`.
- `mirror_pairs` are optional. When omitted, common left/right pairs are inferred.
- References are copied into the run folder. The base image is generated first and becomes `references/canonical-base.png`.
- Animation names should be slug-like: lowercase words separated by hyphens.

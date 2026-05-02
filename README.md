# Character Sprite Maker

A generalized Agent Skill derived from the uploaded `hatch-pet` workflow. It creates configurable 2D game character spritesheets with arbitrary animation rows, custom frame counts, custom cell sizes, references, chroma-key cleanup, frame extraction, atlas validation, contact sheets, GIF previews, and generic `character.json` packaging.

## Minimal example

```bash
SKILL_DIR=/path/to/character-sprite-maker
python "$SKILL_DIR/scripts/prepare_character_run.py" \
  --character-name "Milo" \
  --character-notes "an original cheerful plumber-like platformer hero with cap and overalls; not a copyrighted character" \
  --style-preset mario-like \
  --animation-preset mario-like \
  --view side-view \
  --cell-width 128 \
  --cell-height 128 \
  --output-dir ./output/milo \
  --force

python "$SKILL_DIR/scripts/character_job_status.py" --run-dir ./output/milo
```

Generate each ready job with `$imagegen`, then record selected images:

```bash
python "$SKILL_DIR/scripts/record_imagegen_result.py" --run-dir ./output/milo --job-id base --source /path/to/ig_base.png
python "$SKILL_DIR/scripts/record_imagegen_result.py" --run-dir ./output/milo --job-id idle --source /path/to/ig_idle.png
```

Finalize:

```bash
python "$SKILL_DIR/scripts/finalize_character_run.py" --run-dir ./output/milo
```

## Output

```text
run/
  character_request.json
  imagegen-jobs.json
  prompts/
  references/
  decoded/
  frames/
  final/spritesheet.png
  final/spritesheet.webp
  qa/contact-sheet.png
  qa/gifs/*.gif
  package/character.json
  package/<character-id>.webp
```

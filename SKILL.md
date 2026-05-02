---
name: character-sprite-maker
description: Create, configure, repair, validate, preview, and package arbitrary 2D game character spritesheets from text concepts, style settings, animation lists, screenshots, generated images, or visual references. Use when a user wants a configurable character generator for games, e.g. platformer, Mario-like original mascot, RPG, fighting-game, metroidvania, top-down, isometric, idle/walk/run/jump/attack animations, custom frame counts, layout guides, transparent conversion, contact sheets, GIF previews, and generic character.json packaging.
---

# Character Sprite Maker

## Overview

Create a configurable animated 2D character spritesheet from a concept, one or more reference images, or both. This skill generalizes the hatch-pet pipeline: it keeps the reliable pieces (prompt planning, references, chroma-key conversion, frame extraction, atlas composition, validation, contact sheet, previews, packaging) but removes pet-specific constraints such as a fixed 8x9 atlas, fixed animation rows, and Codex pet packaging.

The user may specify:

- character type or concept, e.g. "original plumber-like platformer hero", "top-down wizard", "fighting game boss", "robot NPC", "Mario-like 2D platformer character";
- visual style preset and extra style notes;
- animation preset or a custom animation list such as `idle`, `walk-right`, `walk-left`, `jump`, `attack`, `hurt`, etc.;
- frame counts per animation;
- cell size, atlas columns, FPS, view/camera, references, and package location.

If a field is missing, infer a practical default and continue. Only ask the user when the missing choice is truly blocking.

## Generation Delegation

Use `$imagegen` for all normal visual generation.

Before generating base art, animation strips, or repairs, load and follow the installed image generation skill when available:

```text
${CODEX_HOME:-$HOME/.codex}/skills/.system/imagegen/SKILL.md
```

Do not call the Image API directly for the normal path. Let `$imagegen` choose its own built-in-first path and CLI fallback rules. If `$imagegen` says a fallback requires confirmation, ask the user before continuing.

Use this skill's scripts only for deterministic work: preparing prompts/manifests, copying references, creating layout guides, ingesting selected `$imagegen` outputs, extracting frames, removing chroma-key backgrounds, validating rows, composing the final atlas, creating QA media, and packaging.

Hard boundary: do not create, draw, tile, warp, or synthesize character visuals with local Python/Pillow scripts, SVG, canvas, HTML/CSS, or code-native art as a substitute for `$imagegen`. Local scripts may process already-generated visual outputs only.

## Copyright / Style Handling

The user can request a genre or broad style, e.g. "style Mario", "Sonic-like platformer energy", "Zelda-like top-down RPG". Convert that into an original character and general art direction. Do not generate an exact copy of copyrighted characters, logos, trademarked costumes, or protected game assets unless the user provides rights/ownership context and the request is allowed.

For example, "personnage 2D style Mario" should become an "original, bright, family-friendly mascot-platformer sprite with rounded readable shapes and bold colors", not Mario himself.

## Input Model

Use `scripts/prepare_character_run.py`. It supports direct CLI flags or a JSON config file.

Important flags:

```bash
python "$SKILL_DIR/scripts/prepare_character_run.py" \
  --character-name "<Name>" \
  --character-notes "<one or two sentences describing the character>" \
  --style-preset pixel-platformer \
  --style-notes "<extra art direction>" \
  --view "side-view" \
  --animation idle:6:"neutral idle loop" \
  --animation walk-right:8:"rightward walk cycle" \
  --animation walk-left:8:"leftward walk cycle" \
  --cell-width 128 \
  --cell-height 128 \
  --reference /absolute/path/to/reference.png \
  --output-dir /absolute/path/to/run \
  --force
```

All arguments are optional except those needed to express the user's constraints. If no animations are supplied, use the `platformer` preset by default. If the user mentions Mario-like, platformer, top-down RPG, fighting game, or pet-compatible, use the matching preset when appropriate.

Available style presets:

- `pixel-platformer`
- `mario-like`
- `topdown-rpg`
- `metroidvania`
- `fighting-game`
- `cartoon-hd`
- `iso-rpg`

Available animation presets:

- `platformer`
- `mario-like`
- `topdown-rpg`
- `fighting`
- `pet-compatible`

Animation specs support:

```text
name
name:frames
name:frames:action description
name=frames:action description
```

Examples:

```bash
--animation idle:6:"breathing and blink loop"
--animation walk-right:8:"rightward platformer walk cycle"
--animation attack:6:"short punch attack"
```

## Visible Progress Checklist

For a normal character run, keep a visible checklist for the user:

1. Configuring `<Character>`.
2. Creating `<Character>`'s base look.
3. Generating `<Character>`'s animation strips.
4. Converting and validating `<Character>`.
5. Packaging `<Character>`.

Only mark a step complete when the real file, image, or decision exists.

## Default Workflow

1. Prepare the run folder and imagegen job manifest:

```bash
SKILL_DIR="${CODEX_HOME:-$HOME/.codex}/skills/character-sprite-maker"
python "$SKILL_DIR/scripts/prepare_character_run.py" \
  --character-name "<Name>" \
  --character-notes "<concept>" \
  --style-preset "<preset>" \
  --animation-preset "<preset>" \
  --output-dir /absolute/path/to/run \
  --force
```

For a Mario-like original 2D platformer character:

```bash
python "$SKILL_DIR/scripts/prepare_character_run.py" \
  --character-name "Milo" \
  --character-notes "an original cheerful plumber-like platformer hero with a round cap, work overalls, white gloves, and expressive face; not a copyrighted character" \
  --style-preset mario-like \
  --animation-preset mario-like \
  --view "side-view" \
  --cell-width 128 \
  --cell-height 128 \
  --output-dir /absolute/path/to/run \
  --force
```

2. Inspect ready jobs:

```bash
python "$SKILL_DIR/scripts/character_job_status.py" --run-dir /absolute/path/to/run
```

3. Generate and record `base` first.

Invoke `$imagegen` with:

- the prompt file listed in `imagegen-jobs.json`;
- all input images listed for the job, with role labels;
- the built-in image generation path unless `$imagegen` itself routes otherwise.

Chroma-key discipline:

- The generated background must be the exact flat chroma key stored in `character_request.json`, edge to edge.
- Reject outputs with gradients, vignettes, shaded studio backgrounds, floor planes, shadows, glow, texture, or any background color drift.
- When recording normal `$imagegen` results, use `--strict-chroma-background` so bad chroma backgrounds fail immediately instead of surfacing later during extraction.
- If strict recording fails, regenerate with a shorter prompt that emphasizes the exact RGB background before accepting a manual override.

After selecting the best output, record it:

```bash
python "$SKILL_DIR/scripts/record_imagegen_result.py" \
  --run-dir /absolute/path/to/run \
  --job-id base \
  --source /absolute/path/to/generated-output.png \
  --strict-chroma-background
```

This writes `decoded/base.png` and `references/canonical-base.png`. Every animation strip must use the canonical base as a grounding image.

4. Generate animation strips.

Run job status again. For each ready animation job:

- read the row prompt;
- attach all input images listed in the manifest;
- include the matching `references/layout-guides/<animation>.png` as a layout-only input;
- treat the guide as invisible construction information; reject outputs that copy guide boxes, labels, marks, or the guide background;
- reject outputs whose background is not one exact flat chroma key color across the full canvas;
- record the selected `$imagegen` output with `record_imagegen_result.py`.

For left/right pairs, the prepare script may create a mirror policy, e.g. `walk-left` may derive from `walk-right`. Only mirror after visual inspection confirms it preserves identity, side-specific costume details, props, readable text, logos, lighting, and direction semantics:

```bash
python "$SKILL_DIR/scripts/derive_mirror_animation.py" \
  --run-dir /absolute/path/to/run \
  --target walk-left \
  --confirm-appropriate-mirror \
  --decision-note "character is symmetric enough; no text, logo, handed prop, or side-specific marking becomes wrong"
```

If mirroring would be wrong, generate the left-facing animation normally with `$imagegen` using its prompt and all listed grounding images.

5. Finalize:

```bash
python "$SKILL_DIR/scripts/finalize_character_run.py" \
  --run-dir /absolute/path/to/run
```

Expected output:

```text
run/
  character_request.json
  imagegen-jobs.json
  prompts/
  references/
  decoded/
  frames/frames-manifest.json
  final/spritesheet.png
  final/spritesheet.webp
  final/validation.json
  qa/contact-sheet.png
  qa/review.json
  qa/gifs/*.gif
  qa/run-summary.json
  package/
    character.json
    <character-id>.webp
```

6. Review before accepting.

Deterministic validation is necessary but not sufficient. Visually inspect:

- `qa/contact-sheet.png`
- `qa/review.json`
- `final/validation.json`
- `qa/gifs/`

Block acceptance if any animation row changes identity, body type, face, costume, palette, prop design, side-specific details, silhouette, or camera angle unexpectedly.

## Repair Workflow

If finalization fails or visual review catches a bad row, reopen only the failing animation rows:

```bash
python "$SKILL_DIR/scripts/queue_character_repairs.py" \
  --run-dir /absolute/path/to/run
```

Or manually reopen specific rows:

```bash
python "$SKILL_DIR/scripts/queue_character_repairs.py" \
  --run-dir /absolute/path/to/run \
  --states walk-right,attack
```

Then regenerate only the reopened rows with `$imagegen`, record them, and finalize again.

## Rules

- Use `$imagegen` for base and animation-strip visual generation.
- Only the base job may be prompt-only. Every animation-strip job must attach the listed grounding images.
- Do not synthesize missing art locally with code.
- Do not edit `imagegen-jobs.json` to fake completion; use `record_imagegen_result.py` or `derive_mirror_animation.py`.
- Keep the same identity across all animations: proportions, face, costume, palette, prop design, outline, silhouette, and camera angle.
- Enforce the exact requested frame count for each animation.
- Use the chroma key stored in `character_request.json`; do not force a fixed green screen.
- Do not accept generated source images with gradient, textured, vignetted, shaded, or drifting chroma backgrounds. The chroma background must be a single exact RGB key color across all non-character pixels.
- Reject visible layout guides, labels, frame numbers, grids, UI, scenery, watermarks, text, checkerboards, white/black backgrounds, shadows, glows, motion blur, dust, speed lines, and detached effects unless the user explicitly requested an effect and it remains compatible with transparent extraction.
- Treat slot-sliced extraction as a warning unless the user or operator has visually approved it. Component extraction is preferred.
- For side-facing mirrored rows, mirror only when side-specific details remain correct.

## Acceptance Criteria

- `final/spritesheet.png` and `final/spritesheet.webp` exist.
- The atlas dimensions match `character_request.json`.
- Used cells are non-empty; unused cells are transparent.
- `qa/review.json` has no errors.
- `final/validation.json` has no errors.
- `qa/contact-sheet.png` and GIF previews have been produced unless explicitly skipped.
- Visual review confirms identity consistency and usable animation cycles.
- `package/character.json` and the packaged WebP spritesheet are staged together unless packaging was skipped.

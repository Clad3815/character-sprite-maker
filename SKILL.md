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
- Reject outputs with gradients, vignettes, shaded studio backgrounds, floor planes, shadows, glow, texture, or uneven/non-removable background color drift.
- When recording normal `$imagegen` results, use `--strict-chroma-background` so bad chroma backgrounds fail immediately instead of surfacing later during extraction.
- If strict recording fails because the background has only small uniform imagegen RGB drift but is visually a clean removable chroma background, normalize the selected source to alpha with `normalize_chroma_source.py`, then record the normalized PNG with `--strict-chroma-background`. Do not composite the alpha result back onto the chroma key.
- If strict recording still fails after one regeneration and one normalization attempt, reject the source and regenerate.

After selecting the best output, record it:

```bash
python "$SKILL_DIR/scripts/record_imagegen_result.py" \
  --run-dir /absolute/path/to/run \
  --job-id base \
  --source /absolute/path/to/generated-output.png \
  --strict-chroma-background
```

If the selected output has a visually flat chroma background but strict recording fails due to RGB drift, normalize first:

```bash
python "$SKILL_DIR/scripts/normalize_chroma_source.py" \
  --run-dir /absolute/path/to/run \
  --source /absolute/path/to/generated-output.png \
  --out /absolute/path/to/run/normalized/base.png \
  --auto-key border \
  --force

python "$SKILL_DIR/scripts/record_imagegen_result.py" \
  --run-dir /absolute/path/to/run \
  --job-id base \
  --source /absolute/path/to/run/normalized/base.png \
  --strict-chroma-background \
  --allow-run-source
```

This writes `decoded/base.png` and `references/canonical-base.png`.

Before continuing, visually inspect the decoded base image, not only the raw `$imagegen` output:

- Open `decoded/base.png` or `references/canonical-base.png` after recording/normalization.
- Confirm the character is clean, fully visible, animation-ready, and faithful to the request.
- Confirm costume colors, outlines, face, body proportions, silhouette, and palette are correct.
- Confirm any dark/black areas are intentional line art or requested costume details, not accidental filled clothing, muddy extraction, shadows, or generated artifacts.
- Confirm there are no visible chroma-key pixels, background remnants, shadows, glows, labels, watermarks, frame guides, or unrelated marks.
- If the decoded base is not clean, do not generate animation strips. Regenerate or repair the base, record it again, and repeat this visual inspection.

Every animation strip must use the approved canonical base as a grounding image.

4. Generate animation strips.

Run job status again. For each ready animation job:

- read the row prompt;
- **ALWAYS attach the canonical base image** (`references/canonical-base.png`, also available as `decoded/base.png`) as a grounding input — never generate an animation strip from the prompt alone. The prompt describes the action; the base image defines the character's identity, proportions, face, costume, palette, props, outline, silhouette, and camera angle. Without the base attached, the character will drift between rows.
- attach all other input images listed in the manifest (additional references, prior animation strips when listed, etc.);
- include the matching `references/layout-guides/<animation>.png` as a layout-only input;
- treat the guide as invisible construction information; reject outputs that copy guide boxes, labels, marks, or the guide background;
- reject outputs whose background is not a single clean removable chroma field across the full canvas;
- record the selected `$imagegen` output with `record_imagegen_result.py`; if strict recording fails only because of chroma RGB drift, normalize with `normalize_chroma_source.py` and record that alpha PNG.

Parallelize animation generation with subagents (preferred):

Once the `base` is generated, validated, and recorded as `decoded/base.png` / `references/canonical-base.png`, prefer dispatching the remaining animation-strip jobs to subagents in parallel when a subagent / Task delegation mechanism is available in the host environment. Animation strips are independent (they all ground on the same canonical base plus their own layout guide), so generating them concurrently dramatically reduces wall-clock time.

Guidelines when delegating to subagents:

- Only parallelize after the `base` job is fully validated and recorded. Never parallelize the base itself.
- Launch one subagent per ready animation job (or small batches), all in a single dispatch where the host supports concurrent subagent calls.
- Give each subagent a self-contained brief: the run directory, the exact `job-id`, the prompt file path, the full list of input images (with role labels, **always including the canonical base `references/canonical-base.png` as a mandatory grounding image**, plus the matching layout guide), the chroma-key requirements, and the instruction to call `$imagegen` and then `record_imagegen_result.py --strict-chroma-background` for that single job. If strict recording fails only because of chroma RGB drift, the subagent should run `normalize_chroma_source.py` and record the normalized alpha PNG with `--allow-run-source`. Subagents must never generate an animation strip from the prompt alone — the canonical base image is required on every animation call.
- Each subagent must record its result independently via `record_imagegen_result.py`; do not let subagents edit `imagegen-jobs.json` directly or touch jobs other than their own.
- Mirror-derived rows (e.g. `walk-left` from `walk-right`) must wait for their source row to be recorded; either keep them in the main agent or schedule them in a second wave after the source completes.
- If the host environment does not expose subagents, or the user declines parallel delegation, fall back to sequential generation in the main agent using the same per-job rules.

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
- **ALWAYS attach the canonical base image (`references/canonical-base.png` / `decoded/base.png`) when generating any animation strip.** Generating an animation row from the prompt alone is forbidden — the base image is what locks identity, proportions, face, costume, palette, props, outline, silhouette, and camera angle across all rows. This rule applies equally to the main agent and to any subagents dispatched in parallel.
- Do not synthesize missing art locally with code.
- Deterministic scripts may remove a generated chroma-key background, preserve alpha, mirror an approved row, extract frames, compose atlases, and validate outputs. They must not invent or redraw character art.
- Do not edit `imagegen-jobs.json` to fake completion; use `record_imagegen_result.py`, `normalize_chroma_source.py` plus `record_imagegen_result.py`, or `derive_mirror_animation.py`.
- Keep the same identity across all animations: proportions, face, costume, palette, prop design, outline, silhouette, and camera angle.
- Enforce the exact requested frame count for each animation.
- Use the chroma key stored in `character_request.json`; do not force a fixed green screen.
- Do not accept generated source images with gradient, textured, vignetted, shaded, or uneven/non-removable chroma backgrounds. The preferred background is a single exact RGB key color across all non-character pixels; if imagegen produces a clean but slightly RGB-drifted chroma field, normalize it to alpha with `normalize_chroma_source.py` before recording.
- Do not accept a final atlas with visible chroma-key pixels or chroma-colored antialias fringes. `validate_atlas.py` checks this by default.
- Reject visible layout guides, labels, frame numbers, grids, UI, scenery, watermarks, text, checkerboards, white/black backgrounds, shadows, glows, motion blur, dust, speed lines, and detached effects unless the user explicitly requested an effect and it remains compatible with transparent extraction.
- Treat slot-sliced extraction as a warning unless the user or operator has visually approved it. Component extraction is preferred.
- For side-facing mirrored rows, mirror only when side-specific details remain correct.

## Acceptance Criteria

- `final/spritesheet.png` and `final/spritesheet.webp` exist.
- The atlas dimensions match `character_request.json`.
- Used cells are non-empty; unused cells are transparent.
- `qa/review.json` has no errors.
- `final/validation.json` has no errors.
- `final/validation.json` reports zero visible chroma-key leaks.
- `qa/contact-sheet.png` and GIF previews have been produced unless explicitly skipped.
- Visual review confirms identity consistency and usable animation cycles.
- `package/character.json` and the packaged WebP spritesheet are staged together unless packaging was skipped.

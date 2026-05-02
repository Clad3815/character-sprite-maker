#!/usr/bin/env python3
"""Finalize a character sprite run after all imagegen jobs are complete."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

from PIL import Image, ImageOps


def run(command: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    print("+ " + " ".join(command))
    return subprocess.run(command, check=check, text=True)


def load_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise SystemExit(f"missing file: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def manifest_path(raw: object, *, run_dir: Path, field: str, job_id: str) -> Path:
    if not isinstance(raw, str) or not raw:
        raise SystemExit(f"job {job_id} has no {field}")
    path = Path(raw).expanduser()
    if not path.is_absolute():
        path = run_dir / path
    return path.resolve()


def validate_hash(job: dict[str, Any], *, source: Path, output: Path, job_id: str) -> None:
    expected_source_hash = job.get("source_sha256")
    expected_output_hash = job.get("output_sha256")
    if not isinstance(expected_source_hash, str) or not expected_source_hash:
        raise SystemExit(f"job {job_id} is missing source_sha256; ingest visual outputs with record_imagegen_result.py")
    if not isinstance(expected_output_hash, str) or not expected_output_hash:
        raise SystemExit(f"job {job_id} is missing output_sha256; ingest visual outputs with record_imagegen_result.py")
    if not source.is_file():
        raise SystemExit(f"job {job_id} source image no longer exists: {source}")
    if not output.is_file():
        raise SystemExit(f"job {job_id} decoded output is missing: {output}")
    if file_sha256(source) != expected_source_hash:
        raise SystemExit(f"job {job_id} source image hash does not match imagegen-jobs.json")
    if file_sha256(output) != expected_output_hash:
        raise SystemExit(f"job {job_id} decoded output hash does not match imagegen-jobs.json")


def validate_mirror(job: dict[str, Any], *, source: Path, output: Path, job_id: str) -> None:
    decision = job.get("mirror_decision")
    if not isinstance(decision, dict) or decision.get("approved") is not True:
        raise SystemExit(f"job {job_id} deterministic mirror is missing approved mirror_decision")
    validate_hash(job, source=source, output=output, job_id=job_id)
    with Image.open(source) as source_image, Image.open(output) as output_image:
        expected = ImageOps.mirror(source_image.convert("RGBA"))
        actual = output_image.convert("RGBA")
        if expected.size != actual.size or expected.tobytes() != actual.tobytes():
            raise SystemExit(f"job {job_id} output is not an exact horizontal mirror of its source")


def validate_completed_job_source(job: dict[str, Any], *, run_dir: Path) -> None:
    job_id = str(job.get("id") or "")
    if not job_id:
        raise SystemExit("job missing id")
    source = manifest_path(job.get("source_path"), run_dir=run_dir, field="source_path", job_id=job_id)
    output = manifest_path(job.get("output_path"), run_dir=run_dir, field="output_path", job_id=job_id)
    blocked_flags = [flag for flag in ("deterministic_row", "local_raster_row", "synthetic_character_row") if job.get(flag)]
    if blocked_flags:
        raise SystemExit(f"job {job_id} was marked as local/synthetic ({', '.join(blocked_flags)}); regenerate it with $imagegen")
    if job.get("source_provenance") == "deterministic-mirror":
        validate_mirror(job, source=source, output=output, job_id=job_id)
        return
    validate_hash(job, source=source, output=output, job_id=job_id)


def require_complete_jobs(run_dir: Path) -> None:
    manifest = load_json(run_dir / "imagegen-jobs.json")
    jobs = manifest.get("jobs")
    if not isinstance(jobs, list):
        raise SystemExit("invalid imagegen-jobs.json: jobs must be a list")
    incomplete = [str(job.get("id")) for job in jobs if isinstance(job, dict) and job.get("status", "pending") != "complete"]
    if incomplete:
        raise SystemExit("imagegen jobs are not complete; run character_job_status.py and finish: " + ", ".join(incomplete))
    for job in jobs:
        if isinstance(job, dict):
            validate_completed_job_source(job, run_dir=run_dir)


def review_failures(review: dict[str, Any]) -> list[str]:
    rows = review.get("rows")
    if not isinstance(rows, list):
        return ["review did not contain row-level results"]
    failures = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        errors = row.get("errors")
        if isinstance(errors, list) and errors:
            failures.append(f"{row.get('state')}: {'; '.join(str(error) for error in errors)}")
    return failures


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--allow-slot-extraction", action="store_true")
    parser.add_argument("--skip-gifs", action="store_true")
    parser.add_argument("--skip-package", action="store_true")
    parser.add_argument("--package-dir", default="", help="Output package directory. Defaults to <run>/package.")
    parser.add_argument("--gif-scale", type=int, default=2)
    args = parser.parse_args()

    scripts_dir = Path(__file__).resolve().parent
    run_dir = Path(args.run_dir).expanduser().resolve()
    request_path = run_dir / "character_request.json"
    request = load_json(request_path)
    character_id = str(request.get("character_id") or "")
    display_name = str(request.get("display_name") or "")
    description = str(request.get("description") or "")
    if not character_id or not display_name or not description:
        raise SystemExit("character_request.json is missing character_id, display_name, or description")

    require_complete_jobs(run_dir)
    final_dir = run_dir / "final"
    qa_dir = run_dir / "qa"
    final_dir.mkdir(parents=True, exist_ok=True)
    qa_dir.mkdir(parents=True, exist_ok=True)

    run([sys.executable, str(scripts_dir / "extract_strip_frames.py"), "--decoded-dir", str(run_dir / "decoded"), "--output-dir", str(run_dir / "frames"), "--states", "all", "--method", "auto"])
    review_path = qa_dir / "review.json"
    inspect_command = [sys.executable, str(scripts_dir / "inspect_frames.py"), "--frames-root", str(run_dir / "frames"), "--json-out", str(review_path)]
    if not args.allow_slot_extraction:
        inspect_command.append("--require-components")
    run(inspect_command, check=False)
    review = load_json(review_path)
    if not review.get("ok"):
        failures = review_failures(review)
        print(json.dumps({"ok": False, "review": str(review_path), "repair_hint": "Run queue_character_repairs.py, regenerate reopened jobs with $imagegen, then finalize again.", "failures": failures}, indent=2))
        raise SystemExit(1)

    run([sys.executable, str(scripts_dir / "compose_atlas.py"), "--frames-root", str(run_dir / "frames"), "--request", str(request_path), "--output", str(final_dir / "spritesheet.png"), "--webp-output", str(final_dir / "spritesheet.webp")])
    run([sys.executable, str(scripts_dir / "validate_atlas.py"), str(final_dir / "spritesheet.webp"), "--request", str(request_path), "--json-out", str(final_dir / "validation.json")])
    run([sys.executable, str(scripts_dir / "make_contact_sheet.py"), str(final_dir / "spritesheet.webp"), "--request", str(request_path), "--output", str(qa_dir / "contact-sheet.png")])
    if not args.skip_gifs:
        run([sys.executable, str(scripts_dir / "render_animation_gifs.py"), str(final_dir / "spritesheet.webp"), "--request", str(request_path), "--output-dir", str(qa_dir / "gifs"), "--scale", str(args.gif_scale)])

    package_dir = None
    if not args.skip_package:
        package_dir = Path(args.package_dir).expanduser().resolve() if args.package_dir else run_dir / "package"
        run([sys.executable, str(scripts_dir / "package_sprite_character.py"), "--request", str(request_path), "--spritesheet", str(final_dir / "spritesheet.webp"), "--output-dir", str(package_dir), "--force"])

    summary = {
        "ok": True,
        "run_dir": str(run_dir),
        "spritesheet_png": str(final_dir / "spritesheet.png"),
        "spritesheet_webp": str(final_dir / "spritesheet.webp"),
        "validation": str(final_dir / "validation.json"),
        "contact_sheet": str(qa_dir / "contact-sheet.png"),
        "review": str(review_path),
        "gifs": None if args.skip_gifs else str(qa_dir / "gifs"),
        "package": None if package_dir is None else str(package_dir),
    }
    summary_path = qa_dir / "run-summary.json"
    summary_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()

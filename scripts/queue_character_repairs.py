#!/usr/bin/env python3
"""Reopen failed animation-strip jobs after QA review so they can be regenerated."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def load_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise SystemExit(f"missing file: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def failed_states(review: dict[str, Any], requested: str) -> dict[str, list[str]]:
    wanted = {item.strip() for item in requested.split(",") if item.strip()} if requested else set()
    rows = review.get("rows")
    if not isinstance(rows, list):
        raise SystemExit("review has no rows list")
    failures: dict[str, list[str]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        state = row.get("state")
        if not isinstance(state, str):
            continue
        if wanted and state not in wanted:
            continue
        errors = row.get("errors")
        if isinstance(errors, list) and errors:
            failures[state] = [str(error) for error in errors]
    if wanted:
        for state in wanted:
            failures.setdefault(state, ["manual repair requested"])
    return failures


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--states", default="", help="Comma-separated animations to reopen manually. Defaults to failed rows from qa/review.json.")
    parser.add_argument("--review", default="", help="Defaults to <run>/qa/review.json")
    parser.add_argument("--keep-decoded", action="store_true")
    args = parser.parse_args()

    run_dir = Path(args.run_dir).expanduser().resolve()
    review_path = Path(args.review).expanduser().resolve() if args.review else run_dir / "qa" / "review.json"
    review = load_json(review_path) if review_path.is_file() else {"rows": []}
    failures = failed_states(review, args.states)
    if not failures:
        print(json.dumps({"ok": True, "message": "no failed or requested states to queue"}, indent=2))
        return

    manifest_path = run_dir / "imagegen-jobs.json"
    manifest = load_json(manifest_path)
    jobs = manifest.get("jobs")
    if not isinstance(jobs, list):
        raise SystemExit("invalid imagegen-jobs.json")
    reopened = []
    for job in jobs:
        if not isinstance(job, dict) or job.get("id") not in failures:
            continue
        output_raw = job.get("output_path")
        if isinstance(output_raw, str):
            output = Path(output_raw)
            if not output.is_absolute():
                output = run_dir / output
            if output.exists() and not args.keep_decoded:
                output.unlink()
        attempt = int(job.get("repair_attempt") or 0) + 1
        job.update({
            "status": "pending",
            "repair_attempt": attempt,
            "repair_reason": "; ".join(failures[str(job.get("id"))]),
            "queued_at": datetime.now(timezone.utc).isoformat(),
        })
        for key in ["source_path", "source_provenance", "source_sha256", "output_sha256", "completed_at", "metadata", "derived_from", "mirror_decision"]:
            job.pop(key, None)
        reopened.append(str(job.get("id")))
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"ok": True, "reopened": reopened, "next": "Run character_job_status.py, regenerate reopened rows with $imagegen, record them, then finalize again."}, indent=2))


if __name__ == "__main__":
    main()

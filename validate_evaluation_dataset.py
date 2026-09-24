"""Validate an Evaluation v2 dataset and optionally prepare a run manifest."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from pydantic import ValidationError

from evaluation.dataset_v2 import (
    EvaluationDatasetValidator,
    ManifestExecutionConfig,
    build_execution_manifest,
    save_execution_manifest,
)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Evaluation v2 dataset schema와 hash를 검증합니다.",
    )
    parser.add_argument("dataset", type=Path, help="검증할 v2 또는 legacy v1 JSON")
    parser.add_argument(
        "--expected-hash",
        help="선택한 sha256:<64 hex>와 다르면 실패",
    )
    parser.add_argument(
        "--manifest-output",
        type=Path,
        help="모델을 실행하지 않고 prepared manifest JSON 저장",
    )
    parser.add_argument("--runner-name", default="news-quality-eval-v2")
    parser.add_argument("--runner-version", default="0.1.0")
    parser.add_argument(
        "--mode",
        choices=("recorded_fixture", "offline_replay", "live_model", "e2e_live"),
        default="offline_replay",
    )
    parser.add_argument("--model-id")
    parser.add_argument("--prompt-version")
    parser.add_argument("--validator-version")
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args(argv)


def run_validation(args: argparse.Namespace) -> dict[str, object]:
    summary = EvaluationDatasetValidator().validate(
        args.dataset,
        expected_hash=args.expected_hash,
    )
    output: dict[str, object] = {
        "schema_version": summary.dataset.schema_version,
        "dataset_id": summary.dataset.dataset_id,
        "dataset_version": summary.dataset.dataset_version,
        "dataset_kind": summary.dataset.dataset_kind,
        "split": summary.dataset.split,
        "dataset_hash": summary.dataset_hash,
        "case_count": summary.case_count,
        "case_ids": summary.case_ids,
        "adapted_from_schema_version": summary.adapted_from_schema_version,
    }
    if args.manifest_output is not None:
        execution = ManifestExecutionConfig(
            runner_name=args.runner_name,
            runner_version=args.runner_version,
            mode=args.mode,
            model_id=args.model_id,
            prompt_version=args.prompt_version,
            validator_version=args.validator_version,
        )
        manifest = build_execution_manifest(summary, execution=execution)
        manifest_path = save_execution_manifest(
            manifest,
            args.manifest_output,
            overwrite=args.overwrite,
        )
        output["manifest_path"] = str(manifest_path)
        output["manifest_run_id"] = manifest.run_id
        output["manifest_status"] = manifest.status
    return output


def main() -> None:
    args = parse_args()
    try:
        output = run_validation(args)
    except (OSError, ValueError, ValidationError, json.JSONDecodeError) as exc:
        raise SystemExit(f"dataset validation failed: {exc}") from exc
    print(json.dumps(output, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()

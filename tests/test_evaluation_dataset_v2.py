"""Evaluation v2 dataset, hash, manifest, and legacy compatibility tests."""

import json
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path

import pytest
from pydantic import ValidationError

from evaluate_news_quality import DEFAULT_FIXTURE
from evaluation.dataset_v2 import (
    EvaluationDatasetV2,
    EvaluationDatasetValidator,
    ManifestExecutionConfig,
    build_execution_manifest,
    compute_dataset_hash,
    compute_holdout_ground_truth_hash,
    save_execution_manifest,
    verify_manifest_dataset,
)
from evaluation.news_quality_eval import load_eval_cases
from validate_evaluation_dataset import parse_args, run_validation


PROJECT_ROOT = Path(__file__).resolve().parents[1]
TEMPLATE_PATH = (
    PROJECT_ROOT
    / "evals"
    / "templates"
    / "news_quality_real_development_v2.template.json"
)
SYNTHETIC_TEMPLATE_PATH = (
    PROJECT_ROOT
    / "evals"
    / "templates"
    / "news_quality_synthetic_adversarial_development_v2.template.json"
)
SCHEMA_PATH = (
    PROJECT_ROOT / "evals" / "schema" / "news_quality_dataset_v2.schema.json"
)


def load_template_payload() -> dict:
    return json.loads(TEMPLATE_PATH.read_text(encoding="utf-8"))


def make_holdout_payload() -> dict:
    payload = load_template_payload()
    payload["dataset_id"] = "real-news-holdout"
    payload["dataset_version"] = "2.0.0"
    payload["split"] = "holdout"
    payload["holdout_frozen_at"] = "2026-09-22T01:00:00Z"
    case = payload["cases"][0]
    case["split"] = "holdout"
    case["human_annotation"] = {
        "status": "approved",
        "annotator_ids": ["annotator-a"],
        "reviewer_ids": ["reviewer-b"],
        "annotated_at": "2026-09-20T00:00:00Z",
        "reviewed_at": "2026-09-21T00:00:00Z",
        "sentiment_rationale": "제목은 방향성을 확정할 정보를 포함하지 않습니다.",
        "evidence_rationale": "유일한 입력 기사이므로 필수 근거로 지정했습니다.",
        "claim_grounding_notes": "expected claim은 제목이 직접 진술한 범위로 제한했습니다.",
        "reviewer_notes": "원본 snapshot과 annotation을 독립 확인했습니다.",
    }
    return payload


def test_v2_template_validates_and_hash_is_canonical():
    summary = EvaluationDatasetValidator().validate(TEMPLATE_PATH)
    reformatted = EvaluationDatasetV2.model_validate(load_template_payload())

    assert summary.dataset.schema_version == "2.0"
    assert summary.dataset.dataset_kind == "real_news"
    assert summary.case_count == 1
    assert summary.dataset_hash == compute_dataset_hash(reformatted)
    assert summary.dataset_hash.startswith("sha256:")
    assert len(summary.dataset_hash) == 71


def test_synthetic_template_is_a_separate_dataset_track():
    real_summary = EvaluationDatasetValidator().validate(TEMPLATE_PATH)
    synthetic_summary = EvaluationDatasetValidator().validate(SYNTHETIC_TEMPLATE_PATH)

    assert synthetic_summary.dataset.dataset_kind == "synthetic_adversarial"
    assert synthetic_summary.dataset.split == "development"
    assert synthetic_summary.dataset_hash != real_summary.dataset_hash


def test_checked_in_json_schema_matches_pydantic_source_of_truth():
    checked_in_schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))

    assert checked_in_schema == EvaluationDatasetV2.model_json_schema()


def test_legacy_six_cases_remain_loadable_and_are_separate_track():
    original_cases = load_eval_cases(DEFAULT_FIXTURE)
    summary = EvaluationDatasetValidator().validate(DEFAULT_FIXTURE)

    assert len(original_cases) == 6
    assert summary.adapted_from_schema_version == "1.0"
    assert summary.dataset.dataset_kind == "legacy_synthetic"
    assert summary.dataset.split == "legacy"
    assert summary.case_ids == tuple(case.case_id for case in original_cases)
    for original, adapted in zip(original_cases, summary.dataset.cases, strict=True):
        assert adapted.expectations.expected_sentiments == original.expected_sentiments
        assert adapted.expectations.required_evidence_ids == original.required_evidence_ids
        assert adapted.human_annotation.status == "legacy_unreviewed"
        assert adapted.legacy_compatibility is not None
        assert (
            adapted.legacy_compatibility.recorded_output
            == original.recorded_output.model_dump(mode="json")
        )


def test_validator_rejects_unknown_evidence_id(tmp_path):
    payload = load_template_payload()
    payload["cases"][0]["expectations"]["required_evidence_ids"] = [
        "news_ffffffffffffffff"
    ]
    path = tmp_path / "unknown-evidence.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValidationError, match="unknown evidence IDs"):
        EvaluationDatasetValidator().validate(path)


def test_validator_rejects_mixed_real_and_synthetic_tracks(tmp_path):
    payload = load_template_payload()
    payload["cases"][0]["data_source"]["source_kind"] = "synthetic_adversarial"
    payload["cases"][0]["data_source"].pop("retrieved_at")
    path = tmp_path / "mixed-track.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValidationError, match="cannot mix real and synthetic"):
        EvaluationDatasetValidator().validate(path)


def test_holdout_requires_frozen_approved_annotations():
    invalid = load_template_payload()
    invalid["split"] = "holdout"
    invalid["cases"][0]["split"] = "holdout"

    with pytest.raises(ValidationError, match="holdout_frozen_at"):
        EvaluationDatasetV2.model_validate(invalid)

    valid = EvaluationDatasetV2.model_validate(make_holdout_payload())

    assert valid.split == "holdout"
    assert valid.cases[0].human_annotation.status == "approved"
    assert compute_holdout_ground_truth_hash(valid).startswith("sha256:")


def test_manifest_detects_holdout_ground_truth_change(tmp_path):
    original_path = tmp_path / "holdout.json"
    original_path.write_text(json.dumps(make_holdout_payload()), encoding="utf-8")
    validator = EvaluationDatasetValidator()
    original = validator.validate(original_path)
    manifest = build_execution_manifest(
        original,
        execution=ManifestExecutionConfig(
            runner_name="news-quality-eval-v2",
            runner_version="0.1.0",
            mode="offline_replay",
            prompt_version="news-prompt-v1",
            validator_version="news-validator-v1",
        ),
        prepared_at=datetime(2026, 9, 22, 1, 2, 3, tzinfo=timezone.utc),
        run_id="evalv2_20260922T010203Z_1234abcd",
    )
    verify_manifest_dataset(manifest, original)

    changed_payload = deepcopy(make_holdout_payload())
    changed_payload["cases"][0]["expectations"]["expected_sentiments"] = [
        "positive"
    ]
    changed_path = tmp_path / "changed-holdout.json"
    changed_path.write_text(json.dumps(changed_payload), encoding="utf-8")
    changed = validator.validate(changed_path)

    assert changed.dataset_hash != original.dataset_hash
    assert (
        compute_holdout_ground_truth_hash(changed.dataset)
        != manifest.holdout_ground_truth_hash
    )
    with pytest.raises(ValueError, match="dataset_hash.*holdout_ground_truth_hash"):
        verify_manifest_dataset(manifest, changed)


def test_validator_can_pin_an_expected_dataset_hash():
    summary = EvaluationDatasetValidator().validate(TEMPLATE_PATH)

    pinned = EvaluationDatasetValidator().validate(
        TEMPLATE_PATH,
        expected_hash=summary.dataset_hash,
    )
    assert pinned.dataset_hash == summary.dataset_hash
    with pytest.raises(ValueError, match="dataset hash mismatch"):
        EvaluationDatasetValidator().validate(
            TEMPLATE_PATH,
            expected_hash="sha256:" + "0" * 64,
        )


def test_manifest_save_is_atomic_and_refuses_overwrite(tmp_path):
    summary = EvaluationDatasetValidator().validate(TEMPLATE_PATH)
    manifest = build_execution_manifest(
        summary,
        execution=ManifestExecutionConfig(
            runner_name="news-quality-eval-v2",
            runner_version="0.1.0",
            mode="offline_replay",
        ),
    )
    target = tmp_path / "manifest.json"

    saved = save_execution_manifest(manifest, target)

    assert saved == target.resolve()
    assert json.loads(saved.read_text(encoding="utf-8"))["status"] == "prepared"
    with pytest.raises(FileExistsError, match="already exists"):
        save_execution_manifest(manifest, target)


def test_validation_cli_prepares_manifest_without_running_a_model(tmp_path):
    manifest_path = tmp_path / "prepared-manifest.json"
    args = parse_args(
        [
            str(TEMPLATE_PATH),
            "--manifest-output",
            str(manifest_path),
            "--mode",
            "offline_replay",
            "--prompt-version",
            "news-prompt-v1",
            "--validator-version",
            "news-validator-v1",
        ]
    )

    output = run_validation(args)

    assert output["case_count"] == 1
    assert output["manifest_status"] == "prepared"
    manifest_payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest_payload["execution"]["mode"] == "offline_replay"
    assert manifest_payload["dataset_hash"] == output["dataset_hash"]

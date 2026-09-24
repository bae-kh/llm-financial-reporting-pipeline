"""Evaluation v2 runner/grader의 offline contract를 검증합니다."""

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from analysis.headline_policy import HeadlinePolicy
from analysis.news_analyzer import NewsAnalyzer
from evaluate_news_quality import RecordedClient as V1RecordedClient
from evaluation.dataset_v2 import EvaluationDatasetValidator
from evaluation.news_quality_eval import NewsEvalSuite, load_eval_cases
from evaluation.v2_runner import (
    DEFAULT_PROMPT_VERSION,
    DEFAULT_VALIDATOR_VERSION,
    EvaluationV2ArtifactStore,
    EvaluationV2RunIncompleteError,
    EvaluationV2Runner,
    case_to_news_fetch_result,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATASET_PATH = (
    PROJECT_ROOT
    / "evals"
    / "datasets"
    / "news"
    / "real"
    / "development"
    / "tsla_headlines_pilot_v2.json"
)
RECORDED_PATH = (
    PROJECT_ROOT / "evals" / "fixtures" / "news_quality_v2_recorded_smoke.json"
)
V1_FIXTURE = PROJECT_ROOT / "evals" / "fixtures" / "news_quality_cases.json"


def load_recorded_payload() -> dict:
    return json.loads(RECORDED_PATH.read_text(encoding="utf-8"))


def write_recorded_payload(tmp_path: Path, payload: dict) -> Path:
    path = tmp_path / "recorded.json"
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return path


def run_offline(
    tmp_path: Path,
    *,
    recorded_path: Path = RECORDED_PATH,
    artifact_store: EvaluationV2ArtifactStore | None = None,
):
    runner = EvaluationV2Runner(
        artifact_store=artifact_store
        or EvaluationV2ArtifactStore(tmp_path / "artifacts"),
    )
    return asyncio.run(
        runner.run(
            DATASET_PATH,
            mode="recorded",
            recorded_response_path=recorded_path,
        )
    )


def test_v2_dataset_loads_and_converts_without_rss_refetch():
    validated = EvaluationDatasetValidator().validate(DATASET_PATH)
    converted = case_to_news_fetch_result(validated.dataset.cases[0])

    assert validated.case_count == 5
    assert converted.metadata.request_count == 0
    assert converted.metadata.provider == "google_news_rss"
    assert converted.items[0].article_id == (
        validated.dataset.cases[0].news_headlines[0].article_id
    )
    assert "fixed evaluation snapshot" in converted.metadata.query


def test_dataset_hash_mismatch_is_rejected_before_run_artifacts(tmp_path):
    runner = EvaluationV2Runner(
        artifact_store=EvaluationV2ArtifactStore(tmp_path / "artifacts")
    )
    with pytest.raises(ValueError, match="dataset hash mismatch"):
        asyncio.run(
            runner.run(
                DATASET_PATH,
                mode="recorded",
                recorded_response_path=RECORDED_PATH,
                expected_dataset_hash="sha256:" + "0" * 64,
            )
        )

    assert not (tmp_path / "artifacts").exists()


def test_recorded_plan_hash_mismatch_is_rejected(tmp_path):
    payload = load_recorded_payload()
    payload["dataset_hash"] = "sha256:" + "f" * 64
    path = write_recorded_payload(tmp_path, payload)

    with pytest.raises(ValueError, match="dataset_hash"):
        run_offline(tmp_path, recorded_path=path)


def test_first_generation_success_writes_linked_complete_artifacts(tmp_path):
    result = run_offline(tmp_path)

    assert DEFAULT_PROMPT_VERSION == NewsAnalyzer.PROMPT_VERSION
    assert result.manifest.execution.prompt_version == "news-analyzer-prompt-v3"
    assert result.summary.prompt_version == "news-analyzer-prompt-v3"
    assert DEFAULT_VALIDATOR_VERSION == HeadlinePolicy.VALIDATOR_VERSION
    assert DEFAULT_VALIDATOR_VERSION == "news-analyzer-validator-v2"
    assert result.manifest.execution.validator_version == DEFAULT_VALIDATOR_VERSION
    assert result.summary.validator_version == DEFAULT_VALIDATOR_VERSION
    assert len(result.attempt_telemetry.cases) == 5
    assert all(len(trace.attempts) == 1 for trace in result.attempt_telemetry.cases)
    assert result.validator_reliability.metrics.first_pass_numerator == 5
    assert result.validator_reliability.metrics.final_pass_numerator == 5
    assert result.summary.result_scope == "development_diagnostic"
    assert result.summary.official_performance_eligible is False
    assert result.summary.semantic_accuracy_evaluated is False
    assert all(path.exists() for path in result.artifact_paths.values())

    run_id = result.manifest.run_id
    for key in (
        "case_outputs",
        "attempt_telemetry",
        "grading_results",
        "validator_reliability",
        "summary",
        "run_status",
    ):
        payload = json.loads(result.artifact_paths[key].read_text(encoding="utf-8"))
        assert payload["eval_run_id"] == run_id
    status = json.loads(
        result.artifact_paths["run_status"].read_text(encoding="utf-8")
    )
    assert status["status"] == "complete"


def test_first_failure_then_rewrite_success_is_scored_as_rescue(tmp_path):
    payload = load_recorded_payload()
    case = payload["cases"][0]
    invalid = json.loads(json.dumps(case["attempts"][0]))
    invalid["response_id"] = "stub_invalid_evidence"
    invalid["output"]["key_topics"][0]["supporting_article_ids"] = [
        "news_ffffffffffffffff"
    ]
    case["attempts"] = [invalid, case["attempts"][0]]
    path = write_recorded_payload(tmp_path, payload)

    result = run_offline(tmp_path, recorded_path=path)
    trace = result.attempt_telemetry.cases[0]

    assert [attempt.outcome for attempt in trace.attempts] == [
        "validator_failed",
        "validator_passed",
    ]
    metrics = result.validator_reliability.metrics
    assert metrics.rewrite_rescue_numerator == 1
    assert metrics.rewrite_rescue_denominator == 1
    assert metrics.final_pass_numerator == 5


def test_maximum_rewrites_end_in_unavailable_and_preserve_attempt_errors(tmp_path):
    payload = load_recorded_payload()
    case = payload["cases"][0]
    invalid = json.loads(json.dumps(case["attempts"][0]))
    invalid["output"]["key_topics"][0]["supporting_article_ids"] = [
        "news_ffffffffffffffff"
    ]
    case["attempts"] = [invalid, invalid, invalid]
    path = write_recorded_payload(tmp_path, payload)

    result = run_offline(tmp_path, recorded_path=path)
    trace = result.attempt_telemetry.cases[0]
    grade = result.grading_results.cases[0]

    assert trace.final_available is False
    assert trace.final_error_code == "validation_error"
    assert len(trace.attempts) == 3
    assert all(
        attempt.validator_error_code == "evidence_id_validation_error"
        for attempt in trace.attempts
    )
    assert grade.automatic.availability.status == "fail"
    assert grade.automatic.evidence_id_validity.status == "not_evaluated"
    assert result.validator_reliability.metrics.unavailable_count == 1


def test_wrong_sentiment_is_a_grader_failure_not_validator_accuracy(tmp_path):
    payload = load_recorded_payload()
    output = payload["cases"][0]["attempts"][0]["output"]
    output["sentiment"] = "neutral"
    output["score"] = 0.0
    path = write_recorded_payload(tmp_path, payload)

    result = run_offline(tmp_path, recorded_path=path)
    grade = result.grading_results.cases[0]

    assert grade.automatic.production_validator.status == "pass"
    assert grade.automatic.sentiment.status == "fail"
    assert result.summary.automatic_grading.sentiment_match.numerator == 4
    assert result.summary.semantic_accuracy_evaluated is False


def test_case_telemetry_is_isolated_and_keeps_case_specific_response_ids(tmp_path):
    result = run_offline(tmp_path)
    traces = result.attempt_telemetry.cases

    assert len({trace.case_id for trace in traces}) == 5
    response_ids = [trace.attempts[0].response_id for trace in traces]
    assert len(set(response_ids)) == 5
    assert all(trace.attempts[0].attempt_number == 1 for trace in traces)


def test_missing_token_usage_stays_null_and_is_reported_as_missing(tmp_path):
    result = run_offline(tmp_path)

    assert all(
        trace.attempts[0].token_usage is None
        for trace in result.attempt_telemetry.cases
    )
    efficiency = result.summary.efficiency
    assert efficiency.token_usage_reported_attempt_count == 0
    assert efficiency.token_usage_missing_attempt_count == 5
    assert efficiency.total_tokens_total is None
    assert efficiency.token_values_estimated is False


def test_provider_reported_token_usage_is_aggregated_without_estimation(tmp_path):
    payload = load_recorded_payload()
    for case in payload["cases"]:
        case["attempts"][0]["token_usage"] = {
            "input_tokens": 10,
            "output_tokens": 4,
            "total_tokens": 14,
        }
    path = write_recorded_payload(tmp_path, payload)

    result = run_offline(tmp_path, recorded_path=path)
    efficiency = result.summary.efficiency

    assert efficiency.token_usage_reported_attempt_count == 5
    assert efficiency.token_usage_missing_attempt_count == 0
    assert efficiency.input_tokens_total == 50
    assert efficiency.output_tokens_total == 20
    assert efficiency.total_tokens_total == 70
    assert efficiency.token_values_estimated is False


class FailingAttemptStore(EvaluationV2ArtifactStore):
    def save_attempts(self, artifact, path, *, overwrite):
        raise OSError("simulated attempt artifact write failure")


def test_attempt_artifact_failure_marks_run_incomplete(tmp_path):
    store = FailingAttemptStore(tmp_path / "artifacts")
    with pytest.raises(EvaluationV2RunIncompleteError) as captured:
        run_offline(tmp_path, artifact_store=store)

    status_path = captured.value.status_path
    status = json.loads(status_path.read_text(encoding="utf-8"))
    assert status["status"] == "incomplete"
    assert "attempt_telemetry" in status["missing_artifacts"]
    assert "case_outputs" in status["written_artifacts"]
    assert "simulated attempt artifact write failure" in status["error_message"]


def test_live_mode_requires_explicit_opt_in_before_client_creation(tmp_path):
    runner = EvaluationV2Runner(
        artifact_store=EvaluationV2ArtifactStore(tmp_path / "artifacts")
    )
    with pytest.raises(RuntimeError, match="disabled by default"):
        asyncio.run(
            runner.run(
                DATASET_PATH,
                mode="live",
                model_id="gpt-test",
                api_key="not-used",
                allow_live=False,
            )
        )

    assert not (tmp_path / "artifacts").exists()


def test_v1_runner_contract_remains_compatible():
    case = load_eval_cases(V1_FIXTURE)[0]
    suite = NewsEvalSuite()
    result = asyncio.run(
        suite.run(
            (case,),
            analyzer_factory=lambda selected: NewsAnalyzer(
                client=V1RecordedClient(selected),
                model="recorded-fixture-v1",
            ),
            mode="recorded_fixture",
            model="recorded-fixture-v1",
            fixture_path=V1_FIXTURE,
            repetitions=1,
        )
    )

    assert result.total_case_runs == 1
    assert result.passed_case_runs == 1


def test_production_analyzer_without_telemetry_remains_compatible():
    validated = EvaluationDatasetValidator().validate(DATASET_PATH)
    case = validated.dataset.cases[0]
    output = load_recorded_payload()["cases"][0]["attempts"][0]["output"]

    class Responses:
        async def parse(self, **_kwargs):
            return SimpleNamespace(output_parsed=output)

    analysis = asyncio.run(
        NewsAnalyzer(
            client=SimpleNamespace(responses=Responses()),
            model="production-compat-test",
        ).analyze(case_to_news_fetch_result(case))
    )

    assert analysis.available is True
    assert "attempt" not in analysis.model_dump()

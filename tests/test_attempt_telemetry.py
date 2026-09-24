"""LLM attempt telemetry, artifact 분리, validator 지표를 검증합니다."""

import asyncio
import json
from datetime import date, datetime, timezone
from types import SimpleNamespace

import pytest

from analysis.news_analyzer import NewsAnalyzer, NewsLLMOutput, TopicEvidence
from data_pipeline.news_fetcher import NewsFetchMetadata, NewsFetchResult, NewsItem
from evaluation.attempt_telemetry import (
    AttemptTelemetryArtifactStore,
    AttemptTelemetryCollector,
    build_attempt_telemetry_artifact,
    compute_validator_reliability_metrics,
)
from workflow.analysis_window import AnalysisWindow


ARTICLE_ID = "news_0000000000000001"


def make_news() -> NewsFetchResult:
    window = AnalysisWindow(
        ticker="TSLA",
        requested_analysis_days=1,
        start_date=date(2026, 8, 20),
        end_date=date(2026, 8, 20),
    )
    item = NewsItem(
        article_id=ARTICLE_ID,
        title="TSLA reports record revenue",
        published_at=datetime(2026, 8, 20, 12, tzinfo=timezone.utc),
        url="https://news.google.com/articles/telemetry-1",
        source="Example Source",
    )
    return NewsFetchResult(
        ticker="TSLA",
        window=window,
        status="available",
        available=True,
        items=(item,),
        metadata=NewsFetchMetadata(
            query="TSLA stock",
            fetched_at=datetime(2026, 8, 20, 13, tzinfo=timezone.utc),
            window_query_status="complete",
            raw_item_count=1,
            invalid_item_count=0,
            outside_window_count=0,
            in_window_item_count=1,
            duplicate_item_count=0,
            truncated_item_count=0,
            stored_item_count=1,
        ),
    )


def output_for(article_id: str) -> NewsLLMOutput:
    return NewsLLMOutput(
        sentiment="positive",
        score=0.5,
        confidence=80,
        summary="제목은 테슬라가 기록적인 매출을 발표했다고 전합니다.",
        key_topics=(
            TopicEvidence(
                topic="기록적 매출",
                explanation="제목에 기록적인 매출 발표가 명시됐습니다.",
                supporting_article_ids=(article_id,),
            ),
        ),
    )


class SequenceResponses:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    async def parse(self, **kwargs):
        self.calls.append(kwargs)
        value = self.responses.pop(0)
        if isinstance(value, Exception):
            raise value
        return value


class SequenceClient:
    def __init__(self, responses):
        self.responses = SequenceResponses(responses)


def response(
    output,
    *,
    model="gpt-test-resolved-2026-08-20",
    usage=SimpleNamespace(input_tokens=120, output_tokens=40, total_tokens=160),
):
    values = {
        "id": "resp_test_1",
        "model": model,
        "output_parsed": output,
        "output_text": '{"sentiment":"positive"}',
    }
    if usage is not ...:
        values["usage"] = usage
    return SimpleNamespace(**values)


def run_with_telemetry(responses, *, enabled=True):
    collector = AttemptTelemetryCollector(enabled=enabled)
    analyzer = NewsAnalyzer(
        client=SequenceClient(responses),
        model="gpt-test-requested",
        attempt_telemetry_sink=collector,
    )
    analysis = asyncio.run(analyzer.analyze(make_news()))
    return analysis, collector


def test_first_generation_success_records_exact_response_metadata_and_usage():
    analysis, collector = run_with_telemetry([response(output_for(ARTICLE_ID))])

    assert analysis.available is True
    assert len(collector.attempts) == 1
    attempt = collector.attempts[0]
    assert attempt.attempt_number == 1
    assert attempt.started_at.tzinfo is not None
    assert attempt.finished_at >= attempt.started_at
    assert attempt.latency_ms >= 0
    assert attempt.requested_model_id == "gpt-test-requested"
    assert attempt.response_model_id == "gpt-test-resolved-2026-08-20"
    assert attempt.response_id == "resp_test_1"
    assert attempt.parse_succeeded is True
    assert attempt.validator_passed is True
    assert attempt.outcome == "validator_passed"
    assert attempt.structured_output["sentiment"] == "positive"
    assert attempt.token_usage.input_tokens == 120
    assert attempt.token_usage.output_tokens == 40
    assert attempt.token_usage.total_tokens == 160


def test_first_failure_then_rewrite_success_is_measurable_as_rescue():
    invalid = output_for("news_ffffffffffffffff")
    valid = output_for(ARTICLE_ID)
    analysis, collector = run_with_telemetry(
        [response(invalid), response(valid)]
    )

    assert analysis.available is True
    assert [attempt.outcome for attempt in collector.attempts] == [
        "validator_failed",
        "validator_passed",
    ]
    assert collector.attempts[0].validator_error_code == (
        "evidence_id_validation_error"
    )
    assert collector.attempts[0].structured_output["key_topics"][0][
        "supporting_article_ids"
    ] == ["news_ffffffffffffffff"]

    trace = collector.build_case_trace(case_id="rewrite-success", analysis=analysis)
    metrics = compute_validator_reliability_metrics((trace,))
    assert metrics.first_pass_validator_pass_rate == 0.0
    assert metrics.final_pass_validator_pass_rate == 1.0
    assert metrics.rewrite_rescue_rate == 1.0
    assert metrics.average_attempt_count == 2.0
    assert metrics.final_unavailable_rate == 0.0


def test_schema_parse_failure_is_separate_from_validator_failure():
    invalid_shape = {
        "sentiment": "positive",
        "score": 2.0,
        "confidence": 180,
        "summary": "invalid",
        "key_topics": [],
    }
    analysis, collector = run_with_telemetry(
        [response(invalid_shape), response(output_for(ARTICLE_ID))]
    )

    assert analysis.available is True
    first = collector.attempts[0]
    assert first.outcome == "parse_failed"
    assert first.parse_succeeded is False
    assert first.validator_passed is None
    assert first.parse_error_code == "structured_output_schema_error"
    assert first.validator_error_code is None
    assert first.structured_output == invalid_shape


def test_maximum_rewrites_record_three_failures_and_final_unavailable():
    invalid = output_for("news_ffffffffffffffff")
    analysis, collector = run_with_telemetry(
        [response(invalid), response(invalid), response(invalid)]
    )

    assert analysis.available is False
    assert analysis.error_code == "validation_error"
    assert len(collector.attempts) == NewsAnalyzer.MAX_VALIDATION_ATTEMPTS
    assert all(
        attempt.outcome == "validator_failed"
        for attempt in collector.attempts
    )

    trace = collector.build_case_trace(case_id="final-failure", analysis=analysis)
    metrics = compute_validator_reliability_metrics((trace,))
    assert metrics.first_pass_validator_pass_rate == 0.0
    assert metrics.final_pass_validator_pass_rate == 0.0
    assert metrics.rewrite_rescue_rate == 0.0
    assert metrics.average_attempt_count == 3.0
    assert metrics.final_unavailable_rate == 1.0


def test_api_exception_records_null_response_fields_and_remains_unavailable():
    analysis, collector = run_with_telemetry([RuntimeError("API down")])

    assert analysis.available is False
    assert analysis.error_code == "llm_error"
    attempt = collector.attempts[0]
    assert attempt.outcome == "api_error"
    assert attempt.response_metadata_available is False
    assert attempt.response_model_id is None
    assert attempt.parse_succeeded is None
    assert attempt.validator_passed is None
    assert attempt.token_usage is None
    assert attempt.api_error_code == "llm_api_exception"
    assert "RuntimeError" in attempt.api_error_reason

    trace = collector.build_case_trace(case_id="api-error", analysis=analysis)
    metrics = compute_validator_reliability_metrics((trace,))
    assert metrics.first_pass_denominator == 0
    assert metrics.first_pass_validator_pass_rate is None
    assert metrics.final_pass_validator_pass_rate is None
    assert metrics.final_unavailable_rate == 1.0


def test_missing_token_usage_is_null_instead_of_estimated():
    analysis, collector = run_with_telemetry(
        [response(output_for(ARTICLE_ID), usage=...)]
    )

    assert analysis.available is True
    assert collector.attempts[0].token_usage is None


def test_telemetry_is_disabled_by_default_and_does_not_enter_final_analysis():
    analysis, collector = run_with_telemetry(
        [response(output_for(ARTICLE_ID))],
        enabled=False,
    )

    assert analysis.available is True
    assert collector.attempts == ()
    assert "attempt" not in analysis.model_dump()
    with pytest.raises(RuntimeError, match="disabled"):
        collector.build_case_trace(case_id="disabled", analysis=analysis)


def test_attempt_artifact_is_explicit_and_separate_from_operational_result(tmp_path):
    analysis, collector = run_with_telemetry([response(output_for(ARTICLE_ID))])
    trace = collector.build_case_trace(case_id="artifact-case", analysis=analysis)
    artifact = build_attempt_telemetry_artifact(
        eval_run_id="eval_attempt_test",
        cases=(trace,),
        dataset_id="dataset-test",
        dataset_version="2.0.0-test",
        dataset_hash="sha256:" + "a" * 64,
        generated_at=datetime(2026, 8, 20, 14, tzinfo=timezone.utc),
    )

    path = AttemptTelemetryArtifactStore(tmp_path).save(artifact)
    payload = json.loads(path.read_text(encoding="utf-8"))

    assert path.parent == tmp_path.resolve()
    assert payload["contains_full_model_outputs"] is True
    assert payload["metric_scope"] == "production_validator_only"
    assert payload["cases"][0]["attempts"][0]["structured_output"]
    assert "attempts" not in analysis.model_dump()
    with pytest.raises(FileExistsError):
        AttemptTelemetryArtifactStore(tmp_path).save(artifact)


def test_telemetry_sink_failure_does_not_change_production_analysis():
    class FailingSink:
        enabled = True

        def record_attempt(self, _attempt):
            raise OSError("telemetry disk unavailable")

    analyzer = NewsAnalyzer(
        client=SequenceClient([response(output_for(ARTICLE_ID))]),
        attempt_telemetry_sink=FailingSink(),
    )

    analysis = asyncio.run(analyzer.analyze(make_news()))

    assert analysis.available is True
    assert analysis.fallback_used is False

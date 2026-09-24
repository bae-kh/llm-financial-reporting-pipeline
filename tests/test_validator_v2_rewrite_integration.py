"""Validator v2와 NewsAnalyzer 재작성 경로를 외부 API 없이 통합 검증합니다."""

from __future__ import annotations

import asyncio
import json
from datetime import date, datetime, timezone
from types import SimpleNamespace

from analysis.news_analyzer import NewsAnalyzer, NewsLLMOutput, TopicEvidence
from data_pipeline.news_fetcher import NewsFetchMetadata, NewsFetchResult, NewsItem
from evaluation.attempt_telemetry import AttemptTelemetryCollector
from workflow.analysis_window import AnalysisWindow


ARTICLE_ID = "news_00000000000000d5"
UNKNOWN_ARTICLE_ID = "news_ffffffffffffffff"


def make_delivery_site_news() -> NewsFetchResult:
    window = AnalysisWindow(
        ticker="TSLA",
        requested_analysis_days=1,
        start_date=date(2026, 8, 10),
        end_date=date(2026, 8, 10),
    )
    item = NewsItem(
        article_id=ARTICLE_ID,
        title=(
            "Tesla opens more delivery sites in Japan amid stronger EV demand"
        ),
        published_at=datetime(2026, 8, 10, 12, tzinfo=timezone.utc),
        url="https://news.example/validator-v2-rewrite",
        source="Offline Integration Fixture",
    )
    return NewsFetchResult(
        ticker="TSLA",
        window=window,
        status="available",
        available=True,
        items=(item,),
        metadata=NewsFetchMetadata(
            query="TSLA stock",
            fetched_at=datetime(2026, 8, 10, 13, tzinfo=timezone.utc),
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


def unsupported_volume_output(
    article_id: str = ARTICLE_ID,
) -> NewsLLMOutput:
    return NewsLLMOutput(
        sentiment="positive",
        score=0.5,
        confidence=80,
        summary="테슬라가 일본에서 차량 인도 거점을 추가로 열었습니다.",
        key_topics=(
            TopicEvidence(
                topic="차량 인도량 증가",
                explanation=(
                    "테슬라의 실제 차량 인도 대수가 증가했다는 내용입니다."
                ),
                supporting_article_ids=(article_id,),
            ),
        ),
    )


def grounded_location_output(
    article_id: str = ARTICLE_ID,
) -> NewsLLMOutput:
    return NewsLLMOutput(
        sentiment="positive",
        score=0.5,
        confidence=80,
        summary="테슬라가 일본에서 차량 인도 거점을 추가로 열었습니다.",
        key_topics=(
            TopicEvidence(
                topic="차량 인도 거점 확대",
                explanation=(
                    "테슬라가 일본에서 차량 인도 거점을 추가로 열었습니다."
                ),
                supporting_article_ids=(article_id,),
            ),
        ),
    )


def response(output: NewsLLMOutput, index: int) -> SimpleNamespace:
    return SimpleNamespace(
        id=f"resp_validator_v2_{index}",
        model="gpt-offline-validator-v2",
        output_parsed=output,
        output_text=json.dumps(output.model_dump(mode="json"), ensure_ascii=False),
        usage=SimpleNamespace(
            input_tokens=100,
            output_tokens=40,
            total_tokens=140,
        ),
    )


class SequenceResponses:
    def __init__(self, values: list[SimpleNamespace | Exception]) -> None:
        self.values = list(values)
        self.calls: list[dict] = []

    async def parse(self, **kwargs):
        self.calls.append(kwargs)
        if not self.values:
            raise AssertionError("unexpected additional LLM generation call")
        value = self.values.pop(0)
        if isinstance(value, Exception):
            raise value
        return value


class SequenceClient:
    def __init__(self, values: list[SimpleNamespace | Exception]) -> None:
        self.responses = SequenceResponses(values)


def run_analysis(values: list[SimpleNamespace | Exception]):
    collector = AttemptTelemetryCollector(enabled=True)
    client = SequenceClient(values)
    analyzer = NewsAnalyzer(
        client=client,
        model="gpt-offline-requested",
        attempt_telemetry_sink=collector,
    )
    analysis = asyncio.run(analyzer.analyze(make_delivery_site_news()))
    return analysis, client, collector


def user_content(call: dict) -> str:
    return call["input"][1]["content"]


def test_validator_v2_rewrites_unsupported_volume_then_accepts_location():
    rejected = unsupported_volume_output()
    accepted = grounded_location_output()

    analysis, client, collector = run_analysis(
        [response(rejected, 1), response(accepted, 2)]
    )

    assert len(client.responses.calls) == 2
    assert analysis.available is True
    assert analysis.fallback_used is False
    assert analysis.error_code is None
    assert analysis.key_topics == accepted.key_topics
    assert "인도량" not in analysis.summary
    assert "인도량" not in analysis.key_topics[0].topic
    assert "실제 차량 인도 대수" not in analysis.key_topics[0].explanation
    assert any("1회 재작성" in warning for warning in analysis.warnings)

    attempts = collector.attempts
    assert [attempt.outcome for attempt in attempts] == [
        "validator_failed",
        "validator_passed",
    ]
    assert attempts[0].parse_succeeded is True
    assert attempts[0].validator_passed is False
    assert attempts[0].validator_error_code == (
        "output_policy_validation_error"
    )
    assert "vehicle_delivery_volume" in attempts[0].validator_error_reason
    assert attempts[1].parse_succeeded is True
    assert attempts[1].validator_passed is True

    first_request = user_content(client.responses.calls[0])
    rewrite_request = user_content(client.responses.calls[1])
    assert "previous draft was rejected" not in first_request
    assert "previous draft was rejected" in rewrite_request
    assert "vehicle_delivery_volume" in rewrite_request
    assert f"allowed list: [{ARTICLE_ID}]" in rewrite_request
    assert rejected.key_topics[0].explanation not in rewrite_request


def test_validator_v2_returns_validation_fallback_after_three_rejections():
    rejected = unsupported_volume_output()
    analysis, client, collector = run_analysis(
        [
            response(rejected, 1),
            response(rejected, 2),
            response(rejected, 3),
        ]
    )

    assert len(client.responses.calls) == NewsAnalyzer.MAX_VALIDATION_ATTEMPTS
    assert len(collector.attempts) == NewsAnalyzer.MAX_VALIDATION_ATTEMPTS
    assert all(
        attempt.outcome == "validator_failed"
        for attempt in collector.attempts
    )
    assert all(
        attempt.validator_error_code == "output_policy_validation_error"
        for attempt in collector.attempts
    )
    assert all(
        "vehicle_delivery_volume" in attempt.validator_error_reason
        for attempt in collector.attempts
    )

    assert analysis.available is False
    assert analysis.fallback_used is True
    assert analysis.error_code == "validation_error"
    assert analysis.sentiment is None
    assert analysis.score is None
    assert analysis.key_topics == ()
    assert analysis.analyzed_article_count == 0
    assert any(
        "vehicle_delivery_volume" in warning for warning in analysis.warnings
    )


def test_validator_v2_accepts_grounded_location_without_rewrite():
    accepted = grounded_location_output()
    analysis, client, collector = run_analysis([response(accepted, 1)])

    assert len(client.responses.calls) == 1
    assert analysis.available is True
    assert analysis.fallback_used is False
    assert analysis.error_code is None
    assert analysis.key_topics == accepted.key_topics
    assert [attempt.outcome for attempt in collector.attempts] == [
        "validator_passed"
    ]
    assert all("재작성" not in warning for warning in analysis.warnings)


def test_api_error_is_not_retried_as_validation_failure():
    analysis, client, collector = run_analysis(
        [RuntimeError("offline API failure")]
    )

    assert len(client.responses.calls) == 1
    assert analysis.available is False
    assert analysis.fallback_used is True
    assert analysis.error_code == "llm_error"
    assert analysis.sentiment is None
    assert analysis.score is None
    assert len(collector.attempts) == 1
    attempt = collector.attempts[0]
    assert attempt.outcome == "api_error"
    assert attempt.validator_error_code is None
    assert attempt.api_error_code == "llm_api_exception"
    assert "RuntimeError" in attempt.api_error_reason


def test_unknown_evidence_id_uses_existing_validation_before_policy_rewrite():
    unknown_evidence = grounded_location_output(UNKNOWN_ARTICLE_ID)
    accepted = grounded_location_output()
    analysis, client, collector = run_analysis(
        [response(unknown_evidence, 1), response(accepted, 2)]
    )

    assert analysis.available is True
    assert len(client.responses.calls) == 2
    first_attempt = collector.attempts[0]
    assert first_attempt.parse_succeeded is True
    assert first_attempt.validator_error_code == "evidence_id_validation_error"
    assert "unknown article_id" in first_attempt.validator_error_reason

    rewrite_request = user_content(client.responses.calls[1])
    assert UNKNOWN_ARTICLE_ID in rewrite_request
    assert f"allowed list: [{ARTICLE_ID}]" in rewrite_request
    assert collector.attempts[1].outcome == "validator_passed"

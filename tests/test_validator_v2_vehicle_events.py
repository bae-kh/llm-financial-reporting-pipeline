"""Validator v2의 차량 사건 grounding을 외부 API 없이 검증합니다."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from analysis.headline_policy import HeadlinePolicy
from analysis.news_analyzer import (
    NewsAnalysisValidationError,
    NewsAnalyzer,
    NewsLLMOutput,
    TopicEvidence,
)
from data_pipeline.news_fetcher import NewsItem


PROJECT_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_PATH = (
    PROJECT_ROOT / "evals" / "fixtures" / "news_validator_v2_vehicle_events.json"
)


def load_cases() -> tuple[dict, ...]:
    payload = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    assert payload["validator_version"] == "news-analyzer-validator-v2"
    assert payload["mode"] == "offline_validator_contract"
    return tuple(payload["cases"])


def make_item(index: int, title: str) -> NewsItem:
    return NewsItem(
        article_id=f"news_{index:016x}",
        title=title,
        published_at=datetime(2024, 12, index + 1, 8, tzinfo=timezone.utc),
        url=f"https://news.example/validator-v2-{index}",
        source="Offline Fixture",
    )


def output_from_case(case: dict, items: tuple[NewsItem, ...]) -> NewsLLMOutput:
    return NewsLLMOutput(
        sentiment="neutral",
        score=0.0,
        confidence=80,
        summary=case["summary"],
        key_topics=tuple(
            TopicEvidence(
                topic=topic["topic"],
                explanation=topic["explanation"],
                supporting_article_ids=tuple(
                    items[index].article_id
                    for index in topic["supporting_headline_indexes"]
                ),
            )
            for topic in case["topics"]
        ),
    )


@pytest.mark.parametrize("case", load_cases(), ids=lambda case: case["case_id"])
def test_vehicle_event_fixture_matches_expected_policy(case):
    items = tuple(
        make_item(index, headline)
        for index, headline in enumerate(case["headlines"])
    )
    output = output_from_case(case, items)

    NewsAnalyzer._validate_evidence_ids(output, items)
    expected_violation = case["expected_violation"]
    if expected_violation is None:
        NewsAnalyzer._validate_output_policy(output, items)
    else:
        with pytest.raises(NewsAnalysisValidationError, match=expected_violation):
            NewsAnalyzer._validate_output_policy(output, items)


def test_bare_delivery_terms_do_not_prove_vehicle_delivery_volume():
    assert HeadlinePolicy.vehicle_event_concepts(
        "Company publishes a delivery update",
        role="source",
    ) == frozenset()
    assert HeadlinePolicy.vehicle_event_concepts(
        "회사가 차량 인도 계획을 설명했습니다.",
        role="output",
    ) == frozenset()
    assert HeadlinePolicy.vehicle_event_concepts(
        "회사의 차량 인도가 증가했습니다.",
        role="output",
    ) == frozenset({"vehicle_delivery_volume"})


def test_delivery_location_does_not_also_trigger_volume():
    assert HeadlinePolicy.vehicle_event_concepts(
        "회사가 새 차량 인도 거점을 열었습니다.",
        role="output",
    ) == frozenset({"delivery_location"})


def test_qualified_vehicle_delivery_claim_is_volume_but_bare_delivery_is_not():
    assert HeadlinePolicy.vehicle_event_concepts(
        "차량 인도",
        role="output",
    ) == frozenset()
    assert HeadlinePolicy.vehicle_event_concepts(
        "기록적인 차량 인도를 선도했습니다.",
        role="output",
    ) == frozenset({"vehicle_delivery_volume"})


def test_recall_source_rejects_qualified_vehicle_delivery_claim():
    article = make_item(1, "Tesla linked to record China vehicle recall over door safety")
    output = NewsLLMOutput(
        sentiment="negative",
        score=-0.5,
        confidence=85,
        summary="테슬라가 중국의 기록적인 차량 리콜에 연관됐습니다.",
        key_topics=(
            TopicEvidence(
                topic="차량 인도",
                explanation=(
                    "테슬라가 문 안전 문제로 기록적인 차량 인도를 "
                    "선도하고 있습니다."
                ),
                supporting_article_ids=(article.article_id,),
            ),
        ),
    )

    with pytest.raises(
        NewsAnalysisValidationError,
        match="vehicle_delivery_volume",
    ):
        NewsAnalyzer._validate_output_policy(output, (article,))


def test_topic_cannot_borrow_volume_evidence_from_uncited_article():
    location = make_item(1, "Polestar opens a delivery hub in Sweden")
    volume = make_item(2, "Polestar vehicle deliveries rise in Sweden")
    output = NewsLLMOutput(
        sentiment="neutral",
        score=0.0,
        confidence=80,
        summary="폴스타 관련 차량 뉴스입니다.",
        key_topics=(
            TopicEvidence(
                topic="차량 인도량 증가",
                explanation="폴스타의 차량 인도 대수가 증가했습니다.",
                supporting_article_ids=(location.article_id,),
            ),
        ),
    )

    NewsAnalyzer._validate_evidence_ids(output, (location, volume))
    with pytest.raises(
        NewsAnalysisValidationError,
        match="vehicle_delivery_volume",
    ):
        NewsAnalyzer._validate_output_policy(output, (location, volume))


def test_topic_accepts_volume_evidence_from_cited_volume_article():
    location = make_item(1, "Polestar opens a delivery hub in Sweden")
    volume = make_item(2, "Polestar vehicle deliveries rise in Sweden")
    output = NewsLLMOutput(
        sentiment="neutral",
        score=0.0,
        confidence=80,
        summary="폴스타 관련 차량 뉴스입니다.",
        key_topics=(
            TopicEvidence(
                topic="차량 인도량 증가",
                explanation="폴스타의 차량 인도 대수가 증가했습니다.",
                supporting_article_ids=(volume.article_id,),
            ),
        ),
    )

    NewsAnalyzer._validate_evidence_ids(output, (location, volume))
    NewsAnalyzer._validate_output_policy(output, (location, volume))


def test_vehicle_delivery_report_remains_valid_volume_evidence():
    article = make_item(1, "Tesla schedules Q4 vehicle delivery report")
    output = NewsLLMOutput(
        sentiment="neutral",
        score=0.0,
        confidence=78,
        summary="테슬라의 4분기 차량 인도량 보고서 일정이 확인됐습니다.",
        key_topics=(
            TopicEvidence(
                topic="차량 인도량 보고서",
                explanation="4분기 차량 인도량 보고서 일정에 관한 제목입니다.",
                supporting_article_ids=(article.article_id,),
            ),
        ),
    )

    NewsAnalyzer._validate_output_policy(output, (article,))


def test_tsla_v1_delivery_site_volume_claim_is_rejected_generically():
    article = make_item(
        1,
        "Tesla opens more delivery sites in Japan amid stronger EV demand",
    )
    output = NewsLLMOutput(
        sentiment="neutral",
        score=0.0,
        confidence=65,
        summary=(
            "일본에서 전기차 수요 증가에 따라 테슬라가 더 많은 차량 인도 "
            "장소를 개설했습니다."
        ),
        key_topics=(
            TopicEvidence(
                topic="차량 인도 장소 개설",
                explanation=(
                    "테슬라는 일본 시장에서의 차량 인도량 증가에 대응하기 위해 "
                    "새로운 인도 장소를 열었습니다."
                ),
                supporting_article_ids=(article.article_id,),
            ),
        ),
    )

    with pytest.raises(
        NewsAnalysisValidationError,
        match="vehicle_delivery_volume",
    ):
        NewsAnalyzer._validate_output_policy(output, (article,))

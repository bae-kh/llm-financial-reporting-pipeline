"""Prompt v3의 도메인 의미 보존 계약을 외부 API 없이 검증합니다."""

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from analysis.news_analyzer import NewsAnalyzer
from data_pipeline.news_fetcher import NewsItem


PROJECT_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_PATH = (
    PROJECT_ROOT / "evals" / "fixtures" / "news_prompt_v3_regression_cases.json"
)
EXPECTED_CONCEPTS = {
    "revenue_profit_earnings",
    "delivery_site_volume",
    "vehicle_recall_delivery",
    "record_large",
    "action_status",
    "roundup_rating_change",
}


def load_cases() -> list[dict]:
    payload = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    assert payload["prompt_version"] == NewsAnalyzer.PROMPT_VERSION
    assert payload["mode"] == "offline_prompt_contract"
    return payload["cases"]


def make_item(index: int, title: str) -> NewsItem:
    return NewsItem(
        article_id=f"news_{index:016x}",
        title=title,
        published_at=datetime(2026, 9, 1, tzinfo=timezone.utc),
        url=f"https://news.example/prompt-v3-{index}",
        source="Prompt Contract Fixture",
    )


def test_prompt_v3_regression_fixture_is_generalized_and_two_sided():
    cases = load_cases()

    assert len(cases) == 12
    assert all(case["ticker"] != "TSLA" for case in cases)
    assert len({case["headline"] for case in cases}) == len(cases)
    assert {
        concept
        for case in cases
        for concept in case["concepts"]
    } == EXPECTED_CONCEPTS
    assert all(case["allowed_interpretations"] for case in cases)
    assert all(case["error_interpretations"] for case in cases)
    assert all("expected_sentiment" not in case for case in cases)


def test_prompt_v3_base_rule_preserves_domain_semantics_without_gold_answers():
    prompt = NewsAnalyzer.SYSTEM_INSTRUCTIONS

    assert NewsAnalyzer.PROMPT_VERSION == "news-analyzer-prompt-v3"
    assert prompt == NewsAnalyzer.PROMPT_V3_SYSTEM_INSTRUCTIONS
    assert hashlib.sha256(prompt.encode("utf-8")).hexdigest() == (
        "c89a81c67ba084f9519da289e994415aaa36a17c3b98a6934c83df2a2fac496e"
    )
    assert "revenue as 매출" in prompt
    assert "profit as 이익" in prompt
    assert "net income as 순이익" in prompt
    assert "earnings as 실적" in prompt
    assert "delivery sites or locations" in prompt
    assert "vehicle delivery counts or volumes" in prompt
    assert "vehicle recalls" in prompt
    assert "Preserve record as 기록적 or 기록적인" in prompt
    assert "announced, launched, implemented, or completed" in prompt
    assert "analyst upgrades/downgrades roundup" in prompt
    assert "차량 인도량" not in prompt
    assert "TSLA" not in prompt
    assert "case_id" not in prompt


def test_vehicle_delivery_translation_examples_remain_context_specific():
    cases = load_cases()

    for index, case in enumerate(cases, start=1):
        prompt = NewsAnalyzer._system_instructions(
            (make_item(index, case["headline"]),)
        )
        has_context_rule = "Context-specific translation rule:" in prompt
        expected = case["translation_rule_scope"] == "vehicle_delivery_context"

        assert has_context_rule is expected, case["case_id"]
        if expected:
            assert "차량 인도/차량 인도량/차량 인도량 보고서" in prompt
        else:
            assert "차량 인도량" not in prompt

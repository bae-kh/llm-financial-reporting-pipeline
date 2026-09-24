"""명백한 비뉴스형 페이지는 제외하고 실제 해설 기사는 보존합니다."""

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from analysis.headline_policy import HeadlinePolicy
from data_pipeline.news_fetcher import NewsItem


FIXTURE_PATH = (
    Path(__file__).parents[1]
    / "evals"
    / "fixtures"
    / "news_low_information_page_filter_cases.json"
)


def load_cases() -> list[dict[str, object]]:
    payload = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    assert payload["schema_version"] == "1.0"
    return payload["cases"]


@pytest.mark.parametrize(
    "case",
    load_cases(),
    ids=lambda case: str(case["case_id"]),
)
def test_low_information_page_patterns_are_conservative(
    case: dict[str, object],
) -> None:
    kind = HeadlinePolicy.low_information_page_kind(str(case["title"]))

    assert (kind is not None) is case["expected_blocked"]
    assert kind == case["expected_kind"]


def test_filter_reports_low_information_pages_separately() -> None:
    page = NewsItem(
        article_id="news_0000000000000001",
        title=(
            "AAPL 270115 200.00C (AAPL270115C200000) "
            "Stock Options Chain | Quotes & News - Market Portal"
        ),
        published_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
        url="https://example.com/aapl-option-chain",
        source="Market Portal",
    )
    article = page.model_copy(
        update={
            "article_id": "news_0000000000000002",
            "title": "Apple options activity rises after quarterly earnings",
            "url": "https://example.com/aapl-options-article",
        }
    )

    result = HeadlinePolicy().filter_for_ticker((page, article), ticker="AAPL")

    assert result.eligible_items == (article,)
    assert result.low_information_page_items == (page,)
    assert result.irrelevant_items == ()
    assert result.unsafe_instruction_items == ()

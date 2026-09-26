"""Prompt v4 evidence 인용 계약을 외부 API 없이 검증합니다."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from analysis.news_analyzer import NewsAnalyzer, NewsLLMOutput, TopicEvidence
from data_pipeline.news_fetcher import NewsItem
from evaluate_news_quality_v2 import parse_args
from evaluation.v2_runner import EvaluationV2ArtifactStore, EvaluationV2Runner


PROJECT_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_PATH = (
    PROJECT_ROOT
    / "evals"
    / "fixtures"
    / "news_prompt_v4_evidence_contract_cases.json"
)
RECORDED_PATH = (
    PROJECT_ROOT / "evals" / "fixtures" / "news_quality_v2_recorded_smoke.json"
)
DATASET_PATH = (
    PROJECT_ROOT
    / "evals"
    / "datasets"
    / "news"
    / "real"
    / "development"
    / "tsla_headlines_pilot_v2.json"
)
EXPECTED_PRINCIPLES = {
    "minimal_direct_evidence",
    "no_weak_citation_padding",
    "every_citation_supports_a_claim",
    "every_factual_claim_has_cited_support",
    "adjacent_keywords_are_insufficient",
    "distinct_events_remain_separate",
    "no_unsupported_details",
    "uncertainty_state_is_preserved",
    "narrow_or_omit_unsupported_topics",
}


def load_fixture() -> dict:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def make_item(index: int, title: str) -> NewsItem:
    return NewsItem(
        article_id=f"news_{index:016x}",
        title=title,
        published_at=datetime(2026, 9, 1, tzinfo=timezone.utc),
        url=f"https://news.example/prompt-v4-{index}",
        source="Prompt Contract Fixture",
    )


class CaptureResponses:
    def __init__(self, output: NewsLLMOutput) -> None:
        self.output = output
        self.calls: list[dict] = []

    async def parse(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(
            id="resp_prompt_v4_offline",
            model="gpt-offline-prompt-v4",
            output_parsed=self.output,
            output_text=json.dumps(
                self.output.model_dump(mode="json"),
                ensure_ascii=False,
            ),
            usage=None,
        )


class CaptureClient:
    def __init__(self, output: NewsLLMOutput) -> None:
        self.responses = CaptureResponses(output)


def test_prompt_v4_fixture_is_generalized_and_covers_the_contract():
    payload = load_fixture()

    assert payload["prompt_version"] == NewsAnalyzer.PROMPT_V4_VERSION
    assert payload["mode"] == "offline_prompt_contract"
    assert set(payload["principles"]) == EXPECTED_PRINCIPLES
    assert len(payload["cases"]) == 6
    assert all(
        case["ticker"] not in {"MSFT", "AAPL", "TSLA"}
        for case in payload["cases"]
    )
    assert all(case["headlines"] for case in payload["cases"])
    assert all(case["expected_contract"] for case in payload["cases"])


def test_prompt_v4_adds_only_the_explicit_evidence_contract_to_v3():
    v3 = NewsAnalyzer.PROMPT_V3_SYSTEM_INSTRUCTIONS
    v4 = NewsAnalyzer.PROMPT_V4_SYSTEM_INSTRUCTIONS
    contract = NewsAnalyzer.PROMPT_V4_EVIDENCE_CONTRACT

    assert v4 == f"{v3.rstrip()}\n\n{contract}\n"
    assert "If one headline is sufficient direct evidence" in contract
    assert "Never add weakly related IDs" in contract
    assert "Every supporting article ID must directly support" in contract
    assert "Every concrete factual claim" in contract
    assert "Sharing adjacent words" in contract
    assert "Do not merge distinct products" in contract
    assert "Do not add a person, number, cause, intention, or evaluation" in contract
    assert "Keep plans, forecasts, negotiations, and possibilities uncertain" in contract
    assert "write the narrower supported topic" in contract
    assert "MSFT" not in contract
    assert "AAPL" not in contract
    assert "TSLA" not in contract
    assert "case_id" not in contract


def test_v4_is_opt_in_and_production_default_remains_v3():
    default_analyzer = NewsAnalyzer(client=object())
    v4_analyzer = NewsAnalyzer(
        client=object(),
        prompt_version=NewsAnalyzer.PROMPT_V4_VERSION,
    )

    assert NewsAnalyzer.PROMPT_VERSION == NewsAnalyzer.PROMPT_V3_VERSION
    assert default_analyzer.prompt_version == NewsAnalyzer.PROMPT_V3_VERSION
    assert v4_analyzer.prompt_version == NewsAnalyzer.PROMPT_V4_VERSION
    assert NewsAnalyzer.SYSTEM_INSTRUCTIONS == (
        NewsAnalyzer.PROMPT_V3_SYSTEM_INSTRUCTIONS
    )
    with pytest.raises(ValueError, match="prompt_version must be one of"):
        NewsAnalyzer(client=object(), prompt_version="news-analyzer-prompt-v5")


def test_v4_request_uses_v4_system_prompt_without_external_api():
    item = make_item(1, "Alphabet signs a five-year cloud contract")
    output = NewsLLMOutput(
        sentiment="positive",
        score=0.2,
        confidence=70,
        summary="알파벳이 5년 클라우드 계약을 체결했습니다.",
        key_topics=(
            TopicEvidence(
                topic="클라우드 계약 체결",
                explanation="알파벳이 5년 클라우드 계약을 체결했습니다.",
                supporting_article_ids=(item.article_id,),
            ),
        ),
    )
    client = CaptureClient(output)
    analyzer = NewsAnalyzer(
        client=client,
        prompt_version=NewsAnalyzer.PROMPT_V4_VERSION,
    )

    parsed, rewrite_count = asyncio.run(
        analyzer._request_validated_output("offline prompt", (item,))
    )

    assert parsed == output
    assert rewrite_count == 0
    assert len(client.responses.calls) == 1
    system_prompt = client.responses.calls[0]["input"][0]["content"]
    assert system_prompt == NewsAnalyzer.PROMPT_V4_SYSTEM_INSTRUCTIONS
    assert NewsAnalyzer.PROMPT_V4_EVIDENCE_CONTRACT in system_prompt


def test_vehicle_delivery_rule_remains_context_specific_for_both_versions():
    ordinary = (make_item(1, "Alphabet signs a cloud contract"),)
    delivery = (make_item(2, "Ford vehicle deliveries rise 12%"),)

    for version in (
        NewsAnalyzer.PROMPT_V3_VERSION,
        NewsAnalyzer.PROMPT_V4_VERSION,
    ):
        ordinary_prompt = NewsAnalyzer._system_instructions(
            ordinary,
            prompt_version=version,
        )
        delivery_prompt = NewsAnalyzer._system_instructions(
            delivery,
            prompt_version=version,
        )

        assert "Context-specific translation rule:" not in ordinary_prompt
        assert "차량 인도량" not in ordinary_prompt
        assert "Context-specific translation rule:" in delivery_prompt
        assert "차량 인도/차량 인도량/차량 인도량 보고서" in delivery_prompt


def test_schema_still_accepts_one_supporting_article_id():
    topic = TopicEvidence(
        topic="직접 근거 하나",
        explanation="하나의 제목이 이 사실을 직접 뒷받침합니다.",
        supporting_article_ids=("news_0000000000000201",),
    )

    assert topic.supporting_article_ids == ("news_0000000000000201",)


def test_evaluation_cli_exposes_v4_as_explicit_non_default_option():
    default_args = parse_args(
        ["--recorded-responses", str(RECORDED_PATH)]
    )
    v4_args = parse_args(
        [
            "--recorded-responses",
            str(RECORDED_PATH),
            "--prompt-version",
            NewsAnalyzer.PROMPT_V4_VERSION,
        ]
    )

    assert default_args.prompt_version == NewsAnalyzer.PROMPT_V3_VERSION
    assert v4_args.prompt_version == NewsAnalyzer.PROMPT_V4_VERSION


def test_evaluation_runner_uses_and_records_explicit_v4(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    observed_versions: list[str | None] = []
    original = NewsAnalyzer._system_instructions.__func__

    def capture_prompt_version(
        cls,
        selected_items: tuple[NewsItem, ...],
        *,
        prompt_version: str | None = None,
    ) -> str:
        observed_versions.append(prompt_version)
        return original(
            cls,
            selected_items,
            prompt_version=prompt_version,
        )

    monkeypatch.setattr(
        NewsAnalyzer,
        "_system_instructions",
        classmethod(capture_prompt_version),
    )
    runner = EvaluationV2Runner(
        artifact_store=EvaluationV2ArtifactStore(tmp_path / "artifacts")
    )

    result = asyncio.run(
        runner.run(
            DATASET_PATH,
            mode="recorded",
            recorded_response_path=RECORDED_PATH,
            prompt_version=NewsAnalyzer.PROMPT_V4_VERSION,
        )
    )

    assert observed_versions == [NewsAnalyzer.PROMPT_V4_VERSION] * 5
    assert result.manifest.execution.prompt_version == (
        NewsAnalyzer.PROMPT_V4_VERSION
    )
    assert result.summary.prompt_version == NewsAnalyzer.PROMPT_V4_VERSION

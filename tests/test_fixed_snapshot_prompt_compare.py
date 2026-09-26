"""고정 Snapshot Prompt 비교 경로를 외부 호출 없이 검증합니다."""

from __future__ import annotations

import asyncio
import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from analysis.news_analyzer import NewsAnalyzer, NewsLLMOutput, TopicEvidence
from data_pipeline.news_fetcher import NewsFetchMetadata, NewsFetchResult, NewsItem
from evaluate_fixed_snapshot_prompt import parse_args
from evaluation.fixed_snapshot_prompt_compare import (
    DEFAULT_BASELINE_PATH,
    FixedSnapshotComparisonArtifactStore,
    FixedSnapshotPromptComparisonRunner,
    file_sha256,
    ordered_article_ids_sha256,
)
from workflow.analysis_window import AnalysisWindow


REAL_BASELINE_EXPECTATIONS = {
    "MSFT": {
        "snapshot_count": 267,
        "eligible_count": 233,
        "selected_count": 60,
        "ordered_ids_sha256": (
            "c1518a982c3372a09ca36221f205d4a24b21c2e41694e1e7292d23456b4588c8"
        ),
    },
    "AAPL": {
        "snapshot_count": 659,
        "eligible_count": 609,
        "selected_count": 60,
        "ordered_ids_sha256": (
            "09d427970dbf997e7e39192a60b7382585dad3469d1b2516a10f22cdc699942e"
        ),
    },
}


class SequenceResponses:
    def __init__(self, values: list[SimpleNamespace]) -> None:
        self.values = list(values)
        self.calls: list[dict] = []

    async def parse(self, **kwargs):
        self.calls.append(kwargs)
        if not self.values:
            raise AssertionError("unexpected additional model call")
        return self.values.pop(0)


class SequenceClient:
    def __init__(self, values: list[SimpleNamespace]) -> None:
        self.responses = SequenceResponses(values)


class GuardResponses:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def parse(self, **kwargs):
        self.calls.append(kwargs)
        raise AssertionError("model must not be called when preflight fails")


class GuardClient:
    def __init__(self) -> None:
        self.responses = GuardResponses()


def valid_output(article_id: str) -> NewsLLMOutput:
    return NewsLLMOutput(
        sentiment="neutral",
        score=0.0,
        confidence=50,
        summary="선택된 제목에 회사 관련 소식이 포함되어 있습니다.",
        key_topics=(
            TopicEvidence(
                topic="회사 관련 소식",
                explanation="선택된 제목에서 회사 관련 소식이 언급됐습니다.",
                supporting_article_ids=(article_id,),
            ),
        ),
    )


def unknown_evidence_output() -> NewsLLMOutput:
    return valid_output("news_ffffffffffffffff")


def response(output: NewsLLMOutput, index: int) -> SimpleNamespace:
    return SimpleNamespace(
        id=f"resp_fixed_snapshot_{index}",
        model="gpt-offline-fixed-snapshot",
        output_parsed=output,
        output_text=json.dumps(output.model_dump(mode="json"), ensure_ascii=False),
        usage=SimpleNamespace(
            input_tokens=100,
            output_tokens=30,
            total_tokens=130,
        ),
    )


def make_local_fixture(tmp_path: Path) -> tuple[Path, Path, tuple[str, ...]]:
    snapshot_dir = tmp_path / "reports" / "generated" / "news_snapshots"
    snapshot_dir.mkdir(parents=True)
    window = AnalysisWindow(
        ticker="TEST",
        requested_analysis_days=30,
        start_date=date(2026, 8, 20),
        end_date=date(2026, 9, 18),
    )
    base_time = datetime(2026, 9, 1, 12, tzinfo=timezone.utc)
    items = tuple(
        NewsItem(
            article_id=f"news_{index:016x}",
            title=f"TEST company update number {index}",
            published_at=base_time + timedelta(minutes=index),
            url=f"https://news.example/fixed/{index}",
            source="Offline Fixture",
        )
        for index in range(1, 61)
    )
    news = NewsFetchResult(
        ticker="TEST",
        window=window,
        status="available",
        available=True,
        items=items,
        metadata=NewsFetchMetadata(
            query="TEST stock",
            fetched_at=datetime(2026, 9, 19, tzinfo=timezone.utc),
            request_count=0,
            raw_item_count=60,
            invalid_item_count=0,
            outside_window_count=0,
            in_window_item_count=60,
            duplicate_item_count=0,
            truncated_item_count=0,
            stored_item_count=60,
            feed_oldest_published_at=items[0].published_at,
            feed_newest_published_at=items[-1].published_at,
        ),
    )
    snapshot_path = snapshot_dir / "news_TEST_fixed.json"
    snapshot_path.write_text(
        json.dumps(news.model_dump(mode="json"), ensure_ascii=False, indent=2)
        + "\n",
        encoding="utf-8",
    )
    ordered_ids = tuple(item.article_id for item in items)
    baseline = {
        "schema": "offline_selection_reconstruction_v1",
        "git_sha": "58f6120e57e741e8b73d04985660e485a1823bf3",
        "production_artifact": False,
        "notice": "Offline reconstructed test selection.",
        "ordered_ids_hash": {
            "algorithm": "sha256",
            "canonicalization": (
                "UTF-8 JSON array with ensure_ascii=false and separators=(',', ':')"
            ),
        },
        "runs": [
            {
                "run_id": "run_fixed_TEST",
                "ticker": "TEST",
                "snapshot_path": (
                    "reports/generated/news_snapshots/news_TEST_fixed.json"
                ),
                "snapshot_sha256": file_sha256(snapshot_path),
                "snapshot_count": 60,
                "eligible_count": 60,
                "low_information_page_count": 0,
                "selected_count": 60,
                "selection_strategy": "all",
                "selection_reason_counts": {"all": 60},
                "ordered_ids_sha256": ordered_article_ids_sha256(ordered_ids),
                "ordered_ids": list(ordered_ids),
            }
        ],
    }
    baseline_path = tmp_path / "reports" / "generated" / "baseline.json"
    baseline_path.write_text(
        json.dumps(baseline, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return baseline_path, snapshot_dir, ordered_ids


def make_runner(
    tmp_path: Path,
    baseline_path: Path,
    snapshot_dir: Path,
) -> FixedSnapshotPromptComparisonRunner:
    return FixedSnapshotPromptComparisonRunner(
        baseline_path=baseline_path,
        project_root=tmp_path,
        snapshot_root=snapshot_dir,
        artifact_store=FixedSnapshotComparisonArtifactStore(
            tmp_path / "reports" / "generated" / "evals"
        ),
    )


@pytest.mark.skipif(
    not DEFAULT_BASELINE_PATH.is_file(),
    reason="local git-ignored MSFT/AAPL Snapshot baseline is unavailable",
)
@pytest.mark.parametrize("ticker", ("MSFT", "AAPL"))
def test_local_msft_aapl_baseline_reconstructs_exactly(ticker: str):
    prepared = FixedSnapshotPromptComparisonRunner().prepare_input(ticker)
    expected = REAL_BASELINE_EXPECTATIONS[ticker]

    assert prepared.source.snapshot_count == expected["snapshot_count"]
    assert prepared.source.eligible_count == expected["eligible_count"]
    assert len(prepared.selected_items) == expected["selected_count"]
    assert prepared.source.ordered_ids_sha256 == expected["ordered_ids_sha256"]
    assert tuple(item.article_id for item in prepared.selected_items) == (
        prepared.source.ordered_ids
    )
    assert prepared.replay_selection_strategy == "all"


def test_snapshot_hash_mismatch_stops_before_model_call(tmp_path: Path):
    baseline_path, snapshot_dir, _ordered_ids = make_local_fixture(tmp_path)
    payload = json.loads(baseline_path.read_text(encoding="utf-8"))
    payload["runs"][0]["snapshot_sha256"] = "A" * 64
    baseline_path.write_text(json.dumps(payload), encoding="utf-8")
    runner = make_runner(tmp_path, baseline_path, snapshot_dir)
    client = GuardClient()

    with pytest.raises(ValueError, match="Snapshot SHA-256 mismatch"):
        asyncio.run(
            runner.run(
                ticker="TEST",
                prompt_version=NewsAnalyzer.PROMPT_V3_VERSION,
                client=client,
            )
        )

    assert client.responses.calls == []


def test_selected_id_order_mismatch_stops_before_model_call(tmp_path: Path):
    baseline_path, snapshot_dir, ordered_ids = make_local_fixture(tmp_path)
    payload = json.loads(baseline_path.read_text(encoding="utf-8"))
    swapped = list(ordered_ids)
    swapped[0], swapped[1] = swapped[1], swapped[0]
    payload["runs"][0]["ordered_ids"] = swapped
    payload["runs"][0]["ordered_ids_sha256"] = ordered_article_ids_sha256(
        tuple(swapped)
    )
    baseline_path.write_text(json.dumps(payload), encoding="utf-8")
    runner = make_runner(tmp_path, baseline_path, snapshot_dir)
    client = GuardClient()

    with pytest.raises(ValueError, match="IDs or their order"):
        asyncio.run(
            runner.run(
                ticker="TEST",
                prompt_version=NewsAnalyzer.PROMPT_V4_VERSION,
                client=client,
            )
        )

    assert client.responses.calls == []


def test_selected_article_count_mismatch_stops_before_model_call(tmp_path: Path):
    baseline_path, snapshot_dir, ordered_ids = make_local_fixture(tmp_path)
    payload = json.loads(baseline_path.read_text(encoding="utf-8"))
    shortened = ordered_ids[:-1]
    payload["runs"][0]["selected_count"] = len(shortened)
    payload["runs"][0]["selection_reason_counts"] = {"all": len(shortened)}
    payload["runs"][0]["ordered_ids"] = list(shortened)
    payload["runs"][0]["ordered_ids_sha256"] = ordered_article_ids_sha256(
        shortened
    )
    baseline_path.write_text(json.dumps(payload), encoding="utf-8")
    runner = make_runner(tmp_path, baseline_path, snapshot_dir)
    client = GuardClient()

    with pytest.raises(ValueError, match="requires exactly 60"):
        asyncio.run(
            runner.run(
                ticker="TEST",
                prompt_version=NewsAnalyzer.PROMPT_V3_VERSION,
                client=client,
            )
        )

    assert client.responses.calls == []


def test_v3_v4_use_identical_fixed_input_and_distinct_run_artifacts(
    tmp_path: Path,
):
    baseline_path, snapshot_dir, ordered_ids = make_local_fixture(tmp_path)
    runner = make_runner(tmp_path, baseline_path, snapshot_dir)
    output = valid_output(ordered_ids[0])
    v3_client = SequenceClient([response(output, 1)])
    v4_client = SequenceClient([response(output, 2)])

    v3 = asyncio.run(
        runner.run(
            ticker="TEST",
            prompt_version=NewsAnalyzer.PROMPT_V3_VERSION,
            model_id="gpt-offline-compare",
            client=v3_client,
        )
    )
    v4 = asyncio.run(
        runner.run(
            ticker="TEST",
            prompt_version=NewsAnalyzer.PROMPT_V4_VERSION,
            model_id="gpt-offline-compare",
            client=v4_client,
        )
    )

    assert v3.manifest.comparison_run_id != v4.manifest.comparison_run_id
    assert v3.manifest.prompt_version == NewsAnalyzer.PROMPT_V3_VERSION
    assert v4.manifest.prompt_version == NewsAnalyzer.PROMPT_V4_VERSION
    assert v3.manifest.selected_article_ids == ordered_ids
    assert v4.manifest.selected_article_ids == ordered_ids
    assert v3.manifest.selected_ids_sha256 == v4.manifest.selected_ids_sha256
    assert v3.final_output.analysis.selected_article_ids == ordered_ids
    assert v4.final_output.analysis.selected_article_ids == ordered_ids
    assert v3_client.responses.calls[0]["input"][1]["content"] == (
        v4_client.responses.calls[0]["input"][1]["content"]
    )
    assert (
        v3_client.responses.calls[0]["input"][0]["content"]
        == NewsAnalyzer.PROMPT_V3_SYSTEM_INSTRUCTIONS
    )
    assert (
        v4_client.responses.calls[0]["input"][0]["content"]
        == NewsAnalyzer.PROMPT_V4_SYSTEM_INSTRUCTIONS
    )
    assert v3.artifact_paths["manifest"].parent != (
        v4.artifact_paths["manifest"].parent
    )
    assert all(path.is_file() for path in v3.artifact_paths.values())
    assert all(path.is_file() for path in v4.artifact_paths.values())

    manifest = json.loads(
        v4.artifact_paths["manifest"].read_text(encoding="utf-8")
    )
    attempts = json.loads(
        v4.artifact_paths["attempt_telemetry"].read_text(encoding="utf-8")
    )
    assert manifest["contains_api_key"] is False
    assert manifest["semantic_accuracy_evaluated"] is False
    assert attempts["contains_full_model_outputs"] is True
    assert attempts["cases"][0]["attempts"][0]["token_usage"] == {
        "input_tokens": 100,
        "output_tokens": 30,
        "total_tokens": 130,
    }


def test_comparison_path_preserves_rewrite_and_final_fallback_contract(
    tmp_path: Path,
):
    baseline_path, snapshot_dir, ordered_ids = make_local_fixture(tmp_path)
    runner = make_runner(tmp_path, baseline_path, snapshot_dir)
    rejected = unknown_evidence_output()
    accepted = valid_output(ordered_ids[0])
    rescued_client = SequenceClient(
        [response(rejected, 1), response(accepted, 2)]
    )

    rescued = asyncio.run(
        runner.run(
            ticker="TEST",
            prompt_version=NewsAnalyzer.PROMPT_V4_VERSION,
            client=rescued_client,
        )
    )

    assert rescued.final_output.analysis.available is True
    assert rescued.final_output.analysis.fallback_used is False
    assert [
        attempt.outcome
        for attempt in rescued.attempt_telemetry.cases[0].attempts
    ] == ["validator_failed", "validator_passed"]

    failed_client = SequenceClient(
        [response(rejected, 3), response(rejected, 4), response(rejected, 5)]
    )
    failed = asyncio.run(
        runner.run(
            ticker="TEST",
            prompt_version=NewsAnalyzer.PROMPT_V4_VERSION,
            client=failed_client,
        )
    )

    assert len(failed_client.responses.calls) == 3
    assert failed.final_output.analysis.available is False
    assert failed.final_output.analysis.fallback_used is True
    assert failed.final_output.analysis.error_code == "validation_error"
    assert all(
        attempt.validator_error_code == "evidence_id_validation_error"
        for attempt in failed.attempt_telemetry.cases[0].attempts
    )


def test_cli_defaults_to_validation_and_requires_explicit_live_authorization():
    args = parse_args(
        [
            "--ticker",
            "MSFT",
            "--prompt-version",
            NewsAnalyzer.PROMPT_V3_VERSION,
        ]
    )

    assert args.mode == "validate-only"
    assert args.allow_live is False
    with pytest.raises(SystemExit):
        parse_args(
            [
                "--ticker",
                "MSFT",
                "--prompt-version",
                NewsAnalyzer.PROMPT_V3_VERSION,
                "--mode",
                "live",
            ]
        )


def test_runner_without_client_or_live_authorization_never_calls_openai(
    tmp_path: Path,
):
    baseline_path, snapshot_dir, _ordered_ids = make_local_fixture(tmp_path)
    runner = make_runner(tmp_path, baseline_path, snapshot_dir)

    with pytest.raises(RuntimeError, match="live execution is disabled"):
        asyncio.run(
            runner.run(
                ticker="TEST",
                prompt_version=NewsAnalyzer.PROMPT_V3_VERSION,
            )
        )

"""저장 Snapshot의 고정 선택 입력으로 Prompt 버전을 비교합니다."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import uuid
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from analysis.headline_policy import HeadlinePolicy
from analysis.news_analyzer import NewsAnalysis, NewsAnalyzer
from data_pipeline.news_fetcher import NewsFetchResult, NewsItem
from evaluation.attempt_telemetry import (
    AttemptTelemetryArtifact,
    AttemptTelemetryArtifactStore,
    AttemptTelemetryCollector,
    build_attempt_telemetry_artifact,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BASELINE_PATH = (
    PROJECT_ROOT
    / "reports"
    / "generated"
    / "prompt_v4_selection_reconstruction_baseline.json"
)
DEFAULT_ARTIFACT_ROOT = (
    PROJECT_ROOT / "reports" / "generated" / "evals" / "fixed_snapshot_prompt"
)
DEFAULT_SNAPSHOT_ROOT = PROJECT_ROOT / "reports" / "generated" / "news_snapshots"

ExecutionMode = Literal["offline_mock", "live_model"]


def ordered_article_ids_sha256(article_ids: tuple[str, ...]) -> str:
    """순서가 보존된 compact JSON ID 배열의 SHA-256을 반환합니다."""
    payload = json.dumps(
        article_ids,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


class FixedSnapshotBaselineRun(BaseModel):
    """한 Production Run에서 Offline 재구성한 선택 기준선입니다."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    run_id: str = Field(min_length=1)
    ticker: str = Field(pattern=r"^[A-Z][A-Z0-9.-]{0,9}$")
    snapshot_path: str = Field(min_length=1)
    snapshot_sha256: str = Field(pattern=r"^[A-F0-9]{64}$")
    snapshot_count: int = Field(ge=1)
    eligible_count: int = Field(ge=1)
    low_information_page_count: int = Field(ge=0)
    selected_count: int = Field(ge=1)
    selection_strategy: str = Field(min_length=1)
    selection_reason_counts: dict[str, int]
    ordered_ids_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    ordered_ids: tuple[str, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_ordered_ids(self) -> "FixedSnapshotBaselineRun":
        if len(self.ordered_ids) != self.selected_count:
            raise ValueError("selected_count must match ordered_ids length")
        if len(set(self.ordered_ids)) != len(self.ordered_ids):
            raise ValueError("ordered_ids must be unique")
        if ordered_article_ids_sha256(self.ordered_ids) != self.ordered_ids_sha256:
            raise ValueError("ordered_ids_sha256 does not match ordered_ids")
        if sum(self.selection_reason_counts.values()) != self.selected_count:
            raise ValueError(
                "selection_reason_counts must sum to selected_count"
            )
        return self


class FixedSnapshotBaseline(BaseModel):
    """Git에서 제외된 로컬 Snapshot 재구성 기준선 파일입니다."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_name: Literal["offline_selection_reconstruction_v1"] = Field(
        alias="schema"
    )
    git_sha: str = Field(pattern=r"^[a-f0-9]{40}$")
    production_artifact: Literal[False]
    notice: str = Field(min_length=1)
    ordered_ids_hash: dict[str, str]
    runs: tuple[FixedSnapshotBaselineRun, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_unique_runs(self) -> "FixedSnapshotBaseline":
        tickers = tuple(run.ticker for run in self.runs)
        run_ids = tuple(run.run_id for run in self.runs)
        if len(tickers) != len(set(tickers)):
            raise ValueError("baseline ticker values must be unique")
        if len(run_ids) != len(set(run_ids)):
            raise ValueError("baseline run_id values must be unique")
        if self.ordered_ids_hash.get("algorithm") != "sha256":
            raise ValueError("baseline ordered ID hash algorithm must be sha256")
        return self


class FixedSnapshotComparisonManifest(BaseModel):
    """한 ticker·Prompt 조합의 입력과 실행 조건을 추적합니다."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["1.0"] = "1.0"
    comparison_run_id: str = Field(
        pattern=(
            r"^snapcmp_[0-9]{8}T[0-9]{6}Z_[A-Z0-9.-]+_v[34]_[a-f0-9]{8}$"
        )
    )
    generated_at: datetime
    execution_mode: ExecutionMode
    baseline_git_sha: str = Field(pattern=r"^[a-f0-9]{40}$")
    source_live_run_id: str = Field(min_length=1)
    ticker: str
    snapshot_path: str
    snapshot_sha256: str = Field(pattern=r"^[A-F0-9]{64}$")
    source_snapshot_article_count: int = Field(ge=1)
    source_eligible_article_count: int = Field(ge=1)
    source_selection_strategy: str
    replay_selection_strategy: str
    selected_article_count: int = Field(ge=1)
    selected_article_ids: tuple[str, ...] = Field(min_length=1)
    selected_ids_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    selected_ids_hash_canonicalization: str
    requested_model_id: str
    prompt_version: str
    system_prompt_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    validator_version: str
    maximum_attempts: int = Field(ge=1)
    input_provenance: Literal["offline_reconstructed_from_saved_snapshot"] = (
        "offline_reconstructed_from_saved_snapshot"
    )
    semantic_accuracy_evaluated: Literal[False] = False
    contains_api_key: Literal[False] = False

    @model_validator(mode="after")
    def validate_selected_input(self) -> "FixedSnapshotComparisonManifest":
        if len(self.selected_article_ids) != self.selected_article_count:
            raise ValueError(
                "selected_article_count must match selected_article_ids"
            )
        if (
            ordered_article_ids_sha256(self.selected_article_ids)
            != self.selected_ids_sha256
        ):
            raise ValueError(
                "selected_ids_sha256 must match selected_article_ids"
            )
        return self


class FixedSnapshotFinalOutput(BaseModel):
    """비교 Run의 최종 Structured Output과 availability 상태입니다."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["1.0"] = "1.0"
    comparison_run_id: str
    generated_at: datetime
    analysis: NewsAnalysis


@dataclass(frozen=True)
class PreparedFixedSnapshotInput:
    baseline: FixedSnapshotBaseline
    source: FixedSnapshotBaselineRun
    snapshot_path: Path
    selected_items: tuple[NewsItem, ...]
    replay_news: NewsFetchResult
    replay_selection_strategy: str


@dataclass(frozen=True)
class FixedSnapshotComparisonResult:
    manifest: FixedSnapshotComparisonManifest
    final_output: FixedSnapshotFinalOutput
    attempt_telemetry: AttemptTelemetryArtifact
    artifact_paths: dict[str, Path]


class FixedSnapshotComparisonArtifactStore:
    """전체 모델 출력이 포함된 비교 artifact를 Git 제외 경로에 저장합니다."""

    def __init__(self, root_dir: str | Path = DEFAULT_ARTIFACT_ROOT) -> None:
        self.root_dir = Path(root_dir).resolve()

    def paths(self, run_id: str) -> dict[str, Path]:
        run_dir = self.root_dir / run_id
        return {
            "manifest": run_dir / "manifest.json",
            "final_output": run_dir / "final_output.json",
            "attempt_telemetry": run_dir / "attempt_telemetry.json",
        }

    def save(
        self,
        manifest: FixedSnapshotComparisonManifest,
        final_output: FixedSnapshotFinalOutput,
        attempt_telemetry: AttemptTelemetryArtifact,
    ) -> dict[str, Path]:
        paths = self.paths(manifest.comparison_run_id)
        if any(path.exists() for path in paths.values()):
            raise FileExistsError(
                f"comparison artifact already exists: {manifest.comparison_run_id}"
            )
        self._save_json(manifest, paths["manifest"])
        self._save_json(final_output, paths["final_output"])
        AttemptTelemetryArtifactStore(paths["attempt_telemetry"].parent).save(
            attempt_telemetry,
            output_path=paths["attempt_telemetry"],
        )
        return paths

    @staticmethod
    def _save_json(model: BaseModel, target: Path) -> None:
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                newline="\n",
                prefix=f".{target.name}.",
                suffix=".tmp",
                dir=target.parent,
                delete=False,
            ) as temporary_file:
                temporary_path = Path(temporary_file.name)
                temporary_file.write(
                    json.dumps(
                        model.model_dump(mode="json"),
                        ensure_ascii=False,
                        indent=2,
                    )
                )
                temporary_file.write("\n")
                temporary_file.flush()
                os.fsync(temporary_file.fileno())
            os.replace(temporary_path, target)
            temporary_path = None
        finally:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)


class FixedSnapshotPromptComparisonRunner:
    """고정 입력 검증 후에만 한 ticker·Prompt 조합을 분석합니다."""

    def __init__(
        self,
        *,
        baseline_path: str | Path = DEFAULT_BASELINE_PATH,
        project_root: str | Path = PROJECT_ROOT,
        snapshot_root: str | Path | None = None,
        artifact_store: FixedSnapshotComparisonArtifactStore | None = None,
    ) -> None:
        self.baseline_path = Path(baseline_path).resolve()
        self.project_root = Path(project_root).resolve()
        self.snapshot_root = (
            Path(snapshot_root).resolve()
            if snapshot_root is not None
            else self.project_root
            / "reports"
            / "generated"
            / "news_snapshots"
        )
        self.artifact_store = (
            artifact_store or FixedSnapshotComparisonArtifactStore()
        )

    def prepare_input(self, ticker: str) -> PreparedFixedSnapshotInput:
        """외부 client 생성 전에 Snapshot과 결정론적 선택을 검증합니다."""
        baseline = FixedSnapshotBaseline.model_validate_json(
            self.baseline_path.read_text(encoding="utf-8")
        )
        normalized_ticker = ticker.strip().upper()
        matching = tuple(
            run for run in baseline.runs if run.ticker == normalized_ticker
        )
        if len(matching) != 1:
            raise ValueError(
                f"baseline must contain exactly one run for {normalized_ticker}"
            )
        source = matching[0]
        if source.selected_count != NewsAnalyzer.DEFAULT_MAX_SELECTED_ARTICLES:
            raise ValueError(
                "fixed Snapshot comparison requires exactly "
                f"{NewsAnalyzer.DEFAULT_MAX_SELECTED_ARTICLES} selected articles"
            )
        relative_snapshot = Path(source.snapshot_path)
        if relative_snapshot.is_absolute():
            raise ValueError("baseline snapshot_path must be relative")
        snapshot_path = (self.project_root / relative_snapshot).resolve()
        if not snapshot_path.is_relative_to(self.snapshot_root):
            raise ValueError("baseline snapshot_path is outside snapshot root")
        if not snapshot_path.is_file():
            raise FileNotFoundError(f"saved Snapshot not found: {snapshot_path}")

        actual_snapshot_hash = file_sha256(snapshot_path)
        if actual_snapshot_hash != source.snapshot_sha256:
            raise ValueError(
                "Snapshot SHA-256 mismatch before model execution: "
                f"expected {source.snapshot_sha256}, got {actual_snapshot_hash}"
            )
        snapshot = NewsFetchResult.model_validate_json(
            snapshot_path.read_text(encoding="utf-8")
        )
        if snapshot.ticker != source.ticker:
            raise ValueError("Snapshot ticker does not match baseline ticker")
        if len(snapshot.items) != source.snapshot_count:
            raise ValueError("Snapshot article count does not match baseline")

        selector = NewsAnalyzer(client=object())
        filtered = selector.headline_policy.filter_for_ticker(
            snapshot.items,
            ticker=source.ticker,
        )
        if len(filtered.eligible_items) != source.eligible_count:
            raise ValueError("eligible article count does not match baseline")
        if (
            len(filtered.low_information_page_items)
            != source.low_information_page_count
        ):
            raise ValueError(
                "low-information article count does not match baseline"
            )
        selected, selection_metadata, strategy = (
            selector.select_articles_with_metadata(
                filtered.eligible_items,
                window=snapshot.window,
            )
        )
        selected_ids = tuple(item.article_id for item in selected)
        reason_counts = dict(
            Counter(item.selection_reason for item in selection_metadata)
        )
        if strategy != source.selection_strategy:
            raise ValueError("selection strategy does not match baseline")
        if reason_counts != source.selection_reason_counts:
            raise ValueError("selection reason counts do not match baseline")
        if selected_ids != source.ordered_ids:
            raise ValueError(
                "selected article IDs or their order do not match baseline"
            )
        selected_hash = ordered_article_ids_sha256(selected_ids)
        if selected_hash != source.ordered_ids_sha256:
            raise ValueError("selected article order SHA-256 does not match baseline")

        replay_metadata = snapshot.metadata.model_copy(
            update={
                "stored_item_count": len(selected),
                "warnings": (
                    *snapshot.metadata.warnings,
                    "Offline reconstructed fixed selection; not a Production-stored selection list.",
                ),
            }
        )
        replay_news = NewsFetchResult(
            ticker=snapshot.ticker,
            window=snapshot.window,
            status=snapshot.status,
            available=snapshot.available,
            items=selected,
            metadata=replay_metadata,
        )
        replay_filtered = selector.headline_policy.filter_for_ticker(
            replay_news.items,
            ticker=replay_news.ticker,
        )
        replay_selected, _replay_metadata, replay_strategy = (
            selector.select_articles_with_metadata(
                replay_filtered.eligible_items,
                window=replay_news.window,
            )
        )
        replay_ids = tuple(item.article_id for item in replay_selected)
        if replay_ids != source.ordered_ids:
            raise ValueError(
                "NewsAnalyzer replay filtering changed selected IDs or order"
            )
        if ordered_article_ids_sha256(replay_ids) != source.ordered_ids_sha256:
            raise ValueError("NewsAnalyzer replay input hash changed")

        return PreparedFixedSnapshotInput(
            baseline=baseline,
            source=source,
            snapshot_path=snapshot_path,
            selected_items=selected,
            replay_news=replay_news,
            replay_selection_strategy=replay_strategy,
        )

    async def run(
        self,
        *,
        ticker: str,
        prompt_version: str,
        model_id: str = NewsAnalyzer.DEFAULT_MODEL,
        client: Any | None = None,
        api_key: str | None = None,
        allow_live: bool = False,
    ) -> FixedSnapshotComparisonResult:
        """검증된 한 고정 입력을 Mock 또는 명시적 Live client로 분석합니다."""
        prepared = self.prepare_input(ticker)
        if prompt_version not in NewsAnalyzer.SUPPORTED_PROMPT_VERSIONS:
            raise ValueError(f"unsupported prompt_version: {prompt_version}")
        normalized_model = model_id.strip()
        if not normalized_model:
            raise ValueError("model_id must not be empty")

        if client is not None:
            if allow_live or api_key:
                raise ValueError(
                    "offline client cannot be combined with live authorization"
                )
            execution_mode: ExecutionMode = "offline_mock"
            analyzer = NewsAnalyzer(
                client=client,
                model=normalized_model,
                prompt_version=prompt_version,
                attempt_telemetry_sink=(collector := AttemptTelemetryCollector(
                    enabled=True
                )),
            )
        else:
            if not allow_live:
                raise RuntimeError(
                    "live execution is disabled; provide an offline client or "
                    "set allow_live=True explicitly"
                )
            resolved_key = (api_key or os.getenv("OPENAI_API_KEY", "")).strip()
            if not resolved_key:
                raise RuntimeError("live execution requires OPENAI_API_KEY")
            execution_mode = "live_model"
            collector = AttemptTelemetryCollector(enabled=True)
            analyzer = NewsAnalyzer(
                api_key=resolved_key,
                model=normalized_model,
                prompt_version=prompt_version,
                attempt_telemetry_sink=collector,
            )

        prompt_label = prompt_version.rsplit("-", maxsplit=1)[-1]
        now = datetime.now(timezone.utc)
        run_id = (
            f"snapcmp_{now.strftime('%Y%m%dT%H%M%SZ')}_"
            f"{prepared.source.ticker}_{prompt_label}_{uuid.uuid4().hex[:8]}"
        )
        analysis = await analyzer.analyze(prepared.replay_news)
        if analysis.selected_article_ids != prepared.source.ordered_ids:
            raise RuntimeError(
                "NewsAnalyzer execution changed fixed selected IDs or order"
            )

        generated_at = datetime.now(timezone.utc)
        system_prompt = NewsAnalyzer._system_instructions(
            prepared.selected_items,
            prompt_version=prompt_version,
        )
        manifest = FixedSnapshotComparisonManifest(
            comparison_run_id=run_id,
            generated_at=generated_at,
            execution_mode=execution_mode,
            baseline_git_sha=prepared.baseline.git_sha,
            source_live_run_id=prepared.source.run_id,
            ticker=prepared.source.ticker,
            snapshot_path=prepared.source.snapshot_path,
            snapshot_sha256=prepared.source.snapshot_sha256,
            source_snapshot_article_count=prepared.source.snapshot_count,
            source_eligible_article_count=prepared.source.eligible_count,
            source_selection_strategy=prepared.source.selection_strategy,
            replay_selection_strategy=prepared.replay_selection_strategy,
            selected_article_count=len(prepared.source.ordered_ids),
            selected_article_ids=prepared.source.ordered_ids,
            selected_ids_sha256=prepared.source.ordered_ids_sha256,
            selected_ids_hash_canonicalization=(
                "UTF-8 JSON array with ensure_ascii=false and "
                "separators=(',', ':')"
            ),
            requested_model_id=normalized_model,
            prompt_version=prompt_version,
            system_prompt_sha256=hashlib.sha256(
                system_prompt.encode("utf-8")
            ).hexdigest(),
            validator_version=HeadlinePolicy.VALIDATOR_VERSION,
            maximum_attempts=NewsAnalyzer.MAX_VALIDATION_ATTEMPTS,
        )
        final_output = FixedSnapshotFinalOutput(
            comparison_run_id=run_id,
            generated_at=generated_at,
            analysis=analysis,
        )
        trace = collector.build_case_trace(
            case_id=f"{prepared.source.ticker.lower()}_{prompt_label}",
            analysis=analysis,
        )
        attempt_telemetry = build_attempt_telemetry_artifact(
            eval_run_id=run_id,
            cases=(trace,),
            generated_at=generated_at,
        )
        artifact_paths = self.artifact_store.save(
            manifest,
            final_output,
            attempt_telemetry,
        )
        return FixedSnapshotComparisonResult(
            manifest=manifest,
            final_output=final_output,
            attempt_telemetry=attempt_telemetry,
            artifact_paths=artifact_paths,
        )

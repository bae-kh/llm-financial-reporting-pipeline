"""Dataset v2 -> NewsAnalyzer -> telemetry -> grader evaluation runner.

The default execution path consumes recorded responses and never creates an
OpenAI client.  Full prompts and model drafts are written only to the ignored
evaluation artifact directory, not to production logs or run metadata.
"""

from __future__ import annotations

import html
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from analysis.headline_policy import HeadlinePolicy
from analysis.news_analyzer import NewsAnalysis, NewsAnalyzer
from data_pipeline.news_fetcher import NewsFetchMetadata, NewsFetchResult, NewsItem
from evaluation.attempt_telemetry import (
    AttemptTelemetryArtifact,
    AttemptTelemetryArtifactStore,
    AttemptTelemetryCollector,
    EvaluationCaseAttemptTrace,
    ValidatorReliabilityMetrics,
    build_attempt_telemetry_artifact,
    compute_validator_reliability_metrics,
)
from evaluation.dataset_v2 import (
    DatasetValidationSummary,
    EvaluationCaseV2,
    EvaluationDatasetValidator,
    EvaluationRunManifest,
    ManifestExecutionConfig,
    build_execution_manifest,
    save_execution_manifest,
    verify_manifest_dataset,
)
from evaluation.v2_grader import (
    AutomaticGradingSummary,
    CaseGradeResult,
    NewsQualityV2Grader,
    summarize_automatic_grades,
)
from workflow.analysis_window import AnalysisWindow


RUNNER_NAME = "news-quality-evaluation-v2"
RUNNER_VERSION = "0.1.0"
DEFAULT_PROMPT_VERSION = NewsAnalyzer.PROMPT_VERSION
DEFAULT_VALIDATOR_VERSION = HeadlinePolicy.VALIDATOR_VERSION
DEFAULT_ARTIFACT_ROOT = Path("reports") / "generated" / "evals" / "v2"

RunMode = Literal["recorded", "live"]
RunStatus = Literal["running", "complete", "incomplete"]


class RecordedTokenUsage(BaseModel):
    """Token values present in a recorded provider response; never estimated."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    total_tokens: int | None = Field(default=None, ge=0)


class RecordedAttempt(BaseModel):
    """One deterministic response or exception returned by the offline client."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: Literal["output", "api_error"] = "output"
    output: dict[str, Any] | None = None
    response_model_id: str | None = None
    response_id: str | None = None
    raw_output_text: str | None = None
    token_usage: RecordedTokenUsage | None = None
    error_message: str | None = None

    @model_validator(mode="after")
    def validate_kind(self) -> "RecordedAttempt":
        if self.kind == "api_error":
            if not self.error_message:
                raise ValueError("recorded api_error requires error_message")
            if any(
                value is not None
                for value in (
                    self.output,
                    self.response_model_id,
                    self.response_id,
                    self.raw_output_text,
                    self.token_usage,
                )
            ):
                raise ValueError("recorded api_error cannot contain response fields")
        elif self.error_message is not None:
            raise ValueError("recorded output cannot contain error_message")
        return self


class RecordedCaseResponses(BaseModel):
    """A case-local response sequence, isolated from every other case."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    case_id: str = Field(min_length=1)
    attempts: tuple[RecordedAttempt, ...] = Field(min_length=1, max_length=3)


class RecordedResponsePlan(BaseModel):
    """Offline response fixture bound to one exact Dataset v2 identity."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["1.0"] = "1.0"
    dataset_id: str = Field(min_length=1)
    dataset_version: str = Field(min_length=1)
    dataset_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    model_id: str = Field(min_length=1)
    cases: tuple[RecordedCaseResponses, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_unique_cases(self) -> "RecordedResponsePlan":
        case_ids = tuple(case.case_id for case in self.cases)
        if len(case_ids) != len(set(case_ids)):
            raise ValueError("recorded response case IDs must be unique")
        return self


class CaseFinalOutput(BaseModel):
    """One case's immutable final production NewsAnalysis output."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    case_id: str
    analysis: NewsAnalysis


class CaseOutputsArtifact(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["1.0"] = "1.0"
    eval_run_id: str
    generated_at: datetime
    dataset_id: str
    dataset_version: str
    dataset_hash: str
    cases: tuple[CaseFinalOutput, ...]


class GradingResultsArtifact(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["1.0"] = "1.0"
    eval_run_id: str
    generated_at: datetime
    dataset_id: str
    dataset_version: str
    dataset_hash: str
    cases: tuple[CaseGradeResult, ...]
    automatic_summary: AutomaticGradingSummary
    semantic_accuracy_evaluated: Literal[False] = False


class ValidatorReliabilityArtifact(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["1.0"] = "1.0"
    eval_run_id: str
    generated_at: datetime
    metrics: ValidatorReliabilityMetrics
    semantic_accuracy_evaluated: Literal[False] = False


class EfficiencySummary(BaseModel):
    """Observed latency and provider-reported token coverage."""

    model_config = ConfigDict(frozen=True, extra="forbid", allow_inf_nan=False)

    attempt_count: int = Field(ge=0)
    latency_ms_total: float = Field(ge=0)
    latency_ms_mean_per_attempt: float | None = Field(default=None, ge=0)
    token_usage_reported_attempt_count: int = Field(ge=0)
    token_usage_missing_attempt_count: int = Field(ge=0)
    input_tokens_total: int | None = Field(default=None, ge=0)
    output_tokens_total: int | None = Field(default=None, ge=0)
    total_tokens_total: int | None = Field(default=None, ge=0)
    token_values_estimated: Literal[False] = False


class EvaluationV2Summary(BaseModel):
    """Top-level report that cannot be mistaken for semantic model accuracy."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["1.0"] = "1.0"
    eval_run_id: str
    generated_at: datetime
    dataset_id: str
    dataset_version: str
    dataset_hash: str
    dataset_kind: str
    split: str
    annotation_status_counts: dict[str, int]
    official_performance_eligible: bool
    result_scope: Literal[
        "official_holdout_performance", "development_diagnostic"
    ]
    runner_name: str
    runner_version: str
    execution_mode: str
    requested_model_id: str | None
    observed_response_model_ids: tuple[str, ...]
    prompt_version: str | None
    validator_version: str | None
    case_count: int = Field(ge=1)
    automatic_grading: AutomaticGradingSummary
    validator_reliability: ValidatorReliabilityMetrics
    efficiency: EfficiencySummary
    semantic_accuracy_evaluated: Literal[False] = False
    warnings: tuple[str, ...]


class EvaluationV2RunStatus(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["1.0"] = "1.0"
    eval_run_id: str
    status: RunStatus
    started_at: datetime
    finished_at: datetime | None = None
    written_artifacts: tuple[str, ...] = ()
    missing_artifacts: tuple[str, ...] = ()
    error_code: str | None = None
    error_message: str | None = None

    @model_validator(mode="after")
    def validate_status(self) -> "EvaluationV2RunStatus":
        if self.status == "running":
            if self.finished_at is not None or self.error_code is not None:
                raise ValueError("running status cannot have completion fields")
        elif self.finished_at is None:
            raise ValueError("terminal run status requires finished_at")
        if self.status == "incomplete" and (
            self.error_code is None or self.error_message is None
        ):
            raise ValueError("incomplete status requires error details")
        if self.status == "complete" and (
            self.error_code is not None or self.error_message is not None
        ):
            raise ValueError("complete status cannot contain error details")
        return self


class EvaluationV2RunResult(BaseModel):
    """In-memory result returned only after all required artifacts are saved."""

    model_config = ConfigDict(frozen=True, extra="forbid", arbitrary_types_allowed=True)

    manifest: EvaluationRunManifest
    summary: EvaluationV2Summary
    case_outputs: CaseOutputsArtifact
    attempt_telemetry: AttemptTelemetryArtifact
    grading_results: GradingResultsArtifact
    validator_reliability: ValidatorReliabilityArtifact
    artifact_paths: dict[str, Path]


class EvaluationV2RunIncompleteError(RuntimeError):
    """Raised when an evaluation cannot produce its complete artifact set."""

    def __init__(self, run_id: str, status_path: Path, cause: Exception) -> None:
        super().__init__(
            f"evaluation run {run_id} is incomplete; see {status_path}: {cause}"
        )
        self.run_id = run_id
        self.status_path = status_path
        self.cause = cause


class _RecordedResponses:
    def __init__(self, attempts: tuple[RecordedAttempt, ...]) -> None:
        self._attempts = list(attempts)

    async def parse(self, **_kwargs: Any) -> SimpleNamespace:
        if not self._attempts:
            raise RuntimeError("recorded response sequence exhausted")
        attempt = self._attempts.pop(0)
        if attempt.kind == "api_error":
            raise RuntimeError(attempt.error_message)
        values: dict[str, Any] = {"output_parsed": attempt.output}
        if attempt.response_model_id is not None:
            values["model"] = attempt.response_model_id
        if attempt.response_id is not None:
            values["id"] = attempt.response_id
        if attempt.raw_output_text is not None:
            values["output_text"] = attempt.raw_output_text
        if attempt.token_usage is not None:
            values["usage"] = SimpleNamespace(**attempt.token_usage.model_dump())
        return SimpleNamespace(**values)


class _RecordedClient:
    def __init__(self, attempts: tuple[RecordedAttempt, ...]) -> None:
        self.responses = _RecordedResponses(attempts)


def load_recorded_response_plan(path: str | Path) -> RecordedResponsePlan:
    with Path(path).resolve().open("r", encoding="utf-8") as fixture_file:
        return RecordedResponsePlan.model_validate(json.load(fixture_file))


def case_to_news_fetch_result(case: EvaluationCaseV2) -> NewsFetchResult:
    """Convert fixed dataset metadata without re-fetching RSS or changing IDs."""

    items = tuple(
        NewsItem.model_validate(article.model_dump(mode="python"))
        for article in case.news_headlines
    )
    published_times = tuple(item.published_at for item in items)
    fetched_at = case.data_source.retrieved_at or max(published_times)
    window_days = (
        case.analysis_window.end_date - case.analysis_window.start_date
    ).days + 1
    window = AnalysisWindow(
        ticker=case.ticker,
        requested_analysis_days=window_days,
        start_date=case.analysis_window.start_date,
        end_date=case.analysis_window.end_date,
        timezone=case.analysis_window.timezone,
    )
    return NewsFetchResult(
        ticker=case.ticker,
        window=window,
        status="available",
        available=True,
        items=items,
        metadata=NewsFetchMetadata(
            provider=case.data_source.provider,
            query=f"{case.ticker} fixed evaluation snapshot",
            fetched_at=fetched_at,
            request_count=0,
            raw_item_count=len(items),
            invalid_item_count=0,
            outside_window_count=0,
            in_window_item_count=len(items),
            duplicate_item_count=0,
            truncated_item_count=0,
            stored_item_count=len(items),
            feed_oldest_published_at=min(published_times),
            feed_newest_published_at=max(published_times),
            warnings=("Fixed Evaluation v2 metadata; RSS was not re-fetched.",),
        ),
    )


class EvaluationV2ArtifactStore:
    """Write sensitive eval artifacts under the git-ignored runtime tree."""

    REQUIRED_ARTIFACTS = (
        "manifest",
        "case_outputs",
        "attempt_telemetry",
        "grading_results",
        "validator_reliability",
        "human_review",
        "summary",
        "report",
        "run_status",
    )

    def __init__(self, root_dir: str | Path = DEFAULT_ARTIFACT_ROOT) -> None:
        self.root_dir = Path(root_dir)

    def paths(self, run_id: str) -> dict[str, Path]:
        run_dir = (self.root_dir / run_id).resolve()
        return {
            "manifest": run_dir / "manifest.json",
            "case_outputs": run_dir / "case_outputs.json",
            "attempt_telemetry": run_dir / "attempt_telemetry.json",
            "grading_results": run_dir / "grading_results.json",
            "validator_reliability": run_dir / "validator_reliability.json",
            "human_review": run_dir / "human_review.md",
            "summary": run_dir / "summary.json",
            "report": run_dir / "report.md",
            "run_status": run_dir / "run_status.json",
        }

    def prepare(
        self,
        manifest: EvaluationRunManifest,
        status: EvaluationV2RunStatus,
        *,
        overwrite: bool,
    ) -> dict[str, Path]:
        paths = self.paths(manifest.run_id)
        save_execution_manifest(manifest, paths["manifest"], overwrite=overwrite)
        self.save_json(status, paths["run_status"], overwrite=overwrite)
        return paths

    def save_attempts(
        self,
        artifact: AttemptTelemetryArtifact,
        path: Path,
        *,
        overwrite: bool,
    ) -> Path:
        return AttemptTelemetryArtifactStore(path.parent).save(
            artifact,
            output_path=path,
            overwrite=overwrite,
        )

    def save_json(
        self,
        model: BaseModel,
        path: Path,
        *,
        overwrite: bool,
    ) -> Path:
        return self._atomic_write(
            path,
            json.dumps(
                model.model_dump(mode="json"),
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            overwrite=overwrite,
        )

    def save_text(self, text: str, path: Path, *, overwrite: bool) -> Path:
        return self._atomic_write(path, text, overwrite=overwrite)

    @staticmethod
    def _atomic_write(path: Path, content: str, *, overwrite: bool) -> Path:
        target = path.resolve()
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists() and not overwrite:
            raise FileExistsError(f"evaluation artifact already exists: {target}")
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
                temporary_file.write(content)
                temporary_file.flush()
                os.fsync(temporary_file.fileno())
            if target.exists() and not overwrite:
                raise FileExistsError(f"evaluation artifact already exists: {target}")
            os.replace(temporary_path, target)
            temporary_path = None
            return target
        finally:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)


class EvaluationV2Runner:
    """Execute Dataset v2 cases with independent analyzers and telemetry sinks."""

    def __init__(
        self,
        *,
        artifact_store: EvaluationV2ArtifactStore | None = None,
        dataset_validator: EvaluationDatasetValidator | None = None,
        grader: NewsQualityV2Grader | None = None,
    ) -> None:
        self.artifact_store = artifact_store or EvaluationV2ArtifactStore()
        self.dataset_validator = dataset_validator or EvaluationDatasetValidator()
        self.grader = grader or NewsQualityV2Grader()

    async def run(
        self,
        dataset_path: str | Path,
        *,
        mode: RunMode = "recorded",
        recorded_response_path: str | Path | None = None,
        manifest_path: str | Path | None = None,
        expected_dataset_hash: str | None = None,
        model_id: str | None = None,
        api_key: str | None = None,
        allow_live: bool = False,
        prompt_version: str = DEFAULT_PROMPT_VERSION,
        validator_version: str = DEFAULT_VALIDATOR_VERSION,
        overwrite: bool = False,
    ) -> EvaluationV2RunResult:
        summary = self.dataset_validator.validate(
            dataset_path,
            expected_hash=expected_dataset_hash,
        )
        response_plan: RecordedResponsePlan | None = None
        if mode == "recorded":
            if recorded_response_path is None:
                raise ValueError("recorded mode requires recorded_response_path")
            response_plan = load_recorded_response_plan(recorded_response_path)
            self._verify_response_plan(response_plan, summary)
            resolved_model = response_plan.model_id
            execution_mode = "offline_replay"
        else:
            if not allow_live:
                raise RuntimeError(
                    "live evaluation is disabled by default; pass allow_live=True explicitly"
                )
            resolved_key = (api_key or os.getenv("OPENAI_API_KEY", "")).strip()
            if not resolved_key:
                raise RuntimeError("live evaluation requires OPENAI_API_KEY")
            if not model_id or not model_id.strip():
                raise ValueError("live evaluation requires an exact model_id")
            api_key = resolved_key
            resolved_model = model_id.strip()
            execution_mode = "live_model"

        execution = ManifestExecutionConfig(
            runner_name=RUNNER_NAME,
            runner_version=RUNNER_VERSION,
            mode=execution_mode,
            model_id=resolved_model,
            prompt_version=prompt_version,
            validator_version=validator_version,
        )
        manifest = self._resolve_manifest(summary, execution, manifest_path)
        started_at = datetime.now(timezone.utc)
        running_status = EvaluationV2RunStatus(
            eval_run_id=manifest.run_id,
            status="running",
            started_at=started_at,
        )
        paths = self.artifact_store.prepare(
            manifest,
            running_status,
            overwrite=overwrite,
        )
        written = ["manifest", "run_status"]

        try:
            case_outputs: list[CaseFinalOutput] = []
            traces: list[EvaluationCaseAttemptTrace] = []
            grades: list[CaseGradeResult] = []
            plan_by_case = (
                {case.case_id: case for case in response_plan.cases}
                if response_plan is not None
                else {}
            )
            for case in summary.dataset.cases:
                collector = AttemptTelemetryCollector(enabled=True)
                if mode == "recorded":
                    client = _RecordedClient(plan_by_case[case.case_id].attempts)
                    analyzer = NewsAnalyzer(
                        client=client,
                        model=resolved_model,
                        attempt_telemetry_sink=collector,
                    )
                else:
                    analyzer = NewsAnalyzer(
                        api_key=api_key,
                        model=resolved_model,
                        attempt_telemetry_sink=collector,
                    )
                analysis = await analyzer.analyze(case_to_news_fetch_result(case))
                trace = collector.build_case_trace(
                    case_id=case.case_id,
                    analysis=analysis,
                )
                grade = self.grader.grade_case(
                    case,
                    analysis,
                    trace,
                    split=summary.dataset.split,
                )
                case_outputs.append(
                    CaseFinalOutput(case_id=case.case_id, analysis=analysis)
                )
                traces.append(trace)
                grades.append(grade)

            # Re-read the source after model execution.  A changed holdout or
            # development file never gets silently paired with the prepared hash.
            verified_summary = self.dataset_validator.validate(
                dataset_path,
                expected_hash=manifest.dataset_hash,
            )
            verify_manifest_dataset(manifest, verified_summary)

            generated_at = datetime.now(timezone.utc)
            trace_tuple = tuple(traces)
            grade_tuple = tuple(grades)
            output_artifact = CaseOutputsArtifact(
                eval_run_id=manifest.run_id,
                generated_at=generated_at,
                dataset_id=manifest.dataset_id,
                dataset_version=manifest.dataset_version,
                dataset_hash=manifest.dataset_hash,
                cases=tuple(case_outputs),
            )
            attempt_artifact = build_attempt_telemetry_artifact(
                eval_run_id=manifest.run_id,
                generated_at=generated_at,
                dataset_id=manifest.dataset_id,
                dataset_version=manifest.dataset_version,
                dataset_hash=manifest.dataset_hash,
                cases=trace_tuple,
            )
            reliability = compute_validator_reliability_metrics(trace_tuple)
            reliability_artifact = ValidatorReliabilityArtifact(
                eval_run_id=manifest.run_id,
                generated_at=generated_at,
                metrics=reliability,
            )
            automatic_summary = summarize_automatic_grades(grade_tuple)
            grading_artifact = GradingResultsArtifact(
                eval_run_id=manifest.run_id,
                generated_at=generated_at,
                dataset_id=manifest.dataset_id,
                dataset_version=manifest.dataset_version,
                dataset_hash=manifest.dataset_hash,
                cases=grade_tuple,
                automatic_summary=automatic_summary,
            )
            evaluation_summary = self._build_summary(
                manifest,
                summary,
                traces=trace_tuple,
                automatic=automatic_summary,
                reliability=reliability,
                generated_at=generated_at,
            )

            jobs = (
                (
                    "case_outputs",
                    lambda: self.artifact_store.save_json(
                        output_artifact,
                        paths["case_outputs"],
                        overwrite=overwrite,
                    ),
                ),
                (
                    "attempt_telemetry",
                    lambda: self.artifact_store.save_attempts(
                        attempt_artifact,
                        paths["attempt_telemetry"],
                        overwrite=overwrite,
                    ),
                ),
                (
                    "grading_results",
                    lambda: self.artifact_store.save_json(
                        grading_artifact,
                        paths["grading_results"],
                        overwrite=overwrite,
                    ),
                ),
                (
                    "validator_reliability",
                    lambda: self.artifact_store.save_json(
                        reliability_artifact,
                        paths["validator_reliability"],
                        overwrite=overwrite,
                    ),
                ),
                (
                    "human_review",
                    lambda: self.artifact_store.save_text(
                        self._render_human_review(
                            manifest,
                            summary,
                            tuple(case_outputs),
                            trace_tuple,
                            grade_tuple,
                        ),
                        paths["human_review"],
                        overwrite=overwrite,
                    ),
                ),
                (
                    "summary",
                    lambda: self.artifact_store.save_json(
                        evaluation_summary,
                        paths["summary"],
                        overwrite=overwrite,
                    ),
                ),
                (
                    "report",
                    lambda: self.artifact_store.save_text(
                        self._render_report(evaluation_summary),
                        paths["report"],
                        overwrite=overwrite,
                    ),
                ),
            )
            for artifact_name, save in jobs:
                save()
                written.append(artifact_name)

            finished_at = datetime.now(timezone.utc)
            complete_status = EvaluationV2RunStatus(
                eval_run_id=manifest.run_id,
                status="complete",
                started_at=started_at,
                finished_at=finished_at,
                written_artifacts=tuple(
                    name
                    for name in self.artifact_store.REQUIRED_ARTIFACTS
                    if name in {*written, "run_status"}
                ),
            )
            self.artifact_store.save_json(
                complete_status,
                paths["run_status"],
                overwrite=True,
            )
            return EvaluationV2RunResult(
                manifest=manifest,
                summary=evaluation_summary,
                case_outputs=output_artifact,
                attempt_telemetry=attempt_artifact,
                grading_results=grading_artifact,
                validator_reliability=reliability_artifact,
                artifact_paths=paths,
            )
        except Exception as exc:
            missing = tuple(
                name
                for name in self.artifact_store.REQUIRED_ARTIFACTS
                if name not in {*written, "run_status"}
            )
            incomplete_status = EvaluationV2RunStatus(
                eval_run_id=manifest.run_id,
                status="incomplete",
                started_at=started_at,
                finished_at=datetime.now(timezone.utc),
                written_artifacts=tuple(dict.fromkeys(written)),
                missing_artifacts=missing,
                error_code="evaluation_execution_or_artifact_failure",
                error_message=f"{type(exc).__name__}: {exc}",
            )
            try:
                self.artifact_store.save_json(
                    incomplete_status,
                    paths["run_status"],
                    overwrite=True,
                )
            except Exception:
                pass
            raise EvaluationV2RunIncompleteError(
                manifest.run_id,
                paths["run_status"],
                exc,
            ) from exc

    @staticmethod
    def _verify_response_plan(
        plan: RecordedResponsePlan,
        summary: DatasetValidationSummary,
    ) -> None:
        mismatches: list[str] = []
        if plan.dataset_id != summary.dataset.dataset_id:
            mismatches.append("dataset_id")
        if plan.dataset_version != summary.dataset.dataset_version:
            mismatches.append("dataset_version")
        if plan.dataset_hash != summary.dataset_hash:
            mismatches.append("dataset_hash")
        response_case_ids = tuple(case.case_id for case in plan.cases)
        if set(response_case_ids) != set(summary.case_ids):
            mismatches.append("case_ids")
        if mismatches:
            raise ValueError(
                "recorded response plan does not match dataset: "
                + ", ".join(mismatches)
            )

    @staticmethod
    def _resolve_manifest(
        summary: DatasetValidationSummary,
        execution: ManifestExecutionConfig,
        manifest_path: str | Path | None,
    ) -> EvaluationRunManifest:
        if manifest_path is None:
            return build_execution_manifest(summary, execution=execution)
        with Path(manifest_path).resolve().open("r", encoding="utf-8") as manifest_file:
            manifest = EvaluationRunManifest.model_validate(json.load(manifest_file))
        verify_manifest_dataset(manifest, summary)
        if manifest.execution != execution:
            raise ValueError("manifest execution config does not match requested run")
        return manifest

    @staticmethod
    def _build_summary(
        manifest: EvaluationRunManifest,
        dataset_summary: DatasetValidationSummary,
        *,
        traces: tuple[EvaluationCaseAttemptTrace, ...],
        automatic: AutomaticGradingSummary,
        reliability: ValidatorReliabilityMetrics,
        generated_at: datetime,
    ) -> EvaluationV2Summary:
        statuses: dict[str, int] = {}
        for case in dataset_summary.dataset.cases:
            status = case.human_annotation.status
            statuses[status] = statuses.get(status, 0) + 1
        official = (
            dataset_summary.dataset.split == "holdout"
            and all(
                case.human_annotation.status == "approved"
                for case in dataset_summary.dataset.cases
            )
        )
        warnings: list[str] = []
        if not official:
            warnings.append(
                "이 결과는 development/draft 진단이며 검증된 모델 정확도나 공식 성능이 아닙니다."
            )
        warnings.append(
            "Validator 통과율은 production 계약 준수율이며 semantic accuracy가 아닙니다."
        )
        efficiency = _summarize_efficiency(traces)
        response_models = tuple(
            dict.fromkeys(
                attempt.response_model_id
                for trace in traces
                for attempt in trace.attempts
                if attempt.response_model_id is not None
            )
        )
        return EvaluationV2Summary(
            eval_run_id=manifest.run_id,
            generated_at=generated_at,
            dataset_id=manifest.dataset_id,
            dataset_version=manifest.dataset_version,
            dataset_hash=manifest.dataset_hash,
            dataset_kind=manifest.dataset_kind,
            split=manifest.split,
            annotation_status_counts=statuses,
            official_performance_eligible=official,
            result_scope=(
                "official_holdout_performance" if official else "development_diagnostic"
            ),
            runner_name=manifest.execution.runner_name,
            runner_version=manifest.execution.runner_version,
            execution_mode=manifest.execution.mode,
            requested_model_id=manifest.execution.model_id,
            observed_response_model_ids=response_models,
            prompt_version=manifest.execution.prompt_version,
            validator_version=manifest.execution.validator_version,
            case_count=manifest.case_count,
            automatic_grading=automatic,
            validator_reliability=reliability,
            efficiency=efficiency,
            warnings=tuple(warnings),
        )

    @staticmethod
    def _render_human_review(
        manifest: EvaluationRunManifest,
        dataset_summary: DatasetValidationSummary,
        outputs: tuple[CaseFinalOutput, ...],
        traces: tuple[EvaluationCaseAttemptTrace, ...],
        grades: tuple[CaseGradeResult, ...],
    ) -> str:
        output_by_id = {output.case_id: output for output in outputs}
        trace_by_id = {trace.case_id: trace for trace in traces}
        grade_by_id = {grade.case_id: grade for grade in grades}
        lines = [
            "# Evaluation v2 Human Review Sheet",
            "",
            f"- Eval run ID: `{manifest.run_id}`",
            f"- Dataset: `{manifest.dataset_id}` `{manifest.dataset_version}`",
            f"- Dataset hash: `{manifest.dataset_hash}`",
            f"- Split: `{manifest.split}`",
            "- 의미 판정은 자동 채점 결과와 별도로 사람이 승인해야 합니다.",
            "",
        ]
        for case in dataset_summary.dataset.cases:
            output = output_by_id[case.case_id]
            trace = trace_by_id[case.case_id]
            grade = grade_by_id[case.case_id]
            lines.extend(
                [
                    f"## {html.escape(case.case_id)}",
                    "",
                    f"Annotation status: `{case.human_annotation.status}`  ",
                    f"Human review required: `{str(grade.human_review_required).lower()}`",
                    "",
                    "### Original headlines",
                    "",
                ]
            )
            for article in case.news_headlines:
                lines.append(
                    f"- `{article.article_id}` — {html.escape(article.title)} "
                    f"({html.escape(article.source)})"
                )
            lines.extend(["", "### Expected claims", ""])
            if case.expectations.expected_claims:
                for claim in case.expectations.expected_claims:
                    lines.append(
                        f"- `{claim.claim_id}` — {html.escape(claim.text)}"
                    )
            else:
                lines.append("- 없음")
            lines.extend(["", "### Forbidden claims", ""])
            if case.expectations.forbidden_claims:
                for claim in case.expectations.forbidden_claims:
                    lines.append(
                        f"- `{claim.claim_id}` — {html.escape(claim.text)}"
                    )
            else:
                lines.append("- 없음")
            lines.extend(
                [
                    "",
                    "### Final NewsAnalysis",
                    "",
                    "<pre>",
                    html.escape(
                        json.dumps(
                            output.analysis.model_dump(mode="json"),
                            ensure_ascii=False,
                            indent=2,
                        )
                    ),
                    "</pre>",
                    "",
                    "### Attempts (including rejected drafts)",
                    "",
                    "<pre>",
                    html.escape(
                        json.dumps(
                            [attempt.model_dump(mode="json") for attempt in trace.attempts],
                            ensure_ascii=False,
                            indent=2,
                        )
                    ),
                    "</pre>",
                    "",
                    "### Human decisions",
                    "",
                    "- [ ] Expected claim grounding 검수",
                    "- [ ] Forbidden claim 발생 검수",
                    "- [ ] Semantic distortion 검수",
                    "- [ ] Unsupported claim 판정 및 분모 기록",
                    "- [ ] Validator false acceptance / rejection 판정",
                    "- Reviewer notes:",
                    "",
                ]
            )
        return "\n".join(lines).rstrip() + "\n"

    @staticmethod
    def _render_report(summary: EvaluationV2Summary) -> str:
        reliability = summary.validator_reliability
        automatic = summary.automatic_grading

        def pct(value: float | None) -> str:
            return "not evaluated" if value is None else f"{value * 100:.1f}%"

        return "\n".join(
            [
                "# Evaluation v2 Report",
                "",
                f"- Eval run ID: `{summary.eval_run_id}`",
                f"- Dataset: `{summary.dataset_id}` `{summary.dataset_version}`",
                f"- Dataset hash: `{summary.dataset_hash}`",
                f"- Scope: `{summary.result_scope}`",
                f"- Official performance eligible: `{str(summary.official_performance_eligible).lower()}`",
                f"- Execution: `{summary.execution_mode}` / `{summary.requested_model_id}`",
                "",
                "## Production validator reliability",
                "",
                f"- First-pass pass rate: {pct(reliability.first_pass_validator_pass_rate)}",
                f"- Final-pass pass rate: {pct(reliability.final_pass_validator_pass_rate)}",
                f"- Rewrite rescue rate: {pct(reliability.rewrite_rescue_rate)}",
                f"- Average attempts: {reliability.average_attempt_count:.3f}",
                f"- Final unavailable rate: {pct(reliability.final_unavailable_rate)}",
                "",
                "## Deterministic case checks",
                "",
                f"- Sentiment match: {automatic.sentiment_match.numerator}/{automatic.sentiment_match.denominator}",
                f"- Availability match: {automatic.availability_match.numerator}/{automatic.availability_match.denominator}",
                f"- Evidence ID validity: {automatic.evidence_id_validity.numerator}/{automatic.evidence_id_validity.denominator}",
                f"- Required evidence: {automatic.required_evidence.numerator}/{automatic.required_evidence.denominator}",
                f"- Forbidden evidence: {automatic.forbidden_evidence.numerator}/{automatic.forbidden_evidence.denominator}",
                "",
                "## Semantic quality",
                "",
                "Not evaluated automatically. Use `human_review.md`; keyword matches are not treated as grounding proof.",
                "",
                "## Warnings",
                "",
                *[f"- {warning}" for warning in summary.warnings],
                "",
            ]
        )


def _summarize_efficiency(
    traces: tuple[EvaluationCaseAttemptTrace, ...],
) -> EfficiencySummary:
    attempts = tuple(attempt for trace in traces for attempt in trace.attempts)
    usages = tuple(attempt.token_usage for attempt in attempts if attempt.token_usage)

    def sum_optional(field_name: str) -> int | None:
        values = tuple(
            value
            for usage in usages
            if (value := getattr(usage, field_name)) is not None
        )
        return sum(values) if values else None

    total_latency = round(sum(attempt.latency_ms for attempt in attempts), 3)
    return EfficiencySummary(
        attempt_count=len(attempts),
        latency_ms_total=total_latency,
        latency_ms_mean_per_attempt=(
            total_latency / len(attempts) if attempts else None
        ),
        token_usage_reported_attempt_count=len(usages),
        token_usage_missing_attempt_count=len(attempts) - len(usages),
        input_tokens_total=sum_optional("input_tokens"),
        output_tokens_total=sum_optional("output_tokens"),
        total_tokens_total=sum_optional("total_tokens"),
    )

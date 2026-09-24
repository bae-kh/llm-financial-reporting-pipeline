"""Evaluation 전용 LLM attempt artifact와 validator 신뢰성 지표입니다."""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from analysis.news_analyzer import NewsAnalysis, NewsAnalysisAttemptTelemetry


class EvaluationCaseAttemptTrace(BaseModel):
    """하나의 평가 case 실행과 그 안의 LLM attempt를 연결합니다."""

    model_config = ConfigDict(frozen=True, allow_inf_nan=False)

    case_id: str = Field(min_length=1)
    repetition: int = Field(default=1, ge=1)
    final_available: bool
    final_error_code: str | None = None
    attempts: tuple[NewsAnalysisAttemptTelemetry, ...] = Field(max_length=3)

    @model_validator(mode="after")
    def validate_case_trace(self) -> "EvaluationCaseAttemptTrace":
        expected_numbers = tuple(range(1, len(self.attempts) + 1))
        actual_numbers = tuple(attempt.attempt_number for attempt in self.attempts)
        if actual_numbers != expected_numbers:
            raise ValueError("attempt numbers must be consecutive and start at 1")

        passed_positions = tuple(
            index
            for index, attempt in enumerate(self.attempts)
            if attempt.outcome == "validator_passed"
        )
        if passed_positions and passed_positions != (len(self.attempts) - 1,):
            raise ValueError("validator pass must be the final attempt")
        if self.final_available:
            if self.final_error_code is not None:
                raise ValueError("available case cannot have final_error_code")
            if not self.attempts or self.attempts[-1].outcome != "validator_passed":
                raise ValueError("available case requires a final validator pass")
        else:
            if self.final_error_code is None:
                raise ValueError("unavailable case requires final_error_code")
            if passed_positions:
                raise ValueError("unavailable case cannot contain a validator pass")
        return self


class AttemptTelemetryArtifact(BaseModel):
    """운영 metadata와 분리 저장되는 평가용 민감 artifact입니다."""

    model_config = ConfigDict(frozen=True, allow_inf_nan=False)

    schema_version: Literal["1.0"] = "1.0"
    eval_run_id: str = Field(min_length=1)
    generated_at: datetime
    dataset_id: str | None = None
    dataset_version: str | None = None
    dataset_hash: str | None = Field(
        default=None,
        pattern=r"^sha256:[0-9a-f]{64}$",
    )
    cases: tuple[EvaluationCaseAttemptTrace, ...] = Field(min_length=1)
    contains_full_model_outputs: Literal[True] = True
    metric_scope: Literal["production_validator_only"] = (
        "production_validator_only"
    )

    @model_validator(mode="after")
    def validate_artifact(self) -> "AttemptTelemetryArtifact":
        if self.generated_at.tzinfo is None:
            raise ValueError("artifact generated_at must be timezone-aware")
        dataset_fields = (
            self.dataset_id,
            self.dataset_version,
            self.dataset_hash,
        )
        if any(value is not None for value in dataset_fields) and not all(
            value is not None for value in dataset_fields
        ):
            raise ValueError("dataset identity fields must be all present or all null")
        case_keys = tuple((case.case_id, case.repetition) for case in self.cases)
        if len(case_keys) != len(set(case_keys)):
            raise ValueError("case_id and repetition pairs must be unique")
        return self


class ValidatorReliabilityMetrics(BaseModel):
    """의미 품질이 아닌 production validator 통과·복구 지표입니다."""

    model_config = ConfigDict(frozen=True, allow_inf_nan=False)

    metric_scope: Literal["production_validator_only"] = (
        "production_validator_only"
    )
    case_count: int = Field(ge=1)
    total_attempt_count: int = Field(ge=0)

    first_pass_numerator: int = Field(ge=0)
    first_pass_denominator: int = Field(ge=0)
    first_pass_validator_pass_rate: float | None = Field(
        default=None,
        ge=0,
        le=1,
    )

    final_pass_numerator: int = Field(ge=0)
    final_pass_denominator: int = Field(ge=0)
    final_pass_validator_pass_rate: float | None = Field(
        default=None,
        ge=0,
        le=1,
    )

    rewrite_rescue_numerator: int = Field(ge=0)
    rewrite_rescue_denominator: int = Field(ge=0)
    rewrite_rescue_rate: float | None = Field(default=None, ge=0, le=1)

    average_attempt_count: float = Field(ge=0)
    unavailable_count: int = Field(ge=0)
    final_unavailable_rate: float = Field(ge=0, le=1)

    @model_validator(mode="after")
    def validate_metric_arithmetic(self) -> "ValidatorReliabilityMetrics":
        rate_fields = (
            (
                self.first_pass_numerator,
                self.first_pass_denominator,
                self.first_pass_validator_pass_rate,
            ),
            (
                self.final_pass_numerator,
                self.final_pass_denominator,
                self.final_pass_validator_pass_rate,
            ),
            (
                self.rewrite_rescue_numerator,
                self.rewrite_rescue_denominator,
                self.rewrite_rescue_rate,
            ),
        )
        for numerator, denominator, rate in rate_fields:
            if numerator > denominator:
                raise ValueError("metric numerator cannot exceed denominator")
            if denominator == 0:
                if rate is not None:
                    raise ValueError("zero-denominator metric rate must be null")
            elif rate is None or abs(rate - numerator / denominator) > 1e-12:
                raise ValueError("metric rate must match numerator and denominator")
        if self.unavailable_count > self.case_count:
            raise ValueError("unavailable_count cannot exceed case_count")
        if abs(
            self.average_attempt_count
            - self.total_attempt_count / self.case_count
        ) > 1e-12:
            raise ValueError("average_attempt_count must match attempt totals")
        if abs(
            self.final_unavailable_rate
            - self.unavailable_count / self.case_count
        ) > 1e-12:
            raise ValueError("final_unavailable_rate must match unavailable_count")
        return self


class AttemptTelemetryCollector:
    """한 case 실행 동안 attempt를 메모리에 모으는 opt-in sink입니다."""

    def __init__(self, *, enabled: bool = False) -> None:
        self.enabled = enabled
        self._attempts: list[NewsAnalysisAttemptTelemetry] = []

    @property
    def attempts(self) -> tuple[NewsAnalysisAttemptTelemetry, ...]:
        return tuple(self._attempts)

    def record_attempt(self, attempt: NewsAnalysisAttemptTelemetry) -> None:
        if self.enabled:
            self._attempts.append(attempt)

    def build_case_trace(
        self,
        *,
        case_id: str,
        analysis: NewsAnalysis,
        repetition: int = 1,
    ) -> EvaluationCaseAttemptTrace:
        if not self.enabled:
            raise RuntimeError("attempt telemetry collector is disabled")
        return EvaluationCaseAttemptTrace(
            case_id=case_id,
            repetition=repetition,
            final_available=analysis.available,
            final_error_code=analysis.error_code,
            attempts=self.attempts,
        )


class AttemptTelemetryArtifactStore:
    """전체 LLM 초안을 일반 운영 로그와 분리해 원자적으로 저장합니다."""

    def __init__(
        self,
        output_dir: str | Path = (
            Path("reports") / "generated" / "evals" / "attempts"
        ),
    ) -> None:
        self.output_dir = Path(output_dir)

    def save(
        self,
        artifact: AttemptTelemetryArtifact,
        *,
        output_path: str | Path | None = None,
        overwrite: bool = False,
    ) -> Path:
        target = (
            Path(output_path)
            if output_path is not None
            else self.output_dir / f"{artifact.eval_run_id}.attempts.json"
        ).resolve()
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists() and not overwrite:
            raise FileExistsError(f"attempt telemetry artifact already exists: {target}")

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
                json.dump(
                    artifact.model_dump(mode="json"),
                    temporary_file,
                    ensure_ascii=False,
                    indent=2,
                )
                temporary_file.write("\n")
                temporary_file.flush()
                os.fsync(temporary_file.fileno())

            if target.exists() and not overwrite:
                raise FileExistsError(
                    f"attempt telemetry artifact already exists: {target}"
                )
            os.replace(temporary_path, target)
            temporary_path = None
            return target
        finally:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)


def build_attempt_telemetry_artifact(
    *,
    eval_run_id: str,
    cases: tuple[EvaluationCaseAttemptTrace, ...],
    dataset_id: str | None = None,
    dataset_version: str | None = None,
    dataset_hash: str | None = None,
    generated_at: datetime | None = None,
) -> AttemptTelemetryArtifact:
    """case trace를 dataset identity에 결합하되 모델을 실행하지 않습니다."""
    timestamp = generated_at or datetime.now(timezone.utc)
    return AttemptTelemetryArtifact(
        eval_run_id=eval_run_id,
        generated_at=timestamp,
        dataset_id=dataset_id,
        dataset_version=dataset_version,
        dataset_hash=dataset_hash,
        cases=cases,
    )


def compute_validator_reliability_metrics(
    cases: tuple[EvaluationCaseAttemptTrace, ...],
) -> ValidatorReliabilityMetrics:
    """attempt trace로 validator 신뢰성 지표를 결정론적으로 집계합니다."""
    if not cases:
        raise ValueError("reliability metrics require at least one case trace")

    # API 예외와 LLM 호출 전 fallback은 validator가 판정할 출력이 없으므로
    # validator pass-rate 분모에서 제외하고 unavailable rate에는 포함합니다.
    validator_eligible = tuple(
        case
        for case in cases
        if case.attempts and case.attempts[0].outcome != "api_error"
    )
    first_pass_numerator = sum(
        case.attempts[0].outcome == "validator_passed"
        for case in validator_eligible
    )
    final_pass_numerator = sum(
        case.final_available
        and case.attempts[-1].outcome == "validator_passed"
        for case in validator_eligible
    )

    rewrite_candidates = tuple(
        case
        for case in validator_eligible
        if case.attempts[0].outcome in {"parse_failed", "validator_failed"}
    )
    rewrite_rescue_numerator = sum(
        case.final_available
        and case.attempts[-1].outcome == "validator_passed"
        for case in rewrite_candidates
    )

    case_count = len(cases)
    total_attempt_count = sum(len(case.attempts) for case in cases)
    unavailable_count = sum(not case.final_available for case in cases)
    first_denominator = len(validator_eligible)
    rescue_denominator = len(rewrite_candidates)
    return ValidatorReliabilityMetrics(
        case_count=case_count,
        total_attempt_count=total_attempt_count,
        first_pass_numerator=first_pass_numerator,
        first_pass_denominator=first_denominator,
        first_pass_validator_pass_rate=(
            first_pass_numerator / first_denominator
            if first_denominator
            else None
        ),
        final_pass_numerator=final_pass_numerator,
        final_pass_denominator=first_denominator,
        final_pass_validator_pass_rate=(
            final_pass_numerator / first_denominator
            if first_denominator
            else None
        ),
        rewrite_rescue_numerator=rewrite_rescue_numerator,
        rewrite_rescue_denominator=rescue_denominator,
        rewrite_rescue_rate=(
            rewrite_rescue_numerator / rescue_denominator
            if rescue_denominator
            else None
        ),
        average_attempt_count=total_attempt_count / case_count,
        unavailable_count=unavailable_count,
        final_unavailable_rate=unavailable_count / case_count,
    )

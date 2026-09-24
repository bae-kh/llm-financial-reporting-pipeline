"""Evaluation v2의 결정론적 grader와 human-review 경계를 정의합니다."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from analysis.news_analyzer import NewsAnalysis
from evaluation.attempt_telemetry import EvaluationCaseAttemptTrace
from evaluation.dataset_v2 import DatasetSplit, EvaluationCaseV2


CheckStatus = Literal["pass", "fail", "not_evaluated"]
ReviewStatus = Literal["needs_human_review", "not_evaluated"]


class AutomaticCheckResult(BaseModel):
    """사람의 의미 판단 없이 확정 가능한 단일 검사 결과입니다."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    status: CheckStatus
    reason: str = Field(min_length=1)


class SemanticReviewResult(BaseModel):
    """자동 exact/keyword match로 정답을 주장하지 않는 의미 평가 상태입니다."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    expected_claim_grounding: ReviewStatus
    forbidden_claim_occurrence: ReviewStatus
    semantic_distortion: ReviewStatus
    unsupported_claim_rate: ReviewStatus
    validator_false_acceptance: ReviewStatus
    validator_false_rejection: ReviewStatus
    reason: str = Field(min_length=1)


class CaseTokenUsageSummary(BaseModel):
    """API가 제공한 값만 합산하고 누락 coverage를 함께 표시합니다."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    attempt_count: int = Field(ge=0)
    usage_reported_attempt_count: int = Field(ge=0)
    usage_missing_attempt_count: int = Field(ge=0)
    input_tokens_total: int | None = Field(default=None, ge=0)
    output_tokens_total: int | None = Field(default=None, ge=0)
    total_tokens_total: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def validate_coverage(self) -> "CaseTokenUsageSummary":
        if (
            self.usage_reported_attempt_count
            + self.usage_missing_attempt_count
            != self.attempt_count
        ):
            raise ValueError("token usage coverage must match attempt_count")
        return self


class CaseAutomaticGrade(BaseModel):
    """최종 출력과 production validator trace의 결정론적 case 채점입니다."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    case_id: str
    expected_available: Literal[True] = True
    expected_availability_source: Literal[
        "dataset_v2_runnable_news_case_contract"
    ] = "dataset_v2_runnable_news_case_contract"
    actual_available: bool
    expected_sentiments: tuple[str, ...]
    actual_sentiment: str | None

    availability: AutomaticCheckResult
    sentiment: AutomaticCheckResult
    evidence_id_validity: AutomaticCheckResult
    required_evidence: AutomaticCheckResult
    forbidden_evidence: AutomaticCheckResult
    structured_output_format: AutomaticCheckResult
    production_validator: AutomaticCheckResult

    input_article_ids: tuple[str, ...]
    cited_evidence_ids: tuple[str, ...]
    unknown_evidence_ids: tuple[str, ...] = ()
    missing_required_evidence_ids: tuple[str, ...] = ()
    cited_forbidden_evidence_ids: tuple[str, ...] = ()
    attempt_error_codes: tuple[str, ...] = ()
    attempt_count: int = Field(ge=0)
    attempt_latency_ms_total: float = Field(ge=0)
    response_model_ids: tuple[str, ...] = ()
    token_usage: CaseTokenUsageSummary


class CaseGradeResult(BaseModel):
    """자동 채점과 별도 의미 검수 상태를 함께 보존합니다."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    case_id: str
    split: DatasetSplit
    annotation_status: str
    official_case_label_eligible: bool
    automatic: CaseAutomaticGrade
    semantic: SemanticReviewResult
    human_review_required: bool


class MetricFraction(BaseModel):
    """분모가 0이면 rate를 null로 유지하는 명시적 집계 값입니다."""

    model_config = ConfigDict(frozen=True, extra="forbid", allow_inf_nan=False)

    numerator: int = Field(ge=0)
    denominator: int = Field(ge=0)
    rate: float | None = Field(default=None, ge=0, le=1)

    @model_validator(mode="after")
    def validate_fraction(self) -> "MetricFraction":
        if self.numerator > self.denominator:
            raise ValueError("metric numerator cannot exceed denominator")
        if self.denominator == 0:
            if self.rate is not None:
                raise ValueError("zero-denominator rate must be null")
        elif self.rate is None or abs(
            self.rate - self.numerator / self.denominator
        ) > 1e-12:
            raise ValueError("metric rate must match numerator and denominator")
        return self


class AutomaticGradingSummary(BaseModel):
    """의미 정확도와 분리된 deterministic diagnostic 집계입니다."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    metric_scope: Literal["deterministic_diagnostic_only"] = (
        "deterministic_diagnostic_only"
    )
    case_count: int = Field(ge=1)
    official_case_label_eligible_count: int = Field(ge=0)
    draft_case_count: int = Field(ge=0)
    availability_match: MetricFraction
    sentiment_match: MetricFraction
    evidence_id_validity: MetricFraction
    required_evidence: MetricFraction
    forbidden_evidence: MetricFraction
    structured_output_format: MetricFraction
    production_validator: MetricFraction
    semantic_accuracy_evaluated: Literal[False] = False


class NewsQualityV2Grader:
    """v2 case의 exact checks만 자동화하고 의미 판정은 보류합니다."""

    def grade_case(
        self,
        case: EvaluationCaseV2,
        analysis: NewsAnalysis,
        trace: EvaluationCaseAttemptTrace,
        *,
        split: DatasetSplit,
    ) -> CaseGradeResult:
        input_ids = tuple(article.article_id for article in case.news_headlines)
        cited_ids = tuple(
            sorted(
                {
                    article_id
                    for topic in analysis.key_topics
                    for article_id in topic.supporting_article_ids
                }
            )
        )
        input_set = set(input_ids)
        cited_set = set(cited_ids)
        unknown_ids = tuple(sorted(cited_set - input_set))
        missing_required = tuple(
            sorted(set(case.expectations.required_evidence_ids) - cited_set)
        )
        cited_forbidden = tuple(
            sorted(set(case.expectations.forbidden_evidence_ids) & cited_set)
        )

        availability = self._boolean_check(
            analysis.available,
            pass_reason="최종 NewsAnalysis가 expected available=true와 일치합니다.",
            fail_reason=(
                "Dataset v2 runnable news case는 available=true를 기대하지만 "
                f"최종 결과는 unavailable({analysis.error_code})입니다."
            ),
        )
        sentiment_pass = (
            analysis.available
            and analysis.sentiment in case.expectations.expected_sentiments
        )
        sentiment = self._boolean_check(
            bool(sentiment_pass),
            pass_reason="최종 sentiment가 expected_sentiments에 포함됩니다.",
            fail_reason=(
                f"최종 sentiment={analysis.sentiment!r}가 expected_sentiments="
                f"{case.expectations.expected_sentiments!r}와 일치하지 않습니다."
            ),
        )

        if analysis.available:
            evidence_validity = self._boolean_check(
                not unknown_ids,
                pass_reason="최종 citation이 모두 case 입력 article ID에 속합니다.",
                fail_reason=f"최종 출력에 unknown evidence ID가 있습니다: {unknown_ids}",
            )
            required_evidence = self._boolean_check(
                not missing_required,
                pass_reason="모든 required evidence ID가 최종 출력에 인용됐습니다.",
                fail_reason=f"누락된 required evidence ID: {missing_required}",
            )
            forbidden_evidence = self._boolean_check(
                not cited_forbidden,
                pass_reason="최종 출력이 forbidden evidence를 인용하지 않았습니다.",
                fail_reason=f"인용된 forbidden evidence ID: {cited_forbidden}",
            )
        else:
            evidence_validity = AutomaticCheckResult(
                status="not_evaluated",
                reason="최종 structured output이 없어 citation membership을 평가하지 않습니다.",
            )
            required_evidence = AutomaticCheckResult(
                status="fail",
                reason=(
                    "최종 출력이 unavailable이므로 required evidence를 충족하지 "
                    f"못했습니다: {case.expectations.required_evidence_ids}"
                ),
            )
            forbidden_evidence = AutomaticCheckResult(
                status="not_evaluated",
                reason="최종 structured output이 없어 forbidden evidence 검사를 보류합니다.",
            )

        last_attempt = trace.attempts[-1] if trace.attempts else None
        structured_format = self._attempt_check(
            None if last_attempt is None else last_attempt.parse_succeeded,
            pass_reason="마지막 attempt가 NewsLLMOutput schema parse에 성공했습니다.",
            fail_reason="마지막 attempt가 NewsLLMOutput schema parse에 실패했습니다.",
            unavailable_reason="parse 결과가 없어 output format을 평가하지 않습니다.",
        )
        production_validator = self._attempt_check(
            None if last_attempt is None else last_attempt.validator_passed,
            pass_reason="마지막 attempt가 production validator를 통과했습니다.",
            fail_reason="마지막 attempt가 production validator를 통과하지 못했습니다.",
            unavailable_reason="validator가 실행된 결과가 없어 평가하지 않습니다.",
        )

        attempt_error_codes = tuple(
            dict.fromkeys(
                code
                for attempt in trace.attempts
                for code in (
                    attempt.parse_error_code,
                    attempt.validator_error_code,
                    attempt.api_error_code,
                )
                if code is not None
            )
        )
        response_model_ids = tuple(
            dict.fromkeys(
                attempt.response_model_id
                for attempt in trace.attempts
                if attempt.response_model_id is not None
            )
        )
        token_usage = self._token_usage(trace)
        semantic = self._semantic_review(case, analysis, trace)
        official_case_label_eligible = (
            split == "holdout" and case.human_annotation.status == "approved"
        )
        return CaseGradeResult(
            case_id=case.case_id,
            split=split,
            annotation_status=case.human_annotation.status,
            official_case_label_eligible=official_case_label_eligible,
            automatic=CaseAutomaticGrade(
                case_id=case.case_id,
                actual_available=analysis.available,
                expected_sentiments=case.expectations.expected_sentiments,
                actual_sentiment=analysis.sentiment,
                availability=availability,
                sentiment=sentiment,
                evidence_id_validity=evidence_validity,
                required_evidence=required_evidence,
                forbidden_evidence=forbidden_evidence,
                structured_output_format=structured_format,
                production_validator=production_validator,
                input_article_ids=input_ids,
                cited_evidence_ids=cited_ids,
                unknown_evidence_ids=unknown_ids,
                missing_required_evidence_ids=missing_required,
                cited_forbidden_evidence_ids=cited_forbidden,
                attempt_error_codes=attempt_error_codes,
                attempt_count=len(trace.attempts),
                attempt_latency_ms_total=round(
                    sum(attempt.latency_ms for attempt in trace.attempts),
                    3,
                ),
                response_model_ids=response_model_ids,
                token_usage=token_usage,
            ),
            semantic=semantic,
            human_review_required=(
                "needs_human_review" in semantic.model_dump(mode="json").values()
            ),
        )

    @staticmethod
    def _boolean_check(
        passed: bool,
        *,
        pass_reason: str,
        fail_reason: str,
    ) -> AutomaticCheckResult:
        return AutomaticCheckResult(
            status="pass" if passed else "fail",
            reason=pass_reason if passed else fail_reason,
        )

    @staticmethod
    def _attempt_check(
        value: bool | None,
        *,
        pass_reason: str,
        fail_reason: str,
        unavailable_reason: str,
    ) -> AutomaticCheckResult:
        if value is None:
            return AutomaticCheckResult(
                status="not_evaluated",
                reason=unavailable_reason,
            )
        return AutomaticCheckResult(
            status="pass" if value else "fail",
            reason=pass_reason if value else fail_reason,
        )

    @staticmethod
    def _token_usage(trace: EvaluationCaseAttemptTrace) -> CaseTokenUsageSummary:
        usages = tuple(
            attempt.token_usage
            for attempt in trace.attempts
            if attempt.token_usage is not None
        )

        def sum_field(field_name: str) -> int | None:
            values = tuple(
                value
                for usage in usages
                if (value := getattr(usage, field_name)) is not None
            )
            return sum(values) if values else None

        return CaseTokenUsageSummary(
            attempt_count=len(trace.attempts),
            usage_reported_attempt_count=len(usages),
            usage_missing_attempt_count=len(trace.attempts) - len(usages),
            input_tokens_total=sum_field("input_tokens"),
            output_tokens_total=sum_field("output_tokens"),
            total_tokens_total=sum_field("total_tokens"),
        )

    @staticmethod
    def _semantic_review(
        case: EvaluationCaseV2,
        analysis: NewsAnalysis,
        trace: EvaluationCaseAttemptTrace,
    ) -> SemanticReviewResult:
        if analysis.available:
            expected_status: ReviewStatus = (
                "needs_human_review"
                if case.expectations.expected_claims
                else "not_evaluated"
            )
            forbidden_status: ReviewStatus = (
                "needs_human_review"
                if case.expectations.forbidden_claims
                else "not_evaluated"
            )
            general_status: ReviewStatus = "needs_human_review"
            false_acceptance: ReviewStatus = "needs_human_review"
        else:
            expected_status = "not_evaluated"
            forbidden_status = "not_evaluated"
            general_status = "not_evaluated"
            false_acceptance = "not_evaluated"

        has_rejected_attempt = any(
            attempt.outcome in {"parse_failed", "validator_failed"}
            for attempt in trace.attempts
        )
        return SemanticReviewResult(
            expected_claim_grounding=expected_status,
            forbidden_claim_occurrence=forbidden_status,
            semantic_distortion=general_status,
            unsupported_claim_rate=general_status,
            validator_false_acceptance=false_acceptance,
            validator_false_rejection=(
                "needs_human_review"
                if has_rejected_attempt
                else "not_evaluated"
            ),
            reason=(
                "Expected/forbidden claim은 단순 문자열 포함 여부로 판정하지 않습니다. "
                "headline, citation, final output과 rejected attempt를 사람이 함께 검토해야 합니다."
            ),
        )


def summarize_automatic_grades(
    grades: tuple[CaseGradeResult, ...],
) -> AutomaticGradingSummary:
    """case grader 결과를 의미 accuracy와 섞지 않고 집계합니다."""
    if not grades:
        raise ValueError("automatic grading summary requires at least one grade")

    def fraction(field_name: str) -> MetricFraction:
        outcomes = tuple(
            getattr(grade.automatic, field_name)
            for grade in grades
        )
        evaluated = tuple(
            outcome for outcome in outcomes if outcome.status != "not_evaluated"
        )
        numerator = sum(outcome.status == "pass" for outcome in evaluated)
        denominator = len(evaluated)
        return MetricFraction(
            numerator=numerator,
            denominator=denominator,
            rate=numerator / denominator if denominator else None,
        )

    return AutomaticGradingSummary(
        case_count=len(grades),
        official_case_label_eligible_count=sum(
            grade.official_case_label_eligible for grade in grades
        ),
        draft_case_count=sum(
            grade.annotation_status == "draft" for grade in grades
        ),
        availability_match=fraction("availability"),
        sentiment_match=fraction("sentiment"),
        evidence_id_validity=fraction("evidence_id_validity"),
        required_evidence=fraction("required_evidence"),
        forbidden_evidence=fraction("forbidden_evidence"),
        structured_output_format=fraction("structured_output_format"),
        production_validator=fraction("production_validator"),
    )

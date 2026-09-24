"""Evaluation v2 dataset contracts, validation, hashing, and run manifests.

This module deliberately does not call an LLM or change the production
``NewsAnalyzer`` validator.  It defines the immutable inputs that later
evaluation runners can consume.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import uuid
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from evaluation.news_quality_eval import NewsEvalCase, load_eval_cases


DatasetKind = Literal["real_news", "synthetic_adversarial", "legacy_synthetic"]
DatasetSplit = Literal["development", "holdout", "legacy"]
NewsSourceKind = Literal["real_news", "synthetic_adversarial"]
Sentiment = Literal["positive", "neutral", "negative"]
Difficulty = Literal["easy", "medium", "hard"]
AnnotationStatus = Literal["draft", "reviewed", "approved", "legacy_unreviewed"]
FailureCategory = Literal[
    "sentiment",
    "missing_evidence",
    "fabricated_evidence",
    "semantic_distortion",
    "unsupported_claim",
    "prompt_injection",
    "irrelevant_news",
    "numeric_hallucination",
    "policy_violation",
    "mixed_signal",
    "temporal_error",
    "source_ambiguity",
    "legacy_regression",
]
PolicyExpectation = Literal[
    "no_investment_advice",
    "no_future_price_prediction",
    "no_prompt_following",
    "no_unsupported_causality",
    "no_unsupported_investor_reaction",
]
ExecutionMode = Literal[
    "recorded_fixture",
    "offline_replay",
    "live_model",
    "e2e_live",
]


class EvaluationArticle(BaseModel):
    """Headline metadata presented to the news analysis component."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    article_id: str = Field(pattern=r"^news_[0-9a-f]{16}$")
    title: str = Field(min_length=1)
    published_at: datetime
    url: str = Field(min_length=1)
    source: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_metadata(self) -> "EvaluationArticle":
        if self.published_at.tzinfo is None:
            raise ValueError("published_at must be timezone-aware")
        parsed_url = urlsplit(self.url)
        if parsed_url.scheme not in {"http", "https"} or not parsed_url.netloc:
            raise ValueError("url must be an absolute HTTP(S) URL")
        return self


class EvaluationWindow(BaseModel):
    """Inclusive calendar window used by one evaluation case."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    start_date: date
    end_date: date
    timezone: str = "America/New_York"

    @model_validator(mode="after")
    def validate_window(self) -> "EvaluationWindow":
        if self.end_date < self.start_date:
            raise ValueError("analysis window end_date cannot precede start_date")
        try:
            ZoneInfo(self.timezone)
        except ZoneInfoNotFoundError as exc:
            raise ValueError("analysis window timezone must be a valid IANA name") from exc
        return self


class EvaluationDataSource(BaseModel):
    """Provenance for the case without asserting source credibility."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    source_kind: NewsSourceKind
    provider: str = Field(min_length=1)
    retrieved_at: datetime | None = None
    snapshot_ref: str | None = None
    provenance_notes: str = Field(min_length=1)
    license_notes: str | None = None

    @model_validator(mode="after")
    def validate_provenance(self) -> "EvaluationDataSource":
        if self.retrieved_at is not None and self.retrieved_at.tzinfo is None:
            raise ValueError("retrieved_at must be timezone-aware")
        if self.source_kind == "real_news" and self.retrieved_at is None:
            raise ValueError("real_news cases require retrieved_at")
        return self


class ExpectedClaim(BaseModel):
    """Atomic claim that a correct answer may express."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    claim_id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]+$")
    text: str = Field(min_length=1)
    supporting_article_ids: tuple[str, ...] = Field(min_length=1)
    importance: Literal["core", "supplemental"] = "core"

    @field_validator("supporting_article_ids")
    @classmethod
    def require_unique_support(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if len(values) != len(set(values)):
            raise ValueError("claim supporting_article_ids must be unique")
        return values


class ForbiddenClaim(BaseModel):
    """Atomic meaning that must not appear in a correct answer."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    claim_id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]+$")
    text: str = Field(min_length=1)
    category: FailureCategory
    rationale: str = Field(min_length=1)


class AutomaticChecks(BaseModel):
    """Deterministic lexical checks retained for legacy evaluator compatibility."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    required_terms: tuple[str, ...] = ()
    required_any_terms: tuple[str, ...] = ()
    forbidden_terms: tuple[str, ...] = ()

    @field_validator("required_terms", "required_any_terms", "forbidden_terms")
    @classmethod
    def require_unique_terms(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if len(values) != len(set(values)):
            raise ValueError("automatic check terms must be unique")
        return values


class CaseExpectations(BaseModel):
    """Ground truth and deterministic expectations for one case."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    expected_sentiments: tuple[Sentiment, ...] = Field(min_length=1)
    required_evidence_ids: tuple[str, ...] = Field(min_length=1)
    optional_evidence_ids: tuple[str, ...] = ()
    forbidden_evidence_ids: tuple[str, ...] = ()
    expected_claims: tuple[ExpectedClaim, ...] = ()
    forbidden_claims: tuple[ForbiddenClaim, ...] = ()
    policy_expectations: tuple[PolicyExpectation, ...] = (
        "no_investment_advice",
        "no_future_price_prediction",
        "no_prompt_following",
        "no_unsupported_causality",
        "no_unsupported_investor_reaction",
    )
    automatic_checks: AutomaticChecks = Field(default_factory=AutomaticChecks)

    @field_validator(
        "expected_sentiments",
        "required_evidence_ids",
        "optional_evidence_ids",
        "forbidden_evidence_ids",
        "policy_expectations",
    )
    @classmethod
    def require_unique_values(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if len(values) != len(set(values)):
            raise ValueError("expectation values must be unique")
        return values

    @model_validator(mode="after")
    def validate_expectations(self) -> "CaseExpectations":
        evidence_groups = (
            set(self.required_evidence_ids),
            set(self.optional_evidence_ids),
            set(self.forbidden_evidence_ids),
        )
        if any(
            evidence_groups[left] & evidence_groups[right]
            for left, right in ((0, 1), (0, 2), (1, 2))
        ):
            raise ValueError("required, optional, and forbidden evidence cannot overlap")
        claim_ids = tuple(
            claim.claim_id for claim in (*self.expected_claims, *self.forbidden_claims)
        )
        if len(claim_ids) != len(set(claim_ids)):
            raise ValueError("expected and forbidden claim IDs must be unique")
        return self


class HumanAnnotation(BaseModel):
    """Human labels and adjudication state; IDs should be pseudonymous."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    status: AnnotationStatus
    annotator_ids: tuple[str, ...] = ()
    reviewer_ids: tuple[str, ...] = ()
    annotated_at: datetime | None = None
    reviewed_at: datetime | None = None
    sentiment_rationale: str | None = None
    evidence_rationale: str | None = None
    claim_grounding_notes: str | None = None
    reviewer_notes: str | None = None

    @field_validator("annotator_ids", "reviewer_ids")
    @classmethod
    def require_unique_people(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if len(values) != len(set(values)):
            raise ValueError("annotation participant IDs must be unique")
        return values

    @model_validator(mode="after")
    def validate_review_state(self) -> "HumanAnnotation":
        timestamps = (self.annotated_at, self.reviewed_at)
        if any(value is not None and value.tzinfo is None for value in timestamps):
            raise ValueError("annotation timestamps must be timezone-aware")
        if self.status in {"reviewed", "approved"}:
            if not self.annotator_ids or self.annotated_at is None:
                raise ValueError("reviewed annotations require annotator_ids and annotated_at")
            rationale_fields = (
                self.sentiment_rationale,
                self.evidence_rationale,
                self.claim_grounding_notes,
            )
            if any(not value or not value.strip() for value in rationale_fields):
                raise ValueError("reviewed annotations require all rationale fields")
        if self.status == "approved":
            if not self.reviewer_ids or self.reviewed_at is None:
                raise ValueError("approved annotations require reviewer_ids and reviewed_at")
            if not self.reviewer_notes or not self.reviewer_notes.strip():
                raise ValueError("approved annotations require reviewer_notes")
        return self


class LegacyCompatibility(BaseModel):
    """Fields consumed by the current v1 deterministic grader."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    recorded_output: dict[str, Any]


class EvaluationCaseV2(BaseModel):
    """One versioned and reviewable news quality evaluation case."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    case_id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]+$")
    description: str = Field(min_length=1)
    split: DatasetSplit
    ticker: str = Field(pattern=r"^[A-Z][A-Z0-9.-]{0,9}$")
    analysis_window: EvaluationWindow
    news_headlines: tuple[EvaluationArticle, ...] = Field(min_length=1)
    data_source: EvaluationDataSource
    expectations: CaseExpectations
    human_annotation: HumanAnnotation
    difficulty: Difficulty
    failure_categories: tuple[FailureCategory, ...] = Field(min_length=1)
    legacy_compatibility: LegacyCompatibility | None = None

    @field_validator("failure_categories")
    @classmethod
    def require_unique_categories(
        cls,
        values: tuple[str, ...],
    ) -> tuple[str, ...]:
        if len(values) != len(set(values)):
            raise ValueError("failure_categories must be unique")
        return values

    @model_validator(mode="after")
    def validate_case_contract(self) -> "EvaluationCaseV2":
        article_ids = tuple(article.article_id for article in self.news_headlines)
        if len(article_ids) != len(set(article_ids)):
            raise ValueError("news headline article IDs must be unique within a case")
        article_id_set = set(article_ids)
        referenced_evidence = {
            *self.expectations.required_evidence_ids,
            *self.expectations.optional_evidence_ids,
            *self.expectations.forbidden_evidence_ids,
        }
        for claim in self.expectations.expected_claims:
            referenced_evidence.update(claim.supporting_article_ids)
        unknown_evidence = referenced_evidence - article_id_set
        if unknown_evidence:
            raise ValueError(
                f"expectations contain unknown evidence IDs: {sorted(unknown_evidence)}"
            )

        window_timezone = ZoneInfo(self.analysis_window.timezone)
        outside_window = tuple(
            article.article_id
            for article in self.news_headlines
            if not (
                self.analysis_window.start_date
                <= article.published_at.astimezone(window_timezone).date()
                <= self.analysis_window.end_date
            )
        )
        if outside_window:
            raise ValueError(
                f"news headlines fall outside the analysis window: {outside_window}"
            )
        return self


class EvaluationDatasetV2(BaseModel):
    """A homogeneous dataset track and split with strict case validation."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["2.0"] = "2.0"
    dataset_id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]+$")
    dataset_version: str = Field(
        pattern=r"^\d+\.\d+\.\d+(?:-[a-z0-9][a-z0-9.-]*)?$"
    )
    description: str = Field(min_length=1)
    dataset_kind: DatasetKind
    split: DatasetSplit
    created_at: datetime | None
    holdout_frozen_at: datetime | None = None
    cases: tuple[EvaluationCaseV2, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_dataset_contract(self) -> "EvaluationDatasetV2":
        if self.created_at is None:
            if self.dataset_kind != "legacy_synthetic":
                raise ValueError("non-legacy datasets require created_at")
        elif self.created_at.tzinfo is None:
            raise ValueError("dataset created_at must be timezone-aware")
        if self.holdout_frozen_at is not None and self.holdout_frozen_at.tzinfo is None:
            raise ValueError("holdout_frozen_at must be timezone-aware")

        case_ids = tuple(case.case_id for case in self.cases)
        if len(case_ids) != len(set(case_ids)):
            raise ValueError("evaluation case IDs must be unique")
        if any(case.split != self.split for case in self.cases):
            raise ValueError("every case split must match the dataset split")

        expected_source = (
            "real_news" if self.dataset_kind == "real_news" else "synthetic_adversarial"
        )
        if any(case.data_source.source_kind != expected_source for case in self.cases):
            raise ValueError("a dataset cannot mix real and synthetic source tracks")

        if self.dataset_kind == "legacy_synthetic" and self.split != "legacy":
            raise ValueError("legacy_synthetic datasets must use the legacy split")
        if self.split == "legacy" and self.dataset_kind != "legacy_synthetic":
            raise ValueError("only legacy_synthetic datasets may use the legacy split")

        if self.split == "holdout":
            if self.holdout_frozen_at is None:
                raise ValueError("holdout datasets require holdout_frozen_at")
            if any(case.human_annotation.status != "approved" for case in self.cases):
                raise ValueError("every holdout case requires an approved annotation")
        elif self.holdout_frozen_at is not None:
            raise ValueError("only holdout datasets may set holdout_frozen_at")
        return self


class DatasetValidationSummary(BaseModel):
    """Result of schema validation without running a model."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    dataset: EvaluationDatasetV2
    source_path: Path
    dataset_hash: str
    case_count: int = Field(ge=1)
    case_ids: tuple[str, ...]
    adapted_from_schema_version: str | None = None


class ManifestExecutionConfig(BaseModel):
    """Configuration identity needed to compare future evaluation runs."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    runner_name: str = Field(min_length=1)
    runner_version: str = Field(min_length=1)
    mode: ExecutionMode
    model_id: str | None = None
    prompt_version: str | None = None
    validator_version: str | None = None

    @model_validator(mode="after")
    def require_model_for_live_mode(self) -> "ManifestExecutionConfig":
        if self.mode in {"live_model", "e2e_live"} and not self.model_id:
            raise ValueError("live execution modes require model_id")
        return self


class EvaluationRunManifest(BaseModel):
    """Prepared run manifest binding an execution to exact dataset bytes."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    manifest_version: Literal["1.0"] = "1.0"
    run_id: str = Field(pattern=r"^evalv2_[0-9]{8}T[0-9]{6}Z_[0-9a-f]{8}$")
    prepared_at: datetime
    status: Literal["prepared"] = "prepared"
    dataset_id: str
    dataset_version: str
    dataset_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    holdout_ground_truth_hash: str | None = Field(
        default=None,
        pattern=r"^sha256:[0-9a-f]{64}$",
    )
    dataset_path: Path
    dataset_kind: DatasetKind
    split: DatasetSplit
    case_count: int = Field(ge=1)
    case_ids: tuple[str, ...]
    execution: ManifestExecutionConfig

    @model_validator(mode="after")
    def validate_manifest(self) -> "EvaluationRunManifest":
        if self.prepared_at.tzinfo is None:
            raise ValueError("manifest prepared_at must be timezone-aware")
        if self.case_count != len(self.case_ids):
            raise ValueError("manifest case_count must match case_ids")
        if len(self.case_ids) != len(set(self.case_ids)):
            raise ValueError("manifest case_ids must be unique")
        if self.split == "holdout" and self.holdout_ground_truth_hash is None:
            raise ValueError("holdout manifests require holdout_ground_truth_hash")
        if self.split != "holdout" and self.holdout_ground_truth_hash is not None:
            raise ValueError("only holdout manifests use holdout_ground_truth_hash")
        return self


class EvaluationDatasetValidator:
    """Load and validate v2 datasets or the preserved v1 six-case fixture."""

    def validate(
        self,
        path: str | Path,
        *,
        expected_hash: str | None = None,
    ) -> DatasetValidationSummary:
        source = Path(path).resolve()
        with source.open("r", encoding="utf-8") as dataset_file:
            payload = json.load(dataset_file)

        schema_version = payload.get("schema_version")
        adapted_from: str | None = None
        if schema_version == "2.0":
            dataset = EvaluationDatasetV2.model_validate(payload)
        elif schema_version == "1.0":
            cases = load_eval_cases(source)
            dataset = adapt_legacy_news_cases(
                cases,
                description=payload.get(
                    "description",
                    "Preserved v1 synthetic news quality fixtures.",
                ),
            )
            adapted_from = "1.0"
        else:
            raise ValueError(f"unsupported evaluation dataset schema_version: {schema_version}")

        dataset_hash = compute_dataset_hash(dataset)
        if expected_hash is not None and dataset_hash != expected_hash:
            raise ValueError(
                f"dataset hash mismatch: expected {expected_hash}, got {dataset_hash}"
            )
        case_ids = tuple(case.case_id for case in dataset.cases)
        return DatasetValidationSummary(
            dataset=dataset,
            source_path=source,
            dataset_hash=dataset_hash,
            case_count=len(dataset.cases),
            case_ids=case_ids,
            adapted_from_schema_version=adapted_from,
        )


def _canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _sha256(value: Any) -> str:
    return f"sha256:{hashlib.sha256(_canonical_json_bytes(value)).hexdigest()}"


def compute_dataset_hash(dataset: EvaluationDatasetV2) -> str:
    """Hash the validated canonical representation, independent of JSON formatting."""

    return _sha256(dataset.model_dump(mode="json"))


def compute_holdout_ground_truth_hash(dataset: EvaluationDatasetV2) -> str | None:
    """Hash holdout labels separately so label edits cannot be hidden by reformatting."""

    if dataset.split != "holdout":
        return None
    labels = [
        {
            "case_id": case.case_id,
            "expectations": case.expectations.model_dump(mode="json"),
            "human_annotation": case.human_annotation.model_dump(mode="json"),
        }
        for case in dataset.cases
    ]
    return _sha256(labels)


def build_execution_manifest(
    summary: DatasetValidationSummary,
    *,
    execution: ManifestExecutionConfig,
    prepared_at: datetime | None = None,
    run_id: str | None = None,
) -> EvaluationRunManifest:
    """Create a prepared manifest; this function does not execute an evaluation."""

    resolved_time = prepared_at or datetime.now(timezone.utc)
    if resolved_time.tzinfo is None:
        raise ValueError("prepared_at must be timezone-aware")
    resolved_time = resolved_time.astimezone(timezone.utc)
    resolved_run_id = run_id or (
        f"evalv2_{resolved_time.strftime('%Y%m%dT%H%M%SZ')}_{uuid.uuid4().hex[:8]}"
    )
    dataset = summary.dataset
    return EvaluationRunManifest(
        run_id=resolved_run_id,
        prepared_at=resolved_time,
        dataset_id=dataset.dataset_id,
        dataset_version=dataset.dataset_version,
        dataset_hash=summary.dataset_hash,
        holdout_ground_truth_hash=compute_holdout_ground_truth_hash(dataset),
        dataset_path=summary.source_path,
        dataset_kind=dataset.dataset_kind,
        split=dataset.split,
        case_count=summary.case_count,
        case_ids=summary.case_ids,
        execution=execution,
    )


def verify_manifest_dataset(
    manifest: EvaluationRunManifest,
    summary: DatasetValidationSummary,
) -> None:
    """Reject execution when the validated dataset differs from its manifest."""

    dataset = summary.dataset
    mismatches: list[str] = []
    if manifest.dataset_id != dataset.dataset_id:
        mismatches.append("dataset_id")
    if manifest.dataset_version != dataset.dataset_version:
        mismatches.append("dataset_version")
    if manifest.dataset_hash != summary.dataset_hash:
        mismatches.append("dataset_hash")
    if manifest.case_ids != summary.case_ids:
        mismatches.append("case_ids")
    if manifest.holdout_ground_truth_hash != compute_holdout_ground_truth_hash(dataset):
        mismatches.append("holdout_ground_truth_hash")
    if mismatches:
        raise ValueError(
            "manifest does not match validated dataset fields: " + ", ".join(mismatches)
        )


def save_execution_manifest(
    manifest: EvaluationRunManifest,
    path: str | Path,
    *,
    overwrite: bool = False,
) -> Path:
    """Atomically save a prepared manifest without silently replacing one."""

    target = Path(path).resolve()
    if target.exists() and not overwrite:
        raise FileExistsError(f"evaluation manifest already exists: {target}")
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
            json.dump(
                manifest.model_dump(mode="json"),
                temporary_file,
                ensure_ascii=False,
                indent=2,
            )
            temporary_file.write("\n")
            temporary_file.flush()
            os.fsync(temporary_file.fileno())
        if target.exists() and not overwrite:
            raise FileExistsError(f"evaluation manifest already exists: {target}")
        os.replace(temporary_path, target)
        temporary_path = None
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
    return target


def adapt_legacy_news_cases(
    cases: tuple[NewsEvalCase, ...],
    *,
    description: str,
) -> EvaluationDatasetV2:
    """Represent the six v1 fixtures in v2 without claiming human annotation."""

    category_map: dict[str, tuple[FailureCategory, ...]] = {
        "positive_results": ("sentiment",),
        "negative_safety": ("sentiment", "policy_violation"),
        "mixed_direction": ("mixed_signal", "sentiment"),
        "prompt_injection": ("prompt_injection", "policy_violation"),
        "irrelevant_noise": ("irrelevant_news", "missing_evidence"),
        "delivery_semantics": ("semantic_distortion",),
    }
    converted: list[EvaluationCaseV2] = []
    for case in cases:
        converted.append(
            EvaluationCaseV2(
                case_id=case.case_id,
                description=case.description,
                split="legacy",
                ticker=case.ticker,
                analysis_window=EvaluationWindow(
                    start_date=case.start_date,
                    end_date=case.end_date,
                ),
                news_headlines=tuple(
                    EvaluationArticle.model_validate(article.model_dump())
                    for article in case.articles
                ),
                data_source=EvaluationDataSource(
                    source_kind="synthetic_adversarial",
                    provider="synthetic_eval_fixture_v1",
                    provenance_notes=(
                        "Adapted from evals/fixtures/news_quality_cases.json; "
                        "not human-adjudicated ground truth."
                    ),
                ),
                expectations=CaseExpectations(
                    expected_sentiments=case.expected_sentiments,
                    required_evidence_ids=case.required_evidence_ids,
                    forbidden_evidence_ids=case.forbidden_evidence_ids,
                    automatic_checks=AutomaticChecks(
                        required_terms=case.required_terms,
                        required_any_terms=case.required_any_terms,
                        forbidden_terms=case.forbidden_terms,
                    ),
                ),
                human_annotation=HumanAnnotation(
                    status="legacy_unreviewed",
                    reviewer_notes=(
                        "Legacy synthetic regression fixture; human semantic labels "
                        "have not been independently adjudicated."
                    ),
                ),
                difficulty="medium",
                failure_categories=category_map.get(
                    case.case_id,
                    ("legacy_regression",),
                ),
                legacy_compatibility=LegacyCompatibility(
                    recorded_output=case.recorded_output.model_dump(mode="json"),
                ),
            )
        )

    return EvaluationDatasetV2(
        dataset_id="news-quality-v1-legacy-synthetic",
        dataset_version="1.0.0-legacy",
        description=description,
        dataset_kind="legacy_synthetic",
        split="legacy",
        created_at=None,
        cases=tuple(converted),
    )

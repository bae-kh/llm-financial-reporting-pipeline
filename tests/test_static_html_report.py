"""저장 artifact 기반 정적 HTML 변환기의 계약을 검증합니다."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from report.html_report import (
    load_html_report_data,
    render_html_report,
    save_html_report,
)


def _write_json(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _write_artifacts(tmp_path: Path, *, llm_available: bool = True) -> tuple[Path, Path]:
    report_path = tmp_path / "report.md"
    snapshot_path = tmp_path / "snapshot.json"
    metadata_path = tmp_path / "run.json"
    context_path = tmp_path / "context.json"

    llm_section = (
        """
| 항목 | 값 |
|---|---:|
| 분석 상태 | available |
| 감성 | neutral |
| 감성 점수 | 0.10 |
| 신뢰도 | 75% |
| 입력/선택/분석 기사 | 2 / 2 / 2 |
| 선택 전략 | all |
| 모델 | test-model |

### 뉴스 요약

요약 <script>alert(1)</script>

### 주요 이슈와 근거

- **Topic <unsafe>**: Explanation <img src=x onerror=alert(1)>
  - `news_aaaaaaaaaaaaaaaa` — ignored rendered text
  - `news_bbbbbbbbbbbbbbbb` — ignored rendered text
"""
        if llm_available
        else """
뉴스 정성 분석을 사용할 수 없습니다. 이를 중립 분석으로 대체하지 않았습니다.

| 항목 | 값 |
|---|---:|
| 분석 상태 | unavailable |
| 뉴스 수집 상태 | available |
| 오류 코드 | validation_error |
| 감성 | N/A |
"""
    )
    report_path.write_text(
        f"""# TEST 금융 분석 리포트

## 1. 분석 개요

| 항목 | 값 |
|---|---|
| Run ID | `run_test_html` |
| 종목 | TEST |
| 요청 분석 기간 | 2026-01-01 ~ 2026-01-30 |
| 실제 가격 범위 | 2026-01-02 ~ 2026-01-30 (20개 거래일) |

## 2. 정량 시장 지표

| 지표 | 값 | 계산 주체 |
|---|---:|---|
| 기간 수익률 | 4.50% | Python |
| 연환산 변동성 | 20.00% | Python |
| 최대 낙폭(MDD) | -3.00% | Python |
| RSI(14) | 55.00 | Python |
| MACD difference | 1.2500 | Python |

## 3. Benchmark 비교

| 항목 | 값 |
|---|---:|
| Benchmark | SPY |
| 상태 | available |
| Benchmark 수익률 | 1.00% |
| 대상 종목 대비 차이 | 3.50% |

## 4. 뉴스 수집 상태

| 항목 | 값 |
|---|---:|
| 수집 상태 | available |
| 저장 기사 | 2 |
| Source coverage | unknown |

## 5. LLM 뉴스 분석
{llm_section}

## 6. 데이터 한계 및 경고
""",
        encoding="utf-8",
    )
    _write_json(
        snapshot_path,
        {
            "ticker": "TEST",
            "window": {
                "ticker": "TEST",
                "start_date": "2026-01-01",
                "end_date": "2026-01-30",
            },
            "items": [
                {
                    "article_id": "news_aaaaaaaaaaaaaaaa",
                    "title": "Same <headline> - Source A",
                    "source": "Source A",
                    "published_at": "2026-01-10T12:00:00Z",
                },
                {
                    "article_id": "news_bbbbbbbbbbbbbbbb",
                    "title": "Same <headline> - Source B",
                    "source": "Source B",
                    "published_at": "2026-01-11T12:00:00Z",
                },
            ],
        },
    )
    _write_json(
        metadata_path,
        {
            "run_id": "run_test_html",
            "status": "completed_with_warnings",
            "ticker": "TEST",
            "requested_start_date": "2026-01-01",
            "requested_end_date": "2026-01-30",
            "timezone": "America/New_York",
            "started_at": "2026-02-01T00:00:00Z",
            "finished_at": "2026-02-01T00:00:02Z",
            "duration_ms": 2000,
            "stages": [],
            "actual_price_start": "2026-01-02",
            "actual_price_end": "2026-01-30",
            "benchmark_status": "available",
            "news_status": "available",
            "llm_status": "available" if llm_available else "unavailable",
            "fallback_used": not llm_available,
            "artifacts": {
                "report_path": str(report_path),
                "news_snapshot_path": str(snapshot_path),
            },
            "warnings": ["coverage <unknown>"],
        },
    )
    _write_json(
        context_path,
        {
            "run_id": "run_test_html",
            "prompt_version": "prompt-v-test",
            "validator_version": "validator-v-test",
            "version_provenance": "test sidecar",
            "human_review": {
                "status": "draft_ai_assisted_review",
                "provenance": "AI <draft>",
                "source_document": "docs/review.md",
                "summary_decision": "pending",
                "topic_decisions": {"Topic <unsafe>": "changes_required"},
            },
        },
    )
    return metadata_path, context_path


def test_loads_artifacts_and_separates_id_validation_from_review(tmp_path: Path):
    metadata_path, context_path = _write_artifacts(tmp_path)

    data = load_html_report_data(metadata_path, context_path=context_path)

    assert data.price_observation_count == 20
    assert data.market_metrics["기간 수익률"] == "4.50%"
    assert data.evidence_id_valid_count == 2
    assert data.evidence_id_total_count == 2
    assert data.duplicate_id_count == 0
    assert data.duplicate_headline_count == 1
    assert data.topics[0].human_review_decision == "changes_required"
    assert data.daily_price_series_available is False


def test_render_escapes_llm_headline_warning_and_review_text(tmp_path: Path):
    metadata_path, context_path = _write_artifacts(tmp_path)
    data = load_html_report_data(metadata_path, context_path=context_path)

    rendered = render_html_report(data)

    assert "<script>alert(1)</script>" not in rendered
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in rendered
    assert "<img src=x onerror=alert(1)>" not in rendered
    assert "Same &lt;headline&gt; - Source A" in rendered
    assert "coverage &lt;unknown&gt;" in rendered
    assert "AI &lt;draft&gt;" in rendered
    assert "의미를 뒷받침한다는 판정이 아닙니다" in rendered
    assert "ID validated" in rendered
    assert "ID verified" not in rendered
    assert "uncalibrated model self-report" in rendered
    assert "Python이 금융 지표를 결정론적으로 계산" in rendered
    assert 'class="review-pill changes"' in rendered
    assert '<details class="technical-provenance">' in rendered
    assert '<details class="technical-provenance" open>' not in rendered
    assert rendered.index("Headline-only.") < rendered.index("Warnings 1")
    assert "Completed with warnings" in rendered
    assert "AI-assisted review draft" in rendered
    assert "completed_with_warnings" in rendered
    assert "draft_ai_assisted_review" in rendered
    assert "Duplicate ID 0 · Duplicate headline 1" in rendered
    assert '<dt>실행 상태</dt>' in rendered
    assert '<dt>Run</dt>' not in rendered
    assert '<details class="source-artifacts">' in rendered
    assert "Sources:" not in rendered


def test_more_than_three_supporting_articles_use_native_details(tmp_path: Path):
    metadata_path, context_path = _write_artifacts(tmp_path)
    report_path = tmp_path / "report.md"
    snapshot_path = tmp_path / "snapshot.json"
    report = report_path.read_text(encoding="utf-8")
    report = report.replace(
        "  - `news_bbbbbbbbbbbbbbbb` — ignored rendered text\n",
        """  - `news_bbbbbbbbbbbbbbbb` — ignored rendered text
  - `news_cccccccccccccccc` — ignored rendered text
  - `news_dddddddddddddddd` — ignored rendered text
  - `news_eeeeeeeeeeeeeeee` — ignored rendered text
""",
    )
    report_path.write_text(report, encoding="utf-8")
    snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
    snapshot["items"].extend(
        {
            "article_id": article_id,
            "title": f"Distinct headline {index}",
            "source": "Source",
            "published_at": f"2026-01-{index + 11:02d}T12:00:00Z",
        }
        for index, article_id in enumerate(
            (
                "news_cccccccccccccccc",
                "news_dddddddddddddddd",
                "news_eeeeeeeeeeeeeeee",
            )
        )
    )
    _write_json(snapshot_path, snapshot)

    rendered = render_html_report(
        load_html_report_data(metadata_path, context_path=context_path)
    )

    details_start = rendered.index('<details class="evidence-more">')
    assert rendered.count("ID validated") == 5
    assert "추가 supporting article 2개 보기" in rendered
    assert rendered.index("news_cccccccccccccccc") < details_start
    assert rendered.index("news_dddddddddddddddd") > details_start
    assert rendered.index("news_eeeeeeeeeeeeeeee") > details_start


def test_context_run_id_mismatch_is_rejected(tmp_path: Path):
    metadata_path, context_path = _write_artifacts(tmp_path)
    context = json.loads(context_path.read_text(encoding="utf-8"))
    context["run_id"] = "run_other"
    _write_json(context_path, context)

    with pytest.raises(ValueError, match="context run_id"):
        load_html_report_data(metadata_path, context_path=context_path)


def test_unavailable_llm_is_not_rendered_as_neutral(tmp_path: Path):
    metadata_path, context_path = _write_artifacts(tmp_path, llm_available=False)
    data = load_html_report_data(metadata_path, context_path=context_path)

    rendered = render_html_report(data)

    assert data.llm_available is False
    assert data.summary is None
    assert data.topics == ()
    assert "LLM unavailable" in rendered
    assert "수용된 Topic 결과가 없습니다" in rendered


def test_save_requires_explicit_overwrite(tmp_path: Path):
    target = tmp_path / "report.html"
    saved = save_html_report("<html>one</html>", target)
    assert saved.read_text(encoding="utf-8") == "<html>one</html>"

    with pytest.raises(FileExistsError):
        save_html_report("<html>two</html>", target)

    save_html_report("<html>two</html>", target, overwrite=True)
    assert target.read_text(encoding="utf-8") == "<html>two</html>"

"""저장된 Markdown·Snapshot·RunMetadata를 독립형 정적 HTML로 변환합니다."""

from __future__ import annotations

import html
import json
import math
import os
import re
import tempfile
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from workflow.run_tracking import RunMetadata


_TOPIC_PATTERN = re.compile(r"^- \*\*(?P<topic>.+?)\*\*: (?P<explanation>.*)$")
_ARTICLE_PATTERN = re.compile(r"^  - `(?P<article_id>[^`]+)`\s+—")
_TRADING_DAY_PATTERN = re.compile(r"\((?P<count>\d+)개 거래일\)")


@dataclass(frozen=True)
class HtmlEvidence:
    article_id: str
    headline: str | None
    source: str | None
    published_date: str | None
    id_valid: bool
    duplicate_id: bool
    duplicate_headline: bool


@dataclass(frozen=True)
class HtmlTopic:
    topic: str
    explanation: str
    evidence: tuple[HtmlEvidence, ...]
    human_review_decision: str | None


@dataclass(frozen=True)
class HtmlReportData:
    run_id: str
    ticker: str
    run_status: str
    requested_start: str
    requested_end: str
    actual_price_start: str | None
    actual_price_end: str | None
    timezone: str
    duration_ms: float
    generated_at: str
    price_observation_count: int | None
    market_metrics: dict[str, str]
    benchmark_metrics: dict[str, str]
    news_metrics: dict[str, str]
    llm_metrics: dict[str, str]
    llm_available: bool
    summary: str | None
    topics: tuple[HtmlTopic, ...]
    evidence_id_valid_count: int
    evidence_id_total_count: int
    duplicate_id_count: int
    duplicate_headline_count: int
    warnings: tuple[str, ...]
    error_code: str | None
    error_message: str | None
    prompt_version: str | None
    validator_version: str | None
    version_provenance: str | None
    git_sha: str | None
    human_review_status: str | None
    human_review_provenance: str | None
    human_review_source: str | None
    summary_review_decision: str | None
    report_filename: str
    snapshot_filename: str
    metadata_filename: str
    daily_price_series_available: bool = False


def load_html_report_data(
    metadata_path: str | Path,
    *,
    context_path: str | Path | None = None,
) -> HtmlReportData:
    """저장된 세 artifact와 선택적 provenance sidecar를 검증해 읽습니다."""
    metadata_source = Path(metadata_path).resolve()
    metadata_raw = _load_json_object(metadata_source)
    metadata = RunMetadata.model_validate(metadata_raw)

    report_path = _resolve_artifact_path(
        metadata.artifacts.report_path,
        metadata_source=metadata_source,
    )
    snapshot_path = _resolve_artifact_path(
        metadata.artifacts.news_snapshot_path,
        metadata_source=metadata_source,
    )
    if report_path is None or snapshot_path is None:
        raise ValueError("HTML generation requires both report and news snapshot artifacts")

    report_markdown = report_path.read_text(encoding="utf-8")
    snapshot = _load_json_object(snapshot_path)
    _validate_artifact_linkage(metadata, report_markdown, snapshot)

    context = (
        _load_json_object(Path(context_path).resolve()) if context_path else {}
    )
    if context and context.get("run_id") != metadata.run_id:
        raise ValueError("HTML context run_id does not match RunMetadata")

    overview = _parse_two_column_table(report_markdown, "## 1. 분석 개요")
    market_metrics = _parse_two_column_table(report_markdown, "## 2. 정량 시장 지표")
    benchmark_metrics = _parse_two_column_table(report_markdown, "## 3. Benchmark 비교")
    news_metrics = _parse_two_column_table(report_markdown, "## 4. 뉴스 수집 상태")
    llm_metrics = _parse_two_column_table(report_markdown, "## 5. LLM 뉴스 분석")
    summary = _parse_summary(report_markdown)
    parsed_topics = _parse_topics(report_markdown)

    articles_by_id = {
        str(item["article_id"]): item
        for item in snapshot.get("items", [])
        if isinstance(item, dict) and item.get("article_id")
    }
    cited_ids = [
        article_id
        for _, _, article_ids in parsed_topics
        for article_id in article_ids
    ]
    id_counts = Counter(cited_ids)
    headline_keys = [
        _headline_key(articles_by_id[article_id])
        for article_id in cited_ids
        if article_id in articles_by_id
    ]
    headline_counts = Counter(headline_keys)

    review = context.get("human_review", {})
    if review and not isinstance(review, dict):
        raise ValueError("human_review context must be an object")
    topic_decisions = review.get("topic_decisions", {}) if review else {}
    if topic_decisions and not isinstance(topic_decisions, dict):
        raise ValueError("topic_decisions must be an object")

    topics: list[HtmlTopic] = []
    for topic, explanation, article_ids in parsed_topics:
        evidence: list[HtmlEvidence] = []
        for article_id in article_ids:
            article = articles_by_id.get(article_id)
            headline_key = _headline_key(article) if article else None
            evidence.append(
                HtmlEvidence(
                    article_id=article_id,
                    headline=str(article.get("title")) if article else None,
                    source=str(article.get("source")) if article else None,
                    published_date=_published_date(article) if article else None,
                    id_valid=article is not None,
                    duplicate_id=id_counts[article_id] > 1,
                    duplicate_headline=(
                        headline_key is not None and headline_counts[headline_key] > 1
                    ),
                )
            )
        topics.append(
            HtmlTopic(
                topic=topic,
                explanation=explanation,
                evidence=tuple(evidence),
                human_review_decision=(
                    str(topic_decisions[topic]) if topic in topic_decisions else None
                ),
            )
        )

    valid_count = sum(article_id in articles_by_id for article_id in cited_ids)
    trading_days = _trading_day_count(overview.get("실제 가격 범위"))
    llm_available = llm_metrics.get("분석 상태") == "available"

    return HtmlReportData(
        run_id=metadata.run_id,
        ticker=metadata.ticker,
        run_status=metadata.status,
        requested_start=metadata.requested_start_date.isoformat(),
        requested_end=metadata.requested_end_date.isoformat(),
        actual_price_start=(
            metadata.actual_price_start.isoformat()
            if metadata.actual_price_start is not None
            else None
        ),
        actual_price_end=(
            metadata.actual_price_end.isoformat()
            if metadata.actual_price_end is not None
            else None
        ),
        timezone=metadata.timezone,
        duration_ms=metadata.duration_ms,
        generated_at=metadata.started_at.isoformat(),
        price_observation_count=trading_days,
        market_metrics=market_metrics,
        benchmark_metrics=benchmark_metrics,
        news_metrics=news_metrics,
        llm_metrics=llm_metrics,
        llm_available=llm_available,
        summary=summary,
        topics=tuple(topics),
        evidence_id_valid_count=valid_count,
        evidence_id_total_count=len(cited_ids),
        duplicate_id_count=sum(count - 1 for count in id_counts.values() if count > 1),
        duplicate_headline_count=sum(
            count - 1 for count in headline_counts.values() if count > 1
        ),
        warnings=metadata.warnings,
        error_code=metadata.error_code,
        error_message=metadata.error_message,
        prompt_version=_optional_string(context.get("prompt_version")),
        validator_version=_optional_string(context.get("validator_version")),
        version_provenance=_optional_string(context.get("version_provenance")),
        git_sha=_optional_string(context.get("git_sha")),
        human_review_status=_optional_string(review.get("status")),
        human_review_provenance=_optional_string(review.get("provenance")),
        human_review_source=_optional_string(review.get("source_document")),
        summary_review_decision=_optional_string(review.get("summary_decision")),
        report_filename=report_path.name,
        snapshot_filename=snapshot_path.name,
        metadata_filename=metadata_source.name,
    )


def render_html_report(data: HtmlReportData) -> str:
    """동적 값 전체를 escape한 독립형 HTML 문서를 생성합니다."""
    status_class = _status_class(data.run_status)
    llm_status = "available" if data.llm_available else "unavailable"
    llm_class = _status_class(llm_status)
    review_status = data.human_review_status or "not_recorded"
    review_status_label = _human_review_status_label(review_status)

    metric_cards = [
        ("기간 수익률", data.market_metrics.get("기간 수익률", "N/A"), "Python"),
        (
            "연환산 변동성",
            data.market_metrics.get("연환산 변동성", "N/A"),
            "Python",
        ),
        ("최대 낙폭", data.market_metrics.get("최대 낙폭(MDD)", "N/A"), "Python"),
        ("RSI · 14", data.market_metrics.get("RSI(14)", "N/A"), "Python"),
        (
            "MACD difference",
            data.market_metrics.get("MACD difference", "N/A"),
            "Python",
        ),
        (
            "Benchmark 차이",
            data.benchmark_metrics.get("대상 종목 대비 차이", "N/A"),
            data.benchmark_metrics.get("Benchmark", "N/A"),
        ),
    ]
    cards_html = "".join(
        f"""
        <article class="kpi-card">
          <span class="eyebrow">{_esc(label)}</span>
          <strong>{_esc(value)}</strong>
          <small>{_esc(detail)}</small>
        </article>"""
        for label, value, detail in metric_cards
    )

    target_return = _parse_percentage(data.market_metrics.get("기간 수익률"))
    benchmark_return = _parse_percentage(data.benchmark_metrics.get("Benchmark 수익률"))
    performance_html = _performance_comparison(target_return, benchmark_return, data)

    topic_html = _render_topics(data)
    warnings_html = (
        "".join(f"<li>{_esc(warning)}</li>" for warning in data.warnings)
        if data.warnings
        else "<li>저장된 경고가 없습니다.</li>"
    )
    stages_html = _render_metadata_grid(data)

    return f"""<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="color-scheme" content="light">
  <title>{_esc(data.ticker)} 금융 분석 리포트</title>
  <style>{_CSS}</style>
</head>
<body>
  <div class="page-shell">
    <header class="hero">
      <div>
        <p class="overline">LLM FINANCIAL REPORTING · OFFLINE ARTIFACT VIEW</p>
        <h1>{_esc(data.ticker)} <span>금융 분석 리포트</span></h1>
        <p class="hero-copy">Python이 금융 지표를 결정론적으로 계산하고, headline 기반 LLM이 뉴스를 해석합니다. 각 Topic에는 supporting evidence와 자동 검증·Human Review 상태를 함께 표시합니다.</p>
      </div>
      <div class="hero-status">
        <span class="status-pill {status_class}">{_esc(_run_status_label(data.run_status))}</span>
        <span class="status-pill {llm_class}">LLM {_esc(llm_status)}</span>
      </div>
      <dl class="run-strip">
        <div><dt>요청 기간</dt><dd>{_esc(data.requested_start)} → {_esc(data.requested_end)}</dd></div>
        <div><dt>실제 가격 기간</dt><dd>{_esc(_date_range(data.actual_price_start, data.actual_price_end))}</dd></div>
        <div><dt>거래일</dt><dd>{_esc(data.price_observation_count if data.price_observation_count is not None else 'N/A')}</dd></div>
        <div><dt>실행 상태</dt><dd>{_esc(_run_status_label(data.run_status))}</dd></div>
      </dl>
    </header>

    <main>
      <section aria-labelledby="market-title">
        <div class="section-heading">
          <div><p class="section-kicker">01 · MARKET</p><h2 id="market-title">핵심 시장 지표</h2></div>
          <p>금융 수치는 저장된 Markdown의 Python 계산 결과입니다.</p>
        </div>
        <div class="kpi-grid">{cards_html}</div>
        {performance_html}
      </section>

      <section aria-labelledby="analysis-title">
        <div class="section-heading">
          <div><p class="section-kicker">02 · NEWS ANALYSIS</p><h2 id="analysis-title">LLM 뉴스 분석</h2></div>
          <p>원문을 교정하지 않은 저장 출력 · headline metadata만 사용</p>
        </div>
        <div class="analysis-summary {llm_class}">
          <div class="summary-meta">
            <span class="status-pill {llm_class}">{_esc(llm_status)}</span>
            <span>감성 {_esc(data.llm_metrics.get('감성', 'N/A'))}</span>
            <span>score {_esc(data.llm_metrics.get('감성 점수', 'N/A'))}</span>
            <span class="confidence-note">confidence {_esc(data.llm_metrics.get('신뢰도', 'N/A'))} · uncalibrated model self-report</span>
          </div>
          <p class="summary-label">AI 생성 Summary</p>
          <p class="summary-text">{_esc(data.summary or '저장된 LLM Summary가 없습니다.')}</p>
          <div class="caution-note">Model confidence는 uncalibrated self-report이며 보정된 실제 정확도 확률이 아닙니다. 이 문장은 투자 조언이나 사람 검수 승인으로 제시되지 않습니다.</div>
        </div>
        <div class="topic-grid">{topic_html}</div>
      </section>

      <section aria-labelledby="validation-title">
        <div class="section-heading">
          <div><p class="section-kicker">03 · VALIDATION</p><h2 id="validation-title">입력·검증 범위</h2></div>
          <p>자동 ID 검증과 사람 의미 검수를 별도 상태로 표시합니다.</p>
        </div>
        <div class="validation-grid">
          <article class="validation-card">
            <span class="eyebrow">자동 Evidence ID 검사</span>
            <strong>{data.evidence_id_valid_count} / {data.evidence_id_total_count}</strong>
            <p>Snapshot에 존재하는 ID 수입니다. Topic 의미를 뒷받침한다는 판정이 아닙니다.</p>
          </article>
          <article class="validation-card">
            <span class="eyebrow">중복 인용 관찰</span>
            <strong>{_esc(_duplicate_summary(data))}</strong>
            <p>동일 ID 재사용과 publisher suffix를 제외한 동일 headline을 표시합니다.</p>
          </article>
          <article class="validation-card review-card">
            <span class="eyebrow">Human Review</span>
            <strong>{_esc(review_status_label)}</strong>
            <p>{_esc(data.human_review_provenance or '별도 사람 검수 provenance가 기록되지 않았습니다.')}</p>
          </article>
        </div>
        {stages_html}
      </section>

      <section aria-labelledby="limits-title">
        <div class="section-heading">
          <div><p class="section-kicker">04 · RUN CONTEXT</p><h2 id="limits-title">Coverage·경고·제약</h2></div>
          <p>저장된 실행 상태를 그대로 표시합니다.</p>
        </div>
        <div class="limitations primary-limitations">
          <p><strong>Headline-only.</strong> 기사 본문 사실 검증과 출처 신뢰도 평가는 수행되지 않았습니다.</p>
          <p><strong>Partial coverage.</strong> 저장된 Source coverage는 {_esc(data.news_metrics.get('Source coverage', 'N/A'))}이며, 선택 기사는 전체 시장 뉴스를 대표하지 않습니다.</p>
          <p><strong>Human review required.</strong> ID 존재 검사는 의미적 근거 적합성이나 사실성을 승인하지 않습니다.</p>
        </div>
        <details class="warning-panel" open>
          <summary>Warnings {len(data.warnings)}</summary>
          <ul>{warnings_html}</ul>
        </details>
        <div class="limitations secondary-limitations">
          <p><strong>시계열 미저장.</strong> 원본 일별 가격·SPY 시계열이 artifact에 없어 가격선 차트는 생성하지 않았습니다.</p>
          <p><strong>정적 산출물.</strong> 외부 API·데이터 수집·브라우저 실행 없이 저장 파일만 읽었습니다.</p>
        </div>
      </section>
    </main>

    <footer>
      <p>연구·교육 목적의 자동 생성 결과이며 투자 추천, 매수·매도 신호 또는 미래 성과 보장을 제공하지 않습니다.</p>
    </footer>
  </div>
</body>
</html>
"""


def save_html_report(
    html_document: str,
    output_path: str | Path,
    *,
    overwrite: bool = False,
) -> Path:
    """UTF-8 HTML을 원자적으로 저장합니다."""
    target = Path(output_path).resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists() and not overwrite:
        raise FileExistsError(f"HTML report already exists: {target}")

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
            temporary_file.write(html_document)
            temporary_file.flush()
            os.fsync(temporary_file.fileno())
        if target.exists() and not overwrite:
            raise FileExistsError(f"HTML report already exists: {target}")
        os.replace(temporary_path, target)
        temporary_path = None
        return target
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def _load_json_object(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as source:
        value = json.load(source)
    if not isinstance(value, dict):
        raise ValueError(f"JSON root must be an object: {path.name}")
    return value


def _resolve_artifact_path(
    value: Path | None,
    *,
    metadata_source: Path,
) -> Path | None:
    if value is None:
        return None
    candidate = Path(value)
    if candidate.is_absolute():
        return candidate
    return (metadata_source.parent / candidate).resolve()


def _validate_artifact_linkage(
    metadata: RunMetadata,
    report_markdown: str,
    snapshot: dict[str, Any],
) -> None:
    if f"`{metadata.run_id}`" not in report_markdown:
        raise ValueError("Markdown report does not contain the RunMetadata run_id")
    if snapshot.get("ticker") != metadata.ticker:
        raise ValueError("Snapshot ticker does not match RunMetadata")
    window = snapshot.get("window")
    if not isinstance(window, dict):
        raise ValueError("Snapshot window is missing")
    if window.get("start_date") != metadata.requested_start_date.isoformat() or (
        window.get("end_date") != metadata.requested_end_date.isoformat()
    ):
        raise ValueError("Snapshot analysis window does not match RunMetadata")


def _section(markdown: str, heading: str) -> list[str]:
    lines = markdown.splitlines()
    try:
        start = lines.index(heading) + 1
    except ValueError:
        return []
    end = len(lines)
    for index in range(start, len(lines)):
        if lines[index].startswith("## "):
            end = index
            break
    return lines[start:end]


def _parse_two_column_table(markdown: str, heading: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for line in _section(markdown, heading):
        cells = _markdown_table_cells(line)
        if len(cells) < 2 or cells[0] in {"항목", "지표"}:
            continue
        if all(set(cell) <= {"-", ":"} for cell in cells):
            continue
        result[_markdown_text(cells[0])] = _markdown_text(cells[1])
    return result


def _markdown_table_cells(line: str) -> list[str]:
    if not line.startswith("|") or not line.endswith("|"):
        return []
    cells: list[str] = []
    current: list[str] = []
    escaped = False
    for character in line[1:-1]:
        if character == "|" and not escaped:
            cells.append("".join(current).strip())
            current = []
            continue
        current.append(character)
        escaped = character == "\\" and not escaped
        if character != "\\":
            escaped = False
    cells.append("".join(current).strip())
    return cells


def _markdown_text(value: str) -> str:
    text = value.strip()
    if text.startswith("`") and text.endswith("`"):
        text = text[1:-1]
    text = re.sub(r"\\([\\|\[\]*_#<>])", r"\1", text)
    return html.unescape(text)


def _parse_summary(markdown: str) -> str | None:
    lines = _section(markdown, "## 5. LLM 뉴스 분석")
    try:
        start = lines.index("### 뉴스 요약") + 1
    except ValueError:
        return None
    content: list[str] = []
    for line in lines[start:]:
        if line.startswith("### "):
            break
        if line.strip():
            content.append(_markdown_text(line))
    return " ".join(content) or None


def _parse_topics(markdown: str) -> list[tuple[str, str, list[str]]]:
    lines = _section(markdown, "## 5. LLM 뉴스 분석")
    try:
        start = lines.index("### 주요 이슈와 근거") + 1
    except ValueError:
        return []
    topics: list[tuple[str, str, list[str]]] = []
    current_topic: str | None = None
    current_explanation = ""
    current_ids: list[str] = []
    for line in lines[start:]:
        topic_match = _TOPIC_PATTERN.match(line)
        if topic_match:
            if current_topic is not None:
                topics.append((current_topic, current_explanation, current_ids))
            current_topic = _markdown_text(topic_match.group("topic"))
            current_explanation = _markdown_text(topic_match.group("explanation"))
            current_ids = []
            continue
        article_match = _ARTICLE_PATTERN.match(line)
        if article_match and current_topic is not None:
            current_ids.append(article_match.group("article_id"))
    if current_topic is not None:
        topics.append((current_topic, current_explanation, current_ids))
    return topics


def _headline_key(article: dict[str, Any] | None) -> str | None:
    if not article:
        return None
    title = re.sub(r"\s+", " ", str(article.get("title", ""))).strip()
    source = re.sub(r"\s+", " ", str(article.get("source", ""))).strip()
    suffix = f" - {source}" if source else ""
    if suffix and title.casefold().endswith(suffix.casefold()):
        title = title[: -len(suffix)].rstrip()
    return title.casefold() or None


def _published_date(article: dict[str, Any]) -> str | None:
    value = article.get("published_at")
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).date().isoformat()
    except ValueError:
        return None


def _trading_day_count(value: str | None) -> int | None:
    if value is None:
        return None
    match = _TRADING_DAY_PATTERN.search(value)
    return int(match.group("count")) if match else None


def _optional_string(value: object) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None


def _parse_percentage(value: str | None) -> float | None:
    if value is None or not value.endswith("%"):
        return None
    try:
        parsed = float(value[:-1])
    except ValueError:
        return None
    return parsed if math.isfinite(parsed) else None


def _performance_comparison(
    target_return: float | None,
    benchmark_return: float | None,
    data: HtmlReportData,
) -> str:
    if target_return is None or benchmark_return is None:
        return '<div class="empty-state">기간 수익률 비교 데이터가 없습니다.</div>'
    scale = max(abs(target_return), abs(benchmark_return), 1.0)
    target_width = max(4.0, abs(target_return) / scale * 100)
    benchmark_width = max(4.0, abs(benchmark_return) / scale * 100)
    benchmark_name = data.benchmark_metrics.get("Benchmark", "Benchmark")
    return f"""
        <div class="performance-panel" aria-label="기간 수익률 비교">
          <div class="panel-copy">
            <span class="eyebrow">저장 집계값 비교</span>
            <h3>{_esc(data.ticker)} vs {_esc(benchmark_name)}</h3>
            <p>일별 시계열 차트가 아닌 동일 기간 집계 수익률입니다.</p>
          </div>
          <div class="bar-list">
            <div class="bar-row"><span>{_esc(data.ticker)}</span><div class="bar-track"><i class="bar target" style="width:{target_width:.1f}%"></i></div><strong>{target_return:.2f}%</strong></div>
            <div class="bar-row"><span>{_esc(benchmark_name)}</span><div class="bar-track"><i class="bar benchmark" style="width:{benchmark_width:.1f}%"></i></div><strong>{benchmark_return:.2f}%</strong></div>
          </div>
        </div>"""


def _render_topics(data: HtmlReportData) -> str:
    if not data.topics:
        return '<div class="empty-state unavailable">수용된 Topic 결과가 없습니다.</div>'
    rendered: list[str] = []
    for index, topic in enumerate(data.topics, start=1):
        review = topic.human_review_decision or "pending"
        visible_evidence = topic.evidence[:3]
        hidden_evidence = topic.evidence[3:]
        evidence_html = "".join(_render_evidence(item) for item in visible_evidence)
        if hidden_evidence:
            hidden_html = "".join(_render_evidence(item) for item in hidden_evidence)
            evidence_html += f"""
                <details class="evidence-more">
                  <summary>추가 supporting article {len(hidden_evidence)}개 보기</summary>
                  <div class="evidence-list evidence-list-collapsed">{hidden_html}</div>
                </details>"""
        if not topic.evidence:
            evidence_html = '<p class="empty-evidence">인용된 supporting article ID가 없습니다.</p>'
        rendered.append(
            f"""
            <article class="topic-card">
              <div class="topic-index">{index:02d}</div>
              <div class="topic-body">
                <div class="topic-title-row"><h3>{_esc(topic.topic)}</h3><span class="review-pill {_review_class(review)}"><span>Human review</span>{_esc(review)}</span></div>
                <p class="ai-label">AI 생성 Explanation</p>
                <p class="topic-explanation">{_esc(topic.explanation)}</p>
                <div class="evidence-list">{evidence_html}</div>
              </div>
            </article>"""
        )
    return "".join(rendered)


def _render_evidence(item: HtmlEvidence) -> str:
    validity = "ID validated" if item.id_valid else "ID missing"
    validity_class = "id-valid" if item.id_valid else "bad"
    duplicate_badges = ""
    if item.duplicate_id:
        duplicate_badges += '<span class="mini-pill warn">reused ID</span>'
    if item.duplicate_headline:
        duplicate_badges += '<span class="mini-pill warn">duplicate headline</span>'
    headline = item.headline or "Snapshot에서 headline을 찾을 수 없습니다."
    meta = " · ".join(
        part for part in (item.published_date, item.source) if part is not None
    )
    return f"""
        <div class="evidence-item">
          <div class="evidence-top"><code>{_esc(item.article_id)}</code><span class="mini-pill {validity_class}" title="선택된 입력/Snapshot에 ID가 존재함; 의미 적합성은 별도 검수">{validity}</span>{duplicate_badges}</div>
          <p>{_esc(headline)}</p>
          <small>{_esc(meta or 'metadata unavailable')}</small>
        </div>"""


def _render_metadata_grid(data: HtmlReportData) -> str:
    prompt = data.prompt_version or "RunMetadata 미기록"
    validator = data.validator_version or "RunMetadata 미기록"
    source = data.human_review_source or "미기록"
    version_note = data.version_provenance or "별도 provenance가 제공되지 않았습니다."
    git_sha = data.git_sha or "RunMetadata 미기록"
    return f"""
        <details class="technical-provenance">
          <summary>Technical provenance</summary>
          <p>개발·재현성 확인을 위한 실행 버전과 artifact 연결 정보입니다.</p>
          <dl class="metadata-grid">
          <div><dt>Run ID</dt><dd class="mono">{_esc(data.run_id)}</dd></div>
          <div><dt>Run status enum</dt><dd class="mono">{_esc(data.run_status)}</dd></div>
          <div><dt>Human Review status enum</dt><dd class="mono">{_esc(data.human_review_status or 'not_recorded')}</dd></div>
          <div><dt>Prompt</dt><dd>{_esc(prompt)}</dd></div>
          <div><dt>Validator</dt><dd>{_esc(validator)}</dd></div>
          <div><dt>버전 provenance</dt><dd>{_esc(version_note)}</dd></div>
          <div><dt>Git SHA</dt><dd class="mono">{_esc(git_sha)}</dd></div>
          <div><dt>뉴스 상태</dt><dd>{_esc(data.news_metrics.get('수집 상태', 'N/A'))}</dd></div>
          <div><dt>Coverage</dt><dd>{_esc(data.news_metrics.get('Source coverage', 'N/A'))}</dd></div>
          <div><dt>입력/선택/분석</dt><dd>{_esc(data.llm_metrics.get('입력/선택/분석 기사', 'N/A'))}</dd></div>
          <div><dt>Human Review source</dt><dd>{_esc(source)}</dd></div>
          </dl>
          <details class="source-artifacts">
            <summary>Source artifacts</summary>
            <ul class="artifact-list">
              <li><span>Markdown report</span><code>{_esc(data.report_filename)}</code></li>
              <li><span>News Snapshot</span><code>{_esc(data.snapshot_filename)}</code></li>
              <li><span>RunMetadata</span><code>{_esc(data.metadata_filename)}</code></li>
            </ul>
          </details>
        </details>"""


def _run_status_label(value: str) -> str:
    labels = {
        "completed": "Completed",
        "completed_with_warnings": "Completed with warnings",
        "failed": "Failed",
    }
    return labels.get(value.casefold(), value.replace("_", " ").capitalize())


def _human_review_status_label(value: str) -> str:
    labels = {
        "user_decisions_recorded": "Human review completed",
        "draft_ai_assisted_review": "AI-assisted review draft",
        "approved": "Approved",
        "changes_required": "Changes required",
        "pending": "Pending review",
        "not_recorded": "Not recorded",
    }
    return labels.get(value.casefold(), value.replace("_", " ").capitalize())


def _duplicate_summary(data: HtmlReportData) -> str:
    if data.duplicate_id_count == 0 and data.duplicate_headline_count == 0:
        return "중복 인용 없음"
    return (
        f"Duplicate ID {data.duplicate_id_count} · "
        f"Duplicate headline {data.duplicate_headline_count}"
    )


def _status_class(value: str) -> str:
    normalized = value.casefold()
    if normalized in {"available", "completed"}:
        return "ok"
    if normalized in {"unavailable", "failed"}:
        return "bad"
    return "warn"


def _review_class(value: str) -> str:
    normalized = value.casefold()
    if normalized in {"approved", "user_approved"}:
        return "approved"
    if normalized in {"changes_required", "rejected"}:
        return "changes"
    return "pending"


def _date_range(start: str | None, end: str | None) -> str:
    if start is None or end is None:
        return "N/A"
    return f"{start} → {end}"


def _esc(value: object) -> str:
    return html.escape(str(value), quote=True)


_CSS = r"""
:root {
  --ink: #132035;
  --muted: #68748a;
  --line: #dfe5ee;
  --surface: #ffffff;
  --surface-soft: #f5f7fb;
  --navy: #10233f;
  --blue: #246bfd;
  --teal: #008a83;
  --amber: #a66500;
  --red: #b42318;
  --shadow: 0 16px 42px rgba(23, 43, 77, .08);
}
* { box-sizing: border-box; }
body { margin: 0; background: #eef2f7; color: var(--ink); font-family: Inter, Pretendard, "Noto Sans KR", system-ui, sans-serif; line-height: 1.62; }
.page-shell { width: min(1440px, 100%); margin: 0 auto; background: var(--surface); min-height: 100vh; box-shadow: var(--shadow); }
.hero { position: relative; overflow: hidden; padding: clamp(18px, 2.2vw, 30px); color: white; background: linear-gradient(120deg, #0b1e36 0%, #123c67 68%, #126f78 100%); }
.hero::after { content: ""; position: absolute; width: 380px; height: 380px; right: -110px; top: -190px; border-radius: 50%; border: 70px solid rgba(255,255,255,.06); }
.overline, .section-kicker, .eyebrow, .ai-label, .summary-label { margin: 0; text-transform: uppercase; letter-spacing: .12em; font-size: .72rem; font-weight: 800; }
.overline { color: #9fd9ff; }
h1 { margin: 4px 0; font-size: clamp(2.1rem, 3vw, 2.55rem); line-height: 1; letter-spacing: -.055em; }
h1 span { display: block; margin-top: 8px; color: #c9d6e8; font-size: .42em; letter-spacing: -.02em; font-weight: 600; }
.hero-copy { max-width: 1100px; margin: 6px 0 0; color: #dce8f5; font-size: .8rem; line-height: 1.4; }
.hero-status { display: flex; flex-wrap: wrap; gap: 8px; position: absolute; top: 20px; right: clamp(18px, 2.2vw, 30px); z-index: 1; }
.status-pill, .review-pill, .mini-pill { display: inline-flex; align-items: center; border-radius: 999px; font-weight: 800; white-space: nowrap; }
.status-pill { padding: 7px 12px; font-size: .72rem; background: rgba(255,255,255,.13); border: 1px solid rgba(255,255,255,.18); }
.status-pill.ok, .mini-pill.ok { color: #08756f; background: #dff8f4; border-color: #a9e7dd; }
.status-pill.warn, .mini-pill.warn, .review-pill.warn { color: #8a5400; background: #fff3d9; border-color: #f5d38a; }
.status-pill.bad, .mini-pill.bad, .review-pill.bad { color: #9d2218; background: #ffebe9; border-color: #f5bbb5; }
.run-strip { position: relative; z-index: 1; display: grid; grid-template-columns: repeat(4, 1fr); gap: 1px; margin: 9px 0 0; border: 1px solid rgba(255,255,255,.14); background: rgba(255,255,255,.13); }
.run-strip div { padding: 5px 12px; background: rgba(6,22,43,.35); min-width: 0; }
.run-strip dt { color: #a8bed6; font-size: .72rem; }
.run-strip dd { margin: 4px 0 0; font-weight: 750; overflow-wrap: anywhere; }
main { padding: 0 clamp(22px, 4vw, 58px) 50px; }
section { padding: clamp(16px, 1.4vw, 22px) 0; border-bottom: 1px solid var(--line); }
.section-heading { display: flex; justify-content: space-between; gap: 28px; align-items: end; margin-bottom: 8px; }
.section-heading h2 { margin: 2px 0 0; font-size: clamp(1.5rem, 2.4vw, 1.85rem); letter-spacing: -.04em; }
.section-heading > p { max-width: 540px; margin: 0; color: var(--muted); text-align: right; }
.section-kicker, .eyebrow { color: var(--blue); }
.kpi-grid { display: grid; grid-template-columns: repeat(6, 1fr); gap: 9px; }
.kpi-card, .validation-card { padding: 7px 12px; border: 1px solid var(--line); border-radius: 16px; background: var(--surface); box-shadow: 0 6px 18px rgba(23,43,77,.035); }
.kpi-card strong, .validation-card strong { display: block; margin: 3px 0 0; font-size: clamp(1.25rem, 1.8vw, 1.55rem); letter-spacing: -.04em; }
.kpi-card small { color: var(--muted); }
.performance-panel { display: grid; grid-template-columns: minmax(220px, .7fr) 1.5fr; gap: 24px; padding: 8px 16px; margin-top: 7px; border-radius: 18px; background: var(--surface-soft); }
.panel-copy h3 { margin: 4px 0; font-size: 1.2rem; }
.panel-copy p { margin: 0; color: var(--muted); font-size: .8rem; }
.bar-list { align-self: center; display: grid; gap: 10px; }
.bar-row { display: grid; grid-template-columns: 56px 1fr 70px; align-items: center; gap: 12px; font-size: .82rem; }
.bar-row strong { text-align: right; }
.bar-track { height: 10px; border-radius: 99px; overflow: hidden; background: #dce3ed; }
.bar { display: block; height: 100%; border-radius: inherit; }
.bar.target { background: linear-gradient(90deg, var(--blue), #5c9cff); }
.bar.benchmark { background: linear-gradient(90deg, var(--teal), #5ec5bb); }
.analysis-summary { padding: clamp(12px, 1.5vw, 17px); border: 1px solid #cdd8e8; border-left: 6px solid var(--blue); border-radius: 18px; background: #f7faff; }
.analysis-summary.warn { border-left-color: var(--amber); background: #fffbf2; }
.analysis-summary.bad { border-left-color: var(--red); background: #fff8f7; }
.summary-meta { display: flex; flex-wrap: wrap; align-items: center; gap: 9px 16px; color: var(--muted); font-size: .82rem; }
.confidence-note { color: #8b95a7; font-size: .72rem; font-weight: 500; }
.summary-label, .ai-label { margin-top: 6px; color: var(--muted); }
.summary-text { max-width: 1000px; margin: 3px 0; font-size: clamp(1.05rem, 1.55vw, 1.25rem); font-weight: 680; letter-spacing: -.015em; }
.caution-note { max-width: 1050px; padding-top: 6px; margin-top: 6px; border-top: 1px solid var(--line); color: var(--muted); font-size: .74rem; line-height: 1.4; }
.topic-grid { display: grid; gap: 16px; margin-top: 14px; }
.topic-card { display: grid; grid-template-columns: 64px 1fr; border: 1px solid var(--line); border-radius: 18px; overflow: hidden; }
.topic-index { display: grid; place-items: start center; padding-top: 15px; color: #86a0bf; background: var(--surface-soft); font-size: 1.3rem; font-weight: 800; }
.topic-body { padding: clamp(14px, 2vw, 22px); min-width: 0; }
.topic-title-row { display: flex; align-items: start; justify-content: space-between; gap: 16px; }
.topic-title-row h3 { margin: 0; font-size: 1.22rem; letter-spacing: -.02em; }
.review-pill, .mini-pill { padding: 3px 8px; border: 1px solid var(--line); font-size: .64rem; }
.review-pill { gap: 7px; padding: 5px 10px; letter-spacing: .01em; }
.review-pill span { color: inherit; opacity: .7; font-size: .58rem; text-transform: uppercase; letter-spacing: .08em; }
.review-pill.approved { color: #08756f; background: #e9f8f5; border-color: #b7e2db; }
.review-pill.changes { color: #8b3a34; background: #fff3f1; border-color: #edc9c5; }
.review-pill.pending { color: #69582f; background: #fff9e9; border-color: #eadcad; }
.topic-explanation { margin: 7px 0 20px; font-size: 1rem; }
.evidence-list { display: grid; gap: 8px; }
.evidence-item { padding: 13px 15px; border-radius: 12px; background: var(--surface-soft); }
.evidence-top { display: flex; flex-wrap: wrap; gap: 6px; align-items: center; }
.evidence-item code, .mono { font-family: "SFMono-Regular", Consolas, monospace; font-size: .76rem; }
.evidence-item p { margin: 8px 0 2px; font-size: .91rem; }
.evidence-item small { color: var(--muted); }
.mini-pill.id-valid { color: #315d91; background: #edf5ff; border-color: #c8dcf5; }
.evidence-more { border: 1px solid var(--line); border-radius: 12px; background: #fbfcfe; }
.evidence-more > summary { cursor: pointer; padding: 11px 14px; color: #43546d; font-size: .82rem; font-weight: 750; }
.evidence-list-collapsed { padding: 0 8px 8px; }
.validation-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 14px; }
.validation-card p { margin-bottom: 0; color: var(--muted); font-size: .88rem; }
.review-card { background: #fffaf0; }
.technical-provenance { margin-top: 18px; border: 1px solid var(--line); border-radius: 14px; background: #fafbfd; }
.technical-provenance > summary { cursor: pointer; padding: 14px 17px; color: #43546d; font-size: .86rem; font-weight: 800; }
.technical-provenance > p { margin: -2px 17px 14px; color: var(--muted); font-size: .8rem; }
.metadata-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 1px; margin: 0; border-top: 1px solid var(--line); background: var(--line); }
.metadata-grid div { padding: 16px; background: white; min-width: 0; }
.metadata-grid dt { color: var(--muted); font-size: .72rem; }
.metadata-grid dd { margin: 5px 0 0; font-size: .88rem; overflow-wrap: anywhere; }
.source-artifacts { margin: 0; border-top: 1px solid var(--line); background: white; }
.source-artifacts > summary { cursor: pointer; padding: 13px 17px; color: #52617a; font-size: .8rem; font-weight: 750; }
.artifact-list { display: grid; gap: 7px; margin: 0; padding: 0 17px 15px; list-style: none; }
.artifact-list li { display: grid; grid-template-columns: 130px 1fr; gap: 12px; min-width: 0; color: var(--muted); font-size: .76rem; }
.artifact-list code { overflow-wrap: anywhere; color: #43546d; }
.warning-panel { margin-top: 16px; border: 1px solid #f0d59e; border-radius: 16px; background: #fffaf0; }
.warning-panel summary { cursor: pointer; padding: 17px 20px; font-weight: 800; }
.warning-panel ul { margin: 0; padding: 0 38px 22px; }
.warning-panel li { margin: 6px 0; color: #694a18; }
.limitations { display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px; margin-top: 16px; }
.limitations p { margin: 0; padding: 17px; border: 1px solid var(--line); border-radius: 14px; color: var(--muted); font-size: .86rem; }
.limitations strong { color: var(--ink); }
.primary-limitations { margin-top: 0; }
.primary-limitations p { background: #f7faff; border-color: #d7e2f1; }
.secondary-limitations { grid-template-columns: repeat(2, 1fr); }
.empty-state { padding: 28px; border: 1px dashed #b8c4d4; border-radius: 14px; text-align: center; color: var(--muted); }
.empty-state.unavailable { border-color: #e7aaa4; color: var(--red); background: #fff8f7; }
footer { padding: 30px clamp(22px, 5vw, 72px) 42px; color: #708097; background: #f3f6fa; font-size: .79rem; }
footer p { margin: 5px 0; overflow-wrap: anywhere; }
@media (max-width: 1100px) {
  .kpi-grid { grid-template-columns: repeat(3, 1fr); }
  .metadata-grid { grid-template-columns: repeat(2, 1fr); }
}
@media (max-width: 760px) {
  .hero-status { position: static; margin-top: 22px; }
  .run-strip, .validation-grid, .limitations, .performance-panel { grid-template-columns: 1fr; }
  .kpi-grid { grid-template-columns: repeat(2, 1fr); }
  .section-heading { display: block; }
  .section-heading > p { margin-top: 8px; text-align: left; }
  .topic-card { grid-template-columns: 46px 1fr; }
  .topic-title-row { display: block; }
  .review-pill { margin-top: 8px; }
}
@media (max-width: 460px) {
  .kpi-grid, .metadata-grid { grid-template-columns: 1fr; }
  .bar-row { grid-template-columns: 48px 1fr 60px; }
}
"""

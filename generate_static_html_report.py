"""저장된 금융 리포트 artifact를 외부 호출 없이 정적 HTML로 변환합니다."""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

from report.html_report import (
    load_html_report_data,
    render_html_report,
    save_html_report,
)


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="저장된 Markdown·Snapshot·RunMetadata를 정적 HTML로 변환",
        epilog=(
            "이 명령은 OpenAI, yfinance, RSS를 호출하지 않습니다. "
            "Prompt/Validator/Human Review 정보는 선택적 context JSON에서만 읽습니다."
        ),
    )
    parser.add_argument(
        "--metadata",
        required=True,
        help="기존 RunMetadata JSON 경로",
    )
    parser.add_argument(
        "--context",
        default=None,
        help="선택적 버전·Human Review provenance sidecar JSON 경로",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="HTML 저장 경로 (기본: reports/generated/html/<run_id>.html)",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="기존 HTML 파일 교체 허용",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    data = load_html_report_data(args.metadata, context_path=args.context)
    output_path = (
        Path(args.output)
        if args.output is not None
        else Path("reports") / "generated" / "html" / f"{data.run_id}.html"
    )
    saved_path = save_html_report(
        render_html_report(data),
        output_path,
        overwrite=args.overwrite,
    )
    logger.info("Static HTML report: %s", saved_path)
    logger.info(
        "Evidence ID validity: %d/%d (semantic relevance is not evaluated)",
        data.evidence_id_valid_count,
        data.evidence_id_total_count,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

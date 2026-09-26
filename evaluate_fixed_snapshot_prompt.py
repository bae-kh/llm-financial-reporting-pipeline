"""고정 Snapshot Prompt 비교 CLI. 기본 동작은 입력 검증만 수행합니다."""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
from pathlib import Path

from dotenv import load_dotenv

from analysis.news_analyzer import NewsAnalyzer
from evaluation.fixed_snapshot_prompt_compare import (
    DEFAULT_ARTIFACT_ROOT,
    DEFAULT_BASELINE_PATH,
    FixedSnapshotComparisonArtifactStore,
    FixedSnapshotPromptComparisonRunner,
)


logger = logging.getLogger(__name__)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "저장 Snapshot의 검증된 동일 입력으로 한 ticker·Prompt 조합을 실행합니다. "
            "기본 모드는 외부 호출 없는 validate-only입니다."
        )
    )
    parser.add_argument("--ticker", required=True)
    parser.add_argument(
        "--prompt-version",
        required=True,
        choices=tuple(sorted(NewsAnalyzer.SUPPORTED_PROMPT_VERSIONS)),
    )
    parser.add_argument(
        "--mode",
        choices=("validate-only", "live"),
        default="validate-only",
    )
    parser.add_argument("--model", default=NewsAnalyzer.DEFAULT_MODEL)
    parser.add_argument("--baseline", type=Path, default=DEFAULT_BASELINE_PATH)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_ARTIFACT_ROOT)
    parser.add_argument(
        "--allow-live",
        action="store_true",
        help="live mode의 실제 OpenAI 호출을 명시적으로 허용합니다.",
    )
    args = parser.parse_args(argv)
    if args.mode == "live" and not args.allow_live:
        parser.error("live mode requires the explicit --allow-live flag")
    if args.mode == "validate-only" and args.allow_live:
        parser.error("--allow-live cannot be used in validate-only mode")
    return args


async def run_cli(args: argparse.Namespace):
    runner = FixedSnapshotPromptComparisonRunner(
        baseline_path=args.baseline,
        artifact_store=FixedSnapshotComparisonArtifactStore(args.output_dir),
    )
    if args.mode == "validate-only":
        prepared = runner.prepare_input(args.ticker)
        logger.info("Input validation passed: %s", prepared.source.ticker)
        logger.info("Source Live Run ID: %s", prepared.source.run_id)
        logger.info("Selected articles: %d", len(prepared.source.ordered_ids))
        logger.info("Selected ID order SHA-256: %s", prepared.source.ordered_ids_sha256)
        logger.info("Prompt version selected for a future run: %s", args.prompt_version)
        return prepared

    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    result = await runner.run(
        ticker=args.ticker,
        prompt_version=args.prompt_version,
        model_id=args.model,
        api_key=api_key,
        allow_live=True,
    )
    logger.info("Comparison Run ID: %s", result.manifest.comparison_run_id)
    logger.info("Final available: %s", result.final_output.analysis.available)
    logger.info("Fallback used: %s", result.final_output.analysis.fallback_used)
    for name, path in result.artifact_paths.items():
        logger.info("%s: %s", name, path)
    return result


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s",
    )
    args = parse_args()
    if args.mode == "live":
        load_dotenv()
    try:
        asyncio.run(run_cli(args))
    except Exception as exc:
        logger.error("Fixed Snapshot Prompt 비교 실행 실패: %s", exc)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()

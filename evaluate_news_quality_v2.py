"""Evaluation v2 CLI with a network-free recorded default."""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
from pathlib import Path

from dotenv import load_dotenv

from analysis.news_analyzer import NewsAnalyzer
from evaluation.v2_runner import (
    DEFAULT_ARTIFACT_ROOT,
    EvaluationV2ArtifactStore,
    EvaluationV2Runner,
)


logger = logging.getLogger(__name__)
PROJECT_ROOT = Path(__file__).resolve().parent
DEFAULT_DATASET = (
    PROJECT_ROOT
    / "evals"
    / "datasets"
    / "news"
    / "real"
    / "development"
    / "tsla_headlines_pilot_v2.json"
)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Dataset v2 뉴스 품질 평가 실행기 (기본: 외부 API 미사용)",
    )
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--mode", choices=("recorded", "live"), default="recorded")
    parser.add_argument(
        "--recorded-responses",
        type=Path,
        help="recorded mode에서 사용할 dataset hash-bound 응답 JSON",
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        help="미리 준비한 manifest.json. 생략하면 새 manifest를 생성합니다.",
    )
    parser.add_argument(
        "--expected-dataset-hash",
        help="명시하면 dataset canonical hash 불일치 시 실행을 거부합니다.",
    )
    parser.add_argument("--model", default=NewsAnalyzer.DEFAULT_MODEL)
    parser.add_argument(
        "--prompt-version",
        choices=tuple(sorted(NewsAnalyzer.SUPPORTED_PROMPT_VERSIONS)),
        default=NewsAnalyzer.PROMPT_VERSION,
        help=(
            "평가 요청에 사용할 System Prompt 버전 "
            "(기본값은 Production 기본 v3)"
        ),
    )
    parser.add_argument(
        "--allow-live",
        action="store_true",
        help="실제 API 호출을 명시적으로 허용합니다. live mode에서만 사용합니다.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_ARTIFACT_ROOT,
        help="git-ignored evaluation artifact root",
    )
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args(argv)
    if args.mode == "recorded" and args.recorded_responses is None:
        parser.error("recorded mode requires --recorded-responses")
    if args.mode == "live" and not args.allow_live:
        parser.error("live mode requires the explicit --allow-live flag")
    if args.mode == "recorded" and args.allow_live:
        parser.error("--allow-live cannot be used in recorded mode")
    return args


async def run_eval(args: argparse.Namespace):
    api_key = None
    if args.mode == "live":
        api_key = os.getenv("OPENAI_API_KEY", "").strip()
    runner = EvaluationV2Runner(
        artifact_store=EvaluationV2ArtifactStore(args.output_dir),
    )
    result = await runner.run(
        args.dataset,
        mode=args.mode,
        recorded_response_path=args.recorded_responses,
        manifest_path=args.manifest,
        expected_dataset_hash=args.expected_dataset_hash,
        model_id=args.model,
        api_key=api_key,
        allow_live=args.allow_live,
        prompt_version=args.prompt_version,
        overwrite=args.overwrite,
    )
    logger.info("Eval run ID: %s", result.manifest.run_id)
    logger.info("Scope: %s", result.summary.result_scope)
    logger.info(
        "Official performance eligible: %s",
        result.summary.official_performance_eligible,
    )
    for name, path in result.artifact_paths.items():
        logger.info("%s: %s", name, path)
    for warning in result.summary.warnings:
        logger.warning(warning)
    return result


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s",
    )
    load_dotenv()
    args = parse_args()
    try:
        asyncio.run(run_eval(args))
    except Exception as exc:
        logger.error("Evaluation v2 실행 실패: %s", exc)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()

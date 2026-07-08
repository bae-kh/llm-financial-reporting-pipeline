"""
generate_report.py — LLM 기반 금융 데이터 리포트 생성 CLI

이 스크립트는 이 프로젝트의 메인 실행 엔트리포인트입니다.
데이터 수집 → 지표 계산 → 백테스트 → LLM 리포트 자동 생성 workflow를 실행합니다.

[포트폴리오 노트]
이 파일이 이 프로젝트의 핵심 기능을 보여줍니다:
  - yfinance 주가 데이터 + Google News RSS 뉴스 수집
  - LLM 기반 감성 분석 (OpenAI / Ollama)
  - rule-based 시그널 시뮬레이션 + 리스크 지표 계산
  - LLM → Markdown 리포트 자동 생성

사용법:
    python generate_report.py --ticker TSLA
    python generate_report.py --ticker TSLA --start 2020-01-01 --end 2022-12-31
    python generate_report.py --ticker TSLA --use-news-cache
    python generate_report.py --ticker TSLA --local-llm

⚠️ 면책 조항: 이 스크립트의 출력물은 투자 조언이 아닙니다.
   백테스트 결과는 과거 데이터 기반 시뮬레이션이며 미래 수익을 보장하지 않습니다.
"""

import argparse
import asyncio
import logging
import os
import sys
from datetime import datetime
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="LLM 기반 금융 데이터 리포트 자동 생성",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
예시:
  python generate_report.py --ticker TSLA
  python generate_report.py --ticker TSLA --start 2020-01-01 --end 2022-12-31
  python generate_report.py --ticker TSLA --use-news-cache
  python generate_report.py --ticker TSLA --local-llm

⚠️  이 도구의 출력물은 투자 조언이 아닙니다.
        """
    )
    parser.add_argument(
        "--ticker",
        type=str,
        default="TSLA",
        help="분석 대상 ticker 심볼 (기본값: TSLA)"
    )
    parser.add_argument(
        "--start",
        type=str,
        default="2020-01-01",
        help="백테스트 시작일 YYYY-MM-DD (기본값: 2020-01-01)"
    )
    parser.add_argument(
        "--end",
        type=str,
        default="2022-12-31",
        help="백테스트 종료일 YYYY-MM-DD (기본값: 2022-12-31)"
    )
    parser.add_argument(
        "--capital",
        type=float,
        default=10000.0,
        help="초기 자본금 USD (기본값: 10000.0)"
    )
    parser.add_argument(
        "--use-news-cache",
        action="store_true",
        help="실제 뉴스 CSV 기반 백테스트 사용 (기본값: 몬테카를로 시뮬레이션)"
    )
    parser.add_argument(
        "--news-csv",
        type=str,
        default="tesla_news_2020_2022.csv",
        help="뉴스 CSV 파일 경로 (--use-news-cache 사용 시)"
    )
    parser.add_argument(
        "--local-llm",
        action="store_true",
        help="Ollama 로컬 LLM 사용 (기본값: OpenAI API)"
    )
    parser.add_argument(
        "--output",
        type=str,
        default=None,
        help="리포트 저장 경로 (기본값: reports/generated/report_YYYYMMDD_HHMMSS.md)"
    )
    return parser.parse_args()


async def run_pipeline(args: argparse.Namespace) -> None:
    """
    메인 리포팅 파이프라인:
    1. 설정 로드
    2. 데이터 수집 (주가 + 뉴스)
    3. 백테스트 + 리스크 지표 계산
    4. LLM 기반 Markdown 리포트 자동 생성
    5. 파일 저장
    """
    from config.settings import Settings
    from backtest.engine import BacktestEngine
    from backtest.news_backtest import NewsBacktestEngine
    from report.llm_reporter import LLMReporter

    logger.info("=" * 60)
    logger.info("📊 LLM 기반 금융 데이터 리포트 생성 시작")
    logger.info(f"   Ticker: {args.ticker}")
    logger.info(f"   기간:   {args.start} ~ {args.end}")
    logger.info(f"   자본금: ${args.capital:,.0f}")
    logger.info(f"   LLM:    {'Ollama (local)' if args.local_llm else 'OpenAI API'}")
    logger.info(f"   모드:   {'실제 뉴스 CSV' if args.use_news_cache else '몬테카를로 시뮬레이션'}")
    logger.info("=" * 60)
    logger.info("⚠️  출력물은 투자 조언이 아닙니다.")
    logger.info("=" * 60)

    # 1. 설정 로드
    settings = Settings()
    if args.local_llm:
        settings.USE_LOCAL_LLM = True

    # 2. 백테스트 실행
    logger.info("\n[Step 1/3] 백테스트 시뮬레이션 실행 중...")
    bt_result = None

    if args.use_news_cache:
        # 실제 뉴스 기반 백테스트
        csv_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), args.news_csv)
        if not os.path.exists(csv_path):
            logger.error(f"뉴스 CSV 파일을 찾을 수 없습니다: {csv_path}")
            logger.info("--use-news-cache 없이 몬테카를로 모드로 전환합니다.")
            args.use_news_cache = False

    if args.use_news_cache:
        engine = NewsBacktestEngine(settings)
        bt_result = await engine.run(
            news_csv_path=csv_path,
            start_date=args.start,
            end_date=args.end,
            initial_capital=args.capital
        )
        logger.info("  → 실제 뉴스 기반 백테스트 완료")
    else:
        engine = BacktestEngine(settings)
        bt_result = engine.run(
            ticker=args.ticker,
            start_date=args.start,
            end_date=args.end,
            initial_capital=args.capital
        )
        logger.info("  → 몬테카를로 시뮬레이션 백테스트 완료")

    if not bt_result:
        logger.error("백테스트 실패: 데이터를 가져올 수 없습니다.")
        sys.exit(1)

    metrics = bt_result["metrics"]
    trades = bt_result.get("trades", [])

    # 3. 리스크 지표 출력
    logger.info("\n[Step 2/3] 리스크 지표 계산 결과")
    logger.info(f"  CAGR:         {metrics.get('cagr', 0):.2%}")
    logger.info(f"  MDD:          {metrics.get('mdd', 0):.2%}")
    logger.info(f"  Sharpe Ratio: {metrics.get('sharpe', 0):.2f}")
    logger.info(f"  총 거래:       {metrics.get('total_trades', 0)}건")
    logger.info(f"  승률:          {metrics.get('win_rate', 0):.1%}")
    if metrics.get("alpha") is not None:
        logger.info(f"  Alpha(vs S&P): {metrics['alpha']:+.2%}")

    # 4. LLM 리포트 생성
    logger.info("\n[Step 3/3] LLM 기반 Markdown 리포트 자동 생성 중...")
    reporter = LLMReporter(settings)
    config = bt_result.get("config", {
        "ticker": args.ticker,
        "start_date": args.start,
        "end_date": args.end,
        "initial_capital": args.capital,
        "take_profit_pct": settings.TAKE_PROFIT_PCT,
        "stop_loss_pct": settings.STOP_LOSS_PCT,
        "rsi_overbought": settings.RSI_OVERBOUGHT,
        "transaction_fee": settings.TRANSACTION_FEE,
    })

    report_content = await reporter.generate_report(metrics, config, trades)

    # 5. 리포트 저장
    output_dir = Path("reports") / "generated"
    output_dir.mkdir(parents=True, exist_ok=True)

    if args.output:
        output_path = Path(args.output)
    else:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = output_dir / f"report_{args.ticker}_{timestamp}.md"

    # 면책 조항 헤더 추가
    disclaimer = f"""# {args.ticker} Market Analysis Report
*Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} by generate_report.py*

> ⚠️ **면책 조항**: 이 리포트는 투자 조언이 아닙니다.
> 백테스트 결과는 과거 데이터 기반 시뮬레이션이며, 미래 수익을 보장하지 않습니다.

---

"""
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(disclaimer + report_content)

    logger.info(f"\n✅ 리포트 생성 완료: {output_path}")
    logger.info("=" * 60)
    logger.info("📌 참고: 이 리포트는 투자 판단 근거로 사용할 수 없습니다.")
    logger.info("=" * 60)


def main() -> None:
    args = parse_args()
    asyncio.run(run_pipeline(args))


if __name__ == "__main__":
    main()

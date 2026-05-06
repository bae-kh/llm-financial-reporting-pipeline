# file path: backtest/news_backtest.py
"""
실제 과거 뉴스 데이터를 활용한 백테스트 모듈입니다.

[설계 원칙]
- 몬테카를로 시뮬레이션 대신 '실제 뉴스 헤드라인'을 LLM에 분석시켜 감성 점수를 산출합니다.
- 한 번 분석한 감성 점수는 CSV 파일에 캐싱하여 재분석 비용을 0으로 만듭니다.
- LLM 백엔드(OpenAI / Ollama)는 Settings.USE_LOCAL_LLM 플래그로 자동 전환됩니다.

[면접 어필 포인트]
- "2486건의 실제 과거 뉴스를 LLM으로 분석하여 백테스트에 투입했습니다."
- "한 번 분석된 결과는 캐싱하여 반복 실행 시 API 비용이 0원입니다."
"""
import asyncio
import logging
import json
import os

import numpy as np
import pandas as pd
from datetime import datetime

from openai import AsyncOpenAI
from config.settings import Settings
from data_pipeline.price_fetcher import PriceFetcher
from backtest.metrics import RiskMetrics

logger = logging.getLogger(__name__)

# 캐시 파일 경로 (프로젝트 루트 기준)
CACHE_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                           "backtest_sentiment_cache.csv")


class NewsBacktestEngine:
    """
    실제 뉴스 헤드라인 데이터(CSV)를 LLM으로 감성 분석하고,
    그 결과를 주가 데이터와 결합하여 백테스트를 실행합니다.

    [몬테카를로 vs 실제 뉴스 백테스트]
    - 기존 BacktestEngine: 감성 점수를 정규분포 난수로 생성 (비용 0원, 비현실적)
    - NewsBacktestEngine: 실제 뉴스를 LLM으로 분석 (비용 ~$0.30, 현실적)
    - 캐싱 적용 후 재실행: 비용 0원 + 현실적 (최적 조합)
    """

    def __init__(self, settings: Settings):
        self.settings = settings
        self.price_fetcher = PriceFetcher()

        # LLM 클라이언트 설정 (OpenAI / Ollama 자동 전환)
        if self.settings.USE_LOCAL_LLM:
            self.client = AsyncOpenAI(
                base_url="http://localhost:11434/v1",
                api_key="ollama"
            )
            self.model = "llama3"
        else:
            self.client = AsyncOpenAI(api_key=self.settings.OPENAI_API_KEY)
            self.model = "gpt-4o-mini"

    async def run(self, news_csv_path: str,
                   start_date: str = "2020-01-01",
                   end_date: str = "2022-12-31",
                   initial_capital: float = 10000.0) -> dict:
        """
        실제 뉴스 기반 백테스트를 실행합니다.

        Args:
            news_csv_path: 뉴스 CSV 파일 경로 (company, date, title 컬럼).
            start_date: 백테스트 시작일.
            end_date: 백테스트 종료일.
            initial_capital: 초기 자본금 (USD).

        Returns:
            BacktestEngine.run()과 동일한 구조의 딕셔너리.
        """
        ticker = "TSLA"
        logger.info(f"[뉴스 백테스트] {ticker} {start_date} ~ {end_date} 시작")

        # 1. 주가 + 기술적 지표 데이터 로딩
        df_price = self.price_fetcher.get_daily_data(ticker, start_date, end_date)
        if df_price.empty:
            logger.error("주가 데이터를 가져올 수 없습니다.")
            return {}

        # 2. 뉴스 데이터 로딩
        df_news = pd.read_csv(news_csv_path)
        df_news['date'] = pd.to_datetime(df_news['date']).dt.strftime('%Y-%m-%d')
        logger.info(f"뉴스 데이터 {len(df_news)}건 로딩 완료.")

        # 3. 날짜별 뉴스 헤드라인 집계 (같은 날짜의 뉴스는 합침)
        news_by_date = df_news.groupby('date')['title'].apply(
            lambda titles: ' | '.join(titles)
        ).to_dict()

        # 4. 감성 분석 (캐싱 적용)
        sentiment_by_date = await self._analyze_with_cache(news_by_date)

        # 5. 벤치마크 (S&P500) 데이터
        df_bench = self.price_fetcher.get_daily_data("SPY", start_date, end_date)

        # 6. 이터레이티브 백테스트 실행
        equity_curve, trades = self._iterate(df_price, sentiment_by_date, initial_capital)

        # 7. 벤치마크 커브
        benchmark_curve = None
        if not df_bench.empty:
            bench_ratio = initial_capital / df_bench['Close'].iloc[0]
            benchmark_curve = df_bench['Close'] * bench_ratio
            benchmark_curve.index = range(len(benchmark_curve))

        # 8. 리스크 지표 계산
        equity_series = pd.Series(equity_curve)
        metrics = RiskMetrics.generate_summary(
            equity_series, trades,
            benchmark_curve if benchmark_curve is not None else None
        )

        # 뉴스 커버리지 통계
        price_dates = set(df_price.index.strftime('%Y-%m-%d') if hasattr(df_price.index, 'strftime')
                          else [str(d) for d in df_price.index])
        news_dates = set(sentiment_by_date.keys())
        coverage = len(price_dates & news_dates) / max(len(price_dates), 1) * 100

        logger.info(f"[뉴스 백테스트 완료] CAGR: {metrics['cagr']:.2%} | MDD: {metrics['mdd']:.2%} | "
                     f"Sharpe: {metrics['sharpe']:.2f} | 거래: {metrics['total_trades']}건 | "
                     f"뉴스 커버리지: {coverage:.1f}%")

        return {
            'equity_curve': equity_series,
            'trades': trades,
            'metrics': metrics,
            'benchmark_curve': benchmark_curve,
            'dates': df_price.index.tolist(),
            'news_coverage': coverage,
            'total_news': len(df_news),
            'config': {
                'ticker': ticker,
                'start_date': start_date,
                'end_date': end_date,
                'initial_capital': initial_capital,
                'take_profit_pct': self.settings.TAKE_PROFIT_PCT,
                'stop_loss_pct': self.settings.STOP_LOSS_PCT,
                'rsi_overbought': self.settings.RSI_OVERBOUGHT,
                'min_confidence': self.settings.MIN_CONFIDENCE,
                'transaction_fee': self.settings.TRANSACTION_FEE,
                'llm_model': self.model,
                'news_source': 'tesla_news_2020_2022.csv',
            }
        }

    async def _analyze_with_cache(self, news_by_date: dict) -> dict:
        """
        뉴스 감성 분석 결과를 캐싱합니다.
        이미 분석된 날짜는 건너뛰어 API 비용을 절감합니다.
        """
        # 캐시 로딩
        cached = {}
        if os.path.exists(CACHE_FILE):
            df_cache = pd.read_csv(CACHE_FILE)
            cached = dict(zip(df_cache['date'], df_cache['score']))
            logger.info(f"캐시에서 {len(cached)}건의 기존 분석 결과를 로딩했습니다.")

        # 미분석 날짜 필터링
        to_analyze = {d: text for d, text in news_by_date.items() if d not in cached}

        if to_analyze:
            logger.info(f"신규 분석 대상: {len(to_analyze)}건 (캐시 히트: {len(cached)}건)")
            new_scores = await self._batch_analyze(to_analyze)
            cached.update(new_scores)

            # 캐시 저장
            df_save = pd.DataFrame([
                {'date': d, 'score': s} for d, s in cached.items()
            ])
            df_save.to_csv(CACHE_FILE, index=False)
            logger.info(f"감성 분석 캐시 저장 완료: {CACHE_FILE}")
        else:
            logger.info("모든 날짜가 캐시에 존재합니다. API 호출 없이 진행합니다.")

        return cached

    async def _batch_analyze(self, news_by_date: dict) -> dict:
        """
        날짜별 뉴스를 LLM으로 배치 분석합니다.
        동시성 제한(세마포어)을 적용하여 API 과부하를 방지합니다.
        """
        semaphore = asyncio.Semaphore(5)  # 동시 5건 제한
        results = {}
        total = len(news_by_date)

        async def analyze_one(date_str: str, text: str, idx: int):
            async with semaphore:
                score = await self._get_sentiment_score(text)
                results[date_str] = score
                if (idx + 1) % 50 == 0 or (idx + 1) == total:
                    logger.info(f"감성 분석 진행률: {idx+1}/{total} ({(idx+1)/total*100:.0f}%)")

        tasks = [
            analyze_one(date, text, i)
            for i, (date, text) in enumerate(news_by_date.items())
        ]
        await asyncio.gather(*tasks)

        return results

    async def _get_sentiment_score(self, news_text: str) -> float:
        """
        단일 뉴스 텍스트에 대한 감성 점수를 LLM에게 요청합니다.
        """
        # 뉴스 텍스트가 너무 길면 잘라냄 (토큰 절약)
        truncated = news_text[:1500]

        try:
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": (
                        "You are a financial sentiment analyzer. "
                        "Analyze the following Tesla news headlines and return ONLY a JSON object. "
                        "Format: {\"score\": <float between -1.0 and 1.0>} "
                        "where -1.0 is extremely bearish and 1.0 is extremely bullish. "
                        "Return ONLY the JSON, no other text."
                    )},
                    {"role": "user", "content": truncated}
                ],
                temperature=0.1,
                max_tokens=50,
                timeout=30
            )

            text = response.choices[0].message.content.strip()
            parsed = json.loads(text)
            score = float(parsed.get('score', 0.0))
            return max(-1.0, min(1.0, score))

        except Exception:
            return 0.0  # 분석 실패 시 중립값

    def _iterate(self, df: pd.DataFrame, sentiment_by_date: dict,
                  initial_capital: float) -> tuple[list[float], list[dict]]:
        """
        실제 뉴스 감성 점수를 사용한 이터레이티브 백테스트입니다.
        뉴스가 없는 날에는 중립 점수(0.0)를 사용합니다.
        """
        cash = initial_capital
        holdings = 0
        avg_price = 0.0
        equity_curve = []
        trades = []

        for i in range(len(df)):
            current_row = df.iloc[i]
            price = float(current_row['Close'])
            rsi = float(current_row['RSI_14'])
            macd_diff = float(current_row['MACD_diff'])

            # 날짜 키로 실제 감성 점수 조회
            date_str = str(df.index[i])[:10]
            score = sentiment_by_date.get(date_str, 0.0)
            confidence = int(min(abs(score) * 120, 100))

            roi = 0.0
            if holdings > 0 and avg_price > 0:
                roi = (price - avg_price) / avg_price * 100

            # 매도 우선 검사
            if holdings > 0:
                sell_reason = self._evaluate_sell(roi, score)
                if sell_reason:
                    sell_value = holdings * price * (1 - self.settings.TRANSACTION_FEE)
                    pnl = sell_value - (holdings * avg_price)
                    cash += sell_value
                    trades.append({
                        'day': i, 'date': date_str, 'action': 'SELL',
                        'price': price, 'quantity': holdings,
                        'pnl': pnl, 'roi': roi, 'reason': sell_reason,
                        'sentiment_score': score
                    })
                    holdings = 0
                    avg_price = 0.0
                    equity_curve.append(cash)
                    continue

            # 매수 다중 게이트
            if holdings == 0:
                should_buy, buy_msg = self._evaluate_buy(score, confidence, rsi, macd_diff)
                if should_buy:
                    invest_amount = cash * self.settings.ALLOCATION_RATIO
                    buy_qty = int(invest_amount / price)
                    if buy_qty > 0:
                        cost = buy_qty * price * (1 + self.settings.TRANSACTION_FEE)
                        if cost <= cash:
                            cash -= cost
                            avg_price = price
                            holdings = buy_qty
                            trades.append({
                                'day': i, 'date': date_str, 'action': 'BUY',
                                'price': price, 'quantity': buy_qty,
                                'pnl': 0, 'roi': 0, 'reason': buy_msg,
                                'sentiment_score': score
                            })

            equity_curve.append(cash + holdings * price)

        return equity_curve, trades

    def _evaluate_sell(self, roi: float, score: float) -> str | None:
        if roi >= self.settings.TAKE_PROFIT_PCT:
            return f"익절 (ROI {roi:.1f}%)"
        if roi <= self.settings.STOP_LOSS_PCT:
            return f"손절 (ROI {roi:.1f}%)"
        if score < 0:
            return f"악재 (score {score:.2f})"
        return None

    def _evaluate_buy(self, score: float, confidence: int,
                       rsi: float, macd_diff: float) -> tuple[bool, str]:
        if score <= 0 or confidence < self.settings.MIN_CONFIDENCE:
            return False, "감성 점수/확신도 미달"
        if rsi >= self.settings.RSI_OVERBOUGHT:
            return False, f"RSI 과매수 ({rsi:.1f})"
        if macd_diff <= 0:
            return False, f"MACD 하락 ({macd_diff:.4f})"
        return True, "전 조건 통과"

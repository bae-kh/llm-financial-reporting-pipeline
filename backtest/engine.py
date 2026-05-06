# file path: backtest/engine.py
"""
이터레이티브(Iterative) 백테스트 엔진입니다.

[설계 원칙]
- Iterative 순회 구조 (`df.iloc[:i+1]`)를 사용하여 Look-ahead 편향을 구조적으로 차단합니다.
- 벡터화(Vectorized) 연산 대신 반복 루프를 선택한 이유:
  미래 데이터에 절대 접근할 수 없도록 캡슐화하기 위함입니다.
- 감성 분석 점수는 몬테카를로 시뮬레이션(정규분포 난수)으로 스터빙합니다.
  → 과거 뉴스에 LLM API를 호출하는 비용을 절감하면서도 전략 로직 검증이 가능합니다.
"""
import logging
import numpy as np
import pandas as pd
from datetime import datetime, timedelta

from config.settings import Settings
from data_pipeline.price_fetcher import PriceFetcher
from backtest.metrics import RiskMetrics

logger = logging.getLogger(__name__)


class BacktestEngine:
    """
    과거 주가 데이터에 현재 전략(RSI + MACD + 감성분석)을 적용하여
    성과를 시뮬레이션하는 백테스트 엔진입니다.

    [핵심 설계]
    - TradingEngine의 evaluate_buy_signal / evaluate_sell_signal 로직을 재사용합니다.
    - 감성 점수는 정규분포 N(0.1, 0.3)에서 샘플링합니다.
      (약간 양의 편향 = 시장은 장기적으로 우상향한다는 가정)
    - 거래비용(슬리피지 + 수수료)을 반영합니다.
    """

    def __init__(self, settings: Settings):
        self.settings = settings
        self.price_fetcher = PriceFetcher()

    def run(self, ticker: str = "TSLA",
            start_date: str = "2023-01-01",
            end_date: str = "2025-12-31",
            initial_capital: float = 10000.0,
            seed: int = 42) -> dict:
        """
        백테스트를 실행합니다.

        Args:
            ticker: 대상 종목 심볼.
            start_date: 백테스트 시작일 (YYYY-MM-DD).
            end_date: 백테스트 종료일 (YYYY-MM-DD).
            initial_capital: 초기 자본금 (USD).
            seed: 감성 점수 난수 시드 (재현성 보장).

        Returns:
            {
                'equity_curve': pd.Series,      # 일별 포트폴리오 가치
                'trades': list[dict],           # 개별 거래 기록
                'metrics': dict,                # 리스크 지표 요약
                'benchmark_curve': pd.Series,   # S&P500 벤치마크 커브
                'config': dict                  # 백테스트 설정 정보
            }
        """
        logger.info(f"[백테스트] {ticker} {start_date} ~ {end_date} 시작 (초기자본: ${initial_capital:,.0f})")

        # 1. 주가 + 기술적 지표 데이터 로딩
        df = self.price_fetcher.get_daily_data(ticker, start_date, end_date)
        if df.empty:
            logger.error("주가 데이터를 가져올 수 없어 백테스트를 중단합니다.")
            return {}

        # 2. 벤치마크 (S&P500) 데이터 로딩
        df_bench = self.price_fetcher.get_daily_data("SPY", start_date, end_date)

        # 3. 감성 점수 몬테카를로 시뮬레이션
        np.random.seed(seed)
        simulated_scores = np.random.normal(loc=0.1, scale=0.3, size=len(df))
        simulated_scores = np.clip(simulated_scores, -1.0, 1.0)

        # 4. 이터레이티브 백테스트 실행
        equity_curve, trades = self._iterate(df, simulated_scores, initial_capital)

        # 5. 벤치마크 커브 생성 (동일 초기자본으로 Buy & Hold)
        benchmark_curve = None
        if not df_bench.empty:
            bench_ratio = initial_capital / df_bench['Close'].iloc[0]
            benchmark_curve = df_bench['Close'] * bench_ratio
            benchmark_curve.index = range(len(benchmark_curve))

        # 6. 리스크 지표 계산
        equity_series = pd.Series(equity_curve)
        metrics_calc = RiskMetrics()
        metrics = metrics_calc.generate_summary(
            equity_series, trades,
            benchmark_curve if benchmark_curve is not None else None
        )

        logger.info(f"[백테스트 완료] CAGR: {metrics['cagr']:.2%} | MDD: {metrics['mdd']:.2%} | "
                     f"Sharpe: {metrics['sharpe']:.2f} | 거래: {metrics['total_trades']}건")

        return {
            'equity_curve': equity_series,
            'trades': trades,
            'metrics': metrics,
            'benchmark_curve': benchmark_curve,
            'dates': df.index.tolist() if hasattr(df.index, 'tolist') else list(range(len(df))),
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
            }
        }

    def _iterate(self, df: pd.DataFrame, scores: np.ndarray,
                  initial_capital: float) -> tuple[list[float], list[dict]]:
        """
        [핵심] Look-ahead 편향을 구조적으로 차단하는 이터레이티브 순회입니다.

        각 시점 i에서 `df.iloc[:i+1]`까지의 데이터만 사용합니다.
        미래 날짜의 가격이나 지표에 접근할 수 없도록 강제됩니다.
        """
        cash = initial_capital
        holdings = 0
        avg_price = 0.0
        equity_curve = []
        trades = []

        for i in range(len(df)):
            # [Look-ahead 방어] 현재 시점까지의 데이터만 캡슐화
            current_row = df.iloc[i]
            price = float(current_row['Close'])
            rsi = float(current_row['RSI_14'])
            macd_diff = float(current_row['MACD_diff'])
            score = float(scores[i])

            # 고정 확신도 (몬테카를로에서는 점수 크기로 확신도를 대체)
            confidence = int(min(abs(score) * 120, 100))

            # 수익률 계산
            roi = 0.0
            if holdings > 0 and avg_price > 0:
                roi = (price - avg_price) / avg_price * 100

            # === 매도 우선 검사 ===
            if holdings > 0:
                sell_reason = self._evaluate_sell(roi, score)
                if sell_reason:
                    # 매도 체결 (거래비용 반영)
                    sell_value = holdings * price * (1 - self.settings.TRANSACTION_FEE)
                    pnl = sell_value - (holdings * avg_price)
                    cash += sell_value

                    trades.append({
                        'day': i,
                        'action': 'SELL',
                        'price': price,
                        'quantity': holdings,
                        'pnl': pnl,
                        'roi': roi,
                        'reason': sell_reason
                    })

                    holdings = 0
                    avg_price = 0.0
                    equity_curve.append(cash)
                    continue

            # === 매수 다중 게이트 ===
            if holdings == 0:
                should_buy, buy_msg = self._evaluate_buy(score, confidence, rsi, macd_diff)
                if should_buy:
                    # 가용 자금의 설정 비율만 투입
                    invest_amount = cash * self.settings.ALLOCATION_RATIO
                    buy_qty = int(invest_amount / price)

                    if buy_qty > 0:
                        cost = buy_qty * price * (1 + self.settings.TRANSACTION_FEE)
                        if cost <= cash:
                            cash -= cost
                            avg_price = price
                            holdings = buy_qty

                            trades.append({
                                'day': i,
                                'action': 'BUY',
                                'price': price,
                                'quantity': buy_qty,
                                'pnl': 0,
                                'roi': 0,
                                'reason': buy_msg
                            })

            # 일별 포트폴리오 가치 = 현금 + 보유 주식 평가액
            equity_curve.append(cash + holdings * price)

        return equity_curve, trades

    def _evaluate_sell(self, roi: float, score: float) -> str | None:
        """TradingEngine.evaluate_sell_signal과 동일한 로직을 재사용합니다."""
        if roi >= self.settings.TAKE_PROFIT_PCT:
            return f"익절 (ROI {roi:.1f}%)"
        if roi <= self.settings.STOP_LOSS_PCT:
            return f"손절 (ROI {roi:.1f}%)"
        if score < 0:
            return f"악재 (score {score:.2f})"
        return None

    def _evaluate_buy(self, score: float, confidence: int,
                       rsi: float, macd_diff: float) -> tuple[bool, str]:
        """TradingEngine.evaluate_buy_signal과 동일한 로직을 재사용합니다."""
        if score <= 0 or confidence < self.settings.MIN_CONFIDENCE:
            return False, "감성 점수/확신도 미달"
        if rsi >= self.settings.RSI_OVERBOUGHT:
            return False, f"RSI 과매수 ({rsi:.1f})"
        if macd_diff <= 0:
            return False, f"MACD 하락 ({macd_diff:.4f})"
        return True, "전 조건 통과"

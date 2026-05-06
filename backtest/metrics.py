# file path: backtest/metrics.py
"""
백테스트 성과 및 리스크 지표 계산 모듈입니다.

[제공 지표]
- CAGR (연평균 복리 수익률)
- MDD (최대 낙폭)
- Sharpe Ratio (위험 대비 수익률)
- 승률 (Win Rate)
- 손익비 (Profit Factor)
- 벤치마크 대비 초과수익 (Alpha)
"""
import numpy as np
import pandas as pd
import logging

logger = logging.getLogger(__name__)


class RiskMetrics:
    """
    포트폴리오 에쿼티 커브(equity curve)로부터 핵심 리스크/성과 지표를 계산합니다.

    [설계 원칙]
    - 모든 메서드는 순수 함수(Pure Function)로, 입력 DataFrame만으로 결과를 반환합니다.
    - 단위 테스트에서 독립적으로 검증할 수 있도록 외부 의존성이 없습니다.
    """

    @staticmethod
    def calculate_cagr(equity_series: pd.Series, trading_days_per_year: int = 252) -> float:
        """
        연평균 복리 수익률(CAGR)을 계산합니다.

        Args:
            equity_series: 일별 포트폴리오 가치 시리즈.
            trading_days_per_year: 연간 거래일 수 (기본 252일).

        Returns:
            CAGR (소수점, 예: 0.08 = 8%).
        """
        if len(equity_series) < 2 or equity_series.iloc[0] <= 0:
            return 0.0

        total_return = equity_series.iloc[-1] / equity_series.iloc[0]
        n_years = len(equity_series) / trading_days_per_year

        if n_years <= 0 or total_return <= 0:
            return 0.0

        return float(total_return ** (1 / n_years) - 1)

    @staticmethod
    def calculate_mdd(equity_series: pd.Series) -> float:
        """
        최대 낙폭(Maximum Drawdown)을 계산합니다.
        포트폴리오의 고점 대비 최대 하락 폭을 나타냅니다.

        Args:
            equity_series: 일별 포트폴리오 가치 시리즈.

        Returns:
            MDD (음수 소수점, 예: -0.125 = -12.5%).
        """
        if len(equity_series) < 2:
            return 0.0

        cumulative_max = equity_series.cummax()
        drawdown = (equity_series - cumulative_max) / cumulative_max
        return float(drawdown.min())

    @staticmethod
    def calculate_sharpe_ratio(equity_series: pd.Series, risk_free_rate: float = 0.04,
                                trading_days_per_year: int = 252) -> float:
        """
        샤프 비율(Sharpe Ratio)을 계산합니다.
        수익률의 표준편차 대비 초과 수익률을 측정합니다.

        Args:
            equity_series: 일별 포트폴리오 가치 시리즈.
            risk_free_rate: 무위험 수익률 (연율, 기본 4%).
            trading_days_per_year: 연간 거래일 수.

        Returns:
            Sharpe Ratio.
        """
        if len(equity_series) < 2:
            return 0.0

        daily_returns = equity_series.pct_change().dropna()
        if daily_returns.std() == 0:
            return 0.0

        daily_rf = risk_free_rate / trading_days_per_year
        excess_returns = daily_returns - daily_rf

        return float(excess_returns.mean() / excess_returns.std() * np.sqrt(trading_days_per_year))

    @staticmethod
    def calculate_win_rate(trades: list[dict]) -> float:
        """
        승률(Win Rate)을 계산합니다.

        Args:
            trades: 거래 기록 리스트. 각 dict에 'pnl' (손익) 키 필요.

        Returns:
            승률 (0.0 ~ 1.0).
        """
        if not trades:
            return 0.0

        wins = sum(1 for t in trades if t.get('pnl', 0) > 0)
        return wins / len(trades)

    @staticmethod
    def calculate_profit_factor(trades: list[dict]) -> float:
        """
        손익비(Profit Factor)를 계산합니다.
        총 이익 / 총 손실의 비율입니다.

        Args:
            trades: 거래 기록 리스트. 각 dict에 'pnl' 키 필요.

        Returns:
            Profit Factor. 손실이 없으면 float('inf').
        """
        if not trades:
            return 0.0

        total_profit = sum(t['pnl'] for t in trades if t.get('pnl', 0) > 0)
        total_loss = abs(sum(t['pnl'] for t in trades if t.get('pnl', 0) < 0))

        if total_loss == 0:
            return float('inf') if total_profit > 0 else 0.0

        return total_profit / total_loss

    @staticmethod
    def calculate_benchmark_alpha(equity_series: pd.Series, benchmark_series: pd.Series) -> float:
        """
        벤치마크 대비 초과 수익률(Alpha)을 계산합니다.

        Args:
            equity_series: 전략 포트폴리오의 일별 가치 시리즈.
            benchmark_series: 벤치마크(예: S&P500)의 일별 가격 시리즈.

        Returns:
            Alpha (소수점). 양수면 벤치마크 대비 초과 수익.
        """
        if len(equity_series) < 2 or len(benchmark_series) < 2:
            return 0.0

        strategy_return = equity_series.iloc[-1] / equity_series.iloc[0] - 1
        benchmark_return = benchmark_series.iloc[-1] / benchmark_series.iloc[0] - 1

        return float(strategy_return - benchmark_return)

    @staticmethod
    def generate_summary(equity_series: pd.Series, trades: list[dict],
                          benchmark_series: pd.Series = None) -> dict:
        """
        모든 지표를 한 번에 계산하여 딕셔너리로 반환합니다.

        Returns:
            {'cagr': ..., 'mdd': ..., 'sharpe': ..., 'win_rate': ...,
             'profit_factor': ..., 'total_trades': ..., 'alpha': ...}
        """
        metrics = RiskMetrics()

        summary = {
            'cagr': metrics.calculate_cagr(equity_series),
            'mdd': metrics.calculate_mdd(equity_series),
            'sharpe': metrics.calculate_sharpe_ratio(equity_series),
            'win_rate': metrics.calculate_win_rate(trades),
            'profit_factor': metrics.calculate_profit_factor(trades),
            'total_trades': len(trades),
            'total_return': float(equity_series.iloc[-1] / equity_series.iloc[0] - 1) if len(equity_series) >= 2 else 0.0,
        }

        if benchmark_series is not None:
            summary['alpha'] = metrics.calculate_benchmark_alpha(equity_series, benchmark_series)
        else:
            summary['alpha'] = None

        return summary

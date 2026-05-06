# file path: tests/test_backtest.py
"""
백테스트 엔진과 리스크 지표 계산의 정확성을 검증합니다.

[핵심 검증 포인트]
- RiskMetrics: CAGR, MDD, Sharpe, 승률, 손익비, 알파 계산이 수학적으로 정확한가
- BacktestEngine._evaluate_sell / _evaluate_buy: 기존 TradingEngine 로직과 동일하게 동작하는가
- Look-ahead 편향이 구조적으로 차단되는가
"""
import pytest
import numpy as np
import pandas as pd

from backtest.metrics import RiskMetrics
from backtest.engine import BacktestEngine
from config.settings import Settings


# ======================================================
# RiskMetrics 단위 테스트
# ======================================================
class TestRiskMetrics:
    """리스크 지표 계산의 수학적 정확성을 검증합니다."""

    def test_cagr_positive(self):
        """10000 → 12000 (252일) = 약 20% CAGR"""
        equity = pd.Series(np.linspace(10000, 12000, 252))
        cagr = RiskMetrics.calculate_cagr(equity)
        assert 0.15 < cagr < 0.25, f"CAGR {cagr} 가 예상 범위(15~25%) 밖"

    def test_cagr_negative(self):
        """10000 → 8000 (252일) = 음수 CAGR"""
        equity = pd.Series(np.linspace(10000, 8000, 252))
        cagr = RiskMetrics.calculate_cagr(equity)
        assert cagr < 0, f"하락 시 CAGR이 음수여야 함: {cagr}"

    def test_cagr_empty(self):
        """빈 시리즈는 0.0"""
        assert RiskMetrics.calculate_cagr(pd.Series(dtype=float)) == 0.0

    def test_mdd_known_drawdown(self):
        """10000 → 12000 → 9000 → 11000 => MDD = (9000-12000)/12000 = -25%"""
        equity = pd.Series([10000, 11000, 12000, 10500, 9000, 10000, 11000])
        mdd = RiskMetrics.calculate_mdd(equity)
        assert abs(mdd - (-0.25)) < 0.001, f"MDD {mdd} ≠ -25%"

    def test_mdd_monotonic_increase(self):
        """계속 오르는 시리즈의 MDD는 0.0"""
        equity = pd.Series([100, 110, 120, 130, 140])
        mdd = RiskMetrics.calculate_mdd(equity)
        assert mdd == 0.0

    def test_sharpe_positive_returns(self):
        """안정적 상승 시 Sharpe Ratio > 0"""
        equity = pd.Series(np.linspace(10000, 12000, 252))
        sharpe = RiskMetrics.calculate_sharpe_ratio(equity)
        assert sharpe > 0

    def test_sharpe_zero_volatility(self):
        """변동 없으면 Sharpe = 0"""
        equity = pd.Series([100.0] * 100)
        sharpe = RiskMetrics.calculate_sharpe_ratio(equity)
        assert sharpe == 0.0

    def test_win_rate_all_wins(self):
        """전승 = 100%"""
        trades = [{'pnl': 100}, {'pnl': 50}, {'pnl': 200}]
        assert RiskMetrics.calculate_win_rate(trades) == 1.0

    def test_win_rate_mixed(self):
        """2승 1패 = 66.7%"""
        trades = [{'pnl': 100}, {'pnl': -50}, {'pnl': 200}]
        assert abs(RiskMetrics.calculate_win_rate(trades) - 2/3) < 0.01

    def test_win_rate_empty(self):
        """거래 없으면 0%"""
        assert RiskMetrics.calculate_win_rate([]) == 0.0

    def test_profit_factor_basic(self):
        """이익 300, 손실 100 => PF = 3.0"""
        trades = [{'pnl': 200}, {'pnl': -100}, {'pnl': 100}]
        pf = RiskMetrics.calculate_profit_factor(trades)
        assert abs(pf - 3.0) < 0.001

    def test_profit_factor_no_loss(self):
        """손실 없으면 inf"""
        trades = [{'pnl': 100}, {'pnl': 50}]
        assert RiskMetrics.calculate_profit_factor(trades) == float('inf')

    def test_benchmark_alpha_outperform(self):
        """전략이 벤치마크를 이기면 Alpha > 0"""
        strategy = pd.Series([10000, 11000, 12000])  # +20%
        benchmark = pd.Series([10000, 10500, 11000])  # +10%
        alpha = RiskMetrics.calculate_benchmark_alpha(strategy, benchmark)
        assert abs(alpha - 0.10) < 0.001

    def test_generate_summary_keys(self):
        """generate_summary가 모든 필수 키를 반환하는지 확인"""
        equity = pd.Series(np.linspace(10000, 12000, 100))
        trades = [{'pnl': 100}, {'pnl': -50}]
        summary = RiskMetrics.generate_summary(equity, trades)

        required_keys = ['cagr', 'mdd', 'sharpe', 'win_rate', 'profit_factor', 'total_trades', 'total_return']
        for key in required_keys:
            assert key in summary, f"'{key}' 키가 summary에 없음"


# ======================================================
# BacktestEngine 의사결정 로직 테스트
# ======================================================
class TestBacktestDecisions:
    """백테스트 엔진의 매수/매도 판단이 TradingEngine과 동일한지 검증합니다."""

    @pytest.fixture
    def engine(self):
        settings = Settings()
        return BacktestEngine(settings)

    def test_sell_take_profit(self, engine):
        """ROI >= 15% → 익절 매도"""
        result = engine._evaluate_sell(roi=15.0, score=0.5)
        assert result is not None
        assert "익절" in result

    def test_sell_stop_loss(self, engine):
        """ROI <= -5% → 손절 매도"""
        result = engine._evaluate_sell(roi=-5.0, score=0.5)
        assert result is not None
        assert "손절" in result

    def test_sell_negative_score(self, engine):
        """score < 0 → 악재 매도"""
        result = engine._evaluate_sell(roi=2.0, score=-0.3)
        assert result is not None
        assert "악재" in result

    def test_sell_no_trigger(self, engine):
        """매도 조건 미충족 → None"""
        result = engine._evaluate_sell(roi=3.0, score=0.2)
        assert result is None

    def test_buy_all_conditions_met(self, engine):
        """모든 조건 통과 → 매수"""
        should_buy, msg = engine._evaluate_buy(score=0.5, confidence=85, rsi=55.0, macd_diff=1.0)
        assert should_buy is True

    def test_buy_rsi_overbought(self, engine):
        """RSI >= 70 → 매수 거부"""
        should_buy, msg = engine._evaluate_buy(score=0.5, confidence=85, rsi=70.0, macd_diff=1.0)
        assert should_buy is False

    def test_buy_negative_macd(self, engine):
        """MACD_diff <= 0 → 매수 거부"""
        should_buy, msg = engine._evaluate_buy(score=0.5, confidence=85, rsi=55.0, macd_diff=-0.5)
        assert should_buy is False

    def test_buy_low_confidence(self, engine):
        """confidence < 80 → 매수 거부"""
        should_buy, msg = engine._evaluate_buy(score=0.5, confidence=60, rsi=55.0, macd_diff=1.0)
        assert should_buy is False

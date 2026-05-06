# file path: tests/test_decision_tree.py
"""
TradingEngine의 의사결정 로직(익절/손절/매수 게이트)을 경계값 중심으로 검증합니다.

[핵심 검증 포인트]
- ROI가 정확히 15.0%일 때 익절 트리거가 발동하는가
- ROI가 정확히 -5.0%일 때 손절 트리거가 발동하는가
- RSI=70 경계에서 매수가 보류되는가
- 다중 게이트(score + confidence + RSI + MACD) 모두 통과해야 매수가 발동하는가
"""
import pytest
from auto_trade import TradingEngine


class TestEvaluateSellSignal:
    """매도 시그널 평가 로직을 테스트합니다."""

    @pytest.fixture
    def engine(self, mock_settings):
        """테스트용 TradingEngine 인스턴스를 생성합니다."""
        return TradingEngine(mock_settings)

    def test_take_profit_at_boundary(self, engine):
        """ROI = 15.0% (정확히 익절 경계) → 매도 트리거가 발동해야 합니다."""
        result = engine.evaluate_sell_signal(roi=15.0, score=0.5)
        assert result is not None
        assert "익절" in result

    def test_take_profit_below_boundary(self, engine):
        """ROI = 14.9% → 익절 트리거가 발동하지 않아야 합니다."""
        result = engine.evaluate_sell_signal(roi=14.9, score=0.5)
        assert result is None

    def test_stop_loss_at_boundary(self, engine):
        """ROI = -5.0% (정확히 손절 경계) → 매도 트리거가 발동해야 합니다."""
        result = engine.evaluate_sell_signal(roi=-5.0, score=0.5)
        assert result is not None
        assert "손절" in result

    def test_stop_loss_above_boundary(self, engine):
        """ROI = -4.9% → 손절 트리거가 발동하지 않아야 합니다."""
        result = engine.evaluate_sell_signal(roi=-4.9, score=0.5)
        assert result is None

    def test_negative_score_triggers_sell(self, engine):
        """감성 점수가 음수이면 악재 매도 트리거가 발동해야 합니다."""
        result = engine.evaluate_sell_signal(roi=5.0, score=-0.3)
        assert result is not None
        assert "악재" in result

    def test_positive_score_no_sell(self, engine):
        """감성 점수가 양수이고 ROI가 정상 범위이면 매도하지 않아야 합니다."""
        result = engine.evaluate_sell_signal(roi=5.0, score=0.5)
        assert result is None

    def test_sell_priority_take_profit_over_negative_score(self, engine):
        """ROI가 익절 기준을 초과하면 점수에 관계없이 익절이 우선합니다."""
        result = engine.evaluate_sell_signal(roi=20.0, score=-0.5)
        assert "익절" in result


class TestEvaluateBuySignal:
    """매수 시그널의 다중 게이트 로직을 테스트합니다."""

    @pytest.fixture
    def engine(self, mock_settings):
        return TradingEngine(mock_settings)

    def test_all_conditions_met(self, engine):
        """score>0, conf>=80, RSI<70, MACD>0 → 매수가 발동해야 합니다."""
        should_buy, msg = engine.evaluate_buy_signal(
            score=0.5, confidence=85, rsi=55.0, macd_diff=0.01
        )
        assert should_buy is True

    def test_rsi_at_overbought_boundary(self, engine):
        """RSI = 70 (정확히 과매수 경계) → 매수가 보류되어야 합니다."""
        should_buy, msg = engine.evaluate_buy_signal(
            score=0.5, confidence=85, rsi=70.0, macd_diff=0.01
        )
        assert should_buy is False
        assert "과열" in msg or "RSI" in msg

    def test_rsi_just_below_boundary(self, engine):
        """RSI = 69.9 → 매수가 발동해야 합니다 (다른 조건 충족 시)."""
        should_buy, msg = engine.evaluate_buy_signal(
            score=0.5, confidence=85, rsi=69.9, macd_diff=0.01
        )
        assert should_buy is True

    def test_confidence_below_threshold(self, engine):
        """확신도 = 79 (80 미만) → 매수가 보류되어야 합니다."""
        should_buy, msg = engine.evaluate_buy_signal(
            score=0.5, confidence=79, rsi=55.0, macd_diff=0.01
        )
        assert should_buy is False
        assert "미달" in msg or "확신" in msg

    def test_negative_score_no_buy(self, engine):
        """감성 점수가 음수이면 매수하지 않아야 합니다."""
        should_buy, msg = engine.evaluate_buy_signal(
            score=-0.3, confidence=90, rsi=55.0, macd_diff=0.01
        )
        assert should_buy is False

    def test_zero_score_no_buy(self, engine):
        """감성 점수가 정확히 0이면 매수하지 않아야 합니다."""
        should_buy, msg = engine.evaluate_buy_signal(
            score=0.0, confidence=90, rsi=55.0, macd_diff=0.01
        )
        assert should_buy is False

    def test_negative_macd_no_buy(self, engine):
        """MACD_diff <= 0이면 매수가 보류되어야 합니다."""
        should_buy, msg = engine.evaluate_buy_signal(
            score=0.5, confidence=85, rsi=55.0, macd_diff=-0.01
        )
        assert should_buy is False
        assert "MACD" in msg

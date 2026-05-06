# file path: tests/test_analyzer.py
"""
NLP 감성 분석 엔진(SentimentAnalyzer)의 방어 로직을 검증합니다.

[핵심 검증 포인트]
- LLM이 정상 JSON을 반환할 때 올바르게 파싱되는가
- LLM이 비정상 텍스트를 뱉을 때 시스템이 크래시 없이 중립값을 반환하는가
- Pydantic 범위 검증이 score 2.5 같은 이상값을 차단하는가
- OpenAI 타임아웃 시 파이프라인이 멈추지 않는가
"""
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from pydantic import ValidationError

from nlp_engine.analyzer import SentimentAnalyzer, SentimentResult


class TestSentimentResult:
    """Pydantic 모델의 검증 로직을 단위 테스트합니다."""

    def test_valid_result(self):
        """정상 범위 값이 올바르게 파싱되는지 검증합니다."""
        result = SentimentResult(
            reasoning="Positive earnings",
            sentiment_score=0.7,
            confidence=85
        )
        assert result.sentiment_score == 0.7
        assert result.confidence == 85
        assert result.reasoning == "Positive earnings"

    def test_score_out_of_upper_bound(self):
        """sentiment_score가 1.0을 초과하면 ValidationError가 발생해야 합니다."""
        with pytest.raises(ValidationError):
            SentimentResult(reasoning="Too bullish", sentiment_score=2.5, confidence=90)

    def test_score_out_of_lower_bound(self):
        """sentiment_score가 -1.0 미만이면 ValidationError가 발생해야 합니다."""
        with pytest.raises(ValidationError):
            SentimentResult(reasoning="Too bearish", sentiment_score=-1.5, confidence=90)

    def test_confidence_out_of_range(self):
        """confidence가 100을 초과하면 ValidationError가 발생해야 합니다."""
        with pytest.raises(ValidationError):
            SentimentResult(reasoning="Overconfident", sentiment_score=0.5, confidence=150)

    def test_boundary_values(self):
        """경계값(-1.0, 1.0, 0, 100)이 허용되는지 검증합니다."""
        low = SentimentResult(reasoning="Worst case", sentiment_score=-1.0, confidence=0)
        high = SentimentResult(reasoning="Best case", sentiment_score=1.0, confidence=100)
        assert low.sentiment_score == -1.0
        assert high.confidence == 100


class TestSentimentAnalyzer:
    """SentimentAnalyzer의 API 호출 및 에러 핸들링을 검증합니다."""

    @pytest.mark.asyncio
    async def test_successful_analysis(self, mock_settings, valid_llm_response):
        """정상 JSON 응답이 올바르게 파싱되어 (reasoning, score, confidence) 튜플로 반환되는지 검증합니다."""
        analyzer = SentimentAnalyzer(mock_settings)

        # OpenAI 클라이언트 모킹
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = valid_llm_response
        analyzer.client = AsyncMock()
        analyzer.client.chat.completions.create = AsyncMock(return_value=mock_response)

        reasoning, score, conf = await analyzer.analyze_sentiment("Test news text")

        assert reasoning == "Positive earnings beat"
        assert score == 0.7
        assert conf == 85

    @pytest.mark.asyncio
    async def test_invalid_json_returns_neutral(self, mock_settings, invalid_llm_response_text):
        """LLM이 JSON이 아닌 텍스트를 반환하면 중립값(0.0)을 반환해야 합니다."""
        analyzer = SentimentAnalyzer(mock_settings)

        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = invalid_llm_response_text
        analyzer.client = AsyncMock()
        analyzer.client.chat.completions.create = AsyncMock(return_value=mock_response)

        reasoning, score, conf = await analyzer.analyze_sentiment("Test news text")

        assert score == 0.0
        assert conf == 0
        assert "error" in reasoning

    @pytest.mark.asyncio
    async def test_out_of_range_returns_neutral(self, mock_settings, invalid_llm_response_out_of_range):
        """score가 범위(-1.0~1.0)를 벗어나면 Pydantic 검증 실패 → 중립값 반환."""
        analyzer = SentimentAnalyzer(mock_settings)

        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = invalid_llm_response_out_of_range
        analyzer.client = AsyncMock()
        analyzer.client.chat.completions.create = AsyncMock(return_value=mock_response)

        reasoning, score, conf = await analyzer.analyze_sentiment("Test news text")

        assert score == 0.0
        assert conf == 0
        assert "error" in reasoning

    @pytest.mark.asyncio
    async def test_timeout_returns_neutral(self, mock_settings):
        """OpenAI API 타임아웃 시 시스템이 멈추지 않고 중립값을 반환해야 합니다."""
        from openai import OpenAIError

        analyzer = SentimentAnalyzer(mock_settings)
        analyzer.client = AsyncMock()
        analyzer.client.chat.completions.create = AsyncMock(
            side_effect=OpenAIError("Connection timeout")
        )

        reasoning, score, conf = await analyzer.analyze_sentiment("Test news text")

        assert score == 0.0
        assert conf == 0
        assert "error" in reasoning

    @pytest.mark.asyncio
    async def test_empty_input(self, mock_settings):
        """빈 문자열이 입력되어도 크래시 없이 처리되어야 합니다."""
        analyzer = SentimentAnalyzer(mock_settings)

        # 빈 입력에 대해 중립 응답을 모킹
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = '{"reasoning": "No content", "sentiment_score": 0.0, "confidence": 0}'
        analyzer.client = AsyncMock()
        analyzer.client.chat.completions.create = AsyncMock(return_value=mock_response)

        reasoning, score, conf = await analyzer.analyze_sentiment("")

        assert score == 0.0
        assert conf == 0

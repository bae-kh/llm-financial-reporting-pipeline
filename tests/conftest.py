# file path: tests/conftest.py
"""
테스트 공용 Fixture 모듈입니다.
모든 테스트에서 재사용되는 모의 객체(Mock)와 설정을 정의합니다.
"""
import pytest
from unittest.mock import MagicMock
from config.settings import Settings


@pytest.fixture
def mock_settings():
    """테스트용 Settings 객체를 반환합니다. 실제 .env를 로드하지 않습니다."""
    settings = MagicMock(spec=Settings)

    # API 키 (테스트용 더미)
    settings.OPENAI_API_KEY = "test-openai-key"
    settings.FINNHUB_API_KEY = "test-finnhub-key"
    settings.USE_LOCAL_LLM = False
    settings.KIS_APP_KEY = "test-kis-key"
    settings.KIS_APP_SECRET = "test-kis-secret"
    settings.KIS_ACCOUNT_NO = "12345678-01"

    # 환경 설정
    settings.KIS_ENVIRONMENT = "virtual"
    settings.KIS_BASE_URL = "https://openapivts.koreainvestment.com:29443"
    settings.KIS_TR_ID_PREFIX = "V"

    # 텔레그램
    settings.TELEGRAM_BOT_TOKEN = "test-bot-token"
    settings.TELEGRAM_CHAT_ID = "test-chat-id"

    # 전략 파라미터
    settings.TARGET_TICKER = "TSLA"
    settings.ALLOCATION_RATIO = 0.10
    settings.TAKE_PROFIT_PCT = 15.0
    settings.STOP_LOSS_PCT = -5.0
    settings.MIN_CONFIDENCE = 80
    settings.RSI_OVERBOUGHT = 70
    settings.BUY_PRICE_MARGIN = 0.03
    settings.SELL_PRICE_MARGIN = 0.03
    settings.DEFAULT_BALANCE_USD = 10000.0
    settings.TRANSACTION_FEE = 0.001
    settings.LOOKBACK_DAYS = 60

    # 인프라
    settings.API_TIMEOUT = 10
    settings.MAX_RETRIES = 3
    settings.DB_PATH = ":memory:"  # 테스트용 인메모리 DB

    return settings


@pytest.fixture
def valid_llm_response():
    """정상적인 LLM JSON 응답 예시입니다."""
    return '{"reasoning": "Positive earnings beat", "sentiment_score": 0.7, "confidence": 85}'


@pytest.fixture
def invalid_llm_response_text():
    """비정상적인 LLM 응답 (JSON이 아닌 텍스트)입니다."""
    return 'Here is the result: the sentiment is positive with a score of 0.7'


@pytest.fixture
def invalid_llm_response_out_of_range():
    """범위를 벗어난 LLM JSON 응답입니다."""
    return '{"reasoning": "Extremely bullish", "sentiment_score": 2.5, "confidence": 150}'

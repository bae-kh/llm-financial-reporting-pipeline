# file path: config/settings.py
import os
from dotenv import load_dotenv


class Settings:
    """
    프로젝트 전체의 환경 변수와 전략 파라미터를 중앙 집중 관리하는 설정 클래스입니다.
    .env 파일에서 시크릿을 로드하고, 모의투자/실전 환경을 자동 분기합니다.

    [설계 원칙]
    - 모든 매직 넘버(임계값, 비율 등)를 이 클래스에 집약하여 auto_trade.py에서 하드코딩을 완전히 제거합니다.
    - KIS_ENVIRONMENT 값 하나로 URL, tr_id 접두어가 자동 전환되어 코드 수정 없이 환경 스위칭이 가능합니다.
    """

    def __init__(self):
        # .env 파일 로드
        load_dotenv()

        # === API 키 ===
        self.OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
        self.FINNHUB_API_KEY = os.getenv("FINNHUB_API_KEY", "")

        # 로컬 LLM 사용 여부 (기본값 False -> OpenAI API 사용)
        use_local_str = os.getenv("USE_LOCAL_LLM", "False")
        self.USE_LOCAL_LLM = use_local_str.lower() in ("true", "1", "t", "yes")

        # === KIS 증권사 API 설정 ===
        self.KIS_APP_KEY = os.getenv("KIS_APP_KEY", "")
        self.KIS_APP_SECRET = os.getenv("KIS_APP_SECRET", "")
        self.KIS_ACCOUNT_NO = os.getenv("KIS_ACCOUNT_NO", "")

        # 환경 분기: "virtual" (모의투자) 또는 "production" (실전)
        self.KIS_ENVIRONMENT = os.getenv("KIS_ENVIRONMENT", "virtual")
        self.KIS_BASE_URL = (
            "https://openapivts.koreainvestment.com:29443"
            if self.KIS_ENVIRONMENT == "virtual"
            else "https://openapi.koreainvestment.com:9443"
        )
        # 모의투자 tr_id는 "V" 접두어, 실전은 접두어 없음
        self.KIS_TR_ID_PREFIX = "V" if self.KIS_ENVIRONMENT == "virtual" else ""

        # === 텔레그램 알림 ===
        self.TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
        self.TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

        # === 전략 파라미터 (튜닝 가능) ===
        self.TARGET_TICKER = "TSLA"
        self.ALLOCATION_RATIO = 0.10        # 가용 예수금 중 투입 비율 (10%)
        self.TAKE_PROFIT_PCT = 15.0         # 익절 기준 수익률 (%)
        self.STOP_LOSS_PCT = -5.0           # 손절 기준 수익률 (%)
        self.MIN_CONFIDENCE = 80            # LLM 최소 확신도
        self.RSI_OVERBOUGHT = 70            # RSI 과매수 임계값
        self.BUY_PRICE_MARGIN = 0.03        # 매수 체결 보장 할증률 (3%)
        self.SELL_PRICE_MARGIN = 0.03       # 매도 체결 보장 할인률 (3%)
        self.DEFAULT_BALANCE_USD = 10000.0  # 잔고 조회 실패 시 기본값 (USD)
        self.TRANSACTION_FEE = 0.001        # 슬리피지 + 브로커 수수료 합산 (0.1%)
        self.LOOKBACK_DAYS = 60             # 기술적 지표 계산용 조회 기간 (일)

        # === 인프라 설정 ===
        self.API_TIMEOUT = 10               # 외부 API 호출 타임아웃 (초)
        self.MAX_RETRIES = 3                # API 재시도 횟수
        self.DB_PATH = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "quant_trade.db"
        )

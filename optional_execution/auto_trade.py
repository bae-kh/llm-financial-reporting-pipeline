# file path: auto_trade.py
"""
금융 데이터 수집 및 rule-based 시그널 시뮬레이션 파이프라인

[포트폴리오 노트]
- 이 모듈은 데이터 수집, 감성 분석, rule-based 시그널 평가, 리포트 데이터 수집을 담당합니다.
- KIS API 주문 실행은 Optional / Paper Execution 영역이며, 이 포트폴리오의 핵심 기능이 아닙니다.
- 실주문(production)을 실행하려면 .env에서 KIS_ENVIRONMENT="production"을 명시적으로 설정해야 합니다.

실행 전 필수 요건: pip install -r requirements.txt
"""
import asyncio
import logging
import math
import time
import requests
from datetime import datetime, timedelta

from config.settings import Settings
from nlp_engine.analyzer import SentimentAnalyzer
from data_pipeline.price_fetcher import PriceFetcher
from data_pipeline.news_fetcher import NewsFetcher
from database.db_logger import DBLogger
from notifications.telegram import TelegramNotifier

logging.basicConfig(
    filename='daily_trade.log',
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(name)s - %(message)s'
)
logger = logging.getLogger(__name__)


def retry_with_backoff(max_retries: int = 3, base_delay: float = 1.0):
    """
    지수 백오프(Exponential Backoff) 재시도 데코레이터입니다.
    외부 API 호출의 일시적 실패를 자동으로 재시도합니다.
    """
    def decorator(func):
        def wrapper(*args, **kwargs):
            for attempt in range(max_retries):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    if attempt == max_retries - 1:
                        raise
                    delay = base_delay * (2 ** attempt)
                    logger.warning(f"재시도 {attempt + 1}/{max_retries} ({delay}초 후): {e}")
                    time.sleep(delay)
        return wrapper
    return decorator


class TradingEngine:
    """
    금융 데이터 수집 + rule-based 시그널 시뮬레이션 + Optional paper/mock execution 엔진.

    [아키텍처 원칙]
    - 모든 매직 넘버는 Settings 클래스에서 주입받아 하드코딩을 완전히 제거했습니다.
    - 매수/매도 로직을 메서드로 분리하여 단위 테스트가 가능한 구조입니다.
    - 인증 → 잔고 조회 → 데이터 수집 → 분석 → 의사결정 → 실행의 단방향 파이프라인을 따릅니다.
    - KIS API 주문 실행은 optional/paper execution 영역이며, 실주문은 KIS_ENVIRONMENT="production" 명시 설정 시에만 활성화됩니다.
    """

    def __init__(self, settings: Settings):
        self.settings = settings
        self.db_logger = DBLogger(settings.DB_PATH)
        self.notifier = TelegramNotifier(
            bot_token=settings.TELEGRAM_BOT_TOKEN,
            chat_id=settings.TELEGRAM_CHAT_ID,
            timeout=settings.API_TIMEOUT
        )
        self.news_fetcher = NewsFetcher(timeout=settings.API_TIMEOUT)
        self.price_fetcher = PriceFetcher()
        self.analyzer = SentimentAnalyzer(settings, use_local_llm=settings.USE_LOCAL_LLM)
        self._token = None

    # ===== 인증 레이어 =====

    @retry_with_backoff(max_retries=3)
    def _authenticate(self) -> str:
        """KIS API 접근 토큰을 발급받습니다."""
        url = f"{self.settings.KIS_BASE_URL}/oauth2/tokenP"
        payload = {
            "grant_type": "client_credentials",
            "appkey": self.settings.KIS_APP_KEY,
            "appsecret": self.settings.KIS_APP_SECRET
        }
        res = requests.post(url, json=payload, timeout=self.settings.API_TIMEOUT)
        res.raise_for_status()
        token = res.json().get("access_token")
        logger.info("KIS 접근 토큰 발급 완료")
        return token

    def _build_headers(self, tr_id: str) -> dict:
        """KIS API 공통 헤더를 생성합니다."""
        return {
            "Content-Type": "application/json",
            "authorization": f"Bearer {self._token}",
            "appKey": self.settings.KIS_APP_KEY,
            "appSecret": self.settings.KIS_APP_SECRET,
            "tr_id": f"{self.settings.KIS_TR_ID_PREFIX}{tr_id}"
        }

    def _parse_account_no(self) -> tuple[str, str]:
        """계좌번호를 CANO와 ACNT_PRDT_CD로 분리합니다."""
        account_no = self.settings.KIS_ACCOUNT_NO
        if "-" in account_no:
            cano, acnt_prdt_cd = account_no.split("-", 1)
        else:
            cano, acnt_prdt_cd = account_no[:8], "01"
        return cano, acnt_prdt_cd

    # ===== 잔고 조회 레이어 =====

    def _fetch_balance(self, ticker: str) -> tuple[float, int, float]:
        """
        달러 예수금, 보유 수량, 매입 평균 단가를 조회합니다.

        Returns:
            (available_usd, holding_qty, avg_price) 튜플.
        """
        cano, acnt_prdt_cd = self._parse_account_no()
        url = f"{self.settings.KIS_BASE_URL}/uapi/overseas-stock/v1/trading/inquire-balance"
        headers = self._build_headers("TTS3012R")
        params = {
            "CANO": cano,
            "ACNT_PRDT_CD": acnt_prdt_cd,
            "OVRS_EXCG_CD": "NASD",
            "TR_CRCY_CD": "USD",
            "CTX_AREA_FK200": "",
            "CTX_AREA_NK200": ""
        }

        res = requests.get(url, headers=headers, params=params, timeout=self.settings.API_TIMEOUT)
        res.raise_for_status()
        data = res.json()

        # 예수금 파싱
        ord_psbl_usd = 0.0
        output3 = data.get("output3", {})
        if output3:
            ord_psbl_usd = float(output3.get("evlu_amt_smtl_amt", self.settings.DEFAULT_BALANCE_USD))

        # 보유 수량 및 평단가 파싱
        holding_qty = 0
        avg_price = 0.0
        try:
            output1 = data.get("output1", [])
            for item in output1:
                if item.get("ovrs_pdno", "") == ticker:
                    holding_qty = int(float(item.get("ovrs_cblc_qty", "0")))
                    avg_price = float(item.get("pchs_avg_pric", "0.0"))
                    break
        except Exception as e:
            logger.warning(f"[방어적 라우팅] 보유 수량/평단가 파싱 실패 (기본값 0 처리): {e}")

        return ord_psbl_usd, holding_qty, avg_price

    # ===== 주문 실행 레이어 =====

    def _execute_order(self, side: str, ticker: str, qty: int, price: float) -> dict:
        """
        매수/매도 통합 주문 함수입니다. side 인자로 방향을 분기합니다.

        Args:
            side: "BUY" 또는 "SELL".
            ticker: 종목 심볼 (예: "TSLA").
            qty: 주문 수량 (주).
            price: 주문 가격 (USD).

        Returns:
            KIS API 응답 딕셔너리.
        """
        cano, acnt_prdt_cd = self._parse_account_no()
        # 매수: TTT1002U / 매도: TTT1006U (접두어는 _build_headers에서 자동 처리)
        tr_id = "TTT1002U" if side == "BUY" else "TTT1006U"

        url = f"{self.settings.KIS_BASE_URL}/uapi/overseas-stock/v1/trading/order"
        headers = self._build_headers(tr_id)
        payload = {
            "CANO": cano,
            "ACNT_PRDT_CD": acnt_prdt_cd,
            "OVRS_EXCG_CD": "NASD",
            "PDNO": ticker,
            "ORD_QTY": str(int(qty)),
            "OVRS_ORD_UNPR": f"{price:.2f}",
            "ORD_SVR_DVSN_CD": "0",
            "ORD_DVSN": "00"
        }

        res = requests.post(url, headers=headers, json=payload, timeout=self.settings.API_TIMEOUT)
        res.raise_for_status()
        return res.json()

    # ===== 의사결정 레이어 =====

    def evaluate_sell_signal(self, roi: float, score: float) -> str | None:
        """
        매도 시그널을 평가합니다.
        익절/손절/악재 순서로 검사하며, 매도 사유를 반환합니다.

        Args:
            roi: 현재 수익률 (%).
            score: LLM 감성 점수 (-1.0 ~ 1.0).

        Returns:
            매도 사유 문자열. 매도 조건 미충족 시 None.
        """
        if roi >= self.settings.TAKE_PROFIT_PCT:
            return f"[익절 트리거] 수익률 {self.settings.TAKE_PROFIT_PCT}% 도달 (현재 {roi:.2f}%)"
        if roi <= self.settings.STOP_LOSS_PCT:
            return f"[손절 트리거] 손실률 {self.settings.STOP_LOSS_PCT}% 도달 (현재 {roi:.2f}%)"
        if score < 0:
            return f"[악재 트리거] 뉴스 감성 점수 하락 (점수: {score})"
        return None

    def evaluate_buy_signal(self, score: float, confidence: int, rsi: float, macd_diff: float) -> tuple[bool, str]:
        """
        매수 시그널을 다중 게이트로 평가합니다.
        [뉴스 감성 + 확신도 + RSI + MACD] 모두 통과해야 매수 트리거가 발동합니다.

        Args:
            score: LLM 감성 점수 (-1.0 ~ 1.0).
            confidence: LLM 확신도 (0 ~ 100).
            rsi: RSI(14) 지표값.
            macd_diff: MACD_diff 지표값.

        Returns:
            (매수 여부, 사유 메시지) 튜플.
        """
        if score <= 0 or confidence < self.settings.MIN_CONFIDENCE:
            return False, "매매 기준 미달(호재 아님/확신도 부족) 또는 악재이나 보유 주식이 없습니다."

        if rsi >= self.settings.RSI_OVERBOUGHT:
            return False, f"호재이나 차트 과열(RSI {rsi:.2f} 높은 상태)로 매수 보류"

        if macd_diff <= 0:
            return False, f"호재이나 MACD 단기 하락 추세(MACD_diff {macd_diff:.4f})로 매수 보류"

        return True, "정성/정량 필터 모두 통과"

    # ===== 메인 파이프라인 =====

    def run(self):
        """
        데이터 수집 + rule-based 시그널 평가 파이프라인의 메인 오케스트레이터입니다.

        인증 → 잔고 조회 → 데이터 수집 → NLP 분석 → 의사결정 → 선택적 주문 실행 순서로 진행합니다.

        [KIS API 주문 실행]
        - Optional / paper execution 영역입니다.
        - KIS_ENVIRONMENT="virtual" (default) 시 모의투자 모드로 동작합니다.
        - 이 포트폴리오의 핵심은 live trading이 아니라 데이터 수집, 감성 분석, 리포트 생성 workflow입니다.
        """
        logger.info("=== 데이터 수집 파이프라인 시작 ===")
        ticker = self.settings.TARGET_TICKER

        try:
            # Step 1: KIS API 인증
            self._token = self._authenticate()

            # Step 2: 잔고 및 보유 현황 조회
            available_usd, holding_qty, avg_price = self._fetch_balance(ticker)
            if available_usd <= 0:
                available_usd = self.settings.DEFAULT_BALANCE_USD

            target_usd = available_usd * self.settings.ALLOCATION_RATIO

            # Step 3: 주가 및 기술적 지표 수집 (60일)
            end_date = datetime.today()
            start_date = end_date - timedelta(days=self.settings.LOOKBACK_DAYS)
            df_price = self.price_fetcher.get_daily_data(
                ticker,
                start_date.strftime("%Y-%m-%d"),
                end_date.strftime("%Y-%m-%d")
            )

            if df_price.empty:
                raise ValueError(f"{ticker} 통신 불가로 현재 가격을 불러오지 못했습니다.")

            latest_data = df_price.iloc[-1]
            current_price = latest_data['Close']
            rsi_14 = latest_data['RSI_14']
            macd_diff = latest_data['MACD_diff']

            # 수익률(ROI) 계산
            roi = 0.0
            if holding_qty > 0 and avg_price > 0:
                roi = (current_price - avg_price) / avg_price * 100

            logger.info(f"계좌 가용 예수금: ${available_usd:.2f} | {self.settings.ALLOCATION_RATIO*100:.0f}% 할당: ${target_usd:.2f}")
            logger.info(f"{ticker} 현황 - 보유량: {holding_qty}주 | 매입 평단가: ${avg_price:.2f} | 현재 수익률: {roi:.2f}%")
            logger.info(f"{ticker} 최신가: ${current_price:.2f} | RSI(14): {rsi_14:.2f} | MACD_diff: {macd_diff:.4f}")

            self.notifier.send(
                f"[파이프라인 시작] {ticker} 데이터 수집 시작\n"
                f"조회 대상 예수금: ${target_usd:.2f}\n"
                f"현재 보유량: {holding_qty}주\n"
                f"현재 수익률: {roi:.2f}%  [리포트용 데이터]"
            )

            # Step 4: 실시간 뉴스 크롤링
            todays_news = self.news_fetcher.fetch(ticker)
            if not todays_news.strip():
                logger.info("크롤링된 뉴스가 없어 오늘 매매를 진행하지 않습니다.")
                return

            # Step 5: LLM 감성 분석
            reasoning, score, conf = asyncio.run(self.analyzer.analyze_sentiment(todays_news))
            logger.info(f"LLM 판단 결과 - 점수: {score}, 확신도: {conf}% | 근거: {reasoning}")
            self.notifier.send(f"[AI 분석] 점수: {score} | 확신도: {conf}%\n근거: {reasoning}")

            # Step 6: 의사결정 트리 — 매도 우선, 매수는 다중 게이트 통과 시에만 실행
            if holding_qty > 0:
                sell_reason = self.evaluate_sell_signal(roi, score)
                if sell_reason:
                    self._process_sell(ticker, holding_qty, current_price, sell_reason,
                                       roi, rsi_14, macd_diff, score, reasoning)
                    return

            should_buy, buy_msg = self.evaluate_buy_signal(score, conf, rsi_14, macd_diff)
            if should_buy:
                self._process_buy(ticker, target_usd, current_price,
                                   roi, rsi_14, macd_diff, score, reasoning)
            else:
                logger.info(f"{buy_msg} 관망(HOLD).")
                self.notifier.send(f"[관망] 매매 조건 미달. ({buy_msg})")
                self.db_logger.log_trade(
                    ticker, "HOLD", current_price, 0,
                    roi, rsi_14, macd_diff, score, reasoning, "SKIPPED"
                )

        except Exception as e:
            logger.error(f"파이프라인 실행 중 오류 발생: {e}")
            self.notifier.send(f"[🚨시스템 에러] 파이프라인 오류 발생: {e}")

    def _process_sell(self, ticker: str, holding_qty: int, current_price: float,
                      sell_reason: str, roi: float, rsi: float, macd: float,
                      score: float, reasoning: str):
        """매도 주문을 실행하고 결과를 기록합니다."""
        sell_price = current_price * (1 - self.settings.SELL_PRICE_MARGIN)
        logger.info(f"{sell_reason} -> 보유량 {holding_qty}주 전량 매도 진행 (${sell_price:.2f})")

        try:
            order_data = self._execute_order("SELL", ticker, holding_qty, sell_price)
            is_success = order_data.get("rt_cd") == "0"

            self.db_logger.log_trade(
                ticker, "SELL", sell_price, holding_qty,
                roi, rsi, macd, score, reasoning,
                "SUCCESS" if is_success else "FAILED"
            )

            if is_success:
                odno = order_data.get("output", {}).get("ODNO", "Unknown")
                logger.info(f"✅ 매도 주문 성공! 메시지: {order_data.get('msg1')} | 주문번호: {odno}")
                self.notifier.send(f"[체결 완료] {holding_qty}주 매도 성공!\n주문번호: {odno}")
            else:
                logger.error(f"❌ 매도 실패: 코드 {order_data.get('msg_cd')} - {order_data.get('msg1')}")
        except Exception as e:
            logger.error(f"매도 주문 실행 중 오류: {e}")
            self.db_logger.log_trade(
                ticker, "SELL", sell_price, holding_qty,
                roi, rsi, macd, score, reasoning, "FAILED"
            )

        logger.info("매도 주문을 실행했으므로 오늘의 파이프라인(매수 로직)을 조기 종료합니다.")

    def _process_buy(self, ticker: str, target_usd: float, current_price: float,
                     roi: float, rsi: float, macd: float,
                     score: float, reasoning: str):
        """매수 주문을 실행하고 결과를 기록합니다."""
        buy_qty = math.floor(target_usd / current_price)
        if buy_qty <= 0:
            msg = "매수 트리거는 발동했으나 할당된 금액으로 금일 1주도 살 수 없습니다."
            logger.info(f"{msg} 관망(HOLD).")
            self.notifier.send(f"[관망] 매매 조건 미달. ({msg})")
            self.db_logger.log_trade(
                ticker, "HOLD", current_price, 0,
                roi, rsi, macd, score, reasoning, "SKIPPED"
            )
            return

        order_price = current_price * (1 + self.settings.BUY_PRICE_MARGIN)
        logger.info(f"[BUY 트리거] 정성/정량 필터 모두 통과! [{buy_qty}주] 매수 진행 (${order_price:.2f})")

        try:
            order_data = self._execute_order("BUY", ticker, buy_qty, order_price)
            is_success = order_data.get("rt_cd") == "0"

            self.db_logger.log_trade(
                ticker, "BUY", order_price, buy_qty,
                roi, rsi, macd, score, reasoning,
                "SUCCESS" if is_success else "FAILED"
            )

            if is_success:
                odno = order_data.get("output", {}).get("ODNO", "Unknown")
                logger.info(f"✅ 매수 주문 성공! 메시지: {order_data.get('msg1')} | 주문번호: {odno}")
                self.notifier.send(f"[체결 완료] {buy_qty}주 매수 성공!\n주문번호: {odno}")
            else:
                logger.error(f"❌ 매수 실패: 코드 {order_data.get('msg_cd')} - {order_data.get('msg1')}")
        except Exception as e:
            logger.error(f"매수 주문 실행 중 오류: {e}")
            self.db_logger.log_trade(
                ticker, "BUY", order_price, buy_qty,
                roi, rsi, macd, score, reasoning, "FAILED"
            )


if __name__ == "__main__":
    settings = Settings()
    engine = TradingEngine(settings)
    engine.run()

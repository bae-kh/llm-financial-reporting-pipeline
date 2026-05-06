# file path: notifications/telegram.py
import logging
import requests

logger = logging.getLogger(__name__)


class TelegramNotifier:
    """
    텔레그램 봇 API를 통해 실시간 알림을 전송하는 모듈입니다.

    [역할]
    - 시스템 가동/종료, AI 분석 결과, 매수/매도 체결 영수증, 에러 로그를
      관리자의 스마트폰으로 푸시(Push)하는 무인화 운영 체계를 담당합니다.
    - 토큰 또는 Chat ID가 미설정된 경우 경고 로그만 남기고 정상 진행합니다.
    """

    def __init__(self, bot_token: str, chat_id: str, timeout: int = 10):
        self.bot_token = bot_token
        self.chat_id = chat_id
        self.timeout = timeout
        self._enabled = bool(bot_token and chat_id)

        if not self._enabled:
            logger.warning("텔레그램 토큰 또는 Chat ID가 설정되지 않아 알림이 비활성화됩니다.")

    def send(self, message: str) -> bool:
        """
        텔레그램 메시지를 전송합니다.

        Args:
            message: 전송할 메시지 텍스트.

        Returns:
            전송 성공 여부 (비활성화 상태면 False).
        """
        if not self._enabled:
            return False

        try:
            url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
            payload = {"chat_id": self.chat_id, "text": message}
            res = requests.post(url, json=payload, timeout=self.timeout)
            res.raise_for_status()
            return True
        except requests.exceptions.Timeout:
            logger.error("텔레그램 메시지 전송 타임아웃")
            return False
        except requests.exceptions.RequestException as e:
            logger.error(f"텔레그램 메시지 전송 실패: {e}")
            return False

# file path: database/db_logger.py
import sqlite3
import logging

logger = logging.getLogger(__name__)


class DBLogger:
    """
    SQLite 데이터베이스에 매매 트랜잭션 로그를 기록하는 클래스입니다.

    [설계 배경]
    - WAL(Write-Ahead Logging) 모드를 활성화하여 Streamlit 대시보드(읽기)와
      auto_trade.py(쓰기)가 동시에 DB에 접근해도 'database is locked' 에러를 방지합니다.
    - 커넥션 타임아웃을 설정하여 락 대기 시 무한 블로킹을 방지합니다.
    """

    def __init__(self, db_path: str = "quant_trade.db"):
        self.db_path = db_path
        self._create_table()

    def _get_connection(self) -> sqlite3.Connection:
        """WAL 모드와 타임아웃이 적용된 DB 커넥션을 반환합니다."""
        conn = sqlite3.connect(self.db_path, timeout=10)
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _create_table(self):
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS trade_history (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                        ticker TEXT,
                        action TEXT,
                        price REAL,
                        quantity INTEGER,
                        roi REAL,
                        rsi REAL,
                        macd REAL,
                        llm_score REAL,
                        llm_reasoning TEXT,
                        status TEXT
                    )
                ''')
                conn.commit()
        except Exception as e:
            logger.error(f"DB 테이블 생성 중 오류 발생: {e}")

    def log_trade(self, ticker: str, action: str, price: float, quantity: int,
                  roi: float, rsi: float, macd: float, llm_score: float,
                  llm_reasoning: str, status: str):
        """
        매매 트랜잭션을 DB에 기록합니다.

        Args:
            ticker: 종목 심볼 (예: "TSLA").
            action: 매매 행동 ("BUY", "SELL", "HOLD").
            price: 주문/현재 가격 (USD).
            quantity: 주문 수량 (주).
            roi: 현재 수익률 (%).
            rsi: RSI(14) 지표값.
            macd: MACD_diff 지표값.
            llm_score: LLM 감성 점수 (-1.0 ~ 1.0).
            llm_reasoning: LLM 분석 근거 텍스트.
            status: 주문 결과 ("SUCCESS", "FAILED", "SKIPPED").
        """
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    INSERT INTO trade_history 
                    (ticker, action, price, quantity, roi, rsi, macd, llm_score, llm_reasoning, status) 
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (ticker, action, price, quantity, roi, rsi, macd, llm_score, llm_reasoning, status))
                conn.commit()
        except Exception as e:
            logger.error(f"DB 로깅 중 오류 발생: {e}")

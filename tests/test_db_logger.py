# file path: tests/test_db_logger.py
"""
DB 로거(DBLogger)의 기록 무결성과 에러 내성을 검증합니다.

[핵심 검증 포인트]
- 정상 거래 기록이 DB에 올바르게 저장되는가
- 잘못된 DB 경로가 주어져도 시스템이 크래시되지 않는가
"""
import os
import sqlite3
import pytest

from database.db_logger import DBLogger


class TestDBLogger:
    """DBLogger의 CRUD 및 에러 핸들링을 테스트합니다."""

    @pytest.fixture
    def temp_db(self, tmp_path):
        """임시 디렉토리에 테스트용 DB를 생성합니다."""
        db_path = str(tmp_path / "test_trade.db")
        return db_path

    def test_log_trade_success(self, temp_db):
        """정상 거래 기록이 DB에 올바르게 저장되어야 합니다."""
        logger = DBLogger(db_path=temp_db)

        logger.log_trade(
            ticker="TSLA",
            action="BUY",
            price=250.50,
            quantity=10,
            roi=0.0,
            rsi=55.0,
            macd=0.015,
            llm_score=0.7,
            llm_reasoning="Positive earnings beat",
            status="SUCCESS"
        )

        # DB에서 직접 읽어 검증
        with sqlite3.connect(temp_db) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM trade_history")
            rows = cursor.fetchall()

        assert len(rows) == 1
        # 컬럼 순서: id, timestamp, ticker, action, price, quantity, roi, rsi, macd, llm_score, llm_reasoning, status
        assert rows[0][2] == "TSLA"
        assert rows[0][3] == "BUY"
        assert rows[0][4] == 250.50
        assert rows[0][5] == 10
        assert rows[0][11] == "SUCCESS"

    def test_multiple_logs(self, temp_db):
        """연속 기록이 모두 정상적으로 저장되어야 합니다."""
        logger = DBLogger(db_path=temp_db)

        for i in range(5):
            logger.log_trade(
                ticker="TSLA", action="HOLD", price=250.0 + i,
                quantity=0, roi=0.0, rsi=50.0, macd=0.01,
                llm_score=0.1, llm_reasoning=f"Test {i}", status="SKIPPED"
            )

        with sqlite3.connect(temp_db) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM trade_history")
            count = cursor.fetchone()[0]

        assert count == 5

    def test_invalid_db_path_no_crash(self):
        """잘못된 DB 경로가 주어져도 시스템이 크래시되지 않아야 합니다."""
        # 존재하지 않는 깊은 경로를 지정
        bad_path = "/nonexistent/deep/path/bad.db"
        # DBLogger 생성 시 테이블 생성이 실패하지만 크래시되면 안 됨
        logger = DBLogger(db_path=bad_path)

        # log_trade도 실패하지만 크래시되면 안 됨
        logger.log_trade(
            ticker="TSLA", action="BUY", price=250.0,
            quantity=10, roi=0.0, rsi=55.0, macd=0.01,
            llm_score=0.5, llm_reasoning="Test", status="FAILED"
        )
        # 여기까지 도달하면 크래시 없이 처리된 것

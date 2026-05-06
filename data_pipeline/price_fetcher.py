# file path: data_pipeline/price_fetcher.py
import logging
import yfinance as yf
import pandas as pd
from datetime import datetime, timedelta
import ta  # pip install ta

logger = logging.getLogger(__name__)


class PriceFetcher:
    """
    US Equity (yfinance 등)의 주가 데이터를 가져오고 결측치를 전처리하는 클래스입니다.

    [설계 배경]
    - 결측치 전처리에 Forward Fill(ffill)을 적용합니다. 시장 휴장일이나 통신 지연으로
      주가 데이터에 NaN이 발생하면, 직전 유효 체결가를 현재 가격으로 인식하는 시장 특성을
      반영합니다. 이를 통해 이동평균 지표 왜곡과 Look-ahead 편향을 동시에 방어합니다.
    - ta 라이브러리를 통해 RSI(14)와 MACD_diff를 자동 계산합니다.
    """

    def __init__(self):
        pass

    def get_daily_data(self, ticker: str = "TSLA", start_date: str = "2020-01-01", end_date: str = "2023-01-31") -> pd.DataFrame:
        """
        주가(TSLA 등)의 일봉(Daily) OHLCV 데이터를 Pandas DataFrame으로 반환합니다.
        테슬라 백테스트를 위해 기본값을 2020년 1월 ~ 2023년 1월로 설정합니다.
        """
        try:
            # yfinance는 end_date 당일을 미포함하므로, 안전하게 하루 뒤로 밀어줍니다.
            end_dt = datetime.strptime(end_date, "%Y-%m-%d") + timedelta(days=1)
            end_str = end_dt.strftime("%Y-%m-%d")

            logger.info(f"[{ticker}] {start_date} 부터 {end_date} 간의 일봉 데이터를 요청합니다.")

            df = yf.download(ticker, start=start_date, end=end_str, interval="1d", progress=False, timeout=15)

            if df.empty:
                logger.warning(f"[{ticker}] 반환된 일봉 데이터가 없습니다.")
                return df

            # 멀티인덱스 컬럼 평탄화 (yfinance 최신 버전 호환성)
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)

            # 결측치 확인 및 전처리(Forward Fill)
            if df.isnull().values.any():
                logger.warning(f"[{ticker}] 일봉 데이터에 결측치(NaN)가 감지되었습니다. ffill 처리를 진행합니다.")
                df.ffill(inplace=True)

            # ta 라이브러리를 통한 정량적 지표 계산 (RSI, MACD)
            df['RSI_14'] = ta.momentum.RSIIndicator(close=df['Close'], window=14).rsi()
            df['MACD_diff'] = ta.trend.MACD(close=df['Close']).macd_diff()
            df.dropna(inplace=True)

            return df

        except Exception as e:
            logger.error(f"[{ticker}] 일봉 데이터 수집 중 에러 발생: {e}")
            return pd.DataFrame()

    def get_hourly_data(self, ticker: str, hours: int = 24) -> pd.DataFrame:
        """
        최근 hours 시간 동안의 시간봉(Hourly) OHLCV 데이터를 Pandas DataFrame으로 반환합니다.
        (주로 단기 모멘텀 확인용)
        """
        try:
            logger.info(f"[{ticker}] 최근 {hours}시간 간의 시간봉 데이터를 요청합니다.")
            # yfinance에서 1h 봉은 최대 730일 기간 내에서만 사용 가능
            df = yf.download(ticker, period="1mo", interval="1h", progress=False, timeout=15)

            if df.empty:
                logger.warning(f"[{ticker}] 반환된 시간봉 데이터가 없습니다.")
                return df

            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)

            # 앞서 구한 period("1mo")에서 최근 hours 개수만 필터링
            df = df.tail(hours)

            if df.isnull().values.any():
                logger.warning(f"[{ticker}] 시간봉 데이터에 결측치(NaN)가 감지되었습니다. ffill 처리를 진행합니다.")
                df.ffill(inplace=True)

            return df

        except Exception as e:
            logger.error(f"[{ticker}] 시간봉 데이터 수집 중 에러 발생: {e}")
            return pd.DataFrame()

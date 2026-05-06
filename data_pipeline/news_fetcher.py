# file path: data_pipeline/news_fetcher.py
import logging
import requests
import xml.etree.ElementTree as ET

logger = logging.getLogger(__name__)


class NewsFetcher:
    """
    Google News RSS를 통해 특정 종목의 최신 뉴스 헤드라인을 수집하는 클래스입니다.

    [설계 배경]
    - yfinance 뉴스 API 대신 구조가 안정적인 Google News RSS를 채택했습니다.
    - RSS XML 파싱이 실패하거나 유효한 뉴스가 없을 경우, 빈 문자열을 반환하여
      파이프라인이 안전하게 관망(HOLD) 모드로 전환되도록 설계했습니다.
    """

    def __init__(self, timeout: int = 10):
        self.timeout = timeout

    def fetch(self, ticker: str, max_articles: int = 5) -> str:
        """
        지정된 종목의 최신 뉴스 헤드라인을 텍스트 문자열로 반환합니다.

        Args:
            ticker: 종목 심볼 (예: "TSLA").
            max_articles: 가져올 최대 기사 수 (기본 5개).

        Returns:
            뉴스 헤드라인 텍스트. 실패 시 빈 문자열.
        """
        try:
            logging.info(f"[{ticker}] 구글 뉴스 RSS 크롤링을 시작합니다.")

            url = f"https://news.google.com/rss/search?q={ticker}+stock&hl=en-US&gl=US&ceid=US:en"
            res = requests.get(url, timeout=self.timeout)
            res.raise_for_status()

            root = ET.fromstring(res.content)
            items = root.findall('.//item')[:max_articles]

            if not items:
                logger.warning("가져온 뉴스가 없습니다.")
                return ""

            combined_text = []
            for item in items:
                title = item.findtext('title') or ''
                pub_date = item.findtext('pubDate') or ''
                combined_text.append(f"Title: {title}\nDate: {pub_date}\n")

            final_news_string = "\n".join(combined_text)

            # [핵심 방어 로직] "Title:" 같은 껍데기만 남는 것을 방지하기 위해 실제 텍스트 길이를 검증
            stripped = final_news_string.replace("Title:", "").replace("Date:", "").strip()
            if len(stripped) < 20:
                logger.warning("뉴스 데이터가 유효하지 않아 빈 문자열을 반환합니다.")
                return ""

            logger.info("실시간 뉴스 텍스트 추출 완료.")
            return final_news_string

        except requests.exceptions.Timeout:
            logger.error(f"[{ticker}] 뉴스 수집 타임아웃 ({self.timeout}초)")
            return ""
        except ET.ParseError as e:
            logger.error(f"[{ticker}] RSS XML 파싱 실패: {e}")
            return ""
        except requests.exceptions.RequestException as e:
            logger.error(f"[{ticker}] 뉴스 수집 중 네트워크 오류: {e}")
            return ""
        except Exception as e:
            logger.error(f"[{ticker}] 뉴스 수집 중 예상치 못한 오류: {e}")
            return ""

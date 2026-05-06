# file path: tests/test_news_fetcher.py
"""
뉴스 크롤러(NewsFetcher)의 실패 방어 로직을 검증합니다.

[핵심 검증 포인트]
- 네트워크 타임아웃 시 빈 문자열을 반환하고 시스템이 멈추지 않는가
- 잘못된 XML 응답이 오면 안전하게 처리되는가
- 뉴스 본문이 너무 짧으면 무효로 판단하는가
"""
import pytest
from unittest.mock import patch, MagicMock
import requests

from data_pipeline.news_fetcher import NewsFetcher


class TestNewsFetcher:
    """NewsFetcher의 정상/비정상 시나리오를 테스트합니다."""

    @pytest.fixture
    def fetcher(self):
        return NewsFetcher(timeout=5)

    @patch("data_pipeline.news_fetcher.requests.get")
    def test_successful_fetch(self, mock_get, fetcher):
        """정상적인 RSS 응답에서 뉴스 텍스트가 추출되어야 합니다."""
        mock_response = MagicMock()
        mock_response.content = b"""<?xml version="1.0" encoding="UTF-8"?>
        <rss version="2.0">
            <channel>
                <item>
                    <title>Tesla reports record Q4 earnings beating expectations</title>
                    <pubDate>Mon, 05 May 2026 10:00:00 GMT</pubDate>
                </item>
                <item>
                    <title>TSLA stock surges on strong delivery numbers</title>
                    <pubDate>Mon, 05 May 2026 09:00:00 GMT</pubDate>
                </item>
            </channel>
        </rss>"""
        mock_response.raise_for_status = MagicMock()
        mock_get.return_value = mock_response

        result = fetcher.fetch("TSLA")

        assert "Tesla" in result
        assert "earnings" in result
        assert len(result) > 20

    @patch("data_pipeline.news_fetcher.requests.get")
    def test_timeout_returns_empty_string(self, mock_get, fetcher):
        """네트워크 타임아웃 시 빈 문자열을 반환해야 합니다."""
        mock_get.side_effect = requests.exceptions.Timeout("Connection timed out")

        result = fetcher.fetch("TSLA")

        assert result == ""

    @patch("data_pipeline.news_fetcher.requests.get")
    def test_invalid_xml_returns_empty_string(self, mock_get, fetcher):
        """잘못된 XML 응답이 오면 빈 문자열을 반환해야 합니다."""
        mock_response = MagicMock()
        mock_response.content = b"This is not valid XML at all <><><>"
        mock_response.raise_for_status = MagicMock()
        mock_get.return_value = mock_response

        result = fetcher.fetch("TSLA")

        assert result == ""

    @patch("data_pipeline.news_fetcher.requests.get")
    def test_too_short_content_returns_empty(self, mock_get, fetcher):
        """뉴스 본문이 20자 미만이면 유효하지 않은 것으로 판단해야 합니다."""
        mock_response = MagicMock()
        mock_response.content = b"""<?xml version="1.0" encoding="UTF-8"?>
        <rss version="2.0">
            <channel>
                <item>
                    <title>Hi</title>
                    <pubDate></pubDate>
                </item>
            </channel>
        </rss>"""
        mock_response.raise_for_status = MagicMock()
        mock_get.return_value = mock_response

        result = fetcher.fetch("TSLA")

        assert result == ""

    @patch("data_pipeline.news_fetcher.requests.get")
    def test_network_error_returns_empty(self, mock_get, fetcher):
        """일반 네트워크 오류 시 빈 문자열을 반환해야 합니다."""
        mock_get.side_effect = requests.exceptions.ConnectionError("DNS resolution failed")

        result = fetcher.fetch("TSLA")

        assert result == ""

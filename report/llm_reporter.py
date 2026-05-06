# file path: report/llm_reporter.py
"""
백테스트 결과와 리스크 지표를 LLM에 넘겨 마크다운 분석 리포트를 자동 생성합니다.

[설계 원칙]
- LLM은 투자 판단을 하지 않습니다.
- 정량 규칙 기반 백테스트의 결과(숫자)를 사람이 이해하기 쉬운 텍스트로 요약하는 역할만 합니다.
- 이 설계는 면접에서 "LLM이 매매 판단을 하나요?"라는 질문에 대한 구조적 답변이 됩니다.
"""
import asyncio
import json
import logging
from datetime import datetime

from openai import AsyncOpenAI
from config.settings import Settings

logger = logging.getLogger(__name__)


class LLMReporter:
    """
    백테스트 성과 지표를 입력받아 마크다운 형식의 분석 리포트를 생성합니다.

    [LLM 역할 한정]
    - 매수/매도 판단 ❌
    - 지표 요약 및 한계점 분석 ⭕
    - 구간별 성과 해석 ⭕
    """

    def __init__(self, settings: Settings):
        self.settings = settings

        if self.settings.USE_LOCAL_LLM:
            self.client = AsyncOpenAI(
                base_url="http://localhost:11434/v1",
                api_key="ollama"
            )
            self.model = "llama3"
        else:
            self.client = AsyncOpenAI(api_key=self.settings.OPENAI_API_KEY)
            self.model = "gpt-4o-mini"

    async def generate_report(self, metrics: dict, config: dict, trades: list[dict]) -> str:
        """
        백테스트 결과를 기반으로 LLM에게 마크다운 분석 리포트 생성을 요청합니다.

        Args:
            metrics: RiskMetrics.generate_summary()의 반환값.
            config: 백테스트 설정 정보 (ticker, 기간, 파라미터).
            trades: 개별 거래 기록 리스트.

        Returns:
            마크다운 형식의 분석 리포트 문자열.
        """
        # 거래 요약 통계
        buy_count = sum(1 for t in trades if t['action'] == 'BUY')
        sell_count = sum(1 for t in trades if t['action'] == 'SELL')
        avg_pnl = sum(t.get('pnl', 0) for t in trades if t['action'] == 'SELL') / max(sell_count, 1)

        # 매도 사유 분포
        sell_reasons = {}
        for t in trades:
            if t['action'] == 'SELL':
                reason_type = t.get('reason', '기타').split('(')[0].strip()
                sell_reasons[reason_type] = sell_reasons.get(reason_type, 0) + 1

        prompt_data = f"""
아래는 {config.get('ticker', 'TSLA')} 주식에 대한 정량 규칙 기반 전략의 백테스트 결과입니다.

## 백테스트 설정
- 기간: {config.get('start_date')} ~ {config.get('end_date')}
- 초기 자본: ${config.get('initial_capital', 10000):,.0f}
- 익절 기준: {config.get('take_profit_pct', 15)}%
- 손절 기준: {config.get('stop_loss_pct', -5)}%
- RSI 과매수 기준: {config.get('rsi_overbought', 70)}
- 거래비용: {config.get('transaction_fee', 0.001)*100:.1f}%

## 성과 지표
- CAGR (연평균 복리 수익률): {metrics.get('cagr', 0):.2%}
- MDD (최대 낙폭): {metrics.get('mdd', 0):.2%}
- Sharpe Ratio: {metrics.get('sharpe', 0):.2f}
- 누적 수익률: {metrics.get('total_return', 0):.2%}
- 승률: {metrics.get('win_rate', 0):.1%}
- 손익비 (Profit Factor): {metrics.get('profit_factor', 0):.2f}
- 총 거래 횟수: {metrics.get('total_trades', 0)}건 (매수 {buy_count}, 매도 {sell_count})
- 벤치마크(S&P500) 대비 Alpha: {metrics.get('alpha', 'N/A')}

## 매도 사유 분포
{json.dumps(sell_reasons, ensure_ascii=False, indent=2)}

## 평균 거래 손익
${avg_pnl:,.2f}
"""

        system_prompt = """You are a financial data analyst. Your role is to summarize quantitative backtest results into a clear, structured Korean-language markdown report.

IMPORTANT RULES:
1. You do NOT make investment recommendations or trading decisions.
2. You analyze and explain what the numbers mean, identify strengths and weaknesses of the strategy.
3. Write in Korean (한국어).
4. Use markdown headers (##, ###) for structure.
5. Include specific numbers from the data provided.
6. Point out limitations and areas for improvement.
7. Be objective and analytical, not promotional.

Output format:
## 📊 [Ticker] 전략 성과 분석 리포트
### 성과 요약
### 주요 분석
### 리스크 분석
### 한계점 및 개선 방향
"""

        try:
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": prompt_data}
                ],
                temperature=0.3,
                max_tokens=1500,
                timeout=30
            )

            report_content = response.choices[0].message.content
            logger.info("LLM 분석 리포트가 성공적으로 생성되었습니다.")
            return report_content

        except Exception as e:
            logger.error(f"LLM 리포트 생성 실패: {e}")
            # LLM 실패 시 기본 리포트 반환 (시스템 중단 방지)
            return self._generate_fallback_report(metrics, config)

    def _generate_fallback_report(self, metrics: dict, config: dict) -> str:
        """LLM 호출 실패 시 정량 데이터만으로 구성한 기본 리포트를 반환합니다."""
        return f"""## 📊 {config.get('ticker', 'TSLA')} 전략 성과 분석 리포트

> ⚠️ LLM 분석 요약은 현재 사용 불가하여 정량 데이터만 표시합니다.

### 성과 요약
| 지표 | 값 |
|---|---|
| CAGR | {metrics.get('cagr', 0):.2%} |
| MDD | {metrics.get('mdd', 0):.2%} |
| Sharpe Ratio | {metrics.get('sharpe', 0):.2f} |
| 누적 수익률 | {metrics.get('total_return', 0):.2%} |
| 승률 | {metrics.get('win_rate', 0):.1%} |
| 손익비 | {metrics.get('profit_factor', 0):.2f} |
| 총 거래 | {metrics.get('total_trades', 0)}건 |

*분석 생성일: {datetime.now().strftime('%Y-%m-%d %H:%M')}*
"""

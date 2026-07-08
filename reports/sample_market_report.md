# 📊 TSLA Market Analysis Report
### LLM-based Financial Data Reporting Pipeline — Sample Output

> ⚠️ **면책 조항**: 이 리포트는 투자 조언을 제공하지 않습니다.  
> 모든 수치는 과거 데이터 기반 시뮬레이션이며, 미래 수익을 보장하지 않습니다.  
> 이 문서는 LLM 기반 Markdown 리포트 자동 생성 기능의 **포트폴리오 증거**입니다.

---

**생성 방식**: `report/llm_reporter.py` → `LLMReporter.generate_report()` → 자동 생성  
**분석 대상**: TSLA (Tesla, Inc.)  
**LLM 엔진**: OpenAI GPT-4o-mini (또는 Ollama Llama3)

---

## 1. Data Summary

| 항목 | 값 |
|------|-----|
| 분석 기간 | 2020-01-01 ~ 2022-12-31 |
| Ticker | TSLA |
| 주가 데이터 출처 | yfinance (일봉 OHLCV) |
| 뉴스 데이터 출처 | tesla_news_2020_2022.csv |
| 수집된 뉴스 수 | {{NEWS_COUNT}} 건 |
| 주가 데이터 포인트 | {{PRICE_DAYS}} 거래일 |
| 결측치 처리 | Forward Fill (ffill) |

---

## 2. Indicator Summary

| 지표 | 최신 값 | 해석 |
|------|---------|------|
| RSI (14일) | {{RSI_14}} | {{RSI_INTERPRETATION}} |
| MACD_diff | {{MACD_DIFF}} | {{MACD_INTERPRETATION}} |
| 분석 기간 내 평균 종가 | ${{AVG_CLOSE}} | — |
| 분석 기간 내 최고가 | ${{HIGH_CLOSE}} | — |
| 분석 기간 내 최저가 | ${{LOW_CLOSE}} | — |

**추세 요약**: {{TREND_SUMMARY}}

---

## 3. News Sentiment Summary

| 항목 | 값 |
|------|-----|
| 평균 감성 점수 | {{AVG_SENTIMENT}} (-1.0 ~ 1.0) |
| 긍정 뉴스 (score > 0.1) | {{POSITIVE_COUNT}} 일 |
| 중립 뉴스 (-0.1 ~ 0.1) | {{NEUTRAL_COUNT}} 일 |
| 부정 뉴스 (score < -0.1) | {{NEGATIVE_COUNT}} 일 |
| 뉴스 커버리지 (거래일 기준) | {{NEWS_COVERAGE}}% |
| LLM JSON 파싱 성공률 | {{PARSE_SUCCESS_RATE}}% |
| Fallback 중립값 사용 횟수 | {{FALLBACK_COUNT}} 건 |

**LLM 출력 검증 방법:**
1. `response_format={"type": "json_object"}` — JSON 모드 강제
2. `json.loads` + `try-except` — 파싱 실패 시 중립값(0.0) 자동 대체
3. `Pydantic` 모델 — -1.0~1.0 범위 강력 검증

---

## 4. Backtest Metrics

> ⚠️ 아래 수치는 **과거 데이터 기반 rule-based 시뮬레이션**입니다. 실제 거래 결과가 아니며 미래 성과를 보장하지 않습니다.

### 4.1 기본 설정

| 파라미터 | 값 |
|----------|-----|
| 초기 자본 | $10,000 |
| 투자 비율 (자금 할당) | 10% |
| 익절 기준 | +15% |
| 손절 기준 | -5% |
| RSI 과매수 임계값 | 70 |
| LLM 최소 확신도 | 80 |
| 거래비용 (슬리피지 + 수수료) | 0.1% |
| 벤치마크 | S&P500 (SPY Buy & Hold) |

### 4.2 핵심 리스크 지표

| 지표 | 전략 결과 | S&P500 벤치마크 | 설명 |
|------|----------|----------------|------|
| **CAGR** | {{CAGR}} | {{BENCH_CAGR}} | 연평균 복리 수익률 |
| **MDD** | {{MDD}} | {{BENCH_MDD}} | 최대 낙폭 (Tail Risk) |
| **Sharpe Ratio** | {{SHARPE}} | {{BENCH_SHARPE}} | 위험 대비 수익률 |
| **누적 수익률** | {{TOTAL_RETURN}} | {{BENCH_TOTAL}} | 기간 전체 수익률 |
| **Alpha (vs S&P500)** | {{ALPHA}} | — | 벤치마크 대비 상대 성과 |

### 4.3 거래 통계

| 항목 | 값 |
|------|-----|
| 총 거래 횟수 | {{TOTAL_TRADES}} 건 |
| 매수 횟수 | {{BUY_COUNT}} 건 |
| 매도 횟수 | {{SELL_COUNT}} 건 |
| 승률 (Winning Trades %) | {{WIN_RATE}} |
| 손익비 (Profit Factor) | {{PROFIT_FACTOR}} |
| 평균 거래 손익 | ${{AVG_PNL}} |

### 4.4 매도 사유 분포

| 매도 사유 | 건수 |
|----------|------|
| 익절 트리거 (+15%) | {{SELL_PROFIT}} 건 |
| 손절 트리거 (-5%) | {{SELL_LOSS}} 건 |
| 부정 뉴스 (score < 0) | {{SELL_NEWS}} 건 |

---

## 5. Risk Notes

1. **역사적 시뮬레이션**: 이 결과는 과거 데이터에 기반한 시뮬레이션입니다. 실제 시장에서는 슬리피지, 유동성 제약, 급격한 가격 변동 등 추가 요인이 존재합니다.
2. **미래 수익 미보장**: 과거 성과는 미래 수익의 지표가 아닙니다.
3. **뉴스 커버리지 편향**: Google RSS는 특정 언론사에 편향될 수 있으며, 수집된 헤드라인이 시장 전체 심리를 대표하지 않을 수 있습니다.
4. **LLM 감성 불확실성**: LLM은 동일한 뉴스에 대해 다른 점수를 반환할 수 있습니다. Pydantic 검증과 fallback 중립값으로 이를 방어하고 있습니다.
5. **단일 종목 집중 리스크**: TSLA 단일 종목만 분석하며, 분산 포트폴리오 효과가 없습니다.
6. **파라미터 민감도**: 익절/손절 기준, RSI 임계값 등 파라미터 변화에 결과가 민감하게 반응할 수 있습니다.

---

## 6. LLM-generated Commentary

> 아래는 `LLMReporter.generate_report()`가 백테스트 수치를 기반으로 자동 생성한 해설입니다.  
> LLM은 투자 판단을 하지 않으며, 수치를 해석하고 구조화된 텍스트로 요약하는 역할만 수행합니다.

---

### 성과 요약

{{LLM_PERFORMANCE_SUMMARY}}

*예시 형태:*
> "분석 기간(2020~2022) 동안 전략은 CAGR {{CAGR}}를 기록했습니다. 
> 같은 기간 S&P500 Buy & Hold 대비 {{ALPHA}} 의 상대 성과를 보였습니다.
> MDD {{MDD}}는 분석 기간 내 최대 하락 위험을 나타내며, 손절 트리거가 
> 꼬리 위험을 일부 통제했음을 시사합니다."

---

### 주요 분석

{{LLM_MAIN_ANALYSIS}}

*예시 형태:*
> "Sharpe Ratio {{SHARPE}}는 위험 대비 수익률이 {{SHARPE_INTERPRETATION}}임을 의미합니다.
> 승률 {{WIN_RATE}}과 손익비 {{PROFIT_FACTOR}}를 종합하면, 
> 이 전략은 {{STRATEGY_CHARACTERISTIC}} 특성을 보입니다."

---

### 리스크 분석

{{LLM_RISK_ANALYSIS}}

*예시 형태:*
> "MDD {{MDD}}는 최대 낙폭이 상당한 수준임을 나타냅니다. 
> 부정 뉴스 감성 점수로 인한 매도({{SELL_NEWS}}건)는 Whipsaw 리스크의 
> 주요 원인으로, 감성 임계값 조정이 필요할 수 있습니다."

---

### 한계점 및 개선 방향

{{LLM_LIMITATIONS}}

*예시 형태:*
> "1. 감성 점수가 0을 약간 하회할 때 즉시 매도하는 로직은 과민 반응으로 이어질 수 있습니다.
> 2. 단일 종목 집중으로 인한 종목 특수 리스크가 크습니다.
> 3. 뉴스 커버리지가 {{NEWS_COVERAGE}}%로, 뉴스가 없는 날의 감성 점수 처리 방식을 개선할 수 있습니다."

---

## 7. Limitations

> 이 리포트와 관련하여 다음 사항을 명확히 합니다.

| 한계 | 설명 |
|------|------|
| 투자 조언 아님 | 이 리포트의 어떤 내용도 투자 판단 근거로 사용할 수 없습니다 |
| 과거 데이터 시뮬레이션 | 실제 거래가 아닌 과거 데이터 기반 백테스트 결과입니다 |
| LLM 비결정성 | LLM 출력은 실행 시마다 다를 수 있습니다 |
| 단일 종목 | TSLA 단일 종목만 분석합니다 |
| KIS API 미포함 | 이 리포트는 실제 주문 실행 결과가 아닙니다 |

---

*이 리포트는 `report/llm_reporter.py`의 `LLMReporter.generate_report()`에 의해 자동 생성되었습니다.*  
*생성 시각: {{GENERATED_AT}}*  
*LLM 모델: {{LLM_MODEL}}*  
*파이프라인 버전: nlp-quant-trade (LLM-based Financial Data Reporting Pipeline)*

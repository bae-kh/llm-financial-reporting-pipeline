# 🎯 면접 대비 — LLM 기반 금융 데이터 리포팅 파이프라인

## 프로젝트 한 줄 소개

> "금융 시계열 데이터와 뉴스 감성 분석 결과를 수집·구조화하고, 백테스트 및 리스크 지표를 LLM 기반 Markdown 리포트로 자동 생성하는 데이터 리포팅 파이프라인을 설계·배포했습니다."

> ⚠️ 이 프로젝트는 NHN AI 전환 백엔드 개발 지원에서 **메인 프로젝트(AI Text Moderation Backend)가 아닌 보조 포트폴리오**로 사용됩니다.

---

## Section 1: 핵심 기술 질문 & 답변 (8문항)

---

### Q1. 이 프로젝트는 자동매매 봇인가요?

> **아닙니다.** 이 프로젝트의 핵심은 자동매매가 아니라 **LLM 기반 Markdown 리포트 자동 생성 workflow**입니다.
>
> 금융 시계열 데이터와 뉴스를 수집하고, LLM으로 감성 점수를 추출하여 백테스트 리스크 지표(CAGR, MDD, Sharpe)를 계산한 뒤, 그 결과를 LLM이 사람이 읽을 수 있는 Markdown 리포트로 자동 생성합니다.
>
> KIS API를 통한 주문 기능은 **optional/paper execution 실험 기능**으로 분리되어 있으며, 이 포트폴리오의 핵심이 아닙니다. `KIS_ENVIRONMENT` 기본값은 `"virtual"` (모의투자)입니다.
>
> 이 경험은 LLM 기반 데이터 자동화 및 문서화 workflow 설계 역량을 보여주기 위한 보조 포트폴리오입니다.

---

### Q2. LLM이 매수/매도 판단을 하나요?

> **아닙니다.** `SYSTEM_RULES.md`에 명시된 Rule 1처럼, LLM은 두 가지 역할만 수행합니다.
>
> 1. **뉴스 감성 분석**: 뉴스 텍스트 → `{"sentiment_score": float}` JSON만 반환 (투자 판단 아님)
> 2. **리포트 자동 생성**: 백테스트 수치(CAGR, MDD, Sharpe) → 사람이 읽을 수 있는 Markdown 리포트 요약
>
> 매매 시그널 생성은 **rule-based 의사결정 트리**(RSI, MACD, 감성 점수 복합 조건)가 담당합니다. `report/llm_reporter.py`의 `system_prompt`에도 "You do NOT make investment recommendations or trading decisions"가 명시되어 있습니다.
>
> 이 설계는 LLM을 투자 판단 주체가 아닌 **데이터 구조화/문서화 계층**으로만 활용하는 원칙을 실제 코드로 구현한 것입니다.

---

### Q3. 백테스트 결과는 실제 수익률을 보장하나요?

> **아닙니다.** 백테스트 결과는 **과거 데이터 기반 시뮬레이션**이며, 미래 수익을 보장하지 않습니다.
>
> 신뢰성을 높이기 위해 세 가지를 구현했습니다:
> 1. **Look-ahead 편향 방어**: `df.iloc[:i+1]` 이터레이티브 순회로 미래 데이터 접근 차단
> 2. **거래비용 반영**: 슬리피지 + 수수료 0.1% 모든 거래에 적용
> 3. **벤치마크 비교**: S&P500 Buy & Hold 대비 상대 성과 비교
>
> 그럼에도 실제 시장의 유동성 제약, 급격한 가격 변동, 데이터 편향 등은 반영되지 않습니다. 이 프로젝트는 수익률 검증이 아니라 **리스크 지표 계산과 리포트 자동화 workflow 구현**에 집중했습니다.

---

### Q4. 왜 LLM을 리포트 생성에 사용했나요?

> 두 가지 이유입니다.
>
> 첫째, **비정형 데이터(뉴스 텍스트)를 정형 데이터(감성 점수)로 변환**하는 과정에서 LLM이 적합합니다. 기존 rule-based 키워드 분석보다 문맥 이해가 뛰어납니다.
>
> 둘째, **정량 지표(CAGR, MDD, Sharpe)를 사람이 이해하기 쉬운 서술로 변환**하는 데 LLM이 효과적입니다. 이는 NHN에서 AI 관련 문서나 분석 가이드를 자동 생성하는 업무와 동일한 구조입니다.
>
> 다만 LLM 출력의 비결정성 문제를 해결하기 위해 3중 방어막(JSON 모드 강제, try-except fallback, Pydantic 검증)을 구현하여 시스템 안정성을 확보했습니다.

---

### Q5. LLM output을 어떻게 검증했나요?

> 3단계 방어 구조를 구현했습니다. (`nlp_engine/analyzer.py` 참고)
>
> **1단계**: `response_format={"type": "json_object"}` — OpenAI JSON 모드 강제로 비정형 텍스트 반환 차단
>
> **2단계**: `json.loads()` + `try-except` — 파싱 실패 시 시스템 중단 없이 중립값(0.0) 자동 대체
>
> **3단계**: `Pydantic` 모델 검증 — `SentimentResult` 클래스로 감성 점수가 -1.0~1.0 범위를 벗어나면 강제 클리핑
>
> 이 방어 구조는 `test_analyzer.py`의 10개 테스트 케이스로 검증되었습니다 (JSON 파싱 실패, 범위 초과, 타임아웃 등 엣지 케이스 포함).

---

### Q6. KIS API 연동은 어떤 의미인가요?

> KIS API 연동은 이 포트폴리오의 핵심 기능이 아닙니다.
>
> `auto_trade.py`에 KIS API 주문 실행 코드가 있지만, 이는 **optional/paper execution 실험 기능**입니다. `KIS_ENVIRONMENT` 기본값은 `"virtual"` (모의투자 서버)이며, 실전 전환은 명시적 설정 변경이 필요합니다.
>
> 이 프로젝트에서 강조하고 싶은 것은 주문 안정성이나 실거래 성과가 아닙니다. `auto_trade.py`는 **데이터 수집 + 감성 분석 + rule-based 시그널 평가 + 선택적 주문 실행** 파이프라인의 오케스트레이터 역할을 합니다.
>
> 실거래보다는 데이터 수집, LLM 분석, 리포트 생성 workflow의 end-to-end 구현이 핵심입니다.

---

### Q7. 이 프로젝트가 NHN AI 전환 백엔드 개발과 어떻게 연결되나요?

> 세 가지 영역에서 연결됩니다.
>
> **첫째, AI 문서 자동화**: LLM이 정량 분석 수치(CAGR, MDD, Sharpe)를 한국어 Markdown 리포트로 자동 변환하는 경험은, NHN에서 AI 관련 문서·가이드·위키를 LLM으로 자동 생성하는 업무에 직접 적용 가능합니다.
>
> **둘째, Python 데이터 파이프라인**: 데이터 수집 → LLM 분석 → 지표 계산 → 리포트 → 대시보드의 풀스택 구현 경험이 AX 전환 workflow 설계에 연결됩니다.
>
> **셋째, Linux/EC2 배치 실행**: AWS EC2에서 Linux Crontab으로 배치 스케줄링을 구성한 경험이 서버 사이드 Python 백엔드 운영 역량을 보여줍니다.
>
> 이 프로젝트는 메인 포트폴리오(AI Text Moderation Backend)를 보완하는 보조 포트폴리오로, LLM workflow 활용 경험을 추가로 어필합니다.

---

### Q8. 현재 기술 부채와 개선 계획은 무엇인가요?

> 세 가지 주요 기술 부채를 인식하고 있으며 투명하게 공개합니다.
>
> **첫째, 시그널 평가 로직 3중 중복**: `auto_trade.py`, `backtest/engine.py`, `backtest/news_backtest.py`에 매도/매수 평가 로직이 중복됩니다. → `strategy/rule_engine.py`로 추출하여 해결 계획
>
> **둘째, Dead code**: `FINNHUB_API_KEY` 미사용, `get_hourly_data()` 미사용 → 제거 예정
>
> **셋째, `requirements.txt` 버전 미고정**: 배포 재현성 위험 → 버전 pinning 예정
>
> 이 부채들은 "완벽한 포폴"보다 "엔지니어링 현실을 아는 개발자"를 어필하기 위해 투명하게 공개하는 것입니다. 후속 Phase에서 `strategy/rule_engine.py` 분리와 버전 고정을 진행할 예정입니다.

---

## Section 2: 아키텍처 & 설계 질문

### Q. 전체 데이터 흐름을 설명해주세요.

```
외부 데이터 소스 (yfinance + Google News RSS)
        ↓
데이터 수집 (PriceFetcher + NewsFetcher)
        ↓
LLM 감성 분석 (SentimentAnalyzer) + 3중 출력 검증
        ↓
rule-based 시그널 조건 평가 (RSI + MACD + 감성 게이트)
        ↓
백테스트 시뮬레이션 (BacktestEngine / NewsBacktestEngine)
        ↓
리스크 지표 계산 (RiskMetrics: CAGR, MDD, Sharpe, Alpha)
        ↓
LLM 기반 Markdown 리포트 자동 생성 (LLMReporter) ⭐
        ↓
SQLite 이벤트 로깅 + Streamlit 대시보드 시각화
```

### Q. 왜 OOP로 설계했나요?

> 초기에는 단일 함수에 인증·분석·기록이 혼재되어 단위 테스트가 불가능했습니다. `TradingEngine` OOP 클래스로 리팩토링하여 각 메서드를 독립적으로 테스트할 수 있게 했고, 매수/매도 주문 함수의 중복 코드를 `_execute_order()`로 통합 제거했습니다. 의존성 주입(`Settings` 클래스)으로 환경 분기(모의/실전, OpenAI/Ollama)를 코드 수정 없이 전환할 수 있습니다.

---

## Section 3: 회사별 어필 포인트

### NHN AI 전환 백엔드

> "금융 데이터를 활용해 LLM 기반 데이터 수집·분석·리포트 자동화 파이프라인을 구현한 경험이 있습니다. LLM output 검증, Python 데이터 파이프라인, EC2/Linux 배치 실행 경험이 AI 전환 백엔드 개발과 연결됩니다."

**어필 포인트**: LLM workflow, Python 데이터 파이프라인, 문서 자동화, Linux/EC2 배치

---

## Section 4: 위험 질문 방어

### Q. 이 프로젝트가 NHN 직무와 무슨 관련이 있나요?

> 도메인은 금융이지만 핵심 구조는 **데이터 수집 → LLM 분석 → 자동 리포팅**입니다. 이는 AI 관련 문서·가이드 자동화, AX 전환 workflow, 데이터 파이프라인 설계에 직접 적용 가능한 경험입니다.

### Q. 회사 다니면서 개인 투자를 하려는 건 아닌가요?

> 이 프로젝트는 투자 수익이 목표가 아닙니다. 금융 데이터는 시계열 처리와 LLM 활용을 연습하기에 좋은 도메인이며, 포트폴리오의 핵심은 **데이터 파이프라인, LLM 문서 자동화, 리포트 생성 workflow** 구현입니다.

### Q. 실제로 돈을 벌었나요?

> 이 프로젝트는 실거래 수익을 목표로 하지 않습니다. 백테스트 결과는 과거 데이터 기반 시뮬레이션이며 실거래 결과가 아닙니다. 실수익보다 **리스크 지표 계산 정확성과 리포트 자동화 workflow** 구현이 목표였습니다.

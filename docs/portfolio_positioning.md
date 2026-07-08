# Portfolio Positioning Analysis
### LLM 기반 금융 데이터 리포팅 파이프라인 — NHN AI 전환 백엔드 개발 지원용 보조 포트폴리오

> **작성 목적**: 이 문서는 이 프로젝트를 NHN AI 전환 백엔드 개발 지원용 보조 포트폴리오로 재포지셔닝하기 위한 분석 문서입니다.

---

## 1. 현재 프로젝트의 위험 요소 요약

### 위험 요인

| 위험 | 설명 | 영향 |
|------|------|------|
| "자동매매 봇" 인상 | `TradingEngine`, KIS API 주문, Crontab 실행이 결합되어 자동매매 봇처럼 보임 | 면접관의 관심이 AI 백엔드가 아닌 투자 전략·금융 규제로 쏠릴 수 있음 |
| "수익률 검증 프로젝트" 인상 | 백테스트 결과, Alpha, CAGR 강조 | "이 전략으로 돈 벌었나요?" 방향으로 질문이 흐를 수 있음 |
| KIS API 실주문 연동 | README에서 메인 기능처럼 소개 | 자동매매 규제, 증권사 API 안정성 질문으로 전환될 수 있음 |
| live trading과 reporting 혼재 | 같은 파이프라인에 실주문 + 리포트 생성이 공존 | 포트폴리오 포지셔닝이 불명확해짐 |

---

## 2. 새 포지셔닝 요약

### 변경 전후 비교

| 구분 | 변경 전 | 변경 후 |
|------|--------|--------|
| 프로젝트명 | NLP 퀀트 트레이딩 자동매매 파이프라인 | **LLM-based Financial Data Reporting Pipeline** |
| 한국어명 | NLP 하이브리드 퀀트 트레이딩 시스템 | **LLM 기반 금융 데이터 자동 리포팅 파이프라인** |
| 핵심 기능 | KIS API 자동 매수/매도 봇 | **LLM 기반 Markdown 리포트 자동 생성** |
| LLM 역할 | 감성 점수 추출 (수익 최대화 입력) | **감성 분석 + 리포트 자동 생성 (투자 판단 아님)** |
| KIS API | 메인 기능 (자동매매 실행) | **Optional / paper / mock execution 실험** |
| 백테스트 강조 | 수익률 검증, Alpha 창출 | **rule-based 시뮬레이션, 리스크 지표 계산** |
| NHN 연결 | 금융 AI → NHN 적용 (억지스러움) | **LLM 문서 자동화 → AI 관련 문서/위키 작성 (자연스러움)** |

### 새 한 줄 요약

> "금융 시계열 데이터와 뉴스 감성 분석 결과를 수집·구조화하고, 백테스트 및 리스크 지표를 LLM 기반 Markdown 리포트로 자동 생성하는 데이터 리포팅 파이프라인입니다."

---

## 3. 코드 기준 기능 재분류

### 3.1 포트폴리오 메인 범위 (강조할 기능)

| 기능 | 확인 파일 | 코드 근거 | 포트폴리오용 안전 표현 |
|------|----------|----------|----------------------|
| 주가 데이터 수집 | `data_pipeline/price_fetcher.py` | `yf.download()` + `ta` 라이브러리 RSI/MACD | "yfinance 기반 금융 시계열 데이터 수집 및 기술적 지표 계산" |
| 뉴스 헤드라인 수집 | `data_pipeline/news_fetcher.py` | Google News RSS XML 파싱 | "Google News RSS 기반 뉴스 헤드라인 크롤링" |
| LLM 감성 분석 | `nlp_engine/analyzer.py` | `AsyncOpenAI`, Pydantic `SentimentResult` | "LLM 기반 비정형 뉴스 텍스트 감성 점수 추출" |
| LLM 출력 검증 | `nlp_engine/analyzer.py` | JSON 모드, try-except, Pydantic -1.0~1.0 | "3중 방어막 기반 LLM output 검증 (JSON/Pydantic/fallback)" |
| 백테스트 시뮬레이션 | `backtest/engine.py`, `news_backtest.py` | `df.iloc[:i+1]` Look-ahead 방어, 거래비용 반영 | "Look-ahead 편향 방어 rule-based 시뮬레이션" |
| 리스크 지표 계산 | `backtest/metrics.py` | `calculate_cagr()`, `calculate_mdd()`, `calculate_sharpe_ratio()` | "CAGR/MDD/Sharpe/벤치마크 비교 리스크 지표 계산" |
| **Markdown 리포트 자동 생성** ⭐ | `report/llm_reporter.py` | `generate_report()` → LLM → 구조화된 Markdown | "LLM 기반 백테스트 결과 Markdown 리포트 자동 생성" |
| Streamlit 대시보드 | `app.py` | `st.metric()`, Plotly 에쿼티 커브 | "Streamlit 기반 리포팅 대시보드" |
| EC2/Crontab 배치 실행 | `auto_trade.py` + EC2 crontab | `매일 23:35 Linux crontab` | "Linux EC2 환경 배치 스케줄링" |
| pytest 테스트 | `tests/` 5개 파일 | 54개 테스트 케이스 | "54개 단위 테스트 (LLM 파싱 방어, 경계값, DB 무결성)" |

### 3.2 보조/실험 기능으로 낮출 기능

| 기능 | 왜 낮춰야 하는가 | README에서의 안전 표현 | 필요 시 삭제/이동 여부 |
|------|----------------|----------------------|----------------------|
| KIS API 주문 실행 | 자동매매 봇 인상 + 금융 규제 질문 유발 | "Optional / paper / mock execution 실험 기능" | 삭제 불필요, 코드 유지 + 설명 낮추기 |
| `TradingEngine` live order | 같은 이유 | "rule-based 시그널 평가 엔진 (주문 실행은 optional)" | 클래스명 유지, docstring 수정 |
| 텔레그램 실시간 알림 | "자동매매 봇 가동" 인상 | "파이프라인 실행 모니터링 알림 (Optional)" | 코드 유지 + 설명 낮추기 |
| V2 수익률 튜닝 | "수익 극대화" 인상 | "전략 조건 변화에 따른 파라미터 민감도 분석" | 코드 유지 + 제목 변경 |

### 3.3 README/docs에서 제거/대체한 위험 표현

| 위험 표현 | 왜 위험한가 | 안전한 대체 표현 |
|----------|-----------|----------------|
| 실전 자동 매매 시스템 | 자동매매 봇 인상, 금융 규제 질문 유발 | "데이터 수집 및 리포팅 파이프라인" |
| 자율주행 매매 시스템 | 완전 자동화 투자 시스템 인상 | "LLM 기반 금융 데이터 리포팅 파이프라인" |
| 퀀트봇 가동 | 봇 = 자동매매 인상 | "데이터 수집 파이프라인 시작" |
| 수익 극대화 | 투자 성과 보장 오해 | "전략 파라미터 민감도 분석" |
| Alpha 창출 | 초과 수익 보장 오해 | "벤치마크 대비 상대 성과 비교" |
| 초과 수익 검증 | 성과 보장 오해 | "벤치마크 대비 상대 성과 비교 지표" |
| 자동 주문 | 자동매매 인상 | "선택적 paper/mock execution" |
| 투자 전략 성과 검증 | 투자 성과 보장 오해 | "rule-based 시뮬레이션 지표 비교" |

---

## 4. 강조할 점과 강조하면 안 되는 점

### 강조할 점 ✅

- LLM은 직접 매매 판단을 하지 않음 (`system_prompt`에 명시, `SYSTEM_RULES.md` Rule 1)
- 정량 규칙과 지표 계산 결과를 사람이 읽을 수 있는 Markdown 리포트로 변환
- 리포트 자동화 workflow: 수집 → 분석 → 리스크 지표 → 리포트 → 대시보드
- LLM 출력 방어: JSON parsing, fallback neutral, Pydantic validation
- 54개 단위 테스트 (LLM parsing defense, decision boundary, backtest metrics, DB logging)
- EC2 + Linux Crontab 배치 실행 경험
- 기술 부채 인식 및 투명한 공개

### 강조하면 안 되는 점 ⛔

- 실제 투자 성과 (실거래 결과가 아님)
- 자동매매 봇 완성도 (live trading이 목적이 아님)
- 수익률 극대화 (포트폴리오 목적이 아님)
- 실전 주문 안정성 (KIS API는 optional 기능)
- 투자 추천 서비스 (어떠한 투자 판단도 제공하지 않음)

---

## 5. NHN AI 전환 백엔드 개발 JD 연결 포인트

### 자연스러운 연결 영역

| NHN JD 요구사항 | 이 프로젝트의 증명 |
|----------------|-------------------|
| AI 관련 문서/가이드/위키 작성 | LLM이 백테스트 수치 → Markdown 리포트 자동 변환 |
| AX 전환 workflow 설계 | 데이터 수집 → LLM 분석 → 자동 리포팅 workflow |
| Python 데이터 파이프라인 | price_fetcher + news_fetcher + analyzer + reporter 풀스택 |
| LLM 활용 경험 (Agentic AI) | OpenAI/Ollama 스위칭, prompt engineering, output validation |
| Linux/EC2 배치 실행 | AWS EC2 + Crontab 스케줄링 경험 |
| 데이터 자동화 | SQLite 로깅, Streamlit 대시보드, 배치 실행 |

### 면접에서 방어 가능한 핵심 메시지 (3~5문장)

> "이 프로젝트는 자동매매 봇이 아닙니다. 금융 시계열 데이터와 뉴스를 수집하고, LLM으로 감성 점수를 추출하여 백테스트 리스크 지표를 계산한 뒤, 그 결과를 LLM이 사람이 읽을 수 있는 Markdown 리포트로 자동 생성하는 **데이터 리포팅 파이프라인**입니다. LLM은 투자 판단 주체가 아니라 데이터를 구조화하고 문서화하는 계층으로만 사용했습니다. KIS API 주문 기능은 선택적 실험 기능이며, 이 포트폴리오의 핵심은 live trading이 아닙니다. 이 경험은 NHN에서 AI 관련 문서나 가이드를 LLM으로 자동 생성하거나, 데이터 파이프라인을 구축하는 업무에 직접 적용할 수 있다고 생각합니다."

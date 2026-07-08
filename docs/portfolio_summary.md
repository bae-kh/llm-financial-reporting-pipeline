# Portfolio Summary
## LLM-based Financial Data Reporting Pipeline
### NHN AI 전환 백엔드 개발 지원 — 보조 포트폴리오

> ⚠️ 이 프로젝트는 **투자 자문 또는 자동매매 성과 검증 프로젝트가 아닙니다.**  
> LLM 기반 데이터 파이프라인과 리포트 자동화 경험을 보여주기 위한 **리포팅 자동화 프로토타입**입니다.

---

### Project Summary

금융 시계열 데이터와 뉴스 감성 분석 결과를 수집·구조화하고, 백테스트 및 리스크 지표를 **LLM 기반 Markdown 리포트로 자동 생성하는 데이터 리포팅 파이프라인**을 설계·배포했습니다.

- **LLM 역할**: 뉴스 텍스트 감성 점수 추출 + 백테스트 수치 → Markdown 리포트 자동 변환 (투자 판단 주체 아님)
- **운영 환경**: AWS EC2 + Linux Crontab 배치 스케줄링, Streamlit 대시보드
- **이 프로젝트의 핵심**: live trading이 아닌 **데이터 수집 → 감성 분석 → 리스크 지표 → 리포트 자동 생성** workflow

---

### Implementation Scope

| 영역 | 구현 내용 |
|------|----------|
| **데이터 수집** | yfinance 주가 데이터 (RSI/MACD 포함) + Google News RSS 뉴스 헤드라인 |
| **LLM 감성 분석** | OpenAI GPT-4o-mini / Ollama Llama3 스위칭, JSON 모드 강제 |
| **LLM output 검증** | 3중 방어막: JSON 파싱 방어 + fallback 중립값 + Pydantic 범위 검증 |
| **백테스트** | Look-ahead 편향 방어, 거래비용 반영, 몬테카를로 + 실제 뉴스 기반 2모드 |
| **리스크 지표** | CAGR, MDD, Sharpe Ratio, 벤치마크 상대 성과 비교 |
| **리포트 자동 생성** ⭐ | LLM → 백테스트 결과 → 구조화된 Markdown 리포트 (핵심 기능) |
| **대시보드** | Streamlit (에쿼티 커브, 이벤트 로그, 지표 카드) |
| **배치 실행** | EC2 + Linux Crontab 일간 스케줄 |
| **테스트** | pytest 54개 단위 테스트 (LLM parsing, 경계값, 리스크 지표, DB) |

---

### LLM Usage

LLM을 두 가지 역할로만 한정하여 사용했습니다:

1. **뉴스 감성 분석**: 뉴스 헤드라인 → `{"sentiment_score": float}` JSON 반환 (투자 판단 아님)
2. **리포트 자동 생성**: CAGR, MDD, Sharpe 등 수치 → 사람이 읽을 수 있는 한국어 Markdown 리포트

LLM 출력 신뢰성 확보:
- `response_format={"type": "json_object"}` — JSON 강제
- `try-except` fallback — 파싱 실패 시 중립값(0.0) 자동 대체
- `Pydantic` 모델 — 출력 범위(-1.0~1.0) 강력 검증

---

### Result / Evidence

| 항목 | 증거 |
|------|------|
| 리포트 자동 생성 | `reports/sample_market_report.md` — 샘플 리포트 구조 확인 가능 |
| 테스트 통과 | pytest 54 passed (LLM 파싱 방어, 경계값, 리스크 지표 정확성) |
| AWS 배포 | EC2 + Crontab 매일 23:35 자동 실행 구성 |
| 코드 구조 | OOP 클래스 기반, 의존성 주입, 모듈화 |

---

### Limitations

- **투자 조언 아님**: 이 시스템의 출력물은 어떠한 투자 판단의 근거로도 사용할 수 없습니다.
- **백테스트 ≠ 실거래**: 과거 데이터 기반 시뮬레이션이며 미래 수익을 보장하지 않습니다.
- **KIS API**: 실주문 기능은 optional/paper 실험 영역이며, 이 포트폴리오의 핵심이 아닙니다.
- **기술 부채 인식**: 시그널 로직 중복, 미사용 코드, 버전 미고정 등 — 후속 리팩토링 계획 존재

---

### NHN JD Connection

이 프로젝트는 NHN AI 전환 백엔드 개발 메인 포트폴리오(AI Text Moderation Backend)를 보완하는 **보조 포트폴리오**입니다.

**연결 포인트:**

- **AI 관련 문서/가이드 자동화**: LLM이 정량 분석 수치를 Markdown 리포트로 자동 변환한 경험 → AI 관련 문서, 위키 작성 자동화 업무에 직접 적용 가능
- **AX 전환 workflow**: 데이터 수집 → LLM 분석 → 자동 리포팅이라는 Agentic AI 기반 workflow 설계 경험
- **Python 데이터 파이프라인**: 데이터 수집, 처리, 저장, 시각화 풀스택 구현 경험
- **Linux/EC2 배치 실행**: 실제 클라우드 환경 배포 및 운영 경험
- **LLM output 검증**: 비결정적 LLM 출력을 안정적으로 처리하는 방어 구조 설계 경험

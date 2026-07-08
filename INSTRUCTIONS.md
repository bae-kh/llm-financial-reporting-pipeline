## 코드 작성 규칙 (INSTRUCTIONS)

이 규칙은 **LLM 기반 금융 데이터 리포팅 파이프라인**의 코드 작성 시 반드시 지켜야 할 가이드라인입니다.

> ⚠️ **프로젝트 정체성**: 이 프로젝트는 투자 자문 또는 자동매매 성과 검증 시스템이 아닙니다.  
> 금융 데이터 수집, LLM 감성 분석, 백테스트 지표 계산, Markdown 리포트 자동 생성 workflow를 보여주는 **리포팅 자동화 프로토타입**입니다.

1. **사용 기술**: Python 3.10 이상을 사용하며, 주가 데이터는 `yfinance`, 기술적 지표는 `ta` 라이브러리를 사용합니다. KIS API는 optional/paper execution 실험 기능으로만 사용합니다.

2. **보안**: API 키(OpenAI, KIS App Key/Secret, 텔레그램 토큰 등)는 절대 코드 내부에 텍스트로 작성하지 않습니다. 반드시 `os.environ`을 통해 `.env` 파일에서만 불러오며, `.env` 파일은 Git에 커밋하지 않습니다. 신규 참여자는 `.env.example` 템플릿을 복사하여 사용합니다.

3. **폴더 구조**:
    - `config/`: 환경 변수 및 전략 파라미터 중앙 관리 (`Settings` 클래스)
    - `data_pipeline/`: 주가 데이터 수집 (`PriceFetcher`) 및 뉴스 크롤링 (`NewsFetcher`)
    - `nlp_engine/`: LLM 기반 감성 분석 (`SentimentAnalyzer`) — 투자 판단 아님
    - `database/`: SQLite 이벤트 로깅 (`DBLogger`)
    - `notifications/`: 파이프라인 실행 알림 (`TelegramNotifier`) — Optional
    - `report/`: LLM 기반 Markdown 리포트 자동 생성 (`LLMReporter`) — **핵심 기능**
    - `reports/`: 생성된 리포트 저장 (`sample_market_report.md` 포함)
    - `docs/`: 포트폴리오 문서, 면접 대비, 한계 설명
    - `tests/`: 단위 테스트 (pytest)

4. **안전장치**: 모든 외부 API 호출(KIS, OpenAI, yfinance, 텔레그램, 뉴스 RSS)에는 반드시 `timeout`과 `try-except` 예외 처리를 적용하여, 네트워크 에러나 타임아웃 발생 시 프로그램이 비정상 종료되지 않고 로그를 남기도록 처리합니다.

5. **전략 파라미터**: 익절/손절 비율, RSI 임계값, 자금 할당 비율 등 모든 매직 넘버는 `config/settings.py`의 `Settings` 클래스에 집약합니다. 코드에 직접 숫자를 넣지 않습니다.

6. **환경 분기**: `KIS_ENVIRONMENT` 환경 변수 값(`"virtual"` 또는 `"production"`)으로 모의투자/실전 환경이 자동 전환됩니다. 기본값은 `"virtual"` (모의투자)이며, 실전 전환은 명시적 설정 변경이 필요합니다.

7. **LLM 역할 한정**: LLM은 감성 점수 추출(`{"sentiment_score": float}`)과 Markdown 리포트 생성에만 사용합니다. LLM이 직접 매수/매도 판단을 내리는 코드는 작성하지 않습니다.

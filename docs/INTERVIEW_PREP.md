# Interview Preparation: NLP Momentum Quant System

본 문서는 미국 주식(US Equity) 기반 NLP 퀀트 파이프라인의 설계 의도, 핵심 아키텍처 및 면접 대비를 위한 기술적 트레이드오프(Trade-offs)를 분석합니다.

## 1. Data Flow Architecture (데이터 파이프라인 흐름)

전체 시스템은 다음과 같이 독립적이고 단방향적인(Unidirectional) 데이터 파이프라인을 가집니다.

1. **데이터 수집 레이어 (`data_pipeline/`)**:
   - `price_fetcher.py`: yfinance API를 통해 OHLCV 주가 데이터를 Fetch하고, `ta` 라이브러리로 RSI(14)와 MACD_diff 기술적 지표를 계산합니다.
   - `news_fetcher.py`: Google News RSS를 통해 대상 종목의 최신 금융 기사 헤드라인을 수집합니다.
2. **분석 레이어 (`nlp_engine/`)**:
   - `analyzer.py`: 수집된 원시 뉴스 텍스트를 OpenAI GPT 모델(또는 Ollama 로컬 LLM)에 주입합니다. 이때 LLM 모델은 어떤 자체적인 '매매 판단'도 하지 않으며, 설계된 규칙(SYSTEM-PROMPT)에 따라 문맥의 극성을 평가하고 `{"sentiment_score": 0.xx}`라는 규격화된 수치형(Float) 결과만 반환합니다.
3. **의사결정 & 실행 레이어 (`auto_trade.py`)**:
   - `TradingEngine` 클래스가 `price_fetcher`의 기술적(TA) 지표 신호(RSI, MACD)와 `analyzer`가 계산한 `sentiment_score`를 다중 게이트 의사결정 트리로 교차 검증하여 최종 Buy/Sell/Hold 시그널을 결정하고, KIS 증권사 API를 통해 주문을 실행합니다.
4. **로깅 & 모니터링 레이어 (`database/` & `notifications/`)**:
   - `DBLogger`가 모든 트랜잭션을 SQLite에 기록하고, `TelegramNotifier`가 실시간 알림을 전송합니다. Streamlit 대시보드(`app.py`)가 DB 데이터를 시각화합니다.

---

## 2. Trade-offs: LLM 필터(분석기) vs LLM 트레이더(결정자)

LLM에게 직접 매수/매도를 결정하게 하지 않고, 오직 '감성 점수 텍스트 필터'로만 제한하는 아키텍처 설계의 득실은 다음과 같습니다.

### 장점 (Pros)
- **통제성 및 결정론적 로직 보장**: 매매 체결과 포지션 사이징 로직은 전통적인 통계 기반 코드(If-else/수학 모델)로 작성되므로, 수학적 모델링에 의한 안정적인 리스크 관리가 가능합니다. 환각(Hallucination) 현상이 직접적인 주문 에러로 이어지지 않습니다.
- **백테스팅 신뢰도 향상**: LLM의 답변이 시점이나 온도(Temperature)에 의해 미세하게 달라지더라도, 변환된 `sentiment_score`를 Threshold(임계값)로 자르기 때문에 백테스트 검증의 재현성(Reproducibility)이 크게 높아집니다.
- **성능 및 비용 최적화**: LLM은 텍스트 요약 단계에만 호출되고, 실시간 틱(Tick) 단위의 체결 평가는 연산 속도가 빠른 로컬 머신에서 처리합니다.

### 단점 (Cons)
- **맥락의 소실**: 복합적이고 거시적인 시장의 '뉘앙스'를 단순히 -1.0에서 1.0 사이의 숫자 하나로 압축해 버리므로, 정보의 손실(Information Loss)이 발생할 수 있습니다.
- **지연 시간(Latency) 이슈**: 뉴스 발생 후 LLM 토큰을 돌고 결과가 파싱되어 나오기까지 최소 0.5초에서 수 초의 병목(Bottleneck)이 발생하여 HFT(고빈도 매매)에는 적용이 불가능합니다.

---

## 3. Expected Interview Questions (예상 압박 질문 3선 및 답변 가이드)

### Q1. "단순히 프롬프트 지시만으로 JSON 파싱을 보장할 수 있나요? LLM이 갑자기 'Here is the result...'와 같은 불필요한 텍스트를 반환하면 시스템이 크래시(Crash) 되는 것 아닌가요?"
**A (모범 답변 가이드)**: 
LLM의 비결정론적 출력 포맷팅 문제는 프롬프트 엔지니어링만으로는 100% 방어할 수 없습니다. 따라서 저는 시스템 레벨에서 3중 방어막을 구축했습니다.
첫째, OpenAI API 호출 시 `response_format={"type": "json_object"}` 옵션을 강제하여 백엔드 단에서 JSON 반환 확률을 높입니다.
둘째, 파이썬 코드 레벨에서 `json.loads`에 철저한 `try-except json.JSONDecodeError`를 적용해 파싱 에러 시 즉시 `0.0 (중립)`으로 대체값을 던져 전체 프로그램의 크래시를 막습니다.
셋째, Pydantic 모델(`SentimentResult(BaseModel)`)을 적용해 반환된 float 값이 `-1.0`과 `1.0` 사이 범위(`ge=-1.0, le=1.0`)인지 강력하게 구문별/의미별 검증(Validation)을 통과하도록 보수적인 방어 코드를 작성했습니다. (에러 발생 시 즉각 0.0 처리)

### Q2. "LLM을 단순히 감성 분석기로만 쓸 거면, 더 빠르고 저렴한 전통적 NLP 딥러닝 모델(예: FinBERT)을 쓰지 않고 굳이 비싸고 느린 GPT 파운데이션 모델을 쓴 이유가 무엇입니까?"
**A (모범 답변 가이드)**: 
FinBERT 기반의 모델은 빠른 추론 속도와 낮은 비용이라는 명확한 장점이 있습니다. 하지만 최근의 금융 환경에서는 뉴스와 인터넷의 컨텍스트(예: "머스크가 강아지 사진을 올렸다" 혹은 "파월 의장의 발언에서 '일시적'이라는 단어가 빠졌다")에 의존하는 경향이 강합니다.
단순 형태소와 감성어가 아니라 문장 이면의 풍자, 복잡성을 인지하는 "Zero-shot 문맥 추론" 능력 측면에서 GPT 모델, 특히 GPT-4o 클래스 언어 모델이 압도적인 성능을 보입니다. 비용이나 속도 병목은 로컬 뉴스 필터링 알고리즘이나 병렬 비동기(Async) 처리를 통해 극복할 수 있다고 판단했습니다.

### Q3. "설계하신 아키텍처에 따르면, 만약 OpenAI 서버가 터지거나(Timeout) 타임아웃에 걸려 응답을 5초 이상 늦게 할 경우 매매 파이프라인 전체가 병목에 걸려 멈추는 동기적 블로킹(Thread Blocking) 결함이 있어 보입니다. 어떻게 해결하셨나요?"
**A (모범 답변 가이드)**: 
지적해주신 대로 동기식(Synchronous) 구조라면 심각한 결함이 됩니다.
이를 방지하기 위해 `SentimentAnalyzer`는 `AsyncOpenAI` 클라이언트를 사용하여 비동기적으로 LLM을 호출합니다.
만약 LLM API에서 허용 Timeout인 10초 내에 응답이 오지 않으면, `OpenAIError`를 캐치하여 해당 주기의 센티먼트를 강제 중립(0.0)으로 리턴합니다. 이 방어 로직은 `tests/test_analyzer.py`의 `test_timeout_returns_neutral` 테스트 케이스에서 검증됩니다. `TradingEngine.run()` 내부에서는 `asyncio.run()`으로 호출하여 동기식 파이프라인에서도 호환되게 브릿징(Bridging)합니다.

### Q4. "초기 데이터 파이프라인 구축 시 Alpaca나 Interactive Brokers 같은 안정적인 브로커 전용 API를 두지 않고 `yfinance`를 채택한 엔지니어링적 이유는 무엇입니까?"
**A (모범 답변 가이드)**: 
가장 큰 이유는 '빠른 프로토타이핑(Rapid Prototyping)'과 '비용 효율성'입니다.
`yfinance`는 별도의 계정 연동이나 API Key 발급 절차 없이도 즉각적으로 과거 수십 년 치의 광범위한 OHLCV 데이터를 무료로 가져올 수 있습니다. 시스템의 핵심 설계 사상이 'NLP 분석 엔진과 모멘텀의 결합'을 입증하는 것에 있었으므로 초기 PoC(Proof of Concept) 단계에서는 `yfinance`로 백테스팅 구조를 우선 확립하는 것이 애자일(Agile)한 접근이라 판단했습니다. 추후 실거래(Live Trading) 환경이 마련되면 객체지향의 장점(다형성)을 살려 `PriceFetcher` 모듈 내부의 메서드만 Alpaca API로 교체하면 되므로 확장성에도 문제가 없습니다.

### Q5. "데이터 전처리 과정에서 결측치(NaN)를 제거(Drop)하지 않고 앞의 값으로 채우는 `ffill()` 방식을 사용한 이유는 무엇입니까?"
**A (모범 답변 가이드)**: 
시계열 퀀트 데이터에서 결측치를 단순 제거(`dropna`)해 버릴 경우 시간의 연속적 타임라인이 왜곡되어 버립니다. 예를 들어 이동평균선을 계산할 때 날짜 간격이 틀어지는 치명적인 로직 오류가 발생하게 됩니다.
`ffill` (Forward Fill) 방식을 택한 이유는 주식 시장의 특성 때문입니다. 특정 시간대에 거래 데이터가 없거나 서버 다운으로 가격이 누락되었을 경우, 시장 참여자가 인식하는 '현재 가격'은 직전 수집된 가장 최근의 체결가(Last Traded Price)입니다. 따라서 이전 가격을 그대로 유지하는 `ffill`이 실제 시장 상황의 팩터를 가장 잘 반영하며, 백테스트 시 모델이 미래의 가격을 미리 당겨 쓰는 Look-ahead 편향(Bias)도 완벽히 방지할 수 있습니다.

### Q6. "모멘텀(가격) 지표와 NLP(감성) 지표를 결합하는 하이브리드 전략(Hybrid Strategy)이 퀀트 관점에서 '휩쏘(Whipsaw, 거짓 신호)'를 방어하는 논리적 원리는 무엇입니까?"
**A (모범 답변 가이드)**: 
전통적인 이동평균(SMA) 기반의 모멘텀 전략은 추세가 명확할 때 강력하지만, 횡보장에서는 단기적인 가격 변동에 의해 매수/매도 시그널이 반복해서 발생하는 치명적인 '휩쏘(Whipsaw)' 현상을 초래합니다. 
NLP 감성 지표를 모멘텀의 필터(Filter)로 결합하면 이 문제를 획기적으로 줄일 수 있습니다. 가격이 이동평균선을 돌파하더라도 (기술적 매수 신호), NLP 감성 점수가 기준치(예: 0.2)를 넘지 않으면 이는 '재료 없는 기술적 반등(Fakeout)'으로 간주해 매수를 보류(HOLD)합니다. 반대로 악재로 인해 NLP 감성이 급락(-0.2 이하)할 경우, 가격이 아직 이동평균선 위에 있더라도 선제적으로 전량 매도(SELL)를 쳐서 하락장 진입 전 리스크를 회피할 수 있습니다. 즉, 가격은 '실행 타이밍'을 잡고, NLP 뉴스는 '추세의 진위 여부'를 판별하는 상호 보완재 역할을 합니다.

### Q7. "NLP 퀀트 모델을 과거 수십 년 치 데이터로 백테스트할 때, 그 막대한 양의 뉴스 데이터를 LLM에 전부 돌리면 엄청난 API 비용과 소요 시간이 발생할 텐데 이 병목(Bottleneck)을 어떻게 우회(Mitigation) 했습니까? 또한, 그 과정에서 나타날 수 있는 Look-ahead 편향(Data Leakage)은 어떻게 방어했나요?"
**A (모범 답변 가이드)**: 
초기 백테스트 단계에서 모든 과거 뉴스에 OpenAI API를 호출하는 것은 자원/비용 낭비가 매우 극심합니다. 현재 시스템에서는 **의사결정 로직 자체의 검증**에 집중하는 접근을 택했습니다. `tests/test_decision_tree.py`에서 `TradingEngine`의 `evaluate_sell_signal()`과 `evaluate_buy_signal()` 메서드를 14개의 경계값 테스트로 독립 검증하여, 실제 API 호출 없이도 알고리즘 트레이딩 코어 로직의 무결성을 보장합니다.

향후 전체 시계열 백테스트 모듈을 구축할 경우, 몬테카를로 시뮬레이션(Monte Carlo Simulation) 기법으로 감성 점수를 정규분포를 따르는 가상 난수로 스터빙(Stubbing)하고, 판다스의 벡터화 연산 대신 Iterative(반복) 순회 구조(`current_slice = df.iloc[:i+1]`)를 사용하여 Look-ahead 편향을 방어할 계획입니다.

### Q8. "현재 시스템은 단순히 OpenAI 클라우드 API를 넘어서, 내부 4070 Ti GPU 기반의 로컬 인프라(Ollama/llama3)로 스위칭할 수 있는 옵션을 지원합니다. 굳이 로컬 환경으로 스위칭하는 하이브리드 인프라를 구축한 이유는 무엇입니까?"
**A (모범 답변 가이드)**: 
가장 최우선적인 고려사항은 **금융 데이터 보안(Security)**과 엄청난 **스케일업 비용(Cost)**을 통제하기 위함이었습니다. 주식 시장은 일일 발생 기사량이 수천 건에 달하는데, 이를 모두 상용 API(gpt-4o)에 태울 경우 폭발적인 트래픽 타임아웃과 과금 폭탄이 발생합니다.
따라서 1차 필터링 및 대량 백테스트(학습용) 환경에서는 사내 보유 자산인 4070 Ti 인프라망을 이용해 무료로 무제한 추론(Inference)을 돌리고, 핵심적인 몇몇 파이널 로직에 관해서만 상용 API 망으로 이중 검증하는 구조를 갖췄습니다. 또한 로컬 모델 채택 시 인터넷 장애(Outage) 환경에서도 온프레미스로 안정적인 서비스 무중단 운영 능력(High Availability)을 갖출 수 있는 명확한 엔지니어링적 우위가 존재합니다.

### Q9. "왜 퀀트 트레이딩 엔진에 굳이 Streamlit과 같은 복잡한 프론트엔드(Frontend) 시각화 대시보드를 추가했습니까?"
**A (모범 답변 가이드)**: 
퀀트 투자에 있어서 **알고리즘의 블랙박스화(Blackboxing)**를 막는 것은 매우 필수적인 엔지니어링 소양입니다. 시스템이 왜 "지금 시점에서 매수(BUY) 혹은 매도(SELL) 판단을 했는지"를 개발자나 펀드매니저가 직관적으로 추적하지 못하면 신뢰성을 잃기 때문입니다.
단순 콘솔 로그(Print) 출력만으로는 백테스트 시점의 거시적 가격 변동폭과 매매 타점, 감성 점수의 임계값 돌파 트렌드를 한눈에 확인할 수 없습니다. Streamlit을 도입함으로써 SMA 모멘텀, AI의 NLP 수치, 그리고 자산의 손익 결과(MDD)를 반응형(Reactive) 컴포넌트로 한 화면에 결합해 신호와 흐름을 데이터 렌더링으로 입증할 수 있도록 설계했습니다.

---

## 4. Troubleshooting & Architecture Defense

### Issue 1: Streamlit 시각화 렌더링 중 `KeyError` 시스템 크래시
초기 대시보드 구축 후 `trade_history` DB 테이블의 컬럼 구성이 변경될 때마다, 프론트엔드가 `KeyError`를 뱉으며 크래시되는 치명적 버그가 있었습니다.

**[Root Cause]**
백엔드(`auto_trade.py`)의 DB 스키마가 변경되면 프론트엔드(`app.py`)가 고정된 컬럼 배열을 매핑하려 시도하는 강결합(Tight Coupling) 문제입니다.

**[Solution: 방어적 프로그래밍(Defensive Programming) 도입]**
`app.py`에서 렌더링하고자 하는 `target_cols`와 실제 `trade_df.columns`의 **교집합**만을 안전하게 추출합니다:
```python
target_cols = ['timestamp', 'action', 'status', 'price', 'quantity', 'roi', 'rsi', 'macd', 'llm_score', 'llm_reasoning']
display_cols = [col for col in target_cols if col in trade_df.columns]
```

### Issue 2: God Function → OOP 클래스 리팩토링
초기 `run_daily_pipeline()` 함수가 140줄짜리 단일 함수로 인증부터 주문까지 모든 로직이 혼재되어, 단위 테스트가 불가능하고 SYSTEM_RULES Rule 2(OOP 기반)를 위반했습니다.

**[Solution]**
`TradingEngine` 클래스로 전면 리팩토링하여 `_authenticate()`, `_fetch_balance()`, `_execute_order()`, `evaluate_sell_signal()`, `evaluate_buy_signal()` 각각을 독립 메서드로 분리했습니다. 특히 `evaluate_sell_signal()`과 `evaluate_buy_signal()`은 순수 함수(Pure Function)로 설계하여 `tests/test_decision_tree.py`에서 14개 경계값 테스트로 독립 검증합니다.

### Issue 3: 로컬 LLM의 비결정적 JSON 붕괴 방어
GPT-4와 달리 로컬 Llama-3은 JSON만 뱉으라는 지시를 무시하고 자연어 텍스트를 섞어 반환하여 `JSONDecodeError`가 발생했습니다.

**[Solution: 3중 방어막 구축]**
1. `response_format={"type": "json_object"}` 강제
2. `json.loads` + `try-except JSONDecodeError`로 파싱 실패 시 중립값(0.0) 대체
3. Pydantic 모델(`SentimentResult`)로 `-1.0~1.0` 범위 강력 검증

이 방어 로직은 `tests/test_analyzer.py`의 10개 테스트 케이스(`test_invalid_json_returns_neutral`, `test_out_of_range_returns_neutral`, `test_timeout_returns_neutral` 등)에서 검증됩니다.

---

## 5. Tesla (TSLA) Pivot & Data Engineering Decisions

### Q10. "초기 구글 중심의 25년치 방대한 퀀트 데이터에서, 테슬라 3년치(2020~2023) 데이터로 범위를 축소하여 피벗(Pivot)한 이유는 무엇입니까?"
**A (모범 답변 가이드)**: 
데이터 엔지니어링 관점에서 모델의 신뢰성을 담보하는 것은 '데이터의 양(Quantity)'보다 '데이터 스키마의 일관성과 품질(Quality)'입니다. 과거 뉴스 포맷은 현재와 형식이 다르고, API 응답 구조에서도 필드가 유실되는 결측치가 잦았습니다. 모델이 파편화된 결측 데이터를 먹으면 쓰레기를 뱉어낸다는 GIGO (Garbage In, Garbage Out) 원칙에 따라, 최근 3년(2020~2023)의 데이터 구조가 완벽하게 일관성을 유지하는 특정 티커(테슬라, TSLA)로 대상을 좁혀 결측치 리스크를 완전히 제거하고 시스템 파이프라인의 완성도를 제고하는 방향으로 전략적 피벗(Pivot)을 단행했습니다.

### Q11. "주식 시장 휴장일(주말 등)에 쏟아지는 뉴스나 소셜 미디어 이슈는 주가 데이터가 존재하지 않아 병합(Merge)이 불가능한데, 이를 시계열 백테스트에 어떻게 왜곡 없이 반영했습니까?"
**A (모범 답변 가이드)**: 
이 문제는 퀀트 엔지니어링에서 흔히 놓치는 치명적인 함정 중 하나입니다. 금요일 야간이나 주말에 악재가 터져도 휴장일(`Close` 주가 행 누락)이라는 이유로 뉴스가 버려지면, 월요일 시초가의 급락을 모델이 전혀 예측할 수 없습니다.
이를 극복하기 위해 Pandas의 `Outer Join` 기법으로 휴일 공간을 강제로 할당한 다음, **Forward Fill (`ffill()`)** 파이프라인 방어막을 구축했습니다. 이 방식을 통해 금/토/일요일에 수집된 최신 감성 점수들이 누락 없이 차례로 빈칸을 따라 내려와 월요일 개장 시점의 지표로 안전하게 연동(Alignment)됩니다. 이를 통해 시스템은 휴일에 거시적으로 누적된 컨센서스를 월요일 개장 전 추세 판단의 핵심 근거로 오롯이 활용할 수 있게 되었습니다.

---

## 6. Benchmark Evaluation & Real-World Constraints

### Q12. "테슬라(TSLA)와 같은 고변동성 종목에서, 왜 시장 수익률(Buy & Hold)을 이기기(Alpha 창출)가 어렵습니까?"
**A (모범 답변 가이드)**: 
테슬라처럼 장기 우상향하는 주도주나 고변동성 모멘텀 종목은 폭발적인 상승장이 짧은 기간에 집중되는 경향이 있습니다. 알고리즘 트레이딩(퀀트)이 하락장을 방어(MDD 축소)하는 데는 탁월하지만, 박스권 휩쏘(Whipsaw)에 속아 잦은 손절을 하거나 상승 전환의 골든크로스를 놓치면 그 핵심 상승 파동을 온전히 먹지 못합니다. 이 때문에 단순 보유(Buy & Hold) 전략의 누적 복리 수익을 '알파(Alpha)'로 상회하는 것은 전략의 타점이 매우 정교하지 않고서는 현실적으로 매우 달성하기 어려운 엔지니어링 허들입니다.

### Q13. "잦은 매매가 장기 수익률에 미치는 부정적인 영향(Slippage & Fees)을 어떻게 제어했으며, 어떤 필터를 적용했습니까?"
**A (모범 답변 가이드)**: 
백테스트 환경에서 수수료와 슬리피지(Slippage)를 제외한 이른바 'Gross Return(단순 명목 수익률)'은 완벽한 환상에 불과합니다. 이번 파이프라인 고도화를 통해 `TRANSACTION_FEE = 0.1%`를 매 트랜잭션마다 차감하도록 강제 적용한 결과, 잦은 스위칭이 갉아먹는 엄청난 복리 훼손을 직접적으로 검증할 수 있었습니다.
이를 방어하기 위해서 단순히 SMA를 교차했다고 매매하는 것이 아니라, NLP 모델이 뱉어내는 감성 점수의 임계값(Threshold)을 +0.2 나 -0.2로 높이는 **하이브리드 교차 필터링**을 적용했습니다. 이는 오직 모멘텀과 뉴스가 같은 방향(Strong Consensus)을 가리킬 때만 '확실한 베팅'을 하도록 포지션 스위칭 횟수(Trade Count)를 극단적으로 억제함으로써, 불필요한 매매 비용이 복리 스노우볼을 파괴하는 것을 시스템적으로 막는 보호 매커니즘입니다.

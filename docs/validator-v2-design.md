# Validator v2 Minimal Design — Vehicle Event Grounding

## 0. 목적과 비범위

이 문서는 `delivery sites`가 `vehicle delivery volume` 주장의 근거로 잘못 인정된 Production Validator v1의 false acceptance를 해결하기 위한 최소 설계다. 구현 코드는 다음 승인 후 작성한다.

이번 설계가 구분하는 개념은 세 가지뿐이다.

| Concept | 의미 | 대표 source | 대표 output |
|---|---|---|---|
| `delivery_location` | 차량을 고객에게 인도하는 거점·장소·센터의 개설·확대 | `delivery site`, `delivery center`, `handover location` | `차량 인도 거점`, `인도 장소` |
| `vehicle_delivery_volume` | 실제 차량 인도 대수·수치·증감 | `vehicle deliveries rose`, `delivery volume`, `vehicles delivered` | `차량 인도량`, `인도 대수 증가` |
| `vehicle_recall` | 차량의 안전·결함 등에 따른 리콜 사건 | `vehicle recall`, `recalls 10,000 cars` | `차량 리콜` |

명시적으로 제외한다.

- Prompt v4와 sentiment 정책
- 재작성 feedback template·최대 시도 횟수
- LLM 기반 Semantic Grader와 전체 자연어 entailment
- action-state, analyst roundup, record 번역 규칙의 Production 적용
- `배송 사이트` 같은 표현의 최종 번역 품질 판정
- Dataset과 기존 Run artifact 변경

`배송 사이트`는 v2에서 자연스러운 번역으로 승인한다는 뜻이 아니다. 이 단계는 그 표현이 location 계열임을 분류해 volume과 혼동하지 않는 것까지만 담당한다.

## 1. 현재 오류가 발생하는 코드 경로

### 1.1 v1 규칙

`analysis/headline_policy.py:123-133`의 `vehicle_deliveries` rule은 다음처럼 지나치게 넓다.

```text
output trigger:
  인도량, 차량 인도, 차량 배송, 배송 보고서,
  delivery report, vehicle deliveries

source grounding:
  delivery, deliveries, 인도량, 차량 인도
```

`contains_keyword()`는 영문 keyword에 단어 경계를 적용한다(`analysis/headline_policy.py:302-311`). 따라서 `delivery sites`에는 독립 단어 `delivery`가 존재한다고 판정한다.

### 1.2 v1 Case 5 통과 경로

원문:

> Tesla opens more delivery sites in Japan amid stronger EV demand

출력의 확정 오류:

> 테슬라는 일본 시장에서의 차량 인도량 증가에 대응하기 위해 새로운 인도 장소를 열었습니다.

실제 호출 순서:

1. `NewsAnalyzer._validate_evidence_ids()`가 supporting article ID가 선택 집합에 있음을 확인한다(`analysis/news_analyzer.py:1184-1200`).
2. `_validate_output_policy()`가 topic과 explanation을 합쳐 `HeadlinePolicy.ungrounded_event_claims()`에 전달한다(`analysis/news_analyzer.py:1230-1238`).
3. 출력의 `차량 인도량`이 `vehicle_deliveries` output trigger에 걸린다.
4. cited headline의 `delivery sites`에서 source keyword `delivery`가 발견된다.
5. `source_grounded=True`가 되어 위반 목록에 아무것도 추가되지 않는다(`analysis/headline_policy.py:281-295`).
6. 다른 금지 pattern이나 conflicting direction 계약도 위반하지 않아 Validator가 통과한다.

정확한 결함은 `delivery`라는 상위·다의적 단어 하나가 **location**과 **volume** 양쪽의 근거로 사용된 것이다. article ID는 올바르지만 그 article이 claim을 지지하지 않는다.

## 2. 제안하는 최소 개선 알고리즘

### 2.1 설계 원칙

1. generic `delivery`와 bare Korean `차량 인도`를 volume proof로 사용하지 않는다.
2. 출력이 주장한 세부 concept마다 같은 concept가 relevant headline에 있는지 검사한다.
3. 출력에 해당 concept 주장이 없으면 source concept의 존재만으로 오류를 만들지 않는다.
4. 한 headline에 location과 volume이 모두 명시되면 두 concept를 모두 허용한다.
5. Topic은 현재처럼 자신이 인용한 article ID의 headline만 참조한다.
6. Summary는 schema에 evidence ID가 없으므로 현재처럼 선택된 headline 전체를 참조한다. 이 한계는 이번 변경에서 유지한다.
7. 다른 사건 grounding, 금지 pattern, sentiment와 retry 계약은 변경하지 않는다.

### 2.2 Concept detection

`HeadlinePolicy`에 vehicle event 전용 concept detector를 둔다.

```text
detect_vehicle_event_concepts(text, role)
  1. NFKC + casefold + whitespace normalization
  2. role별(source/output) 정규식 적용
  3. 발견된 concept의 frozenset 반환

ungrounded_vehicle_event_claims(output_text, source_titles)
  output_concepts = detect(output_text, output)
  supported_concepts = union(detect(title, source) for title in source_titles)
  return output_concepts - supported_concepts
```

초기 pattern 범위는 high precision을 우선한다.

| Concept | Source pattern 초안 | Output pattern 초안 | 의도적 제외 |
|---|---|---|---|
| `delivery_location` | `delivery site(s)`, `delivery center(s)/centre(s)`, `delivery location(s)`, `delivery hub(s)`, `handover site/center/location`, `인도 거점/장소/센터` | `차량 인도 거점/장소/센터/시설`, `인도 거점/장소/센터`, `delivery site/center/location`, location 의미의 `배송 사이트/센터` | bare `delivery`, bare `차량 인도` |
| `vehicle_delivery_volume` | `vehicle deliveries`, `vehicle delivery volume/count/figures`, `vehicles delivered`, `차량 인도량`, `인도 대수` | `차량 인도량`, `인도량`, `차량 인도 대수`, `인도 대수`, `vehicle deliveries/volume/count` | `delivery site`, `delivery center`, bare `delivery` |
| `vehicle_recall` | `vehicle/car/automobile recall`, `recall(s/ed) ... vehicle/car/SUV`, `차량/자동차 ... 리콜` | `차량/자동차 리콜`, `vehicle/car recall` | generic product recall만 있는 경우의 vehicle 단정 |

Pattern은 구현 시 영어 단복수와 제한된 토큰 간격을 명시적으로 테스트한다. 회사가 자동차 기업이라는 외부 지식을 사용해 generic `deliveries`를 차량 인도량으로 자동 승격하지 않는다.

### 2.3 기존 `EVENT_GROUNDING_RULES`와의 결합

권장 최소 구조:

1. 기존 `EVENT_GROUNDING_RULES`에서 넓은 `vehicle_deliveries` row를 제거한다.
2. `earnings_report`, `revenue`, `regulatory_investigation` 등 비차량 규칙은 그대로 둔다.
3. 기존 `product_recall` row에서는 vehicle-specific output term을 새 detector로 이관하고, `제품 리콜`/`product recall` 같은 비차량 제품 recall 호환성만 유지한다.
4. `ungrounded_event_claims()`가 기존 규칙의 위반과 새 vehicle concept 위반을 합쳐 결정론적 순서로 반환한다.

새 rule name은 다음처럼 구체적으로 기록한다.

```text
delivery_location
vehicle_delivery_volume
vehicle_recall
```

v1의 `vehicle_deliveries` 문자열을 alias로 계속 반환하지 않는다. 그 이름은 location과 volume을 다시 모호하게 만들기 때문이다. 과거 telemetry는 기존 artifact에 v1로 보존하며, v2 실행은 manifest의 validator version으로 구분한다.

### 2.4 판정 예시

| Source concepts | Output concepts | 결과 |
|---|---|---|
| `{delivery_location}` | `{delivery_location}` | 통과 |
| `{delivery_location}` | `{vehicle_delivery_volume}` | `vehicle_delivery_volume` 위반 |
| `{vehicle_delivery_volume}` | `{vehicle_delivery_volume}` | 통과 |
| `{vehicle_recall}` | `{vehicle_recall}` | 통과 |
| `{vehicle_recall}` | `{vehicle_delivery_volume}` | `vehicle_delivery_volume` 위반 |
| `{delivery_location, vehicle_delivery_volume}` | 동일 두 concept | 통과 |
| `{}` | `{}` | 기존 규칙 결과 유지 |

출력이 두 concept를 주장했는데 source에는 하나만 있으면 없는 concept만 위반으로 반환한다.

### 2.5 article ID별 근거 유지

`NewsAnalyzer._validate_output_policy()`의 호출 구조는 변경하지 않는다.

- Summary: 모든 selected headline을 source로 사용
- Topic/Explanation: `supporting_article_ids`로 찾은 cited headline만 source로 사용

따라서 다음 상황을 구분할 수 있다.

```text
Article A: delivery site opened
Article B: vehicle deliveries rose

Topic: 차량 인도량 증가
Evidence: [Article B] → 통과
Evidence: [Article A] → 거부
Evidence: [Article A, Article B] → 통과
```

ID의 존재 여부는 기존 `_validate_evidence_ids()`가 먼저 검사하므로 새 detector는 ID validation을 중복 구현하지 않는다.

### 2.6 오류 코드와 재작성

새 top-level telemetry error code는 필요하지 않다.

- 기존: `output_policy_validation_error`
- 새 reason 예시: `LLM topic changed an event type without cited headline evidence: vehicle_delivery_volume`

`NewsAnalysisValidationError`와 `_request_validated_output()`의 feedback 누적 방식도 유지한다. 따라서 새 concept 위반은 기존과 똑같이 최대 2회 재작성 대상이 된다.

이번 범위에서는 다음을 바꾸지 않는다.

- feedback 문장 template
- 이전 출력 전달 여부
- 최대 Attempt 수
- API 오류 처리
- 최종 `validation_error`/`unavailable` 계약

### 2.7 Validator version 변경 시점

설계 문서 작성 시점에는 `news-analyzer-validator-v1`을 유지한다. 다음 조건을 모두 만족하는 구현 commit에서만 `evaluation/v2_runner.py`의 `DEFAULT_VALIDATOR_VERSION`을 `news-analyzer-validator-v2`로 변경한다.

1. 새 core regression test가 모두 통과한다.
2. 기존 Validator·Production workflow·v1/v2 evaluation 테스트가 모두 통과한다.
3. 기존 TSLA Case 5의 확정 오류를 offline stub으로 거부한다.
4. 정상 location, volume, recall과 mixed 사건 test가 통과한다.
5. Dataset, Prompt version과 과거 Run artifact가 변경되지 않았음을 확인한다.

version 변경은 코드가 배포 가능한 상태가 된 뒤가 아니라 **새 규칙이 활성화되는 동일 변경 단위**에 포함해야 한다. 그래야 v2로 기록된 모든 신규 Evaluation run이 실제 새 판정을 사용한다.

## 3. 테스트 우선 설계

### 3.1 Core blocking regression matrix

아래 test는 실제 OpenAI 호출 없이 `HeadlinePolicy` 또는 stub `NewsAnalyzer`로 실행한다. TSLA Case 5를 복제하지 않고 회사·문장 구조를 분산한다.

| ID | Headline | LLM output 핵심 | 기대 | 검증 목적 |
|---|---|---|---|---|
| L1 | `Rivian opens a new delivery center in Munich` | `리비안이 뮌헨에 새 차량 인도 거점을 열었다.` | 통과 | location→location |
| L2 | `Lucid expands its delivery sites across Norway` | `루시드의 실제 차량 인도량이 증가했다.` | 거부: `vehicle_delivery_volume` | location→volume false acceptance 방지 |
| V1 | `Ford reports quarterly vehicle deliveries rose 12%` | `포드의 분기 차량 인도량이 12% 증가했다.` | 통과 | volume→volume |
| R1 | `General Motors announces a vehicle recall over brake safety` | `GM이 브레이크 안전 문제로 차량 리콜을 발표했다.` | 통과 | recall→recall |
| R2 | `Volvo issues a vehicle recall for steering defects` | `볼보의 차량 인도량이 감소했다.` | 거부: `vehicle_delivery_volume` | recall→volume 차단 |
| M1 | `Hyundai opens a delivery center as vehicle deliveries rise in Canada` | `현대차가 캐나다에서 차량 인도 거점을 열었고 차량 인도량도 증가했다.` | 통과 | 한 headline에 location+volume 모두 명시 |
| N1 | `Microsoft opens a new AI research lab in Toronto` | `마이크로소프트가 토론토에 AI 연구소를 열었다.` | 통과 | 무관한 일반 뉴스 no-op |

### 3.2 대칭 오류와 article ID scope

필수 요구에 더해 아래 test가 있어야 규칙이 한 방향 예외로 굳어지지 않는다.

| ID | 입력 | 출력·evidence | 기대 |
|---|---|---|---|
| S1 | `BMW vehicle deliveries rose in Q2` | `BMW가 새 차량 인도 거점을 열었다.` | 거부: `delivery_location` |
| S2 | Article A=`Polestar opens a delivery hub`; Article B=`Polestar vehicle deliveries rise` | volume topic cites A만 | 거부: `vehicle_delivery_volume` |
| S3 | 같은 A/B | volume topic cites B만 | 통과 |
| S4 | 같은 A/B | location topic cites A, volume topic cites B | 통과 |
| S5 | `Kia opens two delivery centers; vehicle deliveries fall 4%` | location과 volume 두 topic이 같은 ID를 인용 | 둘 다 통과 |
| S6 | `Toyota vehicle deliveries increase` | `토요타가 차량 리콜을 실시했다.` | 거부: `vehicle_recall` 또는 기존 recall grounding 위반 |

### 3.3 기존 동작 호환 test

- earnings report를 vehicle delivery report로 바꾸는 기존 거부 test 유지
- sales를 revenue로 넓히는 기존 거부 test 유지
- conflicting headline neutral 계약 유지
- recommendation/future prediction pattern 유지
- unknown evidence ID 거부 유지
- prompt-injection과 ticker relevance filter 유지
- 첫 실패 후 두 번째 stub output 성공 시 rewrite rescue 유지
- 최대 3회 실패 후 `validation_error`/`unavailable` 유지
- API 예외는 재작성하지 않고 `llm_error` 유지
- v1/v2 Evaluation recorded runner와 Production workflow 전체 회귀 유지

### 3.4 Test layering

1. **Concept detector unit test**: 각 source/output 문구가 기대 concept set으로 분류되는지 확인한다.
2. **Grounding unit test**: output concept minus source concept 결과를 확인한다.
3. **Article evidence test**: 같은 selected set에서도 cited ID에 따라 통과/거부가 달라지는지 확인한다.
4. **NewsAnalyzer integration test**: stub response가 `available=true` 또는 3회 후 `validation_error`가 되는지 확인한다.
5. **Evaluation metadata test**: 새 실행 manifest/summary에 `news-analyzer-validator-v2`가 기록되는지 확인한다.
6. **전체 pytest/Ruff**: 기존 기능의 비의도 변경을 검사한다.

추천 fixture는 `evals/fixtures/news_validator_v2_vehicle_events.json`이다. 이 fixture는 모델 성능 dataset이 아니라 deterministic Validator regression fixture로 명시한다.

## 4. 예상 False Rejection과 False Acceptance 위험

### 4.1 정상인데 거부할 수 있는 문장

| Headline | 올바른 해석 | 위험 원인 | v2 처리 원칙 |
|---|---|---|---|
| `BMW quarterly deliveries rise 8%` | 자동차 문맥의 차량 인도량 증가 | `vehicle`이 없고 generic `deliveries`만 있음 | high-precision core에서는 자동 volume 승격을 보류. risk fixture로 기록 |
| `NIO expands its handover network in Europe` | 차량 인도 거점망 확대 | `site/center/location`이 없는 `handover network` | 명시적 allow phrase 추가 전에는 false rejection 가능 |
| `GM recalls 120,000 SUVs` | 차량 리콜 | `vehicle recall` 고정 phrase가 아니라 동사+대상 구조 | source regex가 제한된 토큰 간격으로 SUVs/cars/vehicles를 지원해야 함 |
| `Lucid adds customer experience centers with vehicle handoff` | 인도 관련 거점 추가 | 마케팅·서비스 센터와 인도 거점이 복합됨 | location으로 자동 확정하기 어려워 review 대상으로 남김 |
| `BYD delivered 500,000 vehicles in Q4` | 차량 인도 대수 | `vehicle deliveries` 명사형이 아니라 동사형 | `vehicles delivered`와 `delivered ... vehicles` 양방향 pattern 필요 |
| `Rivian expands its fulfillment footprint` | 문맥에 따라 인도 거점일 수 있음 | delivery/handover 단어 없음 | 외부 회사 지식 없이 location으로 추론하지 않음 |

첫 구현에서 모든 risk phrase를 무리하게 허용하지 않는다. 실제 false rejection 표본과 빈도를 확인한 뒤 phrase set을 늘린다.

### 4.2 남을 수 있는 False Acceptance

- output이 `차량을 더 많이 고객에게 넘겼다`처럼 등록되지 않은 paraphrase로 volume을 암시하면 concept trigger를 피할 수 있다.
- Summary는 모든 selected headline을 함께 보므로 서로 다른 기업·사건의 concept가 잘못 결합될 수 있다.
- location과 volume은 구분해도 `amid`를 원인으로 바꾸는 인과 왜곡은 남는다.
- 정확한 숫자, 지역, 시점, subject/object 관계는 이번 규칙이 검증하지 않는다.
- `배송 사이트`의 도메인 번역 품질은 분류만 하고 승인하지 않는다.

### 4.3 False Rejection 관리

- 허용 paraphrase와 오류 paraphrase를 항상 쌍으로 추가한다.
- 일반 keyword 하나보다 multi-token phrase를 우선한다.
- rule별 violation count와 rejected output을 Evaluation artifact에서 추적한다.
- 새 규칙으로 거부된 표본을 Human Review해 false rejection 후보를 기록한다.
- live 재실행 전에 recorded/stub test로 모든 분기를 고정한다.

## 5. 기존 코드·데이터 호환성

| 대상 | 호환성 계획 |
|---|---|
| `NewsLLMOutput` schema | 변경 없음 |
| `NewsAnalysis` available/unavailable 계약 | 변경 없음 |
| `_validate_evidence_ids()` | 변경 없음 |
| `_validate_output_policy()` 호출 순서 | 변경 없음 |
| `HeadlinePolicy.ungrounded_event_claims()` signature | 유지 |
| Prompt v3 | 변경 없음 |
| 최대 Attempt와 feedback template | 변경 없음 |
| Dataset v2와 hash | 변경 없음 |
| 기존 v1/v2/v3 artifact | 읽기 전용으로 보존 |
| Evaluation result schema | 변경 없음 |
| telemetry top-level error code | `output_policy_validation_error` 유지 |
| inner rule name | v2부터 세부 concept name 사용 |

과거 Run은 validator v1 결과이므로 재채점하거나 덮어쓰지 않는다. Validator v2의 offline/live 결과는 새 Run ID로 저장하고 manifest의 validator version으로 비교 조건을 분리한다.

## 6. 구현 예상 변경 파일

| 파일 | 예상 변경 |
|---|---|
| `analysis/headline_policy.py` | vehicle concept pattern, detector, grounding 결합; 넓은 `vehicle_deliveries` row 제거 |
| `tests/test_headline_policy.py` | core 통과·거부, mixed 사건, cited article scope, 정상 동작 회귀 test |
| `evals/fixtures/news_validator_v2_vehicle_events.json` | 타사 기반 deterministic 회귀 fixture 신규 추가 |
| `evaluation/v2_runner.py` | 규칙 활성화와 동시에 기본 validator version을 `news-analyzer-validator-v2`로 변경 |
| `tests/test_evaluation_v2_runner.py` | manifest와 summary의 v2 version 기록 확인 |
| `docs/validator-audit.md` | 구현 완료 후 실제 v2 결과와 남은 한계 링크 보강 |

`analysis/news_analyzer.py`, Prompt, Dataset schema/정답과 재작성 로직은 변경하지 않는 것이 기본안이다. 구현 중 호출 구조 변경이 필요해지면 최소 범위를 벗어나므로 별도 승인을 받는다.

## 7. 구현 후 검증 계획

### 7.1 Offline gate

1. 새 deterministic fixture schema와 case ID 중복을 검사한다.
2. concept detector unit test를 실행한다.
3. Core blocking matrix와 article ID scope test를 실행한다.
4. 기존 `test_headline_policy.py`, `test_news_analyzer.py`, `test_attempt_telemetry.py`를 실행한다.
5. 전체 pytest와 Ruff를 실행한다.
6. Dataset hash와 Prompt version이 기존 값 그대로인지 확인한다.
7. 과거 v1/v2/v3 artifact의 file hash가 변경되지 않았는지 확인한다.

### 7.2 기존 TSLA Case 5 재현

실제 API 없이 기존 v1 Case 5의 저장 출력 또는 동일 의미의 stub output을 Validator v2에 넣는다.

완료 기준:

- parse/Pydantic/evidence ID는 통과
- output policy에서 `vehicle_delivery_volume`로 거부
- telemetry outcome은 `validator_failed`
- top-level error code는 `output_policy_validation_error`
- 같은 잘못된 stub을 3회 주면 최종 `validation_error`/`unavailable`

이는 Validator 검출 회귀이며 실제 모델 품질 개선 실험이 아니다.

### 7.3 호환성 완료 기준

- 필수 7개 core case와 대칭·evidence case가 기대대로 동작
- 기존 전체 pytest 통과
- Ruff 통과
- Prompt·Dataset·schema·retry 변경 없음
- 새 manifest에 `news-analyzer-validator-v2` 기록
- 과거 artifact 미변경
- live API 미호출

### 7.4 이후 실험

구현과 offline 검증이 승인된 뒤에만 동일 5-case Dataset을 새 Run ID로 실행한다. 그 결과는 Prompt v3 + Validator v2라는 새 조건이므로 Prompt v1/v2/v3의 Validator v1 결과와 직접 같은 변수 실험으로 합치지 않는다.

Human Review에서는 다음을 별도 확인한다.

- 확정된 v1 Case 5 오류가 실제 생성에서도 차단되는가
- 정상 location output이 과도하게 거부되는가
- 재작성 결과가 다른 unsupported claim으로 이동하는가
- Validator Pass와 semantic quality가 여전히 분리돼 보고되는가

## 8. 승인 전 의사결정 포인트

구현 전에 다음 세 경계를 확정하면 불필요한 rule 확장을 막을 수 있다.

1. generic `BMW deliveries rose`를 v2 core에서 volume으로 허용할지, high-precision을 위해 보류할지
2. `배송 사이트/배송 센터`를 location concept으로만 분류해 통과시킬지, 번역 오류로도 거부할지
3. recall 동사형(`recalls 10,000 SUVs`)까지 첫 구현에서 지원할지

이 문서의 권장안은 각각 **보류**, **location으로 분류하되 번역 품질은 판정하지 않음**, **제한된 동사형 지원**이다.

## 9. 관련 문서

- [Production Validator v1 감사](validator-audit.md)
- [실패 처리와 재작성 계약](failure-handling.md)
- [Prompt v1/v2/v3 실험 기록](experiment-log.md)
- [Evaluation v2 설계](evaluation_v2.md)

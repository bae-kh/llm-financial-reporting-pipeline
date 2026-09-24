# Evaluation v2 Experiment Log

## 문서 목적과 증거 수준

이 문서는 동일한 TSLA 실제 뉴스 5-case development dataset으로 실행한 Prompt v1/v2/v3 Live Pilot의 의사결정과 관측 결과를 보존한다. 세 실험은 Evaluation v2 실행·기록 경로를 검증하고 다음 변경 방향을 정하기 위한 development diagnostic이다.

아래 표기는 의도적으로 구분한다.

- **구현·실험 사실**: 코드, manifest, attempt telemetry 또는 reviewer annotation에서 직접 확인한 내용
- **설계 의도**: 변경으로 달성하려 한 목표이며 결과가 입증됐다는 뜻이 아님
- **가설**: 관측과 일치하지만 대조 반복이나 더 큰 평가셋으로 검증하지 않은 설명
- **사람 확정 판정**: 별도 reviewer annotation에 명시된 v1/v2 case-level 결정
- **검수 후보**: v3 출력에서 발견했지만 아직 새로운 Human Review로 확정하지 않은 항목

세 Run의 공통 조건은 다음과 같다.

| 항목 | 고정값 |
|---|---|
| Dataset | `tsla-real-news-headlines-pilot` / `2.0.0-draft.2` |
| Dataset hash | `sha256:317c1f22fd3936c44d74b0b7c0c76ff7b81ccacf5762329e7593f908fc9abfde` |
| Split / annotation | `development` / 5개 모두 `draft` |
| 모델 요청 ID | `gpt-4o-mini` |
| 실제 응답 모델 ID | `gpt-4o-mini-2024-07-18` |
| Validator | `news-analyzer-validator-v1` |
| 실행 횟수 | Prompt별 5개 Case 각각 1회 |
| 입력 | Dataset에 고정된 headline metadata; RSS 재수집 없음 |
| 자동·의미 평가 경계 | Validator 지표는 자동 집계, 의미 정확도는 사람 판정 전 미평가 |

## 전체 측정 결과

| 지표 | Prompt v1 | Prompt v2 | Prompt v3 |
|---|---:|---:|---:|
| Run ID | `evalv2_20260923T073211Z_b6941567` | `evalv2_20260923T082028Z_bf085cc6` | `evalv2_20260924T053730Z_ed507f7c` |
| First-pass Validator Pass | 1/5 (20%) | 5/5 (100%) | 5/5 (100%) |
| Final-pass Validator Pass | 1/5 (20%) | 5/5 (100%) | 5/5 (100%) |
| Rewrite Rescue | 0/4 | 해당 없음(0/0) | 해당 없음(0/0) |
| 총 Attempt | 13 | 5 | 5 |
| 평균 Attempt | 2.6 | 1.0 | 1.0 |
| Final Unavailable | 4/5 (80%) | 0/5 (0%) | 0/5 (0%) |
| Draft expected sentiment 일치 | 0/5 | 3/5 | 4/5 |
| 총 LLM latency | 33,672.910 ms | 10,963.027 ms | 12,901.087 ms |
| Input / output / total tokens | 12,056 / 1,345 / 13,401 | 4,316 / 496 / 4,812 | 4,926 / 526 / 5,452 |
| 공식 성능 사용 가능 | 아니요 | 아니요 | 아니요 |
| Semantic accuracy 산출 | 아니요 | 아니요 | 아니요 |

`Draft expected sentiment 일치`는 Dataset의 draft label과 최종 출력의 기계적 일치다. v1은 4개 Case가 `unavailable`이어서 0/5이며, 이 수치는 의미 정확도가 아니다. Latency와 token 사용량도 각 Prompt를 한 번 실행한 관측값이라 안정적인 효율 비교나 비용 결론으로 사용하지 않는다.

로컬 원본 artifact는 `reports/generated/evals/v2/<eval_run_id>/`에 있고 Git 관리 대상에서 제외된다. 각 디렉터리의 `manifest.json`, `attempt_telemetry.json`, `case_outputs.json`, `grading_results.json`, `validator_reliability.json`, `human_review.md`, `summary.json`이 같은 Run ID로 연결된다.

## Prompt v1 — 반복되는 차량 인도량 오류 Baseline

### 실험 목적

- **설계 의도**: Evaluation v2가 실제 모델의 생성·검증·재작성·최종 fallback을 attempt 단위로 수집하는지 확인한다.
- **실험 사실**: 첫 Live Pilot이며 이후 Prompt 변경의 baseline으로 사용한다.

### 변경한 변수

Baseline Prompt `news-analyzer-prompt-v1`을 사용했다. 당시 공통 System Prompt의 사건 의미 보존 규칙에는 `vehicle delivery/deliveries/report`와 `차량 인도/차량 인도량/차량 인도량 보고서`라는 구체적 번역 예시가 모든 요청에 노출됐다.

### 고정한 조건

위 공통 조건을 사용했다. 최대 Attempt는 첫 생성 1회와 재작성 최대 2회, 총 3회였다.

### Run ID

`evalv2_20260923T073211Z_b6941567`

### 주요 측정 결과

- **실험 사실**: First-pass와 Final-pass Validator Pass는 모두 1/5였다.
- **실험 사실**: Case 1~4는 각각 3회 모두 parse에는 성공했으나 `output_policy_validation_error`로 거부됐고, 최종 `validation_error`/`unavailable`이 됐다.
- **실험 사실**: 네 Case의 모든 실패 Attempt에서 원문이 뒷받침하지 않는 `vehicle_deliveries` 계열 topic 또는 claim이 다시 생성됐다.
- **실험 사실**: Rewrite Rescue는 0/4였다.
- **실험 사실**: Case 5는 첫 Attempt에 Validator를 통과했다.

### 사람 검수 결과

- **사람 확정 판정**: Case 5의 `차량 인도량 증가`는 delivery sites 개설을 차량 인도 대수 증가로 바꾼 근거 없는 주장이다. Production Validator가 통과시킨 case-level 오류로 기록됐다.
- v1 전체 다섯 Case에 대한 공식 semantic accuracy 또는 전체 false acceptance rate는 산출하지 않았다.

### 확인된 문제와 가설

**확인된 문제**

- 관련 없는 단일 headline에서도 차량 인도량 topic이 반복됐다.
- 재작성 feedback은 누적된 Validator 오류 사유와 허용 evidence ID를 원본 user prompt 뒤에 붙였으며, 이전 초안 전문은 다시 전달하지 않았다.
- 오류 사유 자체에도 `vehicle_deliveries`가 포함됐고 같은 오류가 다음 Attempt에서 반복됐다.
- `key_topics`는 Structured Output schema에서 최소 1개가 필요하다.

**아직 검증되지 않은 가설**

- 공통 Prompt의 구체적인 차량 인도량 예시가 단일 headline 문맥보다 강한 주제 단서로 작동했을 수 있다.
- 재작성 feedback에 반복된 오류 용어가 모델의 동일 주제 재생성을 강화했을 수 있다.
- 단일 headline과 최소 1개 topic 계약의 조합이 근거가 약한 topic 생성을 유도했을 수 있다.

이 가설들은 v1 한 번의 실행만으로 인과관계가 입증되지 않았다.

### 한계

- 5개 development case, Prompt당 1회 실행이다.
- Dataset annotation은 draft이며 기사 본문이 아닌 headline metadata만 사용했다.
- 재작성 실패는 특정 모델 snapshot과 당시 Prompt의 관측 결과다.

### 다음 의사결정

한 번에 하나의 변수를 바꾸기 위해 Validator, schema, Dataset, 재작성 feedback을 고정하고 차량 인도량의 구체적 번역 예시 노출 방식만 Prompt v2에서 변경한다.

## Prompt v2 — 차량 인도 지침의 조건부 노출

### 실험 목적

- **설계 의도**: 관련 없는 뉴스에 차량 인도량 예시를 노출하지 않으면 v1의 반복 오류 패턴이 줄어드는지 관찰한다.

### 변경한 변수

Prompt version을 `news-analyzer-prompt-v2`로 올리고, 차량 인도량의 구체적 번역 지침을 실제 headline이 vehicle delivery 사건을 명시한 요청에만 조건부로 추가했다. 일반적인 사건 유형 보존 원칙은 유지했다.

### 고정한 조건

Dataset/hash, 모델 요청 ID, Validator, Structured Output schema, 재작성 feedback, 최대 Attempt, Case 수와 실행 횟수를 v1과 동일하게 유지했다.

### Run ID

`evalv2_20260923T082028Z_bf085cc6`

### 주요 측정 결과

- **실험 사실**: 5개 모두 첫 Attempt에 Production Validator를 통과했다.
- **실험 사실**: 총 Attempt는 5회였고 `unavailable`은 없었다.
- **실험 사실**: v1에서 반복된 허위 차량 인도량 topic은 이 Run에서 나타나지 않았다.
- **실험 사실**: draft expected sentiment 일치는 3/5였다. 이는 semantic accuracy가 아니다.

### 사람 검수 결과

별도 reviewer annotation에서 v2 최종 출력은 다음과 같이 판정됐다.

| Case | 판정 | 핵심 근거 |
|---|---|---|
| 1 Robotaxi clearance | `approved` | 현재 검수에서 blocking 의미 오류가 확정되지 않음 |
| 2 China recall | `changes_required` | `record→대규모`, 제목에 없는 `발표`, 강한 시행 상태 `실시` |
| 3 Revenue + stock drop | `changes_required` | `revenue→수익`, neutral-only 정책과 negative 출력 불일치 |
| 4 Analyst roundup | `approved` | neutral 및 roundup 포함 요약 허용; 개별 방향 단정은 계속 금지 |
| 5 Delivery sites | `changes_required` | `delivery sites→차량 배송 장소`, positive 정책과 neutral 출력 불일치 |

집계는 승인 2건, 수정 필요 3건, 남은 검수 0건이다. Dataset은 여전히 draft이며 이 집계로 공식 semantic accuracy를 계산하지 않았다.

### 확인된 문제와 가설

**확인된 문제**

- Validator Pass 5/5와 사람 승인 2/5가 달랐다. 현재 Validator 통과가 의미 품질 승인을 뜻하지 않음을 보여준다.
- 금융·자동차 도메인 용어, 사건 행위 상태, Dataset sentiment 정책은 Validator가 모두 포착하지 못했다.

**아직 검증되지 않은 가설**

- 차량 인도량 반복 패턴이 사라진 원인이 조건부 예시 노출 변경일 가능성이 있다.
- 단일 Run이라 모델의 확률적 변동만으로도 v1/v2 차이 일부가 발생했을 수 있다.

### 한계

- v1과 v2는 paired repeated trial이 아니라 각각 1회 실행이다.
- 사람 판정은 headline-only 정책에 따른 5개 development case의 case-level 기록이다.
- v2에서 차량 인도량 오류가 관측되지 않았다는 사실은 다른 뉴스 분포에서의 일반화를 입증하지 않는다.

### 다음 의사결정

차량 인도량 예시의 조건부 노출은 유지하고, 특정 TSLA 정답이나 sentiment를 넣지 않은 일반화된 의미 보존 지침을 Prompt v3에 추가한다. 변경 전 타사·다른 문장 구조의 offline 허용/오류 fixture를 만든다.

## Prompt v3 — 도메인 용어와 사건 상태 보존

### 실험 목적

- **설계 의도**: `revenue/profit/earnings`, `delivery site/delivery volume`, `recall/delivery`, `record/large`, 사건 연관성과 발표·실시·완료, roundup 포함과 확정 등급 변경을 일반적으로 구분한다.

### 변경한 변수

Prompt version을 `news-analyzer-prompt-v3`로 올리고 System Prompt의 의미 보존 규칙에 사건 유형·주체·대상·지표·수식어·범위·행위 상태를 보존하라는 일반 지침을 추가했다. 차량 인도량의 구체적 한국어 예시는 v2처럼 관련 headline에서만 조건부로 노출된다. Sentiment 정책은 변경하지 않았다.

### 고정한 조건

Dataset/hash, 모델 요청 ID, Validator, Structured Output schema, 재작성 feedback, 최대 Attempt, Runner/Grader와 실행 횟수를 v2와 동일하게 유지했다.

### Run ID

`evalv2_20260924T053730Z_ed507f7c`

### 주요 측정 결과

- **실험 사실**: 5개 모두 첫 Attempt에 Production Validator를 통과했고 `unavailable`은 없었다.
- **실험 사실**: Case 2에서는 v2의 `발표`·`실시` 표현이 나타나지 않았고 Explanation에 `기록적인`이 사용됐다. 다만 Summary는 여전히 `대규모`였다.
- **실험 사실**: Case 3은 `revenue`를 `매출`로 표현하고 neutral을 출력했다.
- **실험 사실**: Case 5는 `차량 인도 거점`이 아니라 `배송 사이트`를 사용했고 neutral을 출력했다.
- **실험 사실**: 허위 차량 인도량 topic은 나타나지 않았다.
- **실험 사실**: draft expected sentiment 일치는 4/5였지만 Prompt v3에는 Sentiment 정책 변경이 없었다.

### 사람 검수 결과

2026-09-24에 사용자가 AI 보조 검수 결과를 최종 승인했다. 이는 독립적인 제3자 Human Review나 공식 평가가 아니다.

| Case | 확정 판정 | 주요 근거 |
|---|---|---|
| 1 Robotaxi clearance | `changes_required` | 출시 승인을 실제 운영 개시로 확장 |
| 2 China recall | `changes_required` | Summary의 `record→대규모` 의미 손실; `주도하고 있다`와 Explanation의 `기록적인`은 허용 |
| 3 Revenue + stock drop | `approved` | `revenue→매출`, 두 사건, neutral 정책 보존; `최근에`는 비차단 삭제 권고 |
| 4 Analyst roundup | `changes_required` | roundup 포함을 TSLA의 상·하향 모두 발표로 확장 |
| 5 Delivery sites | `changes_required` | `배송 사이트` 도메인 용어 오류와 neutral sentiment 정책 불일치 |

Case 5의 `수요 증가에 맞춰/따라`는 이 제목에서 허용했지만, 실제 차량 인도량·판매량·매출 증가로 확장하는 것은 허용하지 않았다. Dataset annotation은 `draft`를 유지하고, 공식 semantic accuracy나 전체 False Acceptance/False Rejection Rate는 계산하지 않았다.

### 확인된 문제와 가설

**확인된 문제**

- 자동 Validator 5/5 통과만으로 위 의미 후보를 판정할 수 없다.
- v3는 Case 3 용어를 개선했지만 Case 5의 목표 용어를 생성하지 않았다.
- 정상으로 검수됐던 v2 Case 1·4와 비교해 v3에 새로운 의미 확장 오류가 확인됐다.

**아직 검증되지 않은 가설**

- 일반 지침이 일부 용어 보존에는 도움을 주지만 다른 사건의 행위 상태를 과도하게 구체화할 수 있다.
- v2/v3 차이는 Prompt 변경 효과와 모델 변동이 섞여 있을 수 있다.
- 4/5 sentiment 일치는 Prompt v3의 효과라고 볼 수 없다. Sentiment 관련 변수를 의도적으로 바꾸지 않았기 때문이다.

### 한계

- v3 판정은 사용자가 승인한 AI 보조 검수이며, 독립적인 제3자 검수가 아니다.
- Offline fixture 12개는 Prompt 문자열·노출 계약을 확인하는 회귀 자료이지 실제 모델 평가 12건이 아니다.
- 5개 Case 한 번의 결과로 일반화 성능이나 인과적 개선을 주장할 수 없다.

### 다음 의사결정

1. 확정된 Case 1·2·4·5 문제를 기준으로 Prompt 추가 변경, Validator 확장 또는 별도 Semantic Grader 중 적절한 책임 경계를 선택한다.
2. 변경 전에 타사·다양한 문장 구조를 포함한 회귀 case와 반복 실행 설계를 확정한다.
3. 이 5-case 결과는 development diagnostic으로만 유지하고 공식 성능 주장에 사용하지 않는다.

## Validator v2 — 차량 사건 근거 구분

### 실험 목적

`delivery_location`, `vehicle_delivery_volume`, `vehicle_recall`을 article ID별 headline 근거와 비교해, 인도 거점·리콜을 인도 대수 주장의 근거로 오인하는 v1 한계를 차단한다.

### 변경한 변수

- Production Validator의 차량 사건 키워드 규칙만 phrase/concept 규칙으로 교체했다.
- Validator version을 `news-analyzer-validator-v2`로 올렸다.
- Prompt는 `news-analyzer-prompt-v3`, Dataset/hash, Structured Output schema, 재작성 로직은 그대로 두었다.

### 검증 결과

- 타사·동의어·복합 headline을 포함한 offline 회귀 matrix를 추가했다.
- 전체 `pytest`: `230 passed`
- Ruff: `All checks passed!`
- 저장된 v1 Run `evalv2_20260923T073211Z_b6941567` 재검증에서 Case 5 Attempt 1은 v1 `pass` → v2 `reject(vehicle_delivery_volume)`로 바뀌었다.
- 저장된 v2/v3 Run의 각 5개 출력은 새 규칙에서도 모두 통과했다. 이는 차량 사건 규칙의 호환성 확인이지 의미 품질 승인이 아니다.
- OpenAI API는 호출하지 않았고, 과거 Run artifact도 수정하지 않았다.

### 확인된 한계

- bare `delivery`/단순 `차량 인도`는 인도 대수 claim으로 보지 않는다. 수량·증감·보고서 문맥이 있어야 한다.
- 새 규칙은 사건 concept grounding의 최소 안전선이며, 번역 적절성·행위 상태·인과관계·전체 의미 일치를 판정하지 않는다.
- v2/v3 출력 통과를 semantic accuracy 또는 False Rejection rate로 해석하지 않는다.

## Validator v2 — Offline 재작성 통합 검증

### 검증 목적

`delivery sites`를 차량 인도 대수 증가로 확장한 Structured Output이 Validator v2에서 거부된 뒤, 기존 `NewsAnalyzer` 재작성·최종 실패 경로와 정상적으로 연결되는지 외부 API 없이 검증했다.

### 검증 결과

| 시나리오 | Mock 생성 호출 | 결과 |
|---|---:|---|
| 첫 초안의 근거 없는 인도 대수 claim → 거점 claim 재작성 | 2 | 첫 Attempt `output_policy_validation_error(vehicle_delivery_volume)`, 두 번째 Attempt 통과, `available=True` |
| 근거 없는 인도 대수 claim 3회 반복 | 3 | 네 번째 호출 없이 `validation_error`, `available=False`, sentiment/score 미제공 |
| 첫 초안부터 인도 거점 claim | 1 | 재작성 없이 정상 반환 |
| API 예외 | 1 | Validator 재작성 없이 `llm_error`, `available=False` |
| 알 수 없는 supporting article ID → 올바른 ID 재작성 | 2 | 첫 Attempt `evidence_id_validation_error`, 두 번째 Attempt 통과 |

재작성 요청에는 Validator 오류 사유와 허용 article ID 목록이 전달되었고, 이전 초안의 문장 전문은 전달되지 않았다. Attempt telemetry에서 Pydantic parse 성공, Validator 실패/통과, API 예외를 서로 다른 outcome으로 확인했다.

- 신규 offline 통합 테스트: 5건 통과
- 전체 `pytest`: `235 passed`
- Ruff: `All checks passed!`
- OpenAI API, Dataset, Prompt v3, Validator v2 규칙, Structured Output schema, 재작성 횟수·feedback template, 기존 Run artifact는 변경하지 않았다.

### 남은 한계

- Mock으로 Production control flow를 검증한 것이며 OpenAI SDK·네트워크 통합 품질을 측정하지 않았다.
- 재작성 feedback은 concept 오류 사유를 전달하지만, 의미 품질 개선을 보장하지 않는다.
- 이 결과는 Validator·재작성 제어 흐름의 회귀 검증이지 실제 모델 품질 평가가 아니다.

## 아직 기록하지 않은 평가

다음 결과는 존재하지 않거나 아직 승인되지 않았으므로 이 문서에 성과로 기록하지 않는다.

- 독립적인 제3자 v3 Human Review
- 공식 semantic accuracy
- 전체 Validator false acceptance/false rejection rate
- Prompt 변경의 통계적 유의성 또는 일반화 효과
- 모델 간 품질·비용 비교
- Offline fixture 12개에 대한 실제 LLM 성능

## 관련 문서

- [Evaluation v2 설계](evaluation_v2.md)
- [실패 처리와 재작성 계약](failure-handling.md)
- v1/v2 사람 판정 원본: `reports/generated/evals/v2/evalv2_20260923T073211Z_b6941567_vs_evalv2_20260923T082028Z_bf085cc6_reviewer_annotation.json`
- v1/v2 판정 정책: `reports/generated/evals/v2/evalv2_20260923T073211Z_b6941567_vs_evalv2_20260923T082028Z_bf085cc6_human_review_policy.md`

# Failure Handling and Rewrite Contract

## 문서 범위와 표기

이 문서는 현재 Production 코드의 실패 처리 계약과 Evaluation v1 Pilot에서 관측한 재작성 실패를 설명한다. 평가 Runner 자체의 artifact 완전성 계약은 [Evaluation v2 설계](evaluation_v2.md#10-evaluation-v2-runner와-grader)를 참고한다.

- **구현 사실**: 현재 코드 경로에서 직접 확인 가능한 동작
- **설계 의도**: 해당 동작으로 달성하려는 운영 목표
- **가설**: 실험과 일치하지만 아직 반복 대조로 검증되지 않은 원인 설명

## NewsAnalyzer 생성·검증 흐름

`analysis/news_analyzer.py`의 `NewsAnalyzer.analyze()`와 `_request_validated_output()`은 다음 순서로 동작한다.

```text
NewsFetchResult
  ├─ 기사 없음 / 수집 unavailable → NewsAnalysis(available=false)
  ├─ HeadlinePolicy 관련성·prompt-injection 필터
  │    └─ eligible 기사 없음 → available=false
  ├─ 날짜 균형 + 사건 중요도로 기사 선택
  ├─ system prompt + 선택 기사 metadata user prompt 구성
  └─ 최대 3 Attempt
       ├─ OpenAI Responses API Structured Output 요청
       ├─ NewsLLMOutput Pydantic schema 검증
       ├─ supporting_article_ids 검증
       ├─ HeadlinePolicy 기반 output policy 검증
       └─ 통과 → NewsAnalysis(available=true)
```

### 1. Structured Output

**구현 사실**: `NewsLLMOutput`은 다음 필드를 강제한다.

- `sentiment`: `positive | neutral | negative`
- `score`: -1.0~1.0, sentiment 방향과 일관돼야 함
- `confidence`: 0~100
- 비어 있지 않은 `summary`
- 1~5개의 `key_topics`; 각 topic은 1~5개의 고유 `supporting_article_ids` 필요

OpenAI `responses.parse(..., text_format=NewsLLMOutput)` 뒤에도 `NewsLLMOutput.model_validate()`를 호출한다. Structured Output은 형식과 필드 계약을 제한하지만 headline과의 의미적 일치 전체를 보장하지 않는다.

### 2. Evidence 검증

**구현 사실**: `_validate_evidence_ids()`는 모든 인용 ID가 실제로 이번 요청에서 선택된 기사 ID인지 확인한다. 존재하지 않는 ID가 있으면 `evidence_id_validation_error`로 Attempt를 거부한다.

### 3. Production output policy

**구현 사실**: `_validate_output_policy()`는 다음을 검사한다.

- 추천·미래 예측 같은 금지 표현
- Summary가 원본 headline에 없는 사건 유형을 생성했는지
- 각 Topic과 Explanation이 자신이 인용한 headline의 사건 유형을 바꿨는지
- 상반된 방향 hint가 함께 있을 때 neutral 및 ±0.2 score 범위를 지켰는지

**설계 의도**: schema만 맞는 출력을 그대로 공개하지 않고 deterministic guardrail을 한 번 더 적용한다.

**확인된 한계**: 자연어 의미 전체를 이해하는 validator가 아니다. 도메인 번역, 행위 상태, 미묘한 인과관계, roundup의 대상별 방향과 Dataset별 expected sentiment 일부는 통과할 수 있다.

## Validator 실패와 최대 2회 재작성

`MAX_VALIDATION_ATTEMPTS=3`이므로 최초 생성 1회와 재작성 최대 2회다.

1. 첫 Attempt는 원본 prompt로 생성한다.
2. parse/schema/evidence/output policy 실패 시 오류 사유를 `validation_feedback`에 누적한다.
3. 다음 Attempt의 user prompt는 원본 기사 records를 그대로 포함하고, 누적 오류 사유와 허용 evidence ID를 추가한다.
4. “해당 위반만 수정하고 새 주장을 추가하지 말라”는 지시로 다시 생성한다.
5. 세 번째 Attempt도 실패하면 마지막 validation 예외를 `analyze()`로 전달한다.
6. `analyze()`는 이를 `error_code=validation_error`, `available=false`, `fallback_used=true`인 `NewsAnalysis`로 바꾼다.

**구현 사실**: 이전 Attempt의 전체 출력은 재작성 prompt에 직접 첨부하지 않는다. 평가 telemetry에는 저장될 수 있지만 재작성 입력과는 별개다.

**설계 의도**: 유효하지 않은 정성 결과를 억지로 공개하기보다 제한된 횟수 안에 계약을 충족하지 못하면 fail closed한다.

## API 오류와 Validation 오류의 차이

| 구분 | 발생 지점 | 재작성 여부 | 최종 NewsAnalysis | 의미 |
|---|---|---|---|---|
| API 오류 | 모델 호출 중 timeout, 인증·network/provider 예외 등 일반 예외 | 현재 코드에서는 즉시 중단, validation 재작성 안 함 | `available=false`, `error_code=llm_error` | 응답을 정상적으로 받아 검증하지 못함 |
| Parse/schema 오류 | Structured Output parse 실패, 결과 없음, Pydantic 불일치 | 최대 2회 재작성 | 모두 실패하면 `validation_error` | 응답 형식 계약을 충족하지 못함 |
| Evidence 오류 | 허용되지 않은 article ID 인용 | 최대 2회 재작성 | 모두 실패하면 `validation_error` | 근거 식별자 계약 위반 |
| Output policy 오류 | 금지 표현, 사건 유형 변경, mixed 방향 규칙 위반 | 최대 2회 재작성 | 모두 실패하면 `validation_error` | 현재 deterministic 의미·정책 규칙 위반 |

Attempt telemetry가 활성화된 Evaluation에서는 API 오류를 `api_error`, parse 문제를 `parse_failed`, Production Validator 문제를 `validator_failed`로 분리한다. API가 model ID나 token usage를 주지 않은 경우 값을 추정하지 않고 `null`로 남긴다.

## Neutral과 Unavailable

두 상태는 같은 의미가 아니다.

### Neutral

```text
available=true
sentiment=neutral
score=-0.2 ~ 0.2
fallback_used=false
error_code=null
```

**구현 사실**: 모델 호출, Structured Output, evidence와 output policy 검증을 모두 통과한 정상 정성 결과다. 상반된 방향의 headline이나 방향이 명확하지 않은 내용이 있을 수 있다.

### Unavailable

```text
available=false
sentiment=null
score=null
summary=null
key_topics=[]
fallback_used=true
error_code=<실패 원인>
```

**구현 사실**: 분석할 뉴스 부재, 관련 기사 부재, API key 부재, 모델 호출 실패 또는 최종 검증 실패처럼 결과를 신뢰 가능한 정성 분석으로 공개할 수 없는 상태다. `NewsAnalysis` 모델 validator가 unavailable 결과에 sentiment나 생성 내용을 넣지 못하게 막는다.

**설계 의도**: 실행 실패를 중립 시장 판단으로 위장하지 않는다.

대표 error code는 다음과 같다.

| 조건 | error code |
|---|---|
| 수집 자체가 unavailable이고 기사 없음 | `news_unavailable` |
| 기간 안 뉴스가 없음 | `no_news_in_window` |
| 관련성·안전성 필터 통과 기사 없음 | `no_relevant_news_for_analysis` |
| API key 없음 | `missing_api_key` |
| Validation 최종 실패 | `validation_error` |
| LLM API 또는 예상하지 못한 호출 오류 | `llm_error` |

## 전체 실패와 부분 실패의 경계

`workflow/reporting_pipeline.py`와 `workflow/financial_reporting_workflow.py`는 필수 정량 경로와 선택적 뉴스·LLM 경로를 구분한다.

| 실패 지점 | 현재 처리 | 실행 경계 |
|---|---|---|
| 대상 종목 가격 수집 | `ReportingPipelineError` | 전체 실패; 이후 단계 `skipped` |
| 대상 시장 분석 | `ReportingPipelineError` | 전체 실패; 이후 단계 `skipped` |
| SPY benchmark 수집·분석 | benchmark `unavailable` 또는 `insufficient_data` | 부분 실패; 대상 종목 분석 계속 |
| 뉴스 수집 | `NewsFetchResult(status=unavailable)` | 부분 실패; 정량 리포트 계속 |
| 일부 뉴스 구간 실패·포화·절단 | `status=partial`과 warning | 부분 성공; coverage 한계를 기록하고 계속 |
| 뉴스 Snapshot 저장 | stage `failed`, snapshot path 없음 | 부분 실패; 분석·리포트 계속 |
| 뉴스 없음·관련 기사 없음 | LLM 호출 없이 `NewsAnalysis.available=false` | 부분 실패; 리포트에 unavailable 표시 |
| API key·LLM API·최종 Validation 실패 | LLM section `unavailable` | 부분 실패; 정량 리포트 계속 |
| Markdown 구성 | `report_build_failure` | 전체 실패 |
| Markdown 저장 | `report_save_failure` | 전체 실패 |
| 최종 Run metadata 저장 | `FinancialReportingWorkflowError` | 전체 실패; 추적 artifact를 필수 조건으로 취급 |

부분 실패가 하나라도 있거나 warning이 있으면 최종 Run은 정상 완료로 위장하지 않고 `completed_with_warnings`가 된다. 필수 단계 실패는 `failed` metadata를 저장하려 시도하며 아직 실행되지 않은 downstream stage를 `skipped`로 기록한다.

## v1에서 재작성으로 복구되지 않은 이유

대상 Run은 `evalv2_20260923T073211Z_b6941567`이다.

### 코드·artifact로 확인된 사실

- Prompt v1의 공통 System Prompt가 차량 인도량의 구체적인 영문·한국어 표현을 모든 요청에 노출했다.
- Case 1~4의 첫 출력은 모두 schema parse에 성공했지만 원문에 없는 `vehicle_deliveries` 계열 주장 때문에 Production Validator가 거부했다.
- 각 Case는 총 3회 생성됐고, 재작성된 Attempt에서도 같은 계열 오류가 반복됐다.
- Case 1~4의 총 12개 Attempt는 모두 `output_policy_validation_error`였으며 Rewrite Rescue는 0/4였다.
- 재작성 prompt는 원본 headline records, 누적 오류 사유, 허용 ID와 수정 지시를 전달했다. 이전 생성 전문은 전달하지 않았다.
- 오류 사유에는 `vehicle_deliveries`라는 구체적 용어가 반복됐다.
- Case 5는 첫 Attempt에 Validator를 통과했지만 Human Review에서 delivery site를 차량 인도량 증가로 바꾼 주장이 확정됐다.

따라서 “Validator가 반복 오류를 감지했다”는 사실과 “재작성이 품질을 개선했다”는 주장은 분리해야 한다. v1에서는 후자가 입증되지 않았고, validator를 통과한 Case 5에도 의미 오류가 있었다.

### 아직 확인되지 않은 가설

- 공통 Prompt의 구체적 예시가 모델의 topic 선택을 priming했을 수 있다.
- 재작성 오류 메시지에 같은 용어가 반복되어 잘못된 주제가 계속 활성화됐을 수 있다.
- 단일 headline인데도 최소 1개 topic을 요구한 구조가 빈약한 근거에서 topic을 채우게 했을 수 있다.
- 생성의 확률적 변동 때문에 동일 패턴이 우연히 반복됐을 가능성을 완전히 배제할 수 없다.

Prompt v2에서 구체적 예시를 조건부로 바꾼 뒤 같은 5개 Case에 해당 반복 패턴이 나타나지 않은 것은 **관측된 대조 결과**다. 각 Prompt를 한 번만 실행했으므로 이 변화가 원인이라고 확정하거나 일반화할 수는 없다.

## 관련 코드와 기록

| 위치 | 책임 |
|---|---|
| `analysis/news_analyzer.py::NewsLLMOutput` | Structured Output schema와 sentiment-score 계약 |
| `analysis/news_analyzer.py::NewsAnalysis` | available/unavailable 결과 계약 |
| `analysis/news_analyzer.py::NewsAnalyzer.analyze` | 입력 상태, fallback, 최종 오류 분류 |
| `analysis/news_analyzer.py::NewsAnalyzer._request_validated_output` | 호출, parse, validator, 최대 2회 재작성 |
| `analysis/news_analyzer.py::_validate_evidence_ids` | 선택된 article ID 검증 |
| `analysis/news_analyzer.py::_validate_output_policy` | Production 의미·정책 guardrail |
| `analysis/headline_policy.py` | 관련성, injection, 방향·사건 의미 규칙 |
| `workflow/reporting_pipeline.py` | 대상 가격 필수·benchmark 선택 경계 |
| `workflow/financial_reporting_workflow.py` | 전체 stage와 fatal/optional 실패 orchestration |
| `workflow/run_tracking.py` | stage/run 상태와 artifact metadata 계약 |
| [실험 기록](experiment-log.md) | Prompt v1/v2/v3 관측 결과와 의사결정 |

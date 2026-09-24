# Evaluation v2 설계

## 1. 목적과 범위

Evaluation v2는 validator가 출력을 받아들였다는 사실과 실제 의미 품질을 분리해 측정한다. 1단계의 데이터 계약·검증·버전·해시·실행 전 manifest, 2단계의 opt-in attempt 관찰 지점에 이어 Dataset→NewsAnalyzer→Telemetry→Grader→Report를 연결하는 로컬 runner를 추가했다. production validator, 리포트 생성 workflow와 기본 운영 로그에는 전체 LLM 출력이 추가되지 않으며 실제 OpenAI API 평가도 자동 실행하지 않는다.

공식 OpenAI Evals 문서가 설명하는 것처럼 평가 데이터 스키마와 testing criteria를 분명히 하고, 서로 다른 grader의 결과를 별도로 유지하는 원칙을 따른다. 이 저장소에서는 특정 플랫폼에 종속되지 않도록 로컬 Pydantic 계약과 JSON Schema를 기준으로 삼는다.

가장 중요한 해석 규칙은 다음과 같다.

- **Validator pass는 형식·정책 계약 통과이지 의미적 정답 판정이 아니다.**
- 의미 정확도는 승인된 ground truth와 atomic claim 단위 판정으로 별도 계산한다.
- `unavailable`을 품질 지표에서 조용히 제외하지 않는다. 품질과 reliability 양쪽에서 분모·처리 방식을 명시한다.
- 실제 뉴스, synthetic adversarial, 기존 6개 legacy synthetic은 서로 다른 track으로 보고한다.
- development와 holdout 결과를 합쳐 하나의 정확도로 보고하지 않는다.
- 자동 grader 결과와 사람 판정 결과를 같은 이름의 지표로 합치지 않는다.

## 2. 지표 설계

### A. Component Quality

| 지표 | 측정 대상과 계산식 | 정답 기준·분모 | 자동화 / 사람 검수 | 현재 확보 정보 | 추가 정보와 현재 상태 |
|---|---|---|---|---|---|
| Sentiment Correctness | 최종 sentiment가 허용 정답 집합에 포함된 case 수 / sentiment gold가 승인된 전체 case 수. `unavailable`은 오답으로 계산하고, available-only 보조 지표도 함께 제시한다. | 사람이 승인한 `expected_sentiments`; 분모는 해당 label을 가진 case 전체 | exact match는 자동, mixed/ambiguous gold 작성은 사람 필요 | v1 6건의 expected sentiment와 최종 출력 | 실제 뉴스의 독립 annotation·adjudication 필요. v1 label은 human-approved가 아니므로 별도 legacy 지표만 가능 |
| Evidence ID Validity | 입력에 존재하는 유효 citation 수 / 출력 citation 전체. case-level로 unknown ID가 하나도 없는 비율도 병기한다. | 실행 시 모델에 제공된 article ID 집합; 분모는 출력 citation 수 | 완전 자동 | 현재 grader와 production validator가 ID membership 확인 | citation이 실제 주장을 지지하는지는 측정하지 못함. citation 0건은 validity N/A이고 evidence completeness로 별도 판정 |
| Claim Grounding | headline metadata가 직접 지지하는 atomic claim 수 / 출력 atomic claim 전체 | 승인된 expected/forbidden claim 및 article별 support mapping | claim 추출 보조는 자동화 가능하나 최종 support 판정은 사람 또는 사람과 calibration된 grader 필요 | 숫자 token·일부 사건 유형·필수 용어 검사 | 출력 atomic claim, claim→citation mapping, 사람 support label 필요. 현재 평가 불가 |
| Semantic Consistency | 사건 종류, 주체, 시점, 방향, 수치가 source 및 출력 내부에서 일관된 case 수 / 검수 가능한 case 전체 | 사람 rubric과 known deterministic rules | 알려진 규칙은 자동, 일반 paraphrase·의미 왜곡은 사람 필요 | sentiment-score, 차량 인도/실적 등 제한적 rule | 일반 의미 entailment label과 grader calibration 필요. 현재는 부분 평가만 가능 |
| Unsupported Claim Rate | source로 지지되지 않는 atomic claim 수 / 출력 atomic claim 전체 | 사람 판정된 claim support label | 사람 기준이 필요하며 자동 grader는 보조 수단 | 숫자 token 및 금지 문구 위반 일부 | 모든 출력 claim 보존·분해와 사람 판정 필요. 현재 계산 불가; claim이 0개면 rate 0과 함께 claim count 0을 보고 |
| Safety / Policy Compliance | 요구 policy를 모두 지킨 case 수 / 해당 policy가 적용되는 case 수. policy별 violation rate도 보고 | `policy_expectations`와 명시적 위반 rubric | 투자 권유·미래 예측·prompt injection 등은 상당 부분 자동, 경계 사례는 사람 필요 | 금지 패턴, prompt injection filter, v1 forbidden terms | 자동 규칙 밖의 우회 표현 label 필요. 현재 제한적 자동 판정만 가능 |

Sentiment, evidence validity, grounding을 하나의 `pass`로만 축약하지 않는다. 종합 gate가 필요하면 각 하위 지표와 분모를 먼저 공개하고, hard safety violation 또는 unknown evidence를 별도 hard-fail로 둔다.

### B. Reliability

| 지표 | 측정 대상과 계산식 | 정답 기준·분모 | 자동화 / 사람 검수 | 현재 확보 정보 | 추가 정보와 현재 상태 |
|---|---|---|---|---|---|
| First-pass Pass Rate | 첫 생성 attempt가 production validator pipeline을 통과한 case 수 / validator가 판정할 첫 생성 결과가 있는 case 수 | production parse·validator 결과 | 자동 | attempt outcome과 명시적 분자·분모 | `compute_validator_reliability_metrics`로 계산 가능. API 예외·호출 전 fallback은 분모에서 제외 |
| Final-pass Pass Rate | 허용 attempt 안에 validator pipeline을 통과한 case 수 / validator가 판정할 첫 생성 결과가 있는 case 수 | 마지막 production validator 상태 | 자동 | attempt sequence와 최종 available 상태 | `compute_validator_reliability_metrics`로 계산 가능. 의미 정확도와는 별개 |
| Rewrite Rescue Rate | 첫 attempt의 parse 또는 validator 실패 후 이후 attempt가 통과한 case 수 / 첫 attempt가 해당 실패인 case 수 | 동일 case의 attempt sequence | 자동 | 모든 attempt outcome | `compute_validator_reliability_metrics`로 계산 가능. API 예외는 rescue 분모에서 제외 |
| Unavailable Rate | 최종 `available=false` case 수 / 실행 대상으로 확정된 case 수 | 최종 structured state | 자동 | case trace의 `final_available`, `final_error_code` | `compute_validator_reliability_metrics`로 계산 가능. 원인별 세부 집계는 v2 runner에서 추가 필요 |
| Validator False Acceptance | 사람이 invalid로 판정했지만 validator가 pass한 attempt 수 / 사람이 invalid로 판정한 attempt 수 | 독립 human validity label | validator 결과 자동 + 사람 gold 필요 | validator 최종 pass/fail | 통과·거부된 모든 attempt와 blind human label 필요. 현재 평가 불가 |
| Validator False Rejection | 사람이 valid로 판정했지만 validator가 fail한 attempt 수 / 사람이 valid로 판정한 attempt 수 | 독립 human validity label | validator 결과 자동 + 사람 gold 필요 | validation error text 일부 | 거부된 raw/parsed output과 blind human label 필요. 현재 평가 불가 |

First/Final pass는 validator behavior 지표다. Sentiment Correctness, Claim Grounding과 같은 의미 품질 지표로 해석하지 않는다. Rewrite Rescue도 “validator를 통과하도록 수정됨”을 뜻하며, 재작성 품질 개선은 first/final 출력에 동일한 semantic rubric을 적용한 score delta로 별도 입증해야 한다.

### C. Efficiency

| 지표 | 측정 대상과 계산식 | 정답 기준·분모 | 자동화 / 사람 검수 | 현재 확보 정보 | 추가 정보와 현재 상태 |
|---|---|---|---|---|---|
| Latency | case 전체, attempt별 LLM, validation, E2E의 wall-clock ms; median·p90·p95와 실패 포함 count | 동일 환경·동일 dataset·동일 반복 조건 | 자동 | attempt 시작·종료와 API 호출+parse+validator 전체 latency | attempt 원자료는 수집 가능. 분포 집계와 환경 metadata 결합은 v2 runner 필요 |
| Token Usage | input, cached input, output, reasoning token 합계와 case당 분포 | provider response usage 원문 | 자동 | API가 제공한 input/output/total token을 attempt별 저장 | cached/reasoning 세부 usage와 분포 집계는 추가 구현 필요. 누락 값은 추정하지 않고 null |
| Cost per Case | attempt별 token × 실행일에 고정한 가격표의 합 / 실행 case 수; 실패 attempt 비용도 포함 | model snapshot별 가격표와 통화·가격 기준일 | 자동 계산, 가격표 확인은 사람 | 없음 | model snapshot, token usage, pricing version/date 필요. 현재 평가 불가 |

서로 다른 모델은 같은 dataset hash, prompt version, validator version, 반복 횟수와 실행 환경으로 paired 비교한다. 평균만 쓰지 않고 case별 차이와 p50/p95를 함께 남긴다.

### D. End-to-End Quality

| 지표 | 측정 대상과 계산식 | 정답 기준·분모 | 자동화 / 사람 검수 | 현재 확보 정보 | 추가 정보와 현재 상태 |
|---|---|---|---|---|---|
| Report Generation Success Rate | 필수 artifact까지 저장된 성공 run 수 / 시작된 적격 E2E run 수 | workflow terminal state와 파일 검증 | 자동 | run metadata와 report path | 고정 E2E case 목록·집계 runner 필요. 현재 과거 실행 사후 집계만 가능 |
| Final Report Grounding | 최종 report의 atomic factual claim 중 가격 snapshot·뉴스 evidence로 지지되는 claim 수 / factual claim 전체 | 고정 input snapshot과 사람 승인 support label | 계산·ID 검사는 자동, 일반 문장 support는 사람 필요 | 정량 값은 Python 계산, 뉴스 topic ID 일부 | raw price snapshot, report claim extraction, human rubric 필요. 현재 종합 평가 불가 |
| Report Completeness | upstream에서 이용 가능했던 필수 항목을 정확한 section에 표시한 run 수 / E2E run 수. 필수 field coverage도 병기 | availability-aware report contract | 대부분 자동, 가독성·유용성은 사람 | ReportBuilder 구조와 available/unavailable 표현 | 명시적 completeness rubric과 parser 필요. 현재 formal metric 없음 |
| Artifact Completeness | 기대한 report, news snapshot, run metadata, eval manifest 및 checksum이 모두 존재·연결된 run 수 / E2E run 수 | artifact contract | 완전 자동 | 세 artifact와 run_id 연결 | eval manifest, checksum, raw price snapshot 추가 필요. 현재 부분 평가만 가능 |

## 3. Dataset v2 구조

Pydantic source of truth는 `evaluation/dataset_v2.py`, 배포 가능한 JSON Schema는 `evals/schema/news_quality_dataset_v2.schema.json`이다. JSON Schema는 테스트에서 Pydantic 생성 결과와 일치하는지 확인한다.

### Dataset 단위

- `schema_version`: 계약 버전. 현재 `2.0`
- `dataset_id`, `dataset_version`: 의미 있는 ID와 semver
- `dataset_kind`: `real_news`, `synthetic_adversarial`, `legacy_synthetic`
- `split`: `development`, `holdout`, `legacy`
- `created_at`, `holdout_frozen_at`
- `cases`: 같은 kind와 split만 포함

한 파일은 하나의 track과 split만 담는다. 따라서 실제 뉴스와 synthetic adversarial, development와 holdout을 실수로 한 정확도에 합산하기 어렵다.

### Case 단위

- `case_id`, 설명, ticker, inclusive analysis window
- `news_headlines`: article ID, headline, 발행 시각, URL, publisher
- `data_source`: 실제/합성 구분, provider, 수집 시각, snapshot reference, provenance·license notes
- `expectations`: 허용 sentiment, required/optional/forbidden evidence, expected/forbidden atomic claims, policy expectation, deterministic lexical checks
- `human_annotation`: draft/reviewed/approved 상태, 익명화한 annotator/reviewer ID, 근거와 reviewer notes
- `difficulty`, `failure_categories`
- legacy case에만 `legacy_compatibility.recorded_output`

Validator는 case ID, article ID, claim ID 중복, 존재하지 않는 evidence 참조, 분석 기간 밖 기사, real/synthetic 혼합, split 혼합, naive datetime을 거부한다. holdout은 모든 case가 `approved`이고 `holdout_frozen_at`이 있어야 한다.

## 4. 데이터 분리와 holdout 운영

권장 경로는 다음과 같다.

```text
evals/datasets/news/
  real/development/*.json
  real/holdout/*.json
  synthetic/development/*.json
  synthetic/holdout/*.json
evals/fixtures/news_quality_cases.json       # 기존 6건, legacy
```

보고서는 최소한 다음 네 줄을 분리한다.

```text
real/development
real/holdout
synthetic/development
synthetic/holdout
```

기존 6건은 다섯 번째 `legacy_synthetic/legacy` 회귀 결과로만 보고한다. 대규모 dataset의 분모에 더하지 않는다.

holdout 운영 규칙:

1. development에서 rubric과 evaluator를 완성한다.
2. 실제 뉴스 case는 1차 annotator와 독립 reviewer가 확인한다. 중요한 holdout은 두 명 이상 annotation 후 adjudication을 권장한다.
3. 승인 완료 후 `split=holdout`, `status=approved`, `holdout_frozen_at`을 기록하고 version을 확정한다.
4. 평가 직전 validator가 canonical dataset SHA-256과 holdout ground-truth SHA-256을 manifest에 기록한다.
5. runner는 시작 직전과 결과 저장 직전에 `verify_manifest_dataset`을 호출한다.
6. holdout 정답 수정이 필요하면 기존 version을 덮어쓰지 말고 dataset version을 올려 새 baseline을 만든다.

해시는 JSON 들여쓰기나 key 순서가 아니라 검증된 canonical model을 대상으로 한다. 따라서 formatting 변경은 결과를 바꾸지 않고 의미 필드 변경은 hash mismatch로 실행을 중단시킨다.

## 5. 기존 6개 synthetic case 호환성

`EvaluationDatasetValidator`는 현재 `schema_version=1.0` fixture를 기존 `load_eval_cases`로 먼저 검증한 뒤 v2 `legacy_synthetic/legacy` view로 변환한다.

- 원본 파일과 기존 evaluator는 변경하지 않는다.
- 6개 case ID, sentiment, evidence, lexical checks, recorded output을 보존한다.
- 독립적인 human ground truth가 없으므로 `human_annotation.status=legacy_unreviewed`로 표시한다.
- v2 실제 뉴스 정확도나 holdout 정확도에 합산하지 않는다.

## 6. 실제 뉴스 case 작성 절차

1. 실제 뉴스는 `evals/templates/news_quality_real_development_v2.template.json`, 합성 공격 case는 `evals/templates/news_quality_synthetic_adversarial_development_v2.template.json`을 각 development dataset 파일로 복사한다. 두 종류를 한 파일에 섞지 않는다.
2. production 수집기가 만든 news snapshot을 기준으로 headline metadata를 옮긴다. 기사 본문을 사용했다면 headline-only 평가와 섞지 말고 별도 schema/version으로 관리한다.
3. analysis window의 미국 동부 날짜 안에 있는지 확인하고 snapshot 경로·수집 시각·provider를 기록한다.
4. 출력이 반드시 다뤄야 할 evidence, 포함해도 되는 evidence, 제외해야 할 evidence를 구분한다.
5. expected/forbidden claim은 한 문장에 하나의 검증 가능한 사실만 담는다. 주가 영향·투자자 반응·인과관계처럼 headline이 직접 말하지 않은 내용은 forbidden으로 둔다.
6. annotator가 sentiment와 evidence/claim rationale을 작성한다. reviewer는 원본 metadata를 독립적으로 확인하고 disagreement를 adjudication한다.
7. development 상태에서 다음 명령으로 검증한다.

```powershell
python .\validate_evaluation_dataset.py .\path\to\dataset.json
```

8. 실제 모델 실행 전 prepared manifest만 만들려면 다음처럼 실행한다. 이 명령은 API를 호출하지 않는다.

```powershell
python .\validate_evaluation_dataset.py .\path\to\dataset.json `
  --manifest-output .\reports\generated\evals\manifests\run.json `
  --mode offline_replay `
  --prompt-version news-prompt-v1 `
  --validator-version news-validator-v1
```

## 7. 사람이 직접 검수해야 하는 항목

- headline이 실제 사건의 주체·시점·상태를 어떤 범위까지 지지하는지
- mixed news에서 허용할 sentiment 집합과 confidence 해석
- paraphrase가 원래 사건을 보존하는지, 인과·확률·투자자 반응을 추가했는지
- atomic claim 분해와 각 claim의 supporting article mapping
- real-news source metadata와 정정 기사, 중복·후속 보도의 관계
- safety rule을 우회하는 간접 투자 권유나 미래 가격 암시
- validator false acceptance/false rejection 판정을 위한 각 attempt의 blind label
- 최종 report의 가독성·중요도·누락 여부

자동 grader 또는 LLM grader를 추가하더라도 사람 gold subset과 일치율, confusion matrix를 먼저 확인한다. calibration되지 않은 LLM grader 점수는 human ground truth로 부르지 않는다.

## 8. 실행 manifest

`EvaluationRunManifest`는 아직 실행 결과가 아니라 `status=prepared`인 실행 전 계약이다. 다음을 고정한다.

- dataset ID/version/path/canonical hash
- holdout ground-truth hash
- case ID와 개수
- runner 이름/version과 mode
- model ID, prompt version, validator version

다음 단계의 runner는 manifest를 먼저 저장하고, attempt trace·metric artifact가 같은 `run_id`를 참조하게 해야 한다. 현재 1단계는 성능 수치를 만들지 않는다.

## 9. Attempt-level Telemetry

`NewsAnalyzer`의 기본 동작은 telemetry 비활성화다. `AttemptTelemetryCollector(enabled=True)`를 명시적으로 주입한 평가 실행만 attempt를 메모리에 수집하고, `AttemptTelemetryArtifactStore.save()`를 호출한 경우에만 별도 JSON 파일을 만든다.

```python
collector = AttemptTelemetryCollector(enabled=True)
analyzer = NewsAnalyzer(
    client=client,
    model=model_id,
    attempt_telemetry_sink=collector,
)
analysis = await analyzer.analyze(news)
case_trace = collector.build_case_trace(case_id=case_id, analysis=analysis)
artifact = build_attempt_telemetry_artifact(
    eval_run_id=eval_run_id,
    cases=(case_trace,),
    dataset_id=dataset_id,
    dataset_version=dataset_version,
    dataset_hash=dataset_hash,
)
AttemptTelemetryArtifactStore().save(artifact)
```

기본 저장 위치는 `reports/generated/evals/attempts/<eval_run_id>.attempts.json`이다. 이 파일에는 통과 출력과 실패 초안, 오류 사유가 들어갈 수 있으므로 운영 `RunMetadata`, 일반 로그, 최종 `NewsAnalysis`와 분리한다. 저장 위치의 접근권한·보존기간·삭제 정책은 평가 환경에서 별도로 설정해야 한다.

attempt별 기록:

- 1부터 시작하는 attempt 번호, UTC 시작·종료 시각
- API 호출, structured parse와 production validator를 합친 wall-clock latency
- 요청 model ID와 응답이 실제 제공한 response model ID·response ID
- parse와 validator 결과를 분리한 outcome 및 단계별 error code/reason
- API 응답에서 접근 가능한 parsed structured output과 raw output text
- API가 제공한 input/output/total token usage; 누락되면 null

`response_model_id`, token usage, structured/raw output처럼 응답 또는 SDK가 제공하지 않은 값은 추정하지 않는다. API 예외에는 response model과 usage가 null이다. telemetry sink 자체가 실패해도 production 분석 성공·fallback 결과는 바뀌지 않는다.

`compute_validator_reliability_metrics`는 First-pass Validator Pass Rate, Final-pass Validator Pass Rate, Rewrite Rescue Rate, 평균 attempt 수, Final Unavailable Rate와 각각의 분자·분모를 계산한다. 이 결과의 `metric_scope`는 항상 `production_validator_only`이며 의미 정확도나 LLM 품질 점수로 부르지 않는다.

## 10. Evaluation v2 Runner와 Grader

`evaluation/v2_runner.py`는 다음 실행 경로를 제공한다.

```text
Dataset v2 validation + hash
  -> prepared manifest
  -> case-local NewsFetchResult (고정 metadata, RSS 재수집 없음)
  -> case-local NewsAnalyzer + AttemptTelemetryCollector
  -> final NewsAnalysis
  -> deterministic grader + human-review queue
  -> eval_run_id로 연결된 artifact set
```

기본 mode는 `recorded`이며 `--recorded-responses`를 반드시 전달해야 한다. recorded response plan도 dataset ID/version/hash 및 정확한 case ID 집합에 결합되므로 다른 dataset의 응답을 재사용할 수 없다. `live`는 `--mode live --allow-live`, 정확한 model ID와 `OPENAI_API_KEY`가 모두 있어야만 실행된다. CLI import나 기본 실행은 OpenAI client를 만들거나 외부 API를 호출하지 않는다.

```powershell
# 네트워크 없는 runner/grader smoke test
python .\evaluate_news_quality_v2.py `
  --dataset .\evals\datasets\news\real\development\tsla_headlines_pilot_v2.json `
  --recorded-responses .\evals\fixtures\news_quality_v2_recorded_smoke.json

# 향후 사용자가 비용 발생을 명시적으로 허용할 때만 실행
python .\evaluate_news_quality_v2.py `
  --mode live `
  --allow-live `
  --dataset .\path\to\approved-dataset.json `
  --model <exact-model-id>
```

`news_quality_v2_recorded_smoke.json`의 출력은 runner contract 검증용 사람이 작성한 stub이다. 현재 모델의 생성 결과나 품질 baseline이 아니다.

### 자동 채점 경계

`evaluation/v2_grader.py`는 다음만 결정론적으로 채점한다.

- 최종 sentiment가 허용 집합에 속하는지
- 최종 availability가 runnable news case의 현재 계약인 `available=true`와 일치하는지
- citation ID가 case 입력에 속하는지
- required/forbidden evidence 충족 여부
- 마지막 attempt의 structured parse와 production validator 결과
- attempt 수, latency, API 응답이 실제 제공한 token usage

현재 Dataset v2 schema에는 case별 `expected_available` 필드가 없다. 따라서 runner가 실행하는 1개 이상의 news headline을 가진 case의 expected availability는 현재 상태 계약에서 `true`로 파생하고 `expected_availability_source=dataset_v2_runnable_news_case_contract`를 결과에 기록한다. 데이터 부재·API/실행 오류·최종 검증 실패는 actual unavailable이며 expected availability 불일치로 남긴다. 추후 의도적인 unavailable case를 dataset에 넣으려면 schema/version을 올려 명시 필드를 추가해야 한다.

Expected Claim Grounding, Forbidden Claim 발생, Semantic Distortion, Unsupported Claim Rate, Validator False Acceptance/False Rejection은 문자열 포함 검사로 확정하지 않는다. 각 결과는 `needs_human_review` 또는 `not_evaluated`이고, `human_review.md`에 원본 headline, final output, 거부된 초안과 rubric checkbox를 함께 제공한다. 따라서 validator pass rate와 semantic accuracy는 결과 JSON에서도 서로 다른 필드이며 `semantic_accuracy_evaluated=false`로 고정된다.

### 결과와 실패 계약

기본 저장 위치는 git에서 제외된 `reports/generated/evals/v2/<eval_run_id>/`이다.

```text
manifest.json
case_outputs.json
attempt_telemetry.json
grading_results.json
validator_reliability.json
human_review.md
summary.json
report.md
run_status.json
```

모든 JSON artifact와 Markdown header는 같은 `eval_run_id`를 가진다. `manifest.json`은 실행 전에 고정한 `prepared` 계약이고 `run_status.json`이 `running`, `complete`, `incomplete` terminal state를 담당한다. 특히 전체 초안이 든 `attempt_telemetry.json` 저장이 실패하면 정상 실행으로 간주하지 않고 `incomplete`와 누락 artifact 목록을 남긴 뒤 non-zero로 종료한다. 이 정책은 evaluation runner에만 적용되며 telemetry 실패가 production `NewsAnalyzer` 결과를 바꾸지 않는 기존 계약은 유지한다.

development 또는 draft case가 하나라도 포함된 현재 pilot 결과는 `result_scope=development_diagnostic`, `official_performance_eligible=false`이다. 공식 결과는 schema가 강제하는 frozen holdout과 전 case `approved` 조건을 만족해야 한다.

## 11. 다음 단계: calibrated semantic grader와 정식 평가

1. 5개 pilot을 독립 annotator와 reviewer가 headline 범위 안에서 adjudication하고 `approved`로 승격한다.
2. development에서 사람 판정 형식과 claim-level 분모를 먼저 고정한다.
3. 사람 gold subset과 비교해 semantic grader의 agreement/confusion matrix를 calibration한다.
4. first/final output 양쪽에 동일한 rubric을 적용해 rewrite 전후 semantic delta와 regression을 계산한다.
5. 거부·통과 attempt 표본을 blind review해 validator false acceptance/rejection을 계산한다.
6. 별도 frozen holdout을 만들고 development와 분리해 실행한다.
7. model ID별 반복 평가 시 동일 dataset hash, prompt, validator와 환경을 고정하고 p50/p95 latency를 보고한다.
8. 실행일 기준 가격표 artifact를 별도 고정한 뒤에만 API 비용을 계산한다.

Semantic grader와 사람 검수가 연결되기 전에는 “재작성으로 의미 품질이 개선됐다”고 주장하지 않는다.

## 참고

- [OpenAI Evals guide: test data와 testing criteria](https://developers.openai.com/api/docs/guides/evals)
- [OpenAI Responses API: response model ID와 token usage](https://developers.openai.com/api/reference/python/resources/responses/methods/retrieve)
- [OpenAI model selection guide: 목표에 맞는 evaluation dataset 구성](https://developers.openai.com/api/docs/guides/model-selection)

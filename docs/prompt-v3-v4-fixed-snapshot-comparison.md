# Prompt v3/v4 고정 Snapshot 비교 요약

## 문서 상태

- 목적: Prompt Evidence 계약 변경의 개발용 진단 결과를 Git 추적 문서로 보존
- 평가 성격: MSFT·AAPL development 사례의 고정 입력 단일 실행
- 사람 검수 상태: AAPL 최종 판정 미확정, MSFT는 최종 수용 출력 없음
- 공식 성능 사용: 불가

이 문서는 `reports/generated/`의 원본 manifest, final output, Attempt telemetry와
검수 초안을 요약한다. 원본 전체를 Git에 포함하지 않으며 공식 semantic
accuracy, 일반화 성능 또는 False Acceptance/False Rejection Rate를 제시하지
않는다.

## 통제 조건

| 구분 | MSFT | AAPL |
|---|---|---|
| 원본 Live Run | `run_20260924T124157_943453Z_MSFT_52e3447a` | `run_20260924T125748_449951Z_AAPL_09ed7635` |
| 고정 입력 | 재구성된 headline metadata 60건 | 재구성된 headline metadata 60건 |
| ID 순서 SHA-256 | `c1518a982c3372a09ca36221f205d4a24b21c2e41694e1e7292d23456b4588c8` | `09d427970dbf997e7e39192a60b7382585dad3469d1b2516a10f22cdc699942e` |
| 요청 모델 | `gpt-4o-mini` | `gpt-4o-mini` |
| Validator | `news-analyzer-validator-v2` | `news-analyzer-validator-v2` |
| 최대 생성 시도 | Prompt별 3회 | Prompt별 3회 |

동일 종목의 v3와 v4는 같은 Snapshot에서 동일한 60개 article ID와 순서를
사용했다. Structured Output/Pydantic, Validator, 재작성 상한은 유지하고 Prompt
version만 변경했다. 네 분석 Case에서 실제 OpenAI 생성 Attempt는 총 11회였다.

## 실행 결과

| 조합 | Attempt | 최종 상태 | 비고 |
|---|---:|---|---|
| MSFT v3 | 3 | `unavailable` | 금지 표현 거부 후 두 번의 supporting ID 중복으로 Pydantic 실패 |
| MSFT v4 | 3 | `unavailable` | 금지 표현, unknown article ID, 금지 영향 표현으로 거부 |
| AAPL v3 | 3 | `available` | 두 번의 정책 거부 후 최종 통과 |
| AAPL v4 | 2 | `available` | 한 번의 정책 거부 후 최종 통과 |

MSFT는 두 Prompt 모두 최종 수용 출력이 없으므로 Summary·Topic 의미 품질이나
Prompt 우열을 비교할 수 없다. 거부 초안은 실패 원인 분석 자료일 뿐 최종 모델
출력이 아니다.

## 관찰된 변화와 남은 문제

AAPL v3 최종 출력은 동일한 자사주 매입 headline의 서로 다른 배포본을 두 번
인용했다. AAPL v4 최종 출력에서는 이 중복 인용이 관찰되지 않았고, 직접 근거
하나만 사용한 Topic이 늘었다.

그러나 AAPL v4에도 다음 의미 품질 후보가 남았다.

- iPhone 18 Topic에 Mac/Mac Mini 매출 기사를 연결함
- headline의 `49.6% revenue stream`을 정확한 분모가 확인되지 않은 상태에서
  `매출의 49.6%`로 압축함
- `중요한 영향을 미칠`, `관심이 높아지고`, `긍정적인 신호`와 같은 평가·영향
  표현을 headline보다 강하게 추가함
- 마지막 실적 발표와 같은 주의 시가총액 사건을 하나의 사건처럼 결합함

따라서 v4는 일부 인용 수와 중복 패턴이 달라졌지만, 일반적인 Topic-level
grounding 문제를 해결했다고 볼 수 없다. Validator 통과 역시 사람 의미 검수
승인을 뜻하지 않는다.

## 해석 한계와 현재 방향

- MSFT·AAPL은 v4 설계에 사용된 development 사례이며 holdout이 아니다.
- 종목·Prompt별 단일 실행이므로 안정적인 품질·지연시간·비용 우위를 말할 수 없다.
- 기사 본문은 확인하지 않았으며 headline metadata 범위만 검수했다.
- AAPL의 AI 보조 검수 제안은 사용자의 최종 승인 판정이 아니다.

현재 작업 방향은 Production 기본 Prompt를 `news-analyzer-prompt-v3`로 유지하고
`news-analyzer-prompt-v4`를 experimental opt-in으로 보존하는 것이다. 이는 제한된
development 결과에 기반한 현재 권고 방향이며, 별도의 사용자 최종 검수·채택
기록이나 공식 성능 결론으로 해석해서는 안 된다.

# AAPL 필터 개선 후 Live E2E Human Review 초안

## 문서 상태와 범위

- 상태: `draft_ai_assisted_review`
- 대상 Run: `run_20260924T125748_449951Z_AAPL_09ed7635`
- 실행 전 확인 Git SHA: `58f6120e57e741e8b73d04985660e485a1823bf3`
- 비교 관찰 Run: `run_20260924T124157_943453Z_MSFT_52e3447a`
- 검수 근거: 저장된 Markdown report, News Snapshot, RunMetadata, 단일 실행 콘솔 기록
- 검수 범위: headline metadata만 사용한 AI 보조 검수 제안

기사 본문이나 외부 자료는 조회하지 않았다. 아래 `direct_support`,
`partial_support`, `unrelated`, `insufficient_headline_information`은 MSFT 검수와
동일한 기준으로 작성한 AI 보조 제안이다. 사람의 최종 판정, 공식 semantic
accuracy, 종목 간 통제된 성능 비교가 아니다. 원본 artifact는 수정하지 않았다.

## 1. Run과 artifact 연결

| Artifact | 저장 경로 | SHA-256 | 연결 확인 |
|---|---|---|---|
| Markdown report | `reports/generated/report_AAPL_2026-08-20_2026-09-18_20260924T125748_449951+0000.md` | `7B08822747BE31058D8432FDD5DCF30EBC98C37E3C1F29BA33BAEDCD94D30BD2` | 동일 Run ID, AAPL, 요청 기간 2026-08-20~2026-09-18 |
| News Snapshot | `reports/generated/news_snapshots/news_AAPL_2026-08-20_2026-09-18_20260924T125749_745945Z.json` | `025E0B7EC18854444B61399AF76E59966E03C0E5B0EA28BC86A60B6FE4106065` | AAPL, 동일 기간, 저장 기사 659건 |
| RunMetadata | `reports/generated/run_metadata/run_20260924T125748_449951Z_AAPL_09ed7635.json` | `2D0255B3EAD686B2E84D3C40C10E58402F490EC74A6D6F970976175CC4ED4BD2` | report와 Snapshot의 위 경로를 연결 |

RunMetadata에는 Git SHA가 별도 필드로 저장되지 않는다. 위 Git SHA는 실행 전
확인 기록으로 Run에 연결한 실행 조건이다.

### 실행·수집 상태

| 항목 | 저장 결과 |
|---|---:|
| 전체 상태 | `completed_with_warnings` |
| LLM 상태 / fallback | `available` / `false` |
| 총 실행 시간 | 56,208.228 ms |
| 실제 가격 범위 | 2026-08-20~2026-09-18, 21 trading days |
| AAPL 기간 수익률 | 7.98% |
| 연환산 변동성 | 21.86% |
| 최대 낙폭 | -3.92% |
| RSI(14) | 64.27 |
| MACD difference | 1.6133 |
| SPY 수익률 / AAPL-SPY 차이 | 0.13% / 7.85% |
| RSS 요청 / 실패 | 29 / 0 |
| 원본 RSS / 기간 밖 / 기간 내 | 1,228 / 15 / 1,213 |
| 중복 제외 / Snapshot 저장 | 554 / 659 |
| 뉴스 coverage | `partial` |

2026-09-08~2026-09-11의 네 일별 구간이 RSS 100건 상한에 도달해 전체 수집을
보장할 수 없다. 따라서 선택 60건과 LLM 출력도 전체 기간을 완전히 대표한다고
볼 수 없다.

### 필터·선택 Offline 재구성

- ticker/회사명 관련성 제외: 45건
- unsafe instruction 제외: 0건
- low-information page 제외: 5건, 모두 정형화된 옵션 계약 목록
- 필터 통과: 609건
- 재구성 선택: 60건
- 선택 이유: `time_balance` 42건, `global_importance` 18건
- 재구성 선택에 남은 low-information page: 0건
- report 인용 ID 8개: Snapshot과 재구성 선택에 모두 존재

Production artifact는 선택된 60개 ID 전체를 저장하지 않는다. 위 선택 관련
결과는 동일 Snapshot에 현재 결정론적 코드를 Offline 재적용한 결과다.

### Attempt 기록 범위

단일 CLI 실행의 콘솔에는 OpenAI HTTP 200 응답 2회가 기록됐다.

1. 첫 초안은 금지 표현 `긍정적인 영향을 미칠`이 검출돼 거부됐다.
2. 한 번 재작성한 두 번째 응답이 최종 채택됐다.

RunMetadata에는 재작성 1회 warning이 남아 있다. Attempt별 원문, token usage,
response ID와 실제 응답 model ID는 저장되지 않았으므로 복원하거나 추정하지
않는다.

### 전체 warnings와 errors

1. 분석 기간 밖 RSS 항목 15건 제외
2. 중복 RSS 항목 554건 제외
3. RSS 100건 상한으로 전체 수집을 보장할 수 없는 구간 4개
4. Google News RSS의 전체 언론사 수집 범위는 알 수 없음
5. ticker/회사명과 직접 연결되지 않은 뉴스 45건 제외
6. 명백한 비뉴스형 페이지 5건 제외
7. 필터 통과 609건 중 날짜 균형 42건과 중요도 18건, 총 60건 선택
8. coverage가 partial이므로 LLM 결과의 전체 기간 대표성을 보장할 수 없음
9. 결정론적 검증 실패 후 1회 재작성

치명적 `error_code`와 `error_message`는 없다.

## 2. Summary·Topic·Explanation 원문

아래 문장은 Markdown report의 최종 LLM 출력을 수정 없이 옮긴 것이다.

### Summary

> 애플은 AI 기능을 갖춘 AirPods를 2027년에 출시할 예정이며, 주식 매입 프로그램과 같은 자본 행동이 주주들에게 중요하다.

### Topic 1

- Topic: `AI 기능을 갖춘 AirPods 출시 계획`
- Explanation: `애플은 AI 기능을 갖춘 AirPods를 2027년에 출시할 예정이며, 이는 회사의 기술적 진전을 나타낸다.`

### Topic 2

- Topic: `EU 앱 스토어 수수료 구조 변경`
- Explanation: `애플은 EU의 규제 분쟁을 해결하기 위해 앱 스토어 수수료 구조를 업데이트했다.`

### Topic 3

- Topic: `주식 매입 프로그램 확대`
- Explanation: `애플은 가장 큰 규모의 자사주 매입을 발표하며 주주 가치를 높이는 노력을 하고 있다.`

### Topic 4

- Topic: `아이폰 18 출시와 매출 증가`
- Explanation: `애플은 아이폰 18 출시를 통해 약 49.6%의 매출 흐름을 강조하며 주가에 긍정적인 영향을 미치고 있다.`

### Topic 5

- Topic: `기대되는 새로운 CEO의 리더십`
- Explanation: `애플의 새로운 CEO 존 터너스는 기존의 프리미엄 가격을 유지할 수 있을지에 대한 기대를 모으고 있다.`

### Summary 검수 제안

- AI AirPods headline은 Apple이 2027년 출시를 `still eyes`한다고 표현한다.
  `출시할 예정`은 계획을 나타낼 수 있지만 원문의 목표·검토 상태보다 확정적으로
  읽힐 위험이 있다.
- buyback headline은 프로그램 규모가 shareholders에게 중요하다고 직접 말해
  Summary 후반은 제목 근거가 있다.
- AI 보조 권고: `changes_required` 또는 `judgment_deferred` 후보. 2027년 출시를
  확정 일정이 아닌 목표·계획으로 제한할지 사람이 결정해야 한다.

사람 판정: [ ] 승인 / [ ] 수정 필요 / [ ] 판단 보류

## 3. Topic 5개 × 인용 기사 8개 검수표

분류 기준은 MSFT 문서와 동일하다.

- `direct_support`: headline이 Topic/Explanation 핵심을 직접 진술한다.
- `partial_support`: 인접한 사실은 있으나 핵심 주장 전체는 뒷받침하지 않는다.
- `unrelated`: headline의 사건이 Topic 핵심과 다르다.
- `insufficient_headline_information`: 본문 없이는 해당 판정을 할 수 없다.

날짜는 Snapshot `published_at`의 UTC 날짜다.

### Topic 1 — AI 기능을 갖춘 AirPods 출시 계획

| Article ID | 날짜 | Headline 원문 | 제안 분류 | 제목 기준 검수 의견 |
|---|---|---|---|---|
| `news_69c0ac8553a3a607` | 2026-08-20 | Apple still eyes 2027 launch for AI-powered AirPods despite video leak - report - Seeking Alpha | `partial_support` | AI-powered AirPods의 2027년 출시 목표는 직접 뒷받침한다. 다만 `still eyes`는 확정 완료가 아닌 목표·계획 상태이고, `회사의 기술적 진전`이라는 평가는 제목에 없다. |

#### Topic 1 종합 의견

- Topic의 출시 계획은 근거가 있지만 Explanation의 확정성 수준과 `기술적
  진전` 평가는 추가 검수가 필요하다.
- AI 보조 권고: `changes_required` 후보.

사람 판정: [ ] 승인 / [ ] 수정 필요 / [ ] 판단 보류

### Topic 2 — EU 앱 스토어 수수료 구조 변경

| Article ID | 날짜 | Headline 원문 | 제안 분류 | 제목 기준 검수 의견 |
|---|---|---|---|---|
| `news_e76f343f1dc1d8a8` | 2026-08-20 | Apple Updates EU App Store Commission Structure to Resolve Regulator Disputes - TIKR.com | `direct_support` | EU App Store commission structure 업데이트와 규제 분쟁 해결 목적을 모두 직접 언급한다. Explanation은 제목 범위를 벗어나지 않는다. |

#### Topic 2 종합 의견

- 제목만을 기준으로 Topic과 Explanation이 직접 뒷받침된다.
- AI 보조 권고: `approved` 후보. 기사의 진위나 실제 분쟁 해결 완료 여부는
  headline 검수 범위 밖이다.

사람 판정: [ ] 승인 / [ ] 수정 필요 / [ ] 판단 보류

### Topic 3 — 주식 매입 프로그램 확대

두 ID는 publisher만 다르고 headline 본문이 동일한 near-duplicate다.

| Article ID | 날짜 | Headline 원문 | 제안 분류 | 제목 기준 검수 의견 |
|---|---|---|---|---|
| `news_4067be5c2ec62860` | 2026-08-22 | Apple Announced Its Largest-Ever Stock Buyback Under Tim Cook's Leadership. Here's Why the Size of the Repurchase Program Matters for Shareholders. - The Motley Fool | `partial_support` | largest-ever buyback 발표와 shareholders에게 규모가 중요하다는 점은 직접 뒷받침한다. 그러나 `주주 가치를 높이는 노력`이라는 회사의 목적·의도는 제목에 명시되지 않는다. |
| `news_caec6a56c29172d6` | 2026-08-22 | Apple Announced Its Largest-Ever Stock Buyback Under Tim Cook's Leadership. Here's Why the Size of the Repurchase Program Matters for Shareholders. - Yahoo Finance | `partial_support` | 위 기사와 동일한 headline이다. 독립된 두 근거라기보다 중복 배포본으로 봐야 하며, 주주 가치 제고 목적은 제목에서 확정할 수 없다. |

#### Topic 3 종합 의견

- 프로그램 규모와 발표는 뒷받침되지만 `주주 가치를 높이는 노력`은 해석이
  추가된 표현이다.
- 동일 headline을 두 번 인용해 evidence 다양성이 증가한 것처럼 보일 수 있다.
- AI 보조 권고: `changes_required` 후보.

사람 판정: [ ] 승인 / [ ] 수정 필요 / [ ] 판단 보류

### Topic 4 — 아이폰 18 출시와 매출 증가

| Article ID | 날짜 | Headline 원문 | 제안 분류 | 제목 기준 검수 의견 |
|---|---|---|---|---|
| `news_eac346be8f83e121` | 2026-08-24 | Apple Shares Gain With iPhone 18 Launch Schedule Highlighting 49.6% Revenue Stream - TechStock² | `partial_support` | iPhone 18 launch schedule, shares gain과 49.6% revenue stream은 제목에 있다. 그러나 `With`라는 동시·연관 표현만으로 출시가 주가 상승에 긍정적 영향을 미쳤다는 인과를 확정하기 어렵고, 49.6%가 매출 증가율인지도 제목만으로 알 수 없다. |
| `news_5bb9c3bb3b1dd963` | 2026-08-25 | Apple Faces 29% Mac Revenue Jump Amid Mac Mini Price Hike - TechStock² | `partial_support` | Apple의 revenue jump를 언급하지만 Mac/Mac Mini 사건이며 iPhone 18 근거가 아니다. 서로 다른 제품의 매출 사건을 하나의 iPhone 18 Topic으로 결합했다. |

#### Topic 4 종합 의견

- 49.6%와 29%는 headline에 존재하므로 숫자 자체를 새로 만든 것은 아니다.
- 다만 49.6%의 정확한 분모·의미는 제목만으로 판단할 수 없고, 이를 `매출
  증가`로 단정하면 의미 확장 위험이 있다.
- 첫 초안의 `긍정적인 영향을 미칠`은 Validator가 거부했지만 최종 Explanation의
  `긍정적인 영향을 미치고 있다`는 통과했다. 후자도 제목의 연관 표현을 인과로
  강화했을 가능성이 있어 사람 검수가 필요하다.
- AI 보조 권고: `changes_required` 후보.

사람 판정: [ ] 승인 / [ ] 수정 필요 / [ ] 판단 보류

### Topic 5 — 기대되는 새로운 CEO의 리더십

| Article ID | 날짜 | Headline 원문 | 제안 분류 | 제목 기준 검수 의견 |
|---|---|---|---|---|
| `news_1fb08af458cc8649` | 2026-09-02 | Tim Cook's Final Earnings Call as Apple CEO Came the Same Week Apple Hit a $5 Trillion Market Cap. Here's What Investors Should Watch Under His Successor. - Yahoo Finance | `partial_support` | Tim Cook의 후임자와 leadership transition은 뒷받침하지만 `John Ternus`라는 이름과 premium pricing 유지는 제목에 없다. $5 trillion market cap을 프리미엄 가격 유지로 바꿀 수도 없다. |
| `news_12f79504f23a1f82` | 2026-09-02 | Apple’s New CEO Has Millions Riding on the Stock Beating the Market - Barron's | `partial_support` | 새 CEO와 주가 성과 이해관계는 언급하지만 CEO의 이름이나 Apple 제품의 premium pricing 유지는 없다. |

#### Topic 5 종합 의견

- 새 CEO·후임자라는 일반 사건은 뒷받침된다.
- `존 터너스`라는 실명과 `기존의 프리미엄 가격을 유지`한다는 과제는 두
  headline 어디에도 없다. 제목만 입력한 시스템에서는 unsupported detail
  후보이며, 본문에서 사실일 가능성이 있다는 이유로 보충해서는 안 된다.
- AI 보조 권고: `changes_required` 후보.

사람 판정: [ ] 승인 / [ ] 수정 필요 / [ ] 판단 보류

## 4. MSFT와 AAPL에서 관찰된 공통점과 차이점

두 Run은 ticker, RSS 입력, coverage와 LLM 출력이 다르므로 정확도 증감,
일반화 성능 또는 오류 발생 확률을 계산하지 않는다.

### 공통으로 관찰된 현상

- 두 Run 모두 저정보성 페이지 필터가 실제 입력에 적용됐고 Offline 재구성
  선택에는 해당 페이지가 남지 않았다.
- 두 Run 모두 최종 supporting article ID가 Snapshot과 재구성 선택에 존재했다.
- 그럼에도 최종 출력에는 일부 supporting headline만 핵심 claim을 뒷받침하고
  나머지는 부분 관련 또는 다른 사건인 Topic이 남았다.
- 두 Run 모두 결정론적 Validator가 초안을 거부해 재작성했지만 최종 출력의
  일반적인 의미 관련성·평가 표현까지 보장하지는 못했다.
- 두 Run의 confidence는 모델 self-report이며 보정된 정확도 확률이 아니다.

### 다르게 관찰된 현상

| 관찰 축 | MSFT | AAPL |
|---|---|---|
| 뉴스 coverage | `available` | RSS 상한 구간 4개로 `partial` |
| Snapshot / low-information 제외 | 267 / 18 | 659 / 5 |
| 최종 Topic / 인용 ID | 3 / 15 | 5 / 8 |
| 대표 의미 문제 | 한 Topic에 이질적 evidence를 다수 결합, `근거 없는` 평가 추가 | 계획 상태 강화, 주가 영향 인과 강화, CEO 실명·premium pricing 추가, near-duplicate evidence |
| 직접 뒷받침되는 Topic 사례 | 제한된 개별 evidence | EU 수수료 구조 변경은 headline과 직접 일치 |
| 재작성 기록 | 2회: unknown ID, duplicate ID | 1회: 금지 영향 표현 |

Snapshot 규모나 제외 건수 차이는 검색 결과량과 coverage가 다르므로 필터 성능
차이로 해석하지 않는다.

## 5. 사람이 승인·수정·보류해야 할 쟁점

| 검수 대상 | AI 보조 제안 | 사람이 결정할 질문 | 최종 판정 |
|---|---|---|---|
| Summary | `changes_required` 또는 `judgment_deferred` 후보 | `still eyes`를 `출시할 예정`으로 표현할 수 있는가? | [ ] 승인 / [ ] 수정 필요 / [ ] 보류 |
| Topic 1 | `changes_required` 후보 | 출시 목표는 유지하되 `기술적 진전` 평가를 제거해야 하는가? | [ ] 승인 / [ ] 수정 필요 / [ ] 보류 |
| Topic 2 | `approved` 후보 | 제목 범위 안의 EU 수수료 구조 변경·분쟁 해결 목적 표현을 승인할 것인가? | [ ] 승인 / [ ] 수정 필요 / [ ] 보류 |
| Topic 3 | `changes_required` 후보 | buyback 발표는 유지하되 주주가치 제고 목적을 제한하고 중복 ID를 하나로 볼 것인가? | [ ] 승인 / [ ] 수정 필요 / [ ] 보류 |
| Topic 4 | `changes_required` 후보 | 49.6% 의미, iPhone/Mac 사건 결합, `긍정적인 영향을 미치고 있다` 인과 표현을 허용할 것인가? | [ ] 승인 / [ ] 수정 필요 / [ ] 보류 |
| Topic 5 | `changes_required` 후보 | 제목에 없는 CEO 실명과 premium pricing 과제를 제거해야 하는가? | [ ] 승인 / [ ] 수정 필요 / [ ] 보류 |
| 전체 Run | `judgment_deferred` | partial RSS coverage를 감안해 이 출력의 대표성을 어디까지 인정할 것인가? | [ ] 승인 / [ ] 수정 필요 / [ ] 보류 |

사람의 최종 판정 전에는 위 제안을 semantic accuracy, false acceptance rate,
종목 간 성능 차이 또는 필터의 의미 품질 개선 수치로 집계하지 않는다.

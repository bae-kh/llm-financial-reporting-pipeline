# MSFT 필터 개선 후 Live E2E Human Review 초안

## 문서 상태와 범위

- 상위 판정 상태: `user_decisions_recorded`
- 기사별 분류 상태: `draft_ai_assisted_review`
- 판정 provenance: 사용자가 AI 보조 검수 근거를 확인하고 Summary와 Topic 1~3의 `changes_required` 판정에 동의함
- 판정 기록 시각: `2026-09-24T12:56:43.7642269Z`
- 대상 Run: `run_20260924T124157_943453Z_MSFT_52e3447a`
- 실행 전 확인 Git SHA: `58f6120e57e741e8b73d04985660e485a1823bf3`
- 비교용 이전 Run: `run_20260924T085316_392408Z_MSFT_67842779`
- 검수 근거: 저장된 Markdown report, News Snapshot, RunMetadata
- 검수 범위: headline metadata만 사용한 AI 보조 검수 제안

기사 본문이나 외부 자료는 조회하지 않았다. 아래 `direct_support`,
`partial_support`, `unrelated`, `insufficient_headline_information`은 AI 보조
기사별 분류이며 사용자가 개별적으로 승인한 판정이 아니다. 사용자가 승인한
범위는 Summary와 Topic 1~3의 상위 `changes_required` 판정이다. 이 기록은
독립적인 제3자 Human Review, 승인된 의미 정확도 또는 공식 성능 지표가 아니다.
원본 artifact와 기존 감사 문서는 수정하지 않았다.

## 1. 새 Run artifact 연결

| Artifact | 저장 경로 | SHA-256 | 연결 확인 |
|---|---|---|---|
| Markdown report | `reports/generated/report_MSFT_2026-08-20_2026-09-18_20260924T124157_943453+0000.md` | `8AAEF37CC697213915AA7CC34F0CFF4347117D23773FE50D1A4CE58076447CFB` | 동일 Run ID, MSFT, 요청 기간 2026-08-20~2026-09-18 |
| News Snapshot | `reports/generated/news_snapshots/news_MSFT_2026-08-20_2026-09-18_20260924T124159_343770Z.json` | `6D20BB80719749EF0C5545A667C0ED01FF73927B17D6EAF3426318CFF3150FE5` | MSFT, 동일 기간, 저장 기사 267건 |
| RunMetadata | `reports/generated/run_metadata/run_20260924T124157_943453Z_MSFT_52e3447a.json` | `BABEBE35B8CE17923718D33C223B18A9D5E93B603B15D449CF36D04566C36FEA` | report와 Snapshot의 위 경로를 연결 |

RunMetadata에는 Git SHA가 별도 필드로 저장되지 않는다. 위 SHA는 Live 실행 전
Git 확인 기록으로 Run에 연결한 실행 조건이며 artifact 자체에서 추출한 값은
아니다. RunMetadata의 상태는 `completed_with_warnings`, LLM 상태는
`available`, fallback은 `false`다.

현재 코드를 Snapshot에 Offline 재적용한 결과는 다음과 같다.

- Snapshot 267건
- ticker/회사명 관련성 제외 16건
- unsafe instruction 제외 0건
- low-information page 제외 18건
- 필터 통과 233건
- 재구성 선택 60건: `time_balance` 42건, `global_importance` 18건
- 재구성 선택에 남은 low-information page: 0건
- report 인용 ID 15개: Snapshot과 재구성 선택에 모두 존재

Production artifact는 선택된 60개 ID 전체를 별도 저장하지 않는다. 따라서
마지막 세 항목은 저장된 선택 목록이 아니라 동일 Snapshot과 결정론적 현재
코드로 재구성한 결과다.

## 2. Summary·Topic·Explanation 원문

아래 문장은 Markdown report의 최종 LLM 출력을 수정 없이 옮긴 것이다.

### Summary

> 마이크로소프트는 최근 몇 가지 기사에서 재무 결과와 관련된 정보가 있었지만 상충되는 경향이 있었다.

### Topic 1

- Topic: `마이크로소프트의 높은 매출 가시성`
- Explanation: `마이크로소프트는 높은 매출 가시성을 보여주고 있으며, 이를 기반으로 한 자본 지출(투자) 측면에서 주목받고 있다.`

### Topic 2

- Topic: `근거 없는 투자 판단`
- Explanation: `여러 기사에서 마이크로소프트와 관련된 투자 판단이 상충되고 있다.`

### Topic 3

- Topic: `AI와 마이크로소프트의 수익 성장 가능성`
- Explanation: `마이크로소프트는 AI와 관련된 새로운 수익 흐름에 대한 잠재력이 있는 것으로 보인다.`

### Summary 검수 제안

- 일부 headline은 revenue visibility, revenue-sharing talks, console revenue,
  dividend와 stock forecast를 언급하므로 넓은 의미의 재무 관련 정보는 있다.
- 그러나 다수는 실제 `재무 결과` 발표가 아니라 전망·협상·의견·주가 예측이다.
  Summary가 이를 실제 financial results처럼 묶는다면 사건 상태를 확장한
  표현이 될 수 있다.
- 긍정·부정·중립적 관점이 섞여 있어 `상충되는 경향`이라는 요약에는 일부
  근거가 있지만, 무엇이 같은 기준에서 상충하는지 명시되지 않았다.
- AI 보조 권고: `changes_required` 후보.

사용자 승인 판정: `changes_required`

## 3. Topic 3개 × 인용 기사 15개 검수표

분류 기준은 다음과 같다.

- `direct_support`: headline이 Topic/Explanation 핵심을 직접 진술한다.
- `partial_support`: 인접한 개념은 있으나 핵심 주장 전체는 뒷받침하지 않는다.
- `unrelated`: headline의 사건이 Topic 핵심과 다르다.
- `insufficient_headline_information`: 본문 없이는 해당 판정을 할 수 없다.

날짜는 Snapshot `published_at`의 UTC 날짜다. UTC 자정 부근 기사는
America/New_York 기준 전날일 수 있다.

### Topic 1 — 마이크로소프트의 높은 매출 가시성

핵심 검수 질문은 다섯 기사가 각각 `높은 매출 가시성`과 이를 기반으로 한
`자본 지출 측면의 주목`을 뒷받침하는지다.

| Article ID | 날짜 | Headline 원문 | 제안 분류 | 제목 기준 검수 의견 |
|---|---|---|---|---|
| `news_1df2ca3b30d2ff63` | 2026-08-22 | Microsoft Stock: Higher Revenue Visibility Met Measured Capex (NASDAQ:MSFT) - Seeking Alpha | `direct_support` | `Higher Revenue Visibility`와 `Measured Capex`를 모두 직접 언급한다. `높은 매출 가시성`과 capex 설명을 직접 뒷받침한다. 기사 본문 없이 그 평가가 사실인지까지 확인할 수는 없다. |
| `news_07ebca4afbf85c39` | 2026-08-25 | MSFT, ORCL and INTC Forecast: Tech Stocks Eye a Rebound - Yahoo Finance | `unrelated` | 기술주 반등 전망은 언급하지만 매출 가시성이나 capex는 없다. `Forecast`라는 단어만으로 revenue visibility를 입증하지 못한다. |
| `news_a5eb54e29c2f9878` | 2026-08-26 | MSFT, AMZN, GOOGL Reportedly In Revenue-Sharing Talks With China's Moonshot AI Over Kimi K3 Model - Yahoo Finance | `partial_support` | revenue-sharing 협상은 잠재 수익원과 인접하지만 MSFT의 높은 매출 가시성이나 capex를 입증하지 않는다. `Reportedly`와 `Talks`라는 협상 상태를 확정 수익으로 확대해서는 안 된다. |
| `news_8414d1023301f38f` | 2026-08-27 | Microsoft launches $899 Xbox Series X25 in bid to gauge pricing power as console revenue drops 29% - TechStock² | `partial_support` | console revenue 29% 감소와 pricing power 측정은 매출 관련 사실이나 `높은 매출 가시성`을 지지하지 않는다. 오히려 부정적 수치가 포함돼 있으며 회사 전체 매출 가시성으로 일반화할 수 없다. |
| `news_632a678ef5f09fa4` | 2026-08-25 | Microsoft shares trade actively in U.S. premarket as MW4 Beta Dates link to Call of Duty recovery with 51% approval at stake - TechStock² | `unrelated` | premarket 거래, 게임 회복, 51% approval을 언급하지만 매출 가시성이나 capex는 없다. 이 수치를 매출 수치로 해석해서는 안 된다. |

#### Topic 1 종합 의견

- 첫 기사만 Topic과 Explanation 전체를 직접 뒷받침한다.
- revenue-sharing과 console revenue 기사는 `revenue`라는 단어를 공유하지만
  서로 다른 사건이며, 높은 매출 가시성의 반복 근거가 아니다.
- 다섯 기사를 하나의 일관된 `높은 매출 가시성` 추세로 묶는 것은 과도한
  일반화 후보다.
- AI 보조 권고: `changes_required` 후보. Topic을 첫 기사 범위로 좁히거나
  나머지 supporting ID를 제거·교체할지 사람이 결정해야 한다.

사용자 승인 판정: `changes_required`

### Topic 2 — 근거 없는 투자 판단

검수 대상을 `근거 없는`이라는 평가와 `투자 판단이 상충되고 있다`는 집합
설명으로 나누어야 한다.

| Article ID | 날짜 | Headline 원문 | 제안 분류 | 제목 기준 검수 의견 |
|---|---|---|---|---|
| `news_3bec1a17fca02b95` | 2026-09-08 | Microsoft Stock Forecast 2040, 2050: How High Can MSFT Go? - CoinCodex | `partial_support` | 장기 주가 전망의 존재는 보여주지만 제목이 질문형이며 방향·근거 수준을 확정하지 않는다. `근거 없는` 전망이라고 판정할 수 없다. |
| `news_31abbc8967d151d7` | 2026-08-31 | Microsoft Has Raised Its Dividend Every Year for More Than a Decade. History Provides Clues of How Big This Year's Raise Might Be. - The Motley Fool | `partial_support` | 배당 이력과 향후 인상 규모의 단서를 다룬다. 넓게는 투자 판단 재료지만 명시적인 투자의견이나 `근거 없음`을 말하지 않는다. |
| `news_5d4fc56aca5655fa` | 2026-09-18 | Microsoft Stock Hit My Target. Now I'm Stepping Back (Rating Downgrade) - Seeking Alpha | `partial_support` | `Rating Downgrade`와 stepping back이라는 부정적 판단을 직접 언급한다. 다만 판단이 근거 없는지는 제목만으로 알 수 없어 Topic 전체를 직접 뒷받침하지는 않는다. |
| `news_5c269070e8da32e1` | 2026-09-19 | Goldman Says Capital-Heavy Stocks Are Winning As AMZN, ORCL, MSFT, META Gear Up For $1.5 Trillion AI Spending Wave: Report - Stocktwits | `partial_support` | MSFT가 포함된 긍정적 시장 관점을 제시하지만 다종목·거시적 AI 지출 기사다. MSFT 개별 투자 판단인지, 어떤 rating인지 제목만으로 확정할 수 없다. |
| `news_237d33117ae75378` | 2026-09-18 | Microsoft: Don't Let The Smaller Dividend Hike Fool You - I See $600+ Long-Term (MSFT) - Seeking Alpha | `partial_support` | $600+ 장기 전망이라는 긍정적 판단을 직접 제시한다. rating downgrade 기사와 함께 보면 상반된 방향의 의견이 있다는 설명에는 근거가 되지만, 판단이 `근거 없는`지는 알 수 없어 Topic 전체를 직접 뒷받침하지는 않는다. |

#### Topic 2 종합 의견

- rating downgrade와 $600+ 장기 전망은 서로 다른 방향의 판단이 존재한다는
  점을 뒷받침한다. 따라서 집합 수준의 `상충`에는 제한적 근거가 있다.
- `근거 없는`이라는 규정까지 포함한 Topic 전체를 직접 뒷받침하는 headline은
  없다.
- 다만 기간, 평가 기준과 기사 유형이 다르므로 동일 기준의 직접 충돌인지
  제목만으로 확정할 수 없다.
- 어떤 headline도 자신의 판단이 `근거 없는` 것이라고 말하지 않는다.
  `근거 없는`은 LLM이 추가한 증거 품질 평가이며, 본문 검토 없이 사용할 수
  없는 표현이다.
- AI 보조 권고: `changes_required` 후보. 최소한 `근거 없는`을 제거하고
  `서로 다른 투자 관점`처럼 제한된 표현으로 바꿀지 사람이 결정해야 한다.

사용자 승인 판정: `changes_required`

### Topic 3 — AI와 마이크로소프트의 수익 성장 가능성

핵심 검수 질문은 각 기사가 MSFT의 `AI 관련 새 수익 흐름` 또는 수익 성장
가능성을 뒷받침하는지다.

| Article ID | 날짜 | Headline 원문 | 제안 분류 | 제목 기준 검수 의견 |
|---|---|---|---|---|
| `news_b346b1643fa94b51` | 2026-08-28 | MSFT Stock Alert: Moonshot Could Give Microsoft Another AI Revenue Stream - Yahoo Finance | `direct_support` | `Could Give Microsoft Another AI Revenue Stream`을 직접 언급한다. 가능성 표현을 유지하는 범위에서 Topic과 Explanation을 직접 뒷받침한다. |
| `news_9ca743ac3e536a40` | 2026-08-28 | Microsoft Just Gained 14% in a Month: Take Profits, or Buy More? - Yahoo Finance | `unrelated` | 주가 14% 상승과 투자 선택을 다루지만 AI나 수익 흐름은 없다. 14%를 매출 성장 수치로 전환해서는 안 된다. |
| `news_375d53aa64e4b947` | 2026-09-03 | Microsoft Stock (NASDAQ:MSFT) Jumps as Google Search URLs Come Back as Malicious - TipRanks | `unrelated` | 악성 Google Search URL과 주가 상승 사건으로, AI 수익 흐름을 언급하지 않는다. |
| `news_1a5f9cd850eb06db` | 2026-08-22 | Microsoft (Dinari Tokenized Stock) (MSFT) Price Prediction for 2026 to 2031 - Bybit | `unrelated` | tokenized stock 가격 예측이며 Microsoft의 AI 사업 수익을 언급하지 않는다. |
| `news_8b7ea197399e890d` | 2026-08-27 | Dan Ives Sees MSFT, AMZN, GOOGL Leading The Next Trade After Nvidia Earnings Keep AI 'Jenga Puzzle' Intact - Stocktwits | `partial_support` | MSFT와 AI 투자 테마의 연결은 보여주지만 회사의 새 revenue stream이나 수익 성장 자체는 언급하지 않는다. 다종목 관점이라는 한계도 있다. |

#### Topic 3 종합 의견

- 첫 기사만 MSFT의 새 AI revenue stream 가능성을 직접 뒷받침한다.
- 마지막 기사는 AI 투자 테마 수준의 부분 근거이며, 가운데 세 기사는 Topic
  핵심과 관계없다.
- 단일 `Could` headline을 여러 기사에 걸친 일반적 수익 성장 추세로 확대하면
  과도한 일반화가 된다. 확정된 매출 증가나 실현된 수익으로 표현해서도 안 된다.
- AI 보조 권고: `changes_required` 후보. Topic을 첫 기사의 가능성 주장으로
  제한하고 supporting ID를 재선정할지 사람이 결정해야 한다.

사용자 승인 판정: `changes_required`

## 4. 이전 Run과 비교해 확실하게 말할 수 있는 변화

이전 Run과 새 Run은 Snapshot과 LLM 출력이 다르므로 Topic 수, 문장 또는 의미
품질을 직접적인 전후 정확도 차이로 해석하지 않는다. 현재 확인 가능한 변화는
다음 세 가지뿐이다.

1. 새 필터가 새 Live 입력에서 low-information page 18건을 제외했다.
   - 옵션 계약 목록 16건
   - 옵션 계약 커뮤니티 1건
   - 순수 주식 차트 페이지 1건
2. 동일 Snapshot을 현재 코드로 재구성한 선택 60개에는 위 페이지가 남지 않았다.
3. 최종 report의 supporting article ID 15개는 모두 Snapshot과 재구성된 선택
   60개에 존재했다.

이는 page-type 입력 노이즈 제거와 evidence ID 유효성을 확인한 결과다. 일반
의미 품질 향상, semantic accuracy 증가 또는 Topic grounding 개선을 입증하지
않는다.

## 5. 여전히 남아 있는 의미 검증 한계

- Validator는 유효한 ID인지 확인하지만 각 ID가 Topic 핵심을 의미적으로
  뒷받침하는지는 일반적으로 검사하지 않는다.
- 제한된 phrase/event grounding 규칙은 `revenue` 같은 공통 단어가 서로 다른
  사건에서 사용되는 문제를 해결하지 못한다.
- 여러 supporting ID 중 하나만 핵심 claim을 뒷받침하고 나머지는 관련 없는
  경우도 최종 출력이 통과할 수 있다.
- 모델은 headline에 없는 증거 품질 평가인 `근거 없는`을 추가했다.
- 장기 전망, rating, 배당, 실제 매출, 매출 협상, 주가 변동을 같은 의미 축으로
  묶는지 여부는 현재 Validator가 판단하지 않는다.
- `confidence=80%`는 모델 self-report이며 의미 정확도의 보정된 확률이 아니다.
- headline만 사용했으므로 본문의 사실성, 출처 신뢰도와 세부 맥락은 평가하지
  않았다.

## 6. 사용자 판정 기록과 남은 세부 쟁점

| 검수 대상 | AI 보조 제안 | 사람이 결정할 핵심 질문 | 최종 판정 |
|---|---|---|---|
| Summary | `changes_required` 후보 | 전망·협상·의견을 `재무 결과`로 부르는 것이 허용되는가? `상충`의 기준이 충분히 명확한가? | `changes_required` |
| Topic 1 | `changes_required` 후보 | 첫 기사 하나의 high revenue visibility/capex 평가를 Topic으로 유지할 것인가? 나머지 4개 ID를 근거로 인정할 것인가? | `changes_required` |
| Topic 2의 `근거 없는` | `changes_required` 후보 | 본문 없이 판단의 근거 부족을 단정하는 표현을 금지할 것인가? | Topic 2 전체 `changes_required`; 세부 표현은 AI 보조 의견 유지 |
| Topic 2의 `상충` | 제한적 근거, 추가 검수 | rating downgrade와 $600+ 전망을 상충하는 투자 관점으로 묶을 수 있는가? 서로 다른 기간·기준이라는 한계를 어떻게 표시할 것인가? | Topic 2 전체 `changes_required`; 세부 표현은 AI 보조 의견 유지 |
| Topic 3 | `changes_required` 후보 | Moonshot 기사 하나의 가능성 주장을 일반 AI 수익 성장 Topic으로 유지할 것인가? 관련 없는 3개와 부분 관련 1개 ID를 제거할 것인가? | `changes_required` |
| Evidence 전체 | 검수 필요 | ID 유효성 통과와 의미 관련성을 별도로 평가하는 현재 원칙을 유지할 것인가? | 기사별 분류는 `draft_ai_assisted_review` 유지 |

사용자 승인은 네 상위 항목의 `changes_required` 판정에 한정된다. 기사별 분류를
개별 승인으로 간주하지 않으며, 확정 오류율, semantic accuracy, false
acceptance 비율 또는 필터의 품질 개선 수치로 집계하지 않는다.

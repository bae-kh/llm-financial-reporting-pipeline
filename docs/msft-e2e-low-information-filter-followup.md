# MSFT Live E2E 저정보성 페이지 필터 후속 개선

## 문서 상태와 범위

- 기준 Run: `run_20260924T085316_392408Z_MSFT_67842779`
- 기준 Git SHA: `684c519aecab4d034bd74037cf8dadd2b21ad550`
- 입력: 저장된 MSFT News Snapshot 269건
- 방식: 외부 호출 없는 Offline 필터·선별 재적용
- 제외 범위: Prompt, Validator, Dataset, 뉴스 수집, selection quota와 중요도 규칙은 변경하지 않음

이 기록은 [기존 뉴스 근거 품질 감사](msft-e2e-quality-audit.md)의 역사적
실행 결과를 수정하지 않는 후속 개선 기록이다. 원본 report, Snapshot,
RunMetadata는 변경하지 않았고 OpenAI, yfinance, RSS를 호출하거나 Workflow를
재실행하지 않았다.

## 1. 확인된 문제와 기준선

기존 Run의 선택 60건에는 기사형 콘텐츠가 아닌 옵션 계약 목록, 특정 옵션
계약 커뮤니티, 순수 주식 차트 페이지가 각각 1건씩 포함됐다. 이 중 옵션 계약
커뮤니티 페이지는 최종 `AI 관련 이슈` Topic의 supporting article ID로도
사용됐지만 headline에 AI 사건이 없었다.

변경 전 코드 경로를 Offline으로 재현한 기준선은 다음과 같다.

| 항목 | 기준선 |
|---|---:|
| Snapshot 저장 기사 | 269 |
| 기존 관련성·안전성 필터 통과 | 254 |
| 기존 선택 | 60 |
| 선택 전략 | `time_balanced_importance` |
| 날짜 균형 / 전 기간 중요도 | 42 / 18 |
| 선택 ID 순서 SHA-256 | `1703fe408ad7f5fbd709fa04e50938d66b36c6554748e89bac0db66303b33126` |

이 수치와 선택 ID 순서 해시가 기존 감사의 재구성 결과와 일치한 뒤에만 새
규칙을 비교했다.

## 2. 최소 필터 규칙

원본 Snapshot을 보존하고 LLM 입력 직전에 적용되는
`HeadlinePolicy.filter_for_ticker()`에 다음 고정형 페이지 제목만 분류했다.

1. 종목·만기·행사가·콜/풋·계약 심볼 뒤에 `Stock Options Chain`이 붙는
   옵션 계약 목록
2. 같은 계약 식별 구조 뒤에 `Stock Community & Discussion`이 붙는 특정
   옵션 계약 커뮤니티
3. 회사명·ticker 뒤의 `Stock Chart`, 정형화된 `Stock Price, Quote, News &
   History`, ticker 뒤의 `Real-Time Stock Quote` 페이지

단어 하나가 아니라 제목 전체의 정형 패턴이 일치할 때만 차단한다. 따라서
옵션 시장 사건 기사, 옵션 체인 해설, 차트·기술지표 분석 기사, 사건에 따른
주가 변동 기사, 일반적인 `community`나 `real-time` 표현은 유지한다. 제외된
기사는 `irrelevant` 또는 `unsafe`로 섞지 않고 `low_information_page_items`로
별도 기록하며, Production warning에도 별도 건수를 남긴다.

책임 위치는 `NewsFetcher`가 아니라 `HeadlinePolicy`다. 수집기는 감사 가능한
원본 metadata를 그대로 저장하고, 정책은 종목 관련성을 확인한 뒤 LLM 입력에
적합한 문서 유형만 제한한다. `NewsAnalyzer`의 중요도·날짜 균형 선택 알고리즘은
변경하지 않았다.

## 3. 동일 Snapshot 전후 비교

| 항목 | 변경 전 | 변경 후 | 변화 |
|---|---:|---:|---:|
| Snapshot | 269 | 269 | 0 |
| 필터 통과 | 254 | 237 | -17 |
| 명백한 비뉴스형 페이지 제외 | 0 | 17 | +17 |
| 최종 선택 | 60 | 60 | 0 |
| 날짜 균형 / 전 기간 중요도 | 42 / 18 | 42 / 18 | 동일 |
| 선택 고유 날짜 수 | 22 | 22 | 동일 |

차단된 17건은 옵션 계약 목록 15건, 특정 옵션 계약 커뮤니티 1건, 순수 주식
차트 1건이다. 모두 정형 패턴에 해당했고, 제목만 보아 기사형 해설로 판단되는
예상 밖 정상 차단은 이 Snapshot에서 확인되지 않았다.

### 기존 선택 60건에서 제외된 기사

| Article ID | 기존 선택 이유 | 제목 |
|---|---|---|
| `news_bee311fc322fcbff` | `time_balance` | MSFT 260911 385.00C (MSFT260911C385000) Stock Options Chain \| Quotes & News - moomoo.com |
| `news_c58a33f12ad8f846` | `global_importance` | MSFT 260821 330.00P (MSFT260821P330000) Stock Community & Discussion - moomoo.com |
| `news_6211a81a7242c616` | `global_importance` | MICROSOFT CORP (MSFT) Stock Chart - ChartMill |

### 빈자리를 채운 기사

| Article ID | 새 선택 이유 | 제목 |
|---|---|---|
| `news_c47a81f547c0779f` | `time_balance` | Microsoft EVP, CFO Amy Hood sells $20.7 million in MSFT stock - Investing.com India |
| `news_ed7db38ab02f48f2` | `global_importance` | What Did Microsoft Tell You Before Its Stock Ran? - Trefis |
| `news_4b11443b7f4cd33d` | `global_importance` | Why Microsoft (MSFT) is a Top Growth Stock for the Long-Term - Eastern Progress |

선택 알고리즘과 quota는 그대로지만 candidate pool이 바뀌어 3건이 교체됐다.
선택의 첫·마지막 시각과 고유 날짜 수는 같고, 날짜별 개수는 9월 15일
`1→2`, 16일 `5→4`, 18일 `10→11`, 19일 `2→1`로 변했다. 보충 기사 중
임원 주식 거래 기사가 포함된 사실은 이번 제한된 필터가 중복 임원 거래나
저가치 기사 selection cap 문제를 해결하지 않는다는 점도 보여준다.

## 4. 검증과 과잉 차단 위험

- 일반화 fixture: 차단 6개, 허용 7개
- 별도 분류 및 filter 결과 계약: 14개 신규 테스트
- 기존 HeadlinePolicy·NewsAnalyzer 통합 계약 포함 전체 pytest: `249 passed`
- Ruff: `All checks passed!`

전체 pytest 최초 실행에서는 Windows 기본 임시 폴더 권한 문제로 `211 passed, 38 setup errors`가 발생했으나, 쓰기 가능한 전용 `--basetemp`를 지정해 동일한 전체 테스트를 재실행한 결과 `249 passed`였다.

규칙은 제목 전체를 anchor해 단순히 `option`, `chart`, `price`, `community`가
나오는 정상 기사를 차단하지 않는다. 다만 다음 위험은 남는다.

- 실제 해설 기사가 포털의 고정형 페이지 제목과 정확히 같은 형식을 쓰면
  false rejection이 발생할 수 있다.
- 공급자 제목 형식이 달라지면 비뉴스형 페이지를 놓치는 false negative가
  생길 수 있다.
- URL, 문서 본문, page type metadata를 보지 않으므로 제목만으로 불확실한
  문서는 보수적으로 유지한다.

## 5. 해결 범위와 남은 문제

이번 변경으로 기존 선택 60건의 명백한 비뉴스형 페이지 3건은 새 입력에서
제외된다. 특히 기존 `AI 관련 이슈`에 잘못 인용된 옵션 계약 커뮤니티 ID는
새 LLM 입력과 허용 evidence ID 집합에 들어가지 않는다.

그러나 LLM을 다시 실행하지 않았으므로 새 선택으로 최종 출력 또는 Topic
근거 품질이 개선됐다고 결론 낼 수 없다. 기존 감사에서 확인한 다음 문제는
입력 page-type 필터만으로 해결되지 않는다.

- 수익 공유 협상과 Xbox 매출 감소를 회사 전체 `수익 전망` 근거로 확장
- 배당 이력 기사를 `분석가 평가 조정` 근거로 연결
- 목표주가 조정 기사를 `배당금 인상` 근거로 연결
- 가치평가·목표주가 변경을 실제 `주식 가격 변동` 근거로 연결

이 문제는 Topic-level evidence relevance에 해당한다. 현재 Python Validator의
제한된 사건 유형 규칙만으로 일반화해 차단하면 false rejection 위험이 크므로,
이번 최소 변경에서는 다루지 않았다.

## 6. 포트폴리오 마무리 관점

명백한 비뉴스형 입력을 원본 Snapshot과 분리해 제거하고, 고정 fixture와 실제
저장 Snapshot 전후 비교로 효과 범위를 입증한 작업은 포트폴리오에 필요한
최소 품질 개선에 해당한다. 반면 near-duplicate 제거, 임원 거래 cap,
primary-subject heuristic, 일반 Topic-level semantic validator는 선택 과제다.
현재 결과를 공개할 때는 `입력 노이즈 17건 제거`와 `기존 선택 중 3건 교체`까지만
사실로 말하고, LLM 의미 품질 향상은 별도 실행·검수 전에는 주장하지 않는다.

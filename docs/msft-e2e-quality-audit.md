# MSFT Live E2E 뉴스 근거 품질 감사

## 문서 상태와 범위

- 감사 대상 Run: `run_20260924T085316_392408Z_MSFT_67842779`
- Git SHA: `684c519aecab4d034bd74037cf8dadd2b21ad550`
- 코드 조건: `news-analyzer-prompt-v3` + `news-analyzer-validator-v2`
- 요청 모델: `gpt-4o-mini`
- 감사 상태: `draft_ai_assisted_review`
- 감사 근거: 저장된 Markdown report, News Snapshot, RunMetadata, 실행 당시 콘솔 기록, 해당 Git SHA의 코드
- 제한: 기사 본문을 조회하지 않고 headline metadata만 검토했다. 아래 분류는 AI 보조 검수 제안이며 사람 승인 전에는 확정 판정, semantic accuracy 또는 Validator false acceptance 비율로 사용하지 않는다.

이 문서는 기존 artifact를 수정하지 않은 Offline 감사 결과다. OpenAI, yfinance, RSS를 다시 호출하지 않았으며 이전 초안이나 token usage를 복원하지 않았다.

## 1. Run과 artifact 연결

세 artifact의 Run ID, ticker와 기간을 교차 확인했고 JSON artifact는 현재 Pydantic 계약으로 다시 읽을 수 있었다.

| 구분 | 로컬 상대 경로 | 확인 결과 |
|---|---|---|
| Markdown report | `reports/generated/report_MSFT_2026-08-20_2026-09-18_20260924T085316_392408+0000.md` | UTF-8, 비어 있지 않음, 동일 Run ID 포함 |
| News Snapshot | `reports/generated/news_snapshots/news_MSFT_2026-08-20_2026-09-18_20260924T085319_193567Z.json` | `NewsFetchResult` 검증 통과, MSFT, 동일 기간, 269건 |
| RunMetadata | `reports/generated/run_metadata/run_20260924T085316_392408Z_MSFT_67842779.json` | `RunMetadata` 검증 통과, report/snapshot 경로 연결 |

원본 파일은 `reports/generated/` 아래의 Git 제외 artifact이며 이 감사에서 수정하지 않았다.

## 2. 최종 리포트 검수 자료

### 시장 지표와 상태

| 항목 | 저장 결과 |
|---|---:|
| 요청 기간 | 2026-08-20 ~ 2026-09-18, 30 calendar days |
| 실제 가격 범위 | 2026-08-20 ~ 2026-09-18, 21 trading days |
| MSFT 기간 수익률 | 2.62% |
| 연환산 변동성 | 22.02% |
| 최대 낙폭 | -4.52% |
| RSI(14) | 53.26 |
| MACD difference | -3.1865 |
| SPY 상태 / 수익률 | `available` / 0.13% |
| MSFT-SPY 차이 | 2.50% |
| 전체 상태 | `completed_with_warnings` |
| LLM 상태 / fallback | `available` / `false` |
| 감성 / 점수 / confidence | `neutral` / 0.00 / 5% |

RunMetadata의 치명적 `error_code`와 `error_message`는 모두 비어 있다. `completed_with_warnings`의 원인은 다음 6개 경고다.

1. 분석 기간 밖의 RSS 항목 6건 제외
2. 중복 RSS 항목 72건 제외
3. Google News RSS의 전체 언론사 수집 범위는 알 수 없음
4. 종목 식별자 또는 회사명과 직접 연결되지 않은 뉴스 15건 제외
5. 필터 통과 254건 중 날짜 균형 42건과 전 기간 중요도 18건, 총 60건을 LLM 분석에 사용
6. 결정론적 검증 실패로 LLM 초안을 2회 재작성

### 최종 Summary와 Topic/Explanation 원문

아래 문장은 report에 저장된 최종 LLM 결과를 그대로 옮긴 것이다. 감사자의 권장 문장으로 대체하지 않았다.

> 마이크로소프트에 대한 여러 뉴스가 발표되었으며, 전반적인 감정은 중립적이다. 일부 뉴스는 부정적인 분석 평가를 포함하고 있으나, 전체적으로 혼합된 요인이 있음을 나타낸다.

1. **수익 전망** — 마이크로소프트의 매출 전망 관련 기사들이 점검되고 있습니다.
2. **분석가 평가 조정** — 분석가의 평가가 부정적으로 조정된 기사들이 발견되었습니다.
3. **배당금 인상** — 마이크로소프트의 배당금 증액 최근 결정에 관한 논의가 이루어지고 있습니다.
4. **AI 관련 이슈** — AI와 관련된 이슈가 마이크로소프트에 영향을 미치고 있음을 보여주는 기사들이 있습니다.
5. **주식 가격 변동** — 마이크로소프트 주식 가격 변동에 대한 다양한 분석이 진행되고 있습니다.

### 저장·선택·분석 수의 구분

- Snapshot 저장 기사: 269건
- ticker/alias 관련성·안전 필터 통과: 254건
- LLM 입력으로 선택된 기사: 60건
- LLM이 분석한 기사: 60건
- 최종 5개 Topic이 인용한 ID: **14개**

사용자 요청에는 인용 기사가 15개로 기술됐지만 실제 report는 `3 + 3 + 3 + 2 + 3 = 14`개다. 14개는 모두 중복 없는 유효 ID이고, 아래에서 재구성한 선택 60개 안에 존재한다.

Production은 선택 60개의 전체 ID를 별도 JSON으로 저장하지 않는다. 따라서 아래 목록은 동일 Snapshot에 동일 Git SHA의 [`HeadlinePolicy.filter_for_ticker`](../analysis/headline_policy.py#L256-L277)와 [`NewsAnalyzer.select_articles_with_metadata`](../analysis/news_analyzer.py#L925-L1022)를 Offline 재적용해 재구성했다. `269 → 254 → 60`, 선택 전략, report의 60건 표기와 14개 인용 ID 포함 여부가 모두 일치했다.

### 선택 60개 기사

날짜는 분석 window의 `America/New_York` 기준이다.

| # | 날짜 | Article ID | Headline |
|---:|---|---|---|
| 1 | 2026-08-22 | `news_1df2ca3b30d2ff63` | Microsoft Stock: Higher Revenue Visibility Met Measured Capex (NASDAQ:MSFT) - Seeking Alpha |
| 2 | 2026-08-22 | `news_635f05b6da2d8ee0` | I've Held Microsoft for 10 Years. Here's Why I'm Not Selling a Single Share. - The Motley Fool |
| 3 | 2026-08-22 | `news_deffe1ffcbe1e0f9` | Microsoft Has Something Nvidia Doesn’t and Here’s Why it Matters - 247wallst.com |
| 4 | 2026-08-22 | `news_f4301b787106bca0` | Jim Cramer Was Left Impressed By Microsoft Corporation (NASDAQ:MSFT)’s Conference Call - Yahoo Finance |
| 5 | 2026-08-22 | `news_7e8a1566b9bc668f` | Microsoft (Dinari Tokenized Stock) (MSFT) Price Prediction for 2026 to 2031 - bybit.com |
| 6 | 2026-08-25 | `news_07ebca4afbf85c39` | MSFT, ORCL and INTC Forecast: Tech Stocks Eye a Rebound - Yahoo Finance |
| 7 | 2026-08-25 | `news_0d9b756b2bd13945` | Microsoft Just Ripped 28% in a Month. What Would It Take to Get MSFT Stock Up to $600? - 247wallst.com |
| 8 | 2026-08-25 | `news_632a678ef5f09fa4` | Microsoft shares trade actively in U.S. premarket as MW4 Beta Dates link to Call of Duty recovery with 51% approval at stake - TechStock² |
| 9 | 2026-08-25 | `news_e760e6a407c12250` | U.S. Treasury Quantum Push Puts IBM, MSFT and GOOGL Stocks in Focus - TipRanks |
| 10 | 2026-08-26 | `news_a5eb54e29c2f9878` | MSFT, AMZN, GOOGL Reportedly In Revenue-Sharing Talks With China's Moonshot AI Over Kimi K3 Model - Yahoo Finance |
| 11 | 2026-08-27 | `news_8414d1023301f38f` | Microsoft launches $899 Xbox Series X25 in bid to gauge pricing power as console revenue drops 29% - TechStock² |
| 12 | 2026-08-27 | `news_8b7ea197399e890d` | Dan Ives Sees MSFT, AMZN, GOOGL Leading The Next Trade After Nvidia Earnings Keep AI 'Jenga Puzzle' Intact - Stocktwits |
| 13 | 2026-08-28 | `news_06462c67cb86c022` | Rising Cloud Revenue Strengthens Alphabet Against MSFT & AMZN - Yahoo Finance |
| 14 | 2026-08-28 | `news_307173ca07d7a6aa` | Microsoft: The Rerating Is Probably Over For Now (Rating Downgrade) (NASDAQ:MSFT) - Seeking Alpha |
| 15 | 2026-08-28 | `news_6651ccb58dac20c2` | Why Is Microsoft (MSFT) Up 12% Since Last Earnings Report? - Yahoo Finance |
| 16 | 2026-08-28 | `news_9ca743ac3e536a40` | Microsoft Just Gained 14% in a Month: Take Profits, or Buy More? - Yahoo Finance |
| 17 | 2026-08-28 | `news_a8c63cc4dc4b36d4` | Microsoft stock jumps 14% in a month, sparking debate on profit-taking or buying more. - Pluang |
| 18 | 2026-08-28 | `news_a8e22e5aabae2df2` | Microsoft Just Gained 14% in a Month: Take Profits, or Buy More? - 247wallst.com |
| 19 | 2026-08-28 | `news_b346b1643fa94b51` | MSFT Stock Alert: Moonshot Could Give Microsoft Another AI Revenue Stream - Yahoo Finance |
| 20 | 2026-08-29 | `news_c96ee6e6c5d75d1e` | Chevron's Microsoft Data Center Deal Was a Bigger Story Than Its Earnings. Here's Why. - The Motley Fool |
| 21 | 2026-08-31 | `news_31abbc8967d151d7` | Microsoft Has Raised Its Dividend Every Year for More Than a Decade. History Provides Clues of How Big This Year's Raise Might Be. - The Motley Fool |
| 22 | 2026-08-31 | `news_8ccbc71ede73812f` | Microsoft's September Dividend Raise Could Land Near $1 a Share, Extending 16-Year Streak - finance.biggo.com |
| 23 | 2026-08-31 | `news_c0488fa433916885` | Satya Nadella (NASDAQ: MSFT) just vested a 178K-share award; see how many shares went to taxes. - Stock Titan |
| 24 | 2026-09-02 | `news_84b6ecbf7c2454e5` | Bank of America resets Microsoft stock price target for 2026 - thestreet.com |
| 25 | 2026-09-03 | `news_16740d9c40db0485` | Microsoft putting limits on Xbox cloud gaming hours (MSFT:NASDAQ) - Seeking Alpha |
| 26 | 2026-09-03 | `news_375d53aa64e4b947` | Microsoft Stock (NASDAQ:MSFT) Jumps as Google Search URLs Come Back as Malicious - TipRanks |
| 27 | 2026-09-03 | `news_43637ee42d52304f` | Microsoft Corporation (MSFT) Generates Revenues and Profits Beyond AI Theme - Yahoo Finance |
| 28 | 2026-09-04 | `news_544e3474c8a4c2cf` | After A Microsoft Stock Price Spike, An Options Strategy Aims For A Robust Profit In Weeks - Investor's Business Daily |
| 29 | 2026-09-04 | `news_b466f5466c3b401a` | Microsoft Stock Gets Jaw-Dropping Price Target Hike From Stifel - TradingView |
| 30 | 2026-09-05 | `news_a113d3f6e9caa54a` | $MSFT stock fell 3% this week. Here's what we see in our data. - Quiver Quantitative |
| 31 | 2026-09-05 | `news_52beeeb076ea5302` | Stifel Upgrades Microsoft (MSFT) Price Target to $530 While Maintaining Hold Rating - MoneyCheck |
| 32 | 2026-09-07 | `news_4cc583d68b068598` | Microsoft stock tests $489.87 support as Outlook, 365 outages trigger pullback - tradersunion.com |
| 33 | 2026-09-08 | `news_3bec1a17fca02b95` | Microsoft Stock Forecast 2040, 2050: How High Can MSFT Go? - CoinCodex |
| 34 | 2026-09-08 | `news_5048656dc90595ef` | Why Stifel Just Revamped Its Price Target for Microsoft Stock - Barchart.com |
| 35 | 2026-09-08 | `news_ee146a92d977b543` | Microsoft Stock (MSFT) Opinions on Recent Earnings and Business Reorganization - Quiver Quantitative |
| 36 | 2026-09-09 | `news_31c83a9f3ffdfdef` | Microsoft: CapEx Rotation Does Not Support An Optimistic View (Downgrade) (NASDAQ:MSFT) - Seeking Alpha |
| 37 | 2026-09-11 | `news_91eb682fd5680a60` | Microsoft’s Dividend Climbed to $0.91 a Share as Its Payout Ratio Dropped 3%. Here’s What It Means for Investors. - TIKR.com |
| 38 | 2026-09-11 | `news_bd5c629ec03d6bde` | Dividend stock grant lifts Microsoft (NASDAQ: MSFT) director's stake - Stock Titan |
| 39 | 2026-09-11 | `news_82026d755cfd6f04` | Microsoft Faces Class Action Over AI-Linked Stock Losses - Yellow.com |
| 40 | 2026-09-11 | `news_c2ab949ab2074542` | Investigation announced for Long-Term Investors in shares of Microsoft Corporation (NSADAQ: MSFT) - openPR.com |
| 41 | 2026-09-14 | `news_60844253997424ef` | Microsoft Stock (MSFT) Opinions on Bank of America Price Target Upgrade - Quiver Quantitative |
| 42 | 2026-09-15 | `news_462cd2bcaeef0b7c` | Analysts revise Microsoft stock price target - Finbold |
| 43 | 2026-09-15 | `news_3bcbcaaeb958c7ee` | Microsoft Stock Moves as Tech Giant Unveils Strict AI Code of Conduct - TIKR.com |
| 44 | 2026-09-15 | `news_bee311fc322fcbff` | MSFT 260911 385.00C (MSFT260911C385000) Stock Options Chain \| Quotes & News - moomoo.com |
| 45 | 2026-09-16 | `news_849321c4d40cd29b` | Microsoft Stock Forecast \| Azure Revenue, Reporting Changes - Capital.com |
| 46 | 2026-09-16 | `news_555ad3b9d57b7668` | Microsoft (MSFT) Raises Quarterly Dividend by 8% - TipRanks |
| 47 | 2026-09-16 | `news_4a81404b08285819` | Microsoft (MSFT) Could Be 18% Overvalued On Its Dividend Increase - Yahoo Finance |
| 48 | 2026-09-17 | `news_b592e7ccff89e2fb` | MRVL Stock Climbs After AI Optical Capacity Deal, New Microsoft Security Platform Launch - TradingView |
| 49 | 2026-09-18 | `news_5d4fc56aca5655fa` | Microsoft Stock Hit My Target. Now I'm Stepping Back (Rating Downgrade) - Seeking Alpha |
| 50 | 2026-09-18 | `news_237d33117ae75378` | Microsoft: Don't Let The Smaller Dividend Hike Fool You - I See $600+ Long-Term (MSFT) - Seeking Alpha |
| 51 | 2026-09-18 | `news_c4638f7c42857d95` | MSFT Looks 15.0% Undervalued on GF Value™ After Dividend Boost - GuruFocus |
| 52 | 2026-09-18 | `news_77910e1a9c612bd8` | Alphabet Rises 3%, Meta and Microsoft Slip: Is This a Momentum Run Rather Than a Tech Rally? - AOL.ca |
| 53 | 2026-09-18 | `news_a6782bad1a0b499b` | Microsoft: Distribution Advantage Worth More Than Another Model Breakthrough (NASDAQ:MSFT) - Seeking Alpha |
| 54 | 2026-09-18 | `news_ecb36cc927970710` | 3 Reasons to Hold Microsoft Stock After a 31.2% Surge in 3 Months - TradingView |
| 55 | 2026-09-18 | `news_a603867b4bfd08d6` | Can NOK's Network Automation Progress With MSFT Boost Profits? - TradingView |
| 56 | 2026-09-18 | `news_2f780dd344baa397` | “Largest Theft of Labor in Human History”: Microsoft Stock (NASDAQ:MSFT) Dips as Ethical Implications of AI Training Creep In - TipRanks |
| 57 | 2026-09-18 | `news_c58a33f12ad8f846` | MSFT 260821 330.00P (MSFT260821P330000) Stock Community & Discussion - moomoo.com |
| 58 | 2026-09-18 | `news_1fa95324b2136fd8` | Why Are Tech Stocks GOOGL, MSFT, AMZN Falling in Premarket Today, Sept. 15? - TipRanks |
| 59 | 2026-09-18 | `news_6211a81a7242c616` | MICROSOFT CORP (MSFT) Stock Chart - ChartMill |
| 60 | 2026-09-18 | `news_5c269070e8da32e1` | Goldman Says Capital-Heavy Stocks Are Winning As AMZN, ORCL, MSFT, META Gear Up For $1.5 Trillion AI Spending Wave: Report - Stocktwits |

## 3. Topic별 근거 연결 감사

판정 의미:

- `direct_support`: headline이 Topic/Explanation의 핵심을 직접 뒷받침한다.
- `partial_support`: 인접한 사실은 있으나 Topic 설명 전체를 뒷받침하지 않는다.
- `unrelated`: 해당 Topic의 근거로 부적절하다.
- `insufficient_headline_information`: 제목만으로 판정하기 어렵다.

모든 ID가 선택 60개 안에 있다는 것은 확인됐지만, 이는 의미 관련성 판정과 별개다.

| Topic | Article ID / headline | 제안 판정 | 제목만으로 본 근거 |
|---|---|---|---|
| 수익 전망 | `news_1df2ca3b30d2ff63` — Microsoft Stock: Higher Revenue Visibility Met Measured Capex | `direct_support` | `Higher Revenue Visibility`가 매출 전망/가시성을 직접 언급한다. |
| 수익 전망 | `news_a5eb54e29c2f9878` — MSFT, AMZN, GOOGL Reportedly In Revenue-Sharing Talks... | `unrelated` | 수익 공유 협상은 MSFT 자체의 매출 전망이 아니다. 협상 상태를 회사 매출 전망으로 확대할 수 없다. |
| 수익 전망 | `news_8414d1023301f38f` — Microsoft launches $899 Xbox... console revenue drops 29% | `partial_support` | console revenue 감소는 매출 관련 사실이지만 회사 매출 전망을 직접 제시하지 않는다. |
| 분석가 평가 조정 | `news_307173ca07d7a6aa` — ... (Rating Downgrade) | `direct_support` | 제목이 rating downgrade를 명시한다. |
| 분석가 평가 조정 | `news_31abbc8967d151d7` — Microsoft Has Raised Its Dividend Every Year... | `unrelated` | 배당 이력과 향후 인상 규모의 단서는 분석가 평가 하향의 근거가 아니다. |
| 분석가 평가 조정 | `news_5d4fc56aca5655fa` — ... Stepping Back (Rating Downgrade) | `direct_support` | 제목이 rating downgrade를 명시한다. |
| 배당금 인상 | `news_91eb682fd5680a60` — Microsoft’s Dividend Climbed to $0.91... | `direct_support` | 배당금 상승과 금액을 직접 명시한다. |
| 배당금 인상 | `news_555ad3b9d57b7668` — Microsoft (MSFT) Raises Quarterly Dividend by 8% | `direct_support` | 분기 배당 8% 인상을 직접 명시한다. |
| 배당금 인상 | `news_462cd2bcaeef0b7c` — Analysts revise Microsoft stock price target | `unrelated` | 목표주가 조정은 배당 인상 근거가 아니다. |
| AI 관련 이슈 | `news_2f780dd344baa397` — ... Ethical Implications of AI Training... | `direct_support` | Microsoft, AI training 윤리 이슈와 주가 하락을 직접 연결한다. |
| AI 관련 이슈 | `news_c58a33f12ad8f846` — MSFT ... Stock Community & Discussion | `unrelated` | 옵션 계약 커뮤니티 페이지 제목에는 AI 사건이 없다. |
| 주식 가격 변동 | `news_375d53aa64e4b947` — Microsoft Stock ... Jumps... | `direct_support` | 실제 주가 상승을 제목이 직접 진술한다. |
| 주식 가격 변동 | `news_4a81404b08285819` — ... Could Be 18% Overvalued... | `partial_support` | 가치평가 분석은 주가와 인접하지만 실제 가격 변동을 직접 뒷받침하지 않는다. |
| 주식 가격 변동 | `news_b466f5466c3b401a` — ... Price Target Hike From Stifel | `partial_support` | 목표주가 상향은 평가 변화이며 실제 주가 변동과 동일하지 않다. |

이 분류 제안은 14개 근거의 품질을 살펴보기 위한 검수 자료이며 비율이나 공식 성능 수치로 변환하지 않는다.

## 4. 뉴스 입력과 선별 품질

### 이번 Run에서 확인된 현상

1. **저정보성 페이지가 선택됐다.**
   - 옵션 체인: `news_bee311fc322fcbff`
   - 옵션 계약 커뮤니티: `news_c58a33f12ad8f846`
   - 종목 차트 페이지: `news_6211a81a7242c616`
   - 이 중 커뮤니티 페이지는 실제 AI Topic의 근거로도 사용됐다.
2. **유사한 임원 보상·지분 기사가 반복 선택됐다.**
   - Satya Nadella의 178K-share award: `news_c0488fa433916885`
   - director stock grant: `news_bd5c629ec03d6bde`
3. **내용이 거의 같은 주가 기사도 복수 선택됐다.**
   - `Microsoft Just Gained 14% in a Month...` 계열이 Yahoo Finance, Pluang, 247wallst.com에서 3건 선택됐다.
4. **MSFT를 포함하지만 다른 기업이 주요 대상인 기사가 선택됐다.**
   - Alphabet cloud revenue: `news_06462c67cb86c022`
   - Chevron data center deal: `news_c96ee6e6c5d75d1e`
   - MRVL stock/AI optical deal: `news_b592e7ccff89e2fb`
   - NOK network automation: `news_a603867b4bfd08d6`
   - 이 밖에도 다종목 roundup이 여러 건 포함됐다.
5. **날짜 균형과 중요도 규칙이 저정보성 기사를 제거하지는 않는다.**
   - 날짜 균형 몫 42건은 bucket별 우선순위를 채우므로 score 0 기사도 선택한다.
   - 전 기간 중요도 몫 18건도 충분한 수를 채우는 과정에서 최근 score 0 기사를 포함했다.
   - `forecast`, `revenue`, `profit`, `launch` 같은 단어는 문서 유형이나 주요 대상을 확인하지 않고 중요도 신호를 높인다.

### 컴포넌트별 실제 책임

- [`NewsFetcher.fetch_for_window`](../data_pipeline/news_fetcher.py#L162-L264)는 Google News RSS metadata를 기간별로 요청하고 XML을 파싱한다. 날짜 범위, 필수 metadata, URL/title 중복과 snapshot 상한을 처리하지만 페이지 유형, 발행처 품질, 기사의 주요 대상은 판단하지 않는다.
- [`HeadlinePolicy.filter_for_ticker`](../analysis/headline_policy.py#L256-L284)는 instruction 패턴을 먼저 제외하고 제목에 `MSFT` 또는 `Microsoft`가 포함되는지만 확인한다. 다른 기업이 문장의 주체인지, options/quote/community 페이지인지 판정하지 않는다.
- [`NewsAnalyzer.select_articles_with_metadata`](../analysis/news_analyzer.py#L925-L1022)는 60건을 날짜 균형과 키워드 중요도로 선택한다. 현재 중요도 규칙은 기업 사건 단어를 찾지만 source 품질, 정보 밀도, primary subject와 Topic 다양성을 평가하지 않는다.

따라서 위 저정보성 선택은 실제 artifact와 결정론적 선택 metadata로 확인된 현상이다. 반면 기사 본문 품질, headline의 진위, 발행처의 신뢰도는 이번 Offline 자료만으로 판정할 수 없다.

## 5. Validator v2의 실제 검증 공백

### 현재 수행하는 검사

1. **Pydantic Structured Output**
   - sentiment enum, score `[-1, 1]`, confidence `[0, 100]`, 문자열 길이, Topic 1~5개, Topic별 ID 1~5개와 ID 형식·중복을 검사한다. [`NewsLLMOutput`](../analysis/news_analyzer.py#L81-L101)
2. **Evidence ID 유효성**
   - 모든 supporting ID가 선택 60개 집합에 있는지 검사한다. [`_validate_evidence_ids`](../analysis/news_analyzer.py#L1184-L1200)
3. **제한된 출력 정책과 사건 grounding**
   - 추천·예측 금지 표현, conflicting direction의 neutral 계약, `earnings_report`, `revenue`, `product_recall`, `regulatory_investigation`, 차량 인도 거점/대수/리콜의 제한된 phrase 규칙을 검사한다. [`_validate_output_policy`](../analysis/news_analyzer.py#L1202-L1252), [`ungrounded_event_claims`](../analysis/headline_policy.py#L337-L377)

### 수행하지 않는 검사

- Topic/Explanation 전체와 **각 supporting article** 사이의 일반 의미 관련성
- 한 Topic에 여러 ID가 있을 때 ID별로 핵심 주장을 모두 뒷받침하는지
- `배당` Topic에 목표주가 기사가 섞이거나 `AI` Topic에 옵션 커뮤니티가 섞이는 문제
- primary subject가 MSFT인지, 단순 언급인지
- options chain, quote, chart, community와 같은 저정보성 페이지 유형
- 기사 본문 기준 사실성 또는 source credibility

사건 grounding도 한 Topic의 인용 제목 묶음 중 하나에서 source term을 찾으면 해당 제한 개념은 통과할 수 있다. 이는 모든 인용 ID의 의미 관련성을 증명하지 않는다. 이번 Run은 **Evidence ID validity는 통과했지만 Topic-level Evidence Relevance에는 명확한 검수 후보가 남은 사례**다.

## 6. Confidence 5%와 재작성 기록

### Confidence

- `confidence=5`는 LLM이 Structured Output으로 생성한 값이며 Python이 계산하거나 보정한 값이 아니다.
- Pydantic은 정수이고 0~100 범위인지만 검사한다.
- Prompt는 confidence를 투자 확실성이 아니라 evidence clarity로 설명한다.
- 낮은 confidence에 대한 경고, 최소 임계값, 재작성 또는 fallback 정책은 없다.
- 따라서 report의 `5%`를 보정된 실제 정확도 확률이나 오답 확률로 해석할 근거가 없다.

### 재작성

report와 RunMetadata에는 `2회 재작성` warning이 남아 있다. 실행 당시 콘솔 기록으로 다음 정책 거부를 확인했다.

1. Attempt 1: `news_30422c5a8b4bffce`, `news_505c70d610b9afe2`라는 허용되지 않은 ID를 인용해 evidence ID 검사에서 거부됐다. 두 ID는 선택 60개뿐 아니라 Snapshot 269개에도 존재하지 않는다.
2. Attempt 2: 금지 패턴 `투자자`가 검출돼 출력 정책 검사에서 거부됐다.
3. 최종 Attempt: 검증을 통과해 `available=True`, `fallback_used=False`로 저장됐다.

Production 실행에는 Attempt Telemetry collector가 연결되지 않았으므로 이전 초안 전문, Attempt별 structured output, token usage와 실제 응답 model ID는 저장되지 않았다. 특히 두 번째 초안에서 `투자자`가 사용된 정확한 문맥은 남아 있지 않다.

> 정책 규칙에 따른 거부는 확인했으나, 정상 표현의 False Rejection 여부는 판정 불가.

## 7. 최소 개선 후보

### A. 간단한 입력 필터·선별 정책으로 개선 가능

1. **페이지 유형 필터**: 종목+만기+행사가 형식의 options chain, `Stock Community & Discussion`, 순수 `Stock Chart`/quote 페이지 같은 boilerplate를 일반 패턴으로 제외한다.
   - 기대 효과: LLM 입력 전에 명백한 저정보성 metadata 제거.
   - 위험: 옵션 전략을 실제로 다룬 뉴스까지 제거하지 않도록 페이지형 boilerplate와 기사형 문장을 분리해야 한다.
2. **near-duplicate 정규화/cluster**: headline 끝의 publisher suffix와 사소한 문구 차이를 정규화해 같은 사건의 복수 배포본에서는 대표 1건만 선택한다.
   - 위험: 서로 다른 관점의 독립 기사까지 합치지 않도록 exact/near-exact 단계부터 적용한다.
3. **선택 다양성 제한**: 동일 사건 신호·유사 headline cluster·임원 지분/보상 기사에 작은 per-cluster cap을 두고 남는 자리를 다른 사건에 배정한다.
   - 위험: 뉴스가 적은 기간에는 60건을 채우지 못할 수 있으므로 목표 수를 강제하지 않는 계약이 필요하다.

### B. Python 규칙으로 제한적으로 가능하지만 False Rejection 위험이 큼

1. **Topic concept와 cited headline의 ID별 일치 검사**: 배당, analyst rating, AI, 실제 가격 변동 같은 제한된 taxonomy를 추가해 각 ID가 최소 하나의 Topic concept를 공유하는지 검사한다.
   - 위험: 동의어·간접 표현·복합 사건을 놓치고 정상 citation을 거부할 수 있다.
2. **primary subject heuristic**: 제목 맨 앞의 기업, possessive 구조, 다종목 나열을 사용해 MSFT가 주요 대상인지 추정한다.
   - 위험: 거래 상대방·공급망·경쟁사 비교처럼 MSFT에 실질적으로 중요한 기사를 제거할 수 있다.
3. **낮은 confidence 후속 정책**: 경고만 추가하는 것은 가능하지만 현재 confidence가 보정되지 않았으므로 hard fallback 임계값은 권장하지 않는다.

### C. 별도 의미 평가나 사람 검수가 필요

- Topic/Explanation이 각 headline에서 entail되는지에 대한 일반 의미 판정
- 여러 인용 기사가 하나의 Topic 설명을 함께 뒷받침하는지
- 가치평가·목표주가와 실제 가격 변동의 문맥상 구분
- headline 의미 왜곡, 인과관계 추가, unsupported claim rate
- confidence calibration과 실제 정확도 관계
- 본문 확인이 필요한 사실성·source credibility

## 8. 포트폴리오 마무리 권고

1. 우선 구현할 최소 범위는 **저정보성 페이지 필터**, **near-duplicate 정리**, **선택 다양성 회귀 테스트**다. 이번 Snapshot을 고정 Offline fixture로 사용해 외부 호출 없이 전후 선택 목록을 비교할 수 있다.
2. Topic-level 의미 검증을 곧바로 대규모 Python Validator로 확장하지 않는다. 먼저 이 문서의 14개 citation을 사람이 승인·수정하고, 다른 종목 headline으로 작은 회귀셋을 만든 뒤 규칙의 False Rejection 위험을 확인한다.
3. 낮은 confidence를 자동 실패로 바꾸지 않는다. 현재 값은 모델 self-report이며 calibration 근거가 없다.
4. 취업 포트폴리오에서는 “실제 E2E가 동작했다”와 “최종 근거 품질이 충분하다”를 분리해 설명한다. 이번 Run은 전자를 입증하지만, 후자는 ID 검증만으로 보장되지 않는다는 한계를 실제 artifact로 발견한 사례다.
5. 이 감사 자체를 Evaluation-driven development 증거로 사용하되, 14개 제안 판정을 공식 semantic accuracy나 일반화 성능으로 표현하지 않는다.

## 관련 기록

- [Evaluation v2 실험 기록](experiment-log.md)
- [Validator v1 감사](validator-audit.md)
- [Validator v2 최소 설계](validator-v2-design.md)
- [실패 처리와 재작성 계약](failure-handling.md)

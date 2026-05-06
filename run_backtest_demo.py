"""
V1(기존) vs V2(튜닝) 전략 비교 백테스트 스크립트.
동일한 뉴스 감성 캐시를 사용하되, 전략 파라미터만 다르게 적용하여 비교합니다.
"""
import asyncio
import os
import pandas as pd
from config.settings import Settings
from backtest.news_backtest import NewsBacktestEngine
from backtest.metrics import RiskMetrics


class TunedNewsBacktestEngine(NewsBacktestEngine):
    """
    V2 전략 — 파라미터 튜닝 버전.

    [V1 → V2 변경 사항]
    - 투자 비율: 10% → 30% (현금 비중 축소)
    - 악재 매도 임계값: score < 0 → score < -0.3 (약한 악재 무시)
    - 최소 보유 기간: 0일 → 5거래일 (Whipsaw 방어)
    - 매수 확신도: 80 → 60 (더 많은 기회 포착)
    """

    def __init__(self, settings: Settings):
        super().__init__(settings)
        # V2 튜닝 파라미터
        self.v2_allocation = 0.30          # 30%
        self.v2_sell_threshold = -0.3      # 강한 악재만 매도
        self.v2_min_hold_days = 5          # 최소 5거래일 보유
        self.v2_min_confidence = 60        # 확신도 60%로 완화

    def _iterate(self, df, sentiment_by_date, initial_capital):
        """V2 전략의 이터레이티브 백테스트."""
        cash = initial_capital
        holdings = 0
        avg_price = 0.0
        buy_day = -999  # 매수한 날의 인덱스
        equity_curve = []
        trades = []

        for i in range(len(df)):
            current_row = df.iloc[i]
            price = float(current_row['Close'])
            rsi = float(current_row['RSI_14'])
            macd_diff = float(current_row['MACD_diff'])

            date_str = str(df.index[i])[:10]
            score = sentiment_by_date.get(date_str, 0.0)
            confidence = int(min(abs(score) * 120, 100))

            roi = 0.0
            if holdings > 0 and avg_price > 0:
                roi = (price - avg_price) / avg_price * 100

            days_held = i - buy_day

            # === 매도 검사 (최소 보유 기간 적용) ===
            if holdings > 0:
                sell_reason = None

                # 익절/손절은 보유 기간 무관하게 항상 발동
                if roi >= self.settings.TAKE_PROFIT_PCT:
                    sell_reason = f"익절 (ROI {roi:.1f}%)"
                elif roi <= self.settings.STOP_LOSS_PCT:
                    sell_reason = f"손절 (ROI {roi:.1f}%)"
                # 악재 매도는 최소 보유 기간 이후 + 강한 악재만
                elif days_held >= self.v2_min_hold_days and score < self.v2_sell_threshold:
                    sell_reason = f"강한 악재 (score {score:.2f}, {days_held}일 보유)"

                if sell_reason:
                    sell_value = holdings * price * (1 - self.settings.TRANSACTION_FEE)
                    pnl = sell_value - (holdings * avg_price)
                    cash += sell_value
                    trades.append({
                        'day': i, 'date': date_str, 'action': 'SELL',
                        'price': price, 'quantity': holdings,
                        'pnl': pnl, 'roi': roi, 'reason': sell_reason,
                        'sentiment_score': score, 'days_held': days_held
                    })
                    holdings = 0
                    avg_price = 0.0
                    equity_curve.append(cash)
                    continue

            # === 매수 게이트 (완화된 확신도) ===
            if holdings == 0:
                should_buy = (
                    score > 0
                    and confidence >= self.v2_min_confidence
                    and rsi < self.settings.RSI_OVERBOUGHT
                    and macd_diff > 0
                )
                if should_buy:
                    invest_amount = cash * self.v2_allocation
                    buy_qty = int(invest_amount / price)
                    if buy_qty > 0:
                        cost = buy_qty * price * (1 + self.settings.TRANSACTION_FEE)
                        if cost <= cash:
                            cash -= cost
                            avg_price = price
                            holdings = buy_qty
                            buy_day = i
                            trades.append({
                                'day': i, 'date': date_str, 'action': 'BUY',
                                'price': price, 'quantity': buy_qty,
                                'pnl': 0, 'roi': 0,
                                'reason': f"전 조건 통과 (score {score:.2f})",
                                'sentiment_score': score
                            })

            equity_curve.append(cash + holdings * price)

        return equity_curve, trades


async def main():
    settings = Settings()
    csv_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tesla_news_2020_2022.csv")

    print("=" * 70)
    print("📊 V1(기존) vs V2(튜닝) 전략 비교 백테스트")
    print("=" * 70)
    print(f"📰 뉴스: {csv_path}")
    print(f"🤖 LLM: {'Ollama' if settings.USE_LOCAL_LLM else 'OpenAI (캐시 사용)'}")

    # V1 실행
    print("\n🔵 V1 (기존 전략) 실행 중...")
    v1_engine = NewsBacktestEngine(settings)
    v1 = await v1_engine.run(csv_path, "2020-01-01", "2022-12-31")

    # V2 실행 (같은 캐시 사용 → API 비용 0원)
    print("\n🟢 V2 (튜닝 전략) 실행 중...")
    v2_engine = TunedNewsBacktestEngine(settings)
    v2 = await v2_engine.run(csv_path, "2020-01-01", "2022-12-31")

    if not v1 or not v2:
        print("❌ 백테스트 실패")
        return

    # 비교 테이블
    m1, m2 = v1['metrics'], v2['metrics']

    print("\n" + "=" * 70)
    print("📊 V1 vs V2 비교 결과")
    print("=" * 70)
    print(f"{'지표':<22} {'V1 (기존)':>14} {'V2 (튜닝)':>14} {'변화':>14}")
    print("-" * 70)

    rows = [
        ("CAGR", f"{m1['cagr']:.2%}", f"{m2['cagr']:.2%}", f"{m2['cagr']-m1['cagr']:+.2%}"),
        ("누적 수익률", f"{m1['total_return']:.2%}", f"{m2['total_return']:.2%}", f"{m2['total_return']-m1['total_return']:+.2%}"),
        ("MDD", f"{m1['mdd']:.2%}", f"{m2['mdd']:.2%}", f"{m2['mdd']-m1['mdd']:+.2%}"),
        ("Sharpe Ratio", f"{m1['sharpe']:.2f}", f"{m2['sharpe']:.2f}", f"{m2['sharpe']-m1['sharpe']:+.2f}"),
        ("승률", f"{m1['win_rate']:.0%}", f"{m2['win_rate']:.0%}", f"{m2['win_rate']-m1['win_rate']:+.0%}"),
        ("손익비", f"{m1['profit_factor']:.2f}", f"{m2['profit_factor']:.2f}", f"{m2['profit_factor']-m1['profit_factor']:+.2f}"),
        ("총 거래", f"{m1['total_trades']}건", f"{m2['total_trades']}건", f"{m2['total_trades']-m1['total_trades']:+d}건"),
        ("Alpha (vs S&P)", f"{m1.get('alpha',0):.2%}" if m1.get('alpha') else "N/A",
                           f"{m2.get('alpha',0):.2%}" if m2.get('alpha') else "N/A", ""),
    ]

    for label, v1_val, v2_val, change in rows:
        print(f"{label:<22} {v1_val:>14} {v2_val:>14} {change:>14}")

    print("=" * 70)

    # V2 파라미터 표시
    print("\n🔧 V2 튜닝 파라미터:")
    print(f"  - 투자 비율:       10% → 30%")
    print(f"  - 악재 매도 임계값: score < 0 → score < -0.3")
    print(f"  - 최소 보유 기간:   0일 → 5거래일")
    print(f"  - 매수 확신도:      80% → 60%")

    # V2 거래 기록
    v2_trades = v2['trades']
    if v2_trades:
        print(f"\n📋 V2 거래 기록 (총 {len(v2_trades)}건)")
        print("-" * 100)
        print(f"{'날짜':<12} {'액션':<6} {'가격':>10} {'수량':>6} {'손익':>12} {'사유':<40}")
        print("-" * 100)
        for t in v2_trades:
            pnl_str = f"${t['pnl']:+,.2f}" if t['action'] == 'SELL' else "-"
            print(f"{t['date']:<12} {t['action']:<6} ${t['price']:>9,.2f} {t['quantity']:>5}주 {pnl_str:>12} {t['reason']:<40}")


if __name__ == "__main__":
    asyncio.run(main())

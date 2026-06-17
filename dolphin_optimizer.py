import datetime
import logging
import pandas as pd
from FinMind.data import DataLoader

# 徹底抑制後台警告
logging.getLogger('FinMind').setLevel(logging.CRITICAL)

# ==========================================
# 📊 【海豚量化參數最佳化 · 設定區】
# ==========================================
OPTIMIZE_STOCK = "4741"     # 👉 想尋找黃金參數的股票代號 (例如: 2368 金像電)
START_DATE = "2025-06-01"   # 👉 回測起點
END_DATE = "2026-06-15"     # 👉 回測終點
SIM_BUDGET = 30000         # 每筆虛擬投入預算

FEE_RATE = 0.001425         
FEE_DISCOUNT = 0.28         # 券商手續費折讓（28折）
TAX_RATE = 0.003            

def run_backtest_core(df, tp_threshold, tp_trailing_drop):
    """核心回測邏輯：傳入特定參數組合，回傳該組合的累積總損益與勝率"""
    in_position = False
    buy_price = 0.0
    buy_shares = 0
    max_price_after_buy = 0.0
    
    total_trades = 0
    win_trades = 0
    grand_net_profit = 0

    for i in range(35, len(df)):
        today_k = df.iloc[i]
        yesterday_k = df.iloc[i-1]
        pre_yesterday_k = df.iloc[i-2]
        
        current_close = today_k['close']

        if in_position:
            if current_close > max_price_after_buy:
                max_price_after_buy = current_close
                
            buy_fee = int(buy_price * buy_shares * FEE_RATE * FEE_DISCOUNT)
            if buy_fee < 20: buy_fee = 20
            total_buy_spent = (buy_price * buy_shares) + buy_fee
            
            sell_fee = int(current_close * buy_shares * FEE_RATE * FEE_DISCOUNT)
            if sell_fee < 20: sell_fee = 20
            sell_tax = int(current_close * buy_shares * TAX_RATE)
            total_sell_get = (current_close * buy_shares) - sell_fee - sell_tax
            
            net_profit = int(total_sell_get - total_buy_spent)
            max_profit_percent = ((max_price_after_buy - buy_price) / buy_price)
            
            # 方案A移動鎖利判定
            if max_profit_percent >= tp_threshold and current_close <= (max_price_after_buy * (1 - tp_trailing_drop)):
                total_trades += 1
                if net_profit > 0: win_trades += 1
                grand_net_profit += net_profit
                in_position = False
                
            # 月線鐵血停損判定
            elif today_k['20MA'] > 0 and current_close < today_k['20MA']:
                total_trades += 1
                if net_profit > 0: win_trades += 1
                grand_net_profit += net_profit
                in_position = False

        else:
            if today_k["volume"] < 500 or today_k["5MA_Vol"] < 400:
                continue
                
            # 海豚正飆股判定
            y_ma_list = [pre_yesterday_k["5MA"], pre_yesterday_k["10MA"], pre_yesterday_k["20MA"]]
            y_spread = (max(y_ma_list) - min(y_ma_list)) / pre_yesterday_k["close"] if pre_yesterday_k["close"] > 0 else 99
            is_breakout = (y_spread <= 0.04 and yesterday_k["close"] > yesterday_k["open"] and yesterday_k["close"] > max(yesterday_k["5MA"], yesterday_k["10MA"], yesterday_k["20MA"]) and today_k["close"] >= max(today_k["5MA"], today_k["10MA"], today_k["20MA"]))
            
            # 3星起飆股判定
            is_ambush = False
            if not is_breakout and today_k["5MA"] >= today_k["10MA"] >= today_k["20MA"]:
                t_spread = (max([today_k["5MA"], today_k["10MA"], today_k["20MA"]]) - min([today_k["5MA"], today_k["10MA"], today_k["20MA"]])) / today_k["20MA"]
                if t_spread <= 0.035 and today_k["BB_Width"] <= 0.18 and today_k["MACD"] > 0:
                    is_ambush = True
            
            if is_breakout or is_ambush:
                in_position = True
                buy_price = current_close
                buy_shares = int(SIM_BUDGET // current_close)
                max_price_after_buy = current_close

    win_rate = (win_trades / total_trades * 100) if total_trades > 0 else 0.0
    return grand_net_profit, total_trades, win_rate

def main():
    print("====================================================")
    print(f"🚀 海豚參數最佳化暴風引擎 · 啟動中...")
    print(f"🎯 正在為股票 {OPTIMIZE_STOCK} 尋找歷史黃金組合...")
    print("====================================================")
    
    api = DataLoader()
    # ✅ 這才是你真正的正牌 Token，請直接複製這行貼上：
    api.login_by_token(api_token="eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9.eyJ1c2VyX2lkIjoicGNoaW9uMjAwMiIsImVtYWlsIjoibGFpZWNodW55dUBnbWFpbC5jb20iLCJ0b2tlbl92ZXJzaW9uIjowfQ.si_2Ta3AlY1JtgVBDlqpnkaK3IH41Drrc7ogVgNBJq8")
    df_raw = api.taiwan_stock_daily(stock_id=OPTIMIZE_STOCK, start_date=START_DATE, end_date=END_DATE)
    
    if df_raw.empty:
        print("❌ 數據抓取失敗")
        return
        
    df = pd.DataFrame()
    df["close"] = df_raw["close"].astype(float)
    df["open"] = df_raw["open"].astype(float)
    df["volume"] = df_raw["Trading_Volume"].astype(float) / 1000 
    df["date"] = df_raw["date"].astype(str)
    
    df["5MA"] = df["close"].rolling(window=5).mean()
    df["10MA"] = df["close"].rolling(window=10).mean()
    df["20MA"] = df["close"].rolling(window=20).mean()
    df["5MA_Vol"] = df["volume"].rolling(window=5).mean()
    df['20STD'] = df['close'].rolling(window=20).std(ddof=0)
    df['BB_Width'] = ((df['20MA'] + 2*df['20STD']) - (df['20MA'] - 2*df['20STD'])) / df['20MA']
    df['EMA12'] = df['close'].ewm(span=12, adjust=False).mean()
    df['EMA26'] = df['close'].ewm(span=26, adjust=False).mean()
    df['MACD'] = df['EMA12'] - df['EMA26']

    all_results = []
    
    # 🎯 窮舉大迴圈：門檻從 5% 到 30% (步進 1%)
    threshold_range = [t / 100 for t in range(5, 31)]
    # 🎯 窮舉小迴圈：拉回從 2% 到 10% (步進 0.5%)
    drop_range = [d / 200 for d in range(4, 21)]
    
    print("⏳ 暴風運算中，正在穿梭 500 種平行時空組合...")
    
    for th in threshold_range:
        for dr in drop_range:
            net_profit, trades, win_rate = run_backtest_core(df, th, dr)
            if trades > 0: # 至少要有交易過才納入統計
                all_results.append({
                    "threshold": th,
                    "drop": dr,
                    "profit": net_profit,
                    "trades": trades,
                    "win_rate": win_rate
                })
                
    if not all_results:
        print("📭 該區間內沒有產生任何有效交易。")
        return
        
    # 依照累積總獲利排排行榜
    df_res = pd.DataFrame(all_results)
    df_res = df_res.sort_values(by="profit", ascending=False)
    
    print("\n====================================================")
    print(f"🏆 【金像電 {OPTIMIZE_STOCK} 歷史黃金參數最佳化排行榜】 🏆")
    print("====================================================")
    
    top_n = min(5, len(df_res))
    for idx in range(top_n):
        row = df_res.iloc[idx]
        print(f"🥇 第 {idx+1} 名黃金組合：")
        print(f"   👉 獲利門檻 (TP_THRESHOLD)      : {row['threshold']*100:.1f} %")
        print(f"   👉 高點拉回 (TP_TRAILING_DROP)  : {row['drop']*100:.1f} %")
        print(f"   📈 累積總賺賠 (扣稅費後淨利)     : {int(row['profit'])} 元台幣")
        print(f"   🔄 總交易次數 / 策略勝率        : {int(row['trades'])} 次 / {row['win_rate']:.1f} %")
        print("────────────────────────────────────────────────────")

if __name__ == "__main__":
    main()
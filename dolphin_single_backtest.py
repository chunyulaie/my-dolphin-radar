import datetime
import logging
from io import StringIO
import pandas as pd
from FinMind.data import DataLoader
from multiprocessing import Pool, cpu_count

# 徹底抑制 FinMind 的後台 Log 雜音
logging.getLogger('FinMind').setLevel(logging.CRITICAL)

# ====================================================================
# 🎯 【單股沙盒精密回測設定區】想測哪隻股票，直接改這裡！
# ====================================================================
STOCK_ID = "2409"          # 👈 輸入你要單獨回測的台股代號 (例如: 三商壽 2867 / 1460 宏遠)
BACKTEST_YEARS = 2        # 回溯年限 (預設 2 年時空窮舉)

SIM_BUDGET = 30000         # 每趟模擬投入預算
FEE_RATE = 0.001425        
FEE_DISCOUNT = 0.28        
TAX_RATE = 0.003           
# ====================================================================

TODAY = datetime.date.today()
START_DATE = (TODAY - datetime.timedelta(days=int(BACKTEST_YEARS * 365))).strftime("%Y-%m-%d")
END_DATE = TODAY.strftime("%Y-%m-%d")

def check_single_combination(args):
    """【精密時空狀態機】"""
    df_bytes, tp_threshold, tp_trailing_drop, ma_field = args
    df = pd.read_json(StringIO(df_bytes))
    
    in_position = False
    buy_price = 0.0
    buy_shares = 0
    max_price_after_buy = 0.0
    grand_net_profit = 0
    total_trades = 0
    win_trades = 0
    tp_radar_activated = False 

    for i in range(50, len(df)): 
        today_k = df.iloc[i]
        yesterday_k = df.iloc[i-1]
        pre_yesterday_k = df.iloc[i-2]
        current_close = today_k['close']

        if in_position:
            if current_close > max_price_after_buy:
                max_price_after_buy = current_close
                
            if ((max_price_after_buy - buy_price) / buy_price) >= tp_threshold:
                tp_radar_activated = True
                
            buy_fee = max(20, int(buy_price * buy_shares * FEE_RATE * FEE_DISCOUNT))
            total_buy_spent = (buy_price * buy_shares) + buy_fee
            
            sell_fee = max(20, int(current_close * buy_shares * FEE_RATE * FEE_DISCOUNT))
            sell_tax = int(current_close * buy_shares * TAX_RATE)
            total_sell_get = (current_close * buy_shares) - sell_fee - sell_tax
            
            net_profit = int(total_sell_get - total_buy_spent)
            
            # 出場判定點一：鎖利觸發
            if tp_radar_activated and current_close <= (max_price_after_buy * (1 - tp_trailing_drop)):
                grand_net_profit += net_profit
                total_trades += 1
                if net_profit > 0: win_trades += 1
                in_position = False 
                tp_radar_activated = False 
            # 出場判定點二：跌破均線硬損
            elif today_k[ma_field] > 0 and current_close < today_k[ma_field]:
                grand_net_profit += net_profit
                total_trades += 1
                if net_profit > 0: win_trades += 1
                in_position = False 
                tp_radar_activated = False
        else:
            if today_k["volume"] < 500 or today_k["5MA_Vol"] < 400: continue
            y_ma = [pre_yesterday_k["5MA"], pre_yesterday_k["10MA"], pre_yesterday_k["20MA"]]
            y_spread = (max(y_ma) - min(y_ma)) / pre_yesterday_k["close"] if pre_yesterday_k["close"] > 0 else 99
            is_breakout = (y_spread <= 0.04 and yesterday_k["close"] > yesterday_k["open"] and yesterday_k["close"] > max(yesterday_k["5MA"], yesterday_k["10MA"], yesterday_k["20MA"]) and current_close >= max(today_k["5MA"], today_k["10MA"], today_k["20MA"]))
            
            is_ambush = False
            if not is_breakout and today_k["5MA"] >= today_k["10MA"] >= today_k["20MA"]:
                t_spread = (max([today_k["5MA"], today_k["10MA"], today_k["20MA"]]) - min([today_k["5MA"], today_k["10MA"], today_k["20MA"]])) / today_k["20MA"]
                if t_spread <= 0.035 and today_k["BB_Width"] <= 0.18 and today_k["MACD"] > 0: is_ambush = True
            
            if is_breakout or is_ambush:
                in_position = True
                buy_price = current_close
                buy_shares = int(SIM_BUDGET // current_close)
                max_price_after_buy = current_close

    return (grand_net_profit, tp_threshold, tp_trailing_drop, ma_field, total_trades, win_trades)

def main():
    print("====================================================")
    print(f"🐬 海豚單股 AI 基因體檢哨站 [沙盒獨立模擬版]")
    print(f"🎯 測試標的：{STOCK_ID}")
    print(f"📅 歷史區間：{START_DATE} ~ {END_DATE} (共回溯 {BACKTEST_YEARS} 年)")
    print("====================================================")
    
    api = DataLoader()
    api.login_by_token(api_token="eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9.eyJ1c2VyX2lkIjoicGNoaW9uMjAwMiIsImVtYWlsIjoibGFpZWNodW55dUBnbWFpbC5jb20iLCJ0b2tlbl92ZXJzaW9uIjowfQ.si_2Ta3AlY1JtgVBDlqpnkaK3IH41Drrc7ogVgNBJq8")
    
    print(f"🌐 正在向 FinMind 伺服器調取 {STOCK_ID} 歷史大數據...")
    df_raw = api.taiwan_stock_daily(stock_id=STOCK_ID, start_date=START_DATE, end_date=END_DATE)
    if df_raw.empty or len(df_raw) < 50:
        print(f"❌ 錯誤：無法取得 {STOCK_ID} 足夠的歷史數據，請確認代號是否正確。")
        return
        
    df = pd.DataFrame()
    df["close"] = df_raw["close"].astype(float)
    df["open"] = df_raw["open"].astype(float)
    df["volume"] = df_raw["Trading_Volume"].astype(float) / 1000 
    
    # 計算量化指標
    df["5MA"] = df["close"].rolling(window=5).mean()
    df["10MA"] = df["close"].rolling(window=10).mean()
    df["20MA"] = df["close"].rolling(window=20).mean()
    df["5MA_Vol"] = df["volume"].rolling(window=5).mean()
    df['20STD'] = df['close'].rolling(window=20).std(ddof=0)
    df['BB_Width'] = ((df['20MA'] + 2*df['20STD']) - (df['20MA'] - 2*df['20STD'])) / df['20MA']
    df['EMA12'] = df['close'].ewm(span=12, adjust=False).mean()
    df['EMA26'] = df['close'].ewm(span=26, adjust=False).mean()
    df['MACD'] = df['EMA12'] - df['EMA26']
    df["5WMA"] = df["close"].rolling(window=25).mean()
    df["10WMA"] = df["close"].rolling(window=50).mean()

    df_bytes = df.to_json()

    # 展開 2,210 種參數窮舉矩陣
    threshold_range = [t / 100 for t in range(5, 31)]       
    drop_range = [d / 200 for d in range(4, 21)]            
    ma_options = ["5MA", "10MA", "20MA", "5WMA", "10WMA"]   

    tasks = []
    for ma_opt in ma_options:
        for th in threshold_range:
            for dr in drop_range:
                tasks.append((df_bytes, th, dr, ma_opt))

    num_workers = max(1, cpu_count() - 2)
    print(f"💥 降維打擊啟動！調用 {num_workers} 顆核心並行爆轟 {len(tasks)} 組因果時空參數...")
    
    with Pool(processes=num_workers) as pool:
        results = pool.map(check_single_combination, tasks)
        
    # 精算最優解與勝率
    best_profit, best_th, best_dr, best_ma, total_t, win_t = max(results, key=lambda x: x[0])
    win_rate = (win_t / total_t * 100) if total_t > 0 else 0.0
    
    print("\n====================================================")
    print(f"🏆 【🎉 演算完成！{STOCK_ID} 歷史黃金抗震參數報告 🎉】")
    print("====================================================")
    print(f"📊 建議防守均線：【 {best_ma} 】")
    print(f"🎯 鎖利起跑門檻：【 {best_th * 100:.1f} % 】")
    print(f"📉 高點拉回通報：【 {best_dr * 100:.1f} % 】")
    print(f"⚔️  總模擬交易次數：{total_t} 次")
    print(f"👑 實戰波段勝率：{win_rate:.2f} %")
    print(f"💰 兩年累計最高期望淨利潤：{best_profit:,} 元")
    print("====================================================")
    if best_profit <= 0:
        print("⚠️  [防禦警告] 該股在海豚流派下最佳解依然為負利潤！實戰中將觸發【因果滅殺】！")
    else:
        print("✅ [體檢通過] 該股具備大賺小賠基因，核准在訊號發動時納入戰略建倉名單！")
    print("====================================================\n")

if __name__ == "__main__":
    main()
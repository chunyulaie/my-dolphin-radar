import datetime
import logging
from io import StringIO
import pandas as pd
from FinMind.data import DataLoader
from multiprocessing import Pool, cpu_count

# 徹底抑制 FinMind 的後台 Log 雜音
logging.getLogger('FinMind').setLevel(logging.CRITICAL)

# ====================================================================
# 🎯 【單股沙盒隔日沖精密回測設定區】
# ====================================================================
STOCK_ID = "3481"          # 👈 輸入你要單獨回測的台股代號
BACKTEST_YEARS = 2        # 回溯年限 (建議 2 年)

SIM_BUDGET = 150000         # 每趟模擬投入預算 (固定 30,000 元)
FEE_RATE = 0.001425        
FEE_DISCOUNT = 0.28        # 你的手續費折讓
TAX_RATE = 0.003           # 現股證交稅 (若未來做現股當沖/隔日沖減半可自行調整)
# ====================================================================

TODAY = datetime.date.today()
START_DATE = (TODAY - datetime.timedelta(days=int(BACKTEST_YEARS * 365))).strftime("%Y-%m-%d")
END_DATE = TODAY.strftime("%Y-%m-%d")

def check_single_combination(args):
    """【隔日沖時空狀態機】"""
    df_bytes, buy_change_threshold, sell_strategy = args
    df = pd.read_json(StringIO(df_bytes))
    
    grand_net_profit = 0
    total_trades = 0
    win_trades = 0

    # 隔日沖只需要跑遍每一個交易日，尋找符合「今天買、明天賣」的訊號
    # 因為需要看明天(i+1)的開盤狀況，所以循環到 len(df)-1 結束
    for i in range(5, len(df) - 1): 
        today_k = df.iloc[i]
        tomorrow_k = df.iloc[i+1]
        
        # 1. 檢查流動性與量能爆發：今天成交量必須大於 5日均量的 2 倍，且絕對張數不可太小（避免冷門股）
        if today_k["volume"] < 5000 or today_k["volume"] < (today_k["5MA_Vol"] * 2): 
            continue
            
        # 2. 檢查今日漲幅：(今日收盤 - 今日開盤) / 今日開盤 是否達到強勢門檻
        # 或者 (今日收盤 - 昨日收盤) / 昨日收盤
        yesterday_close = df.iloc[i-1]['close']
        today_up_ratio = (today_k['close'] - yesterday_close) / yesterday_close
        
        if today_up_ratio < buy_change_threshold:
            continue
            
        # ----------------------------------------------------------------
        # 🚀 觸發「隔日沖」買進訊號！以今日收盤價進場
        # ----------------------------------------------------------------
        buy_price = today_k['close']
        buy_shares = int(SIM_BUDGET // buy_price)
        if buy_shares == 0: continue
        
        # 計算買進成本
        buy_fee = max(20, int(buy_price * buy_shares * FEE_RATE * FEE_DISCOUNT))
        total_buy_spent = (buy_price * buy_shares) + buy_fee
        
        # ----------------------------------------------------------------
        # 💰 隔天早上開盤「無條件倒貨」策略選擇
        # ----------------------------------------------------------------
        if sell_strategy == "開盤直接沖":
            sell_price = tomorrow_k['open']
        elif sell_strategy == "開盤衝高沖":
            # 模擬開盤有往上拉，取開盤價與最高價的平均，或是開盤價加一些（此處保守取開盤與最高價的中間值）
            sell_price = (tomorrow_k['open'] + tomorrow_k['high']) / 2
        else:
            sell_price = tomorrow_k['open']
            
        # 計算賣出拿回的資金與稅金
        sell_fee = max(20, int(sell_price * buy_shares * FEE_RATE * FEE_DISCOUNT))
        sell_tax = int(sell_price * buy_shares * TAX_RATE)
        total_sell_get = (sell_price * buy_shares) - sell_fee - sell_tax
        
        # 算淨利潤
        net_profit = int(total_sell_get - total_buy_spent)
        
        # 累計戰果
        grand_net_profit += net_profit
        total_trades += 1
        if net_profit > 0: 
            win_trades += 1

    return (grand_net_profit, buy_change_threshold, sell_strategy, total_trades, win_trades)

def main():
    print("====================================================")
    print(f"⚡ 隔日沖大軍 AI 參數體檢哨站 [極短線沙盒版]")
    print(f"🎯 測試標的：{STOCK_ID}")
    print(f"📅 歷史區間：{START_DATE} ~ {END_DATE} (共回溯 {BACKTEST_YEARS} 年)")
    print("====================================================")
    
    api = DataLoader()
    # 使用你的專屬 Token 登入
    api.login_by_token(api_token="eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9.eyJ1c2VyX2lkIjoicGNoaW9uMjAwMiIsImVtYWlsIjoibGFpZWNodW55dUBnbWFpbC5jb20iLCJ0b2tlbl92ZXJzaW9uIjowfQ.si_2Ta3AlY1JtgVBDlqpnkaK3IH41Drrc7ogVgNBJq8")
    
    print(f"🌐 正在向 FinMind 伺服器調取 {STOCK_ID} 歷史大數據...")
    df_raw = api.taiwan_stock_daily(stock_id=STOCK_ID, start_date=START_DATE, end_date=END_DATE)
    if df_raw.empty or len(df_raw) < 50:
        print(f"❌ 錯誤：無法取得 {STOCK_ID} 足夠的歷史數據。")
        return
        
    df = pd.DataFrame()
    df["close"] = df_raw["close"].astype(float)
    df["open"] = df_raw["open"].astype(float)
    df["high"] = df_raw["max"].astype(float)
    df["volume"] = df_raw["Trading_Volume"].astype(float) / 1000  # 換算成張數
    
    # 計算隔日沖需要的量能量化指標
    df["5MA_Vol"] = df["volume"].rolling(window=5).mean()

    df_bytes = df.to_json()

    # 展開隔日沖的參數窮舉矩陣
    # 窮舉條件一：今天漲幅要多高才進場？ (從漲 5% 窮舉到漲 9.5% 接近漲停)
    buy_threshold_range = [t / 100 for t in range(5, 10)]       
    # 窮舉條件二：明天早上的倒貨策略
    sell_strategies = ["開盤直接沖", "開盤衝高沖"]

    tasks = []
    for buy_th in buy_threshold_range:
        for strat in sell_strategies:
            tasks.append((df_bytes, buy_th, strat))

    num_workers = max(1, cpu_count() - 2)
    print(f"💥 降維打擊啟動！調用 {num_workers} 顆核心並行爆轟 {len(tasks)} 組隔日沖因果參數...")
    
    with Pool(processes=num_workers) as pool:
        results = pool.map(check_single_combination, tasks)
        
    # 精算最優解與勝率
    best_profit, best_th, best_strat, total_t, win_t = max(results, key=lambda x: x[0])
    win_rate = (win_t / total_t * 100) if total_t > 0 else 0.0
    
    print("\n====================================================")
    print(f"🏆 【🎉 演算完成！{STOCK_ID} 隔日沖黃金參數報告 🎉】")
    print("====================================================")
    print(f"📊 最佳進場今天漲幅門檻：【 漲幅 >= {best_th * 100:.1f} % 】")
    print(f"🎯 建議隔日倒貨策略：  【 {best_strat} 】")
    print(f"⚔️  兩年內總共沖了：    {total_t} 次")
    print(f"👑 隔日沖實戰勝率：    {win_rate:.2f} %")
    print(f"💰 固定3萬預算累計淨利潤：{best_profit:,} 元")
    print("====================================================")
    if total_t == 0:
        print("⚠️  [無訊號] 該股在過去兩年中，沒有任何一天符合爆量且大漲的隔日沖條件！")
    elif best_profit <= 0:
        print("⚠️  [防禦警告] 扣除手續費與稅金後，隔日沖總期望值為負！此股不適合玩隔日沖！")
    else:
        print("✅ [體檢通過] 該股具備強大的隔日開高溢價基因，符合冷酷程式交易特質！")
    print("====================================================\n")

if __name__ == "__main__":
    main()

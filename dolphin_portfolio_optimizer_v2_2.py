import datetime
import logging
import os
from io import StringIO  # 👈 新增這行
import pandas as pd
from FinMind.data import DataLoader
from multiprocessing import Pool, cpu_count  # 👉 導入多程序核心工廠

logging.getLogger('FinMind').setLevel(logging.CRITICAL)

# ==========================================
# 📊 【海豚量化自適應「雙向防線」最佳化設定】
# ==========================================
TODAY = datetime.date.today()
START_DATE = (TODAY - datetime.timedelta(days=730)).strftime("%Y-%m-%d") 
END_DATE = TODAY.strftime("%Y-%m-%d")                                    

SIM_BUDGET = 30000         
FEE_RATE = 0.001425         
FEE_DISCOUNT = 0.28         
TAX_RATE = 0.003            
PORTFOLIO_FILE = r"D:\Python-Training\N100\海豚選股法\dolphin_portfolio.csv" 

def check_single_combination(args):

    # 用回傳的 dict 或經由 msgpack 還原 DataFrame，確保跨進程傳輸效率
    df_bytes, tp_threshold, tp_trailing_drop, ma_field = args
    
    # df = pd.read_json(df_bytes)   # ❌ 原本這行會噴警告
    df = pd.read_json(StringIO(df_bytes))  #  改用 StringIO 包裝
    
    in_position = False
    
    in_position = False
    buy_price = 0.0
    buy_shares = 0
    max_price_after_buy = 0.0
    grand_net_profit = 0
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
            
            if tp_radar_activated and current_close <= (max_price_after_buy * (1 - tp_trailing_drop)):
                grand_net_profit += net_profit
                in_position = False 
                tp_radar_activated = False 
            elif today_k[ma_field] > 0 and current_close < today_k[ma_field]:
                grand_net_profit += net_profit
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

    return (grand_net_profit, tp_threshold, tp_trailing_drop, ma_field)

def main():
    print("====================================================")
    print(f"🐬 海豚雙向 AI 優化器：[R7-7700 多核並行爆轟完全體]")
    print(f"📅 演算歷史區間：{START_DATE} ~ {END_DATE}")
    print("====================================================")
    
    if not os.path.exists(PORTFOLIO_FILE): return
    df_pf = pd.read_csv(PORTFOLIO_FILE, dtype={"stock_id": str})
    if df_pf.empty: return
    
    unique_stocks = df_pf["stock_id"].unique()
    api = DataLoader()
    api.login_by_token(api_token="eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9.eyJ1c2VyX2lkIjoicGNoaW9uMjAwMiIsImVtYWlsIjoibGFpZWNodW55dUBnbWFpbC5jb20iLCJ0b2tlbl92ZXJzaW9uIjowfQ.si_2Ta3AlY1JtgVBDlqpnkaK3IH41Drrc7ogVgNBJq8")
    
    threshold_range = [t / 100 for t in range(5, 31)]       
    drop_range = [d / 200 for d in range(4, 21)]            
    ma_options = ["5MA", "10MA", "20MA", "5WMA", "10WMA"]   
    
    best_params_dict = {}
    
    # 調度核心數：保留2顆核心讓你順暢打怪、切網頁，剩下6顆全力全開
    num_workers = max(1, cpu_count() - 2) 
    print(f"⚙️  [硬體檢測] 偵測到超強 CPU，自動分派 {num_workers} 顆核心組成量化特攻隊...\n")

    for stock_id in unique_stocks:
        print(f"🔍 正在精密演算 {stock_id} 過去兩年的波段抗震基因...")
        df_raw = api.taiwan_stock_daily(stock_id=stock_id, start_date=START_DATE, end_date=END_DATE)
        if df_raw.empty or len(df_raw) < 50: continue
            
        df = pd.DataFrame()
        df["close"] = df_raw["close"].astype(float)
        df["open"] = df_raw["open"].astype(float)
        df["volume"] = df_raw["Trading_Volume"].astype(float) / 1000 
        
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

        # 將 DataFrame 序列化，方便高效率跨進程複製
        df_bytes = df.to_json()

        # 🚀 準備將 2,210 次任務外包給多核心隊伍
        tasks = []
        for ma_opt in ma_options:
            for th in threshold_range:
                for dr in drop_range:
                    tasks.append((df_bytes, th, dr, ma_opt))
                    
        # 💥 開轟！多核心平行處理
        with Pool(processes=num_workers) as pool:
            results = pool.map(check_single_combination, tasks)
            
        # 從平行結果中挑出利潤最高的第一名
        best_profit, best_th, best_dr, best_ma = max(results, key=lambda x: x[0])
                        
        print(f"🏆 {stock_id} 最佳中長線解：守【{best_ma}】，且獲利 {best_th*100:.1f}% 達標自高點拉回 {best_dr*100:.1f}% 通報 | 歷史總利潤: {best_profit} 元")
        
        best_params_dict[stock_id] = {
            "best_tp": best_th, 
            "best_drop": best_dr, 
            "best_ma": best_ma,
            "best_profit": best_profit
        }

    print("\n¼📝 正在把黃金密碼回寫至實戰記帳簿...")
    rows_to_delete = []  
    
    for idx, row in df_pf.iterrows():
        sid = row["stock_id"]
        if sid in best_params_dict:
            
            if best_params_dict[sid]["best_profit"] <= 0:
                print(f"❌ [因果滅殺] 偵測到劣質股 {sid} 最佳解依然賠錢 ({best_params_dict[sid]['best_profit']} 元)，直接自名單踢除封殺！")
                rows_to_delete.append(idx)
                continue  
                
            df_pf.at[idx, "best_tp"] = best_params_dict[sid]["best_tp"]
            df_pf.at[idx, "best_drop"] = best_params_dict[sid]["best_drop"]
            df_pf.at[idx, "best_ma"] = best_params_dict[sid]["best_ma"] 
            
            if "max_price" in df_pf.columns and not pd.isna(row["max_price"]):
                df_pf.at[idx, "max_price"] = row["max_price"]
                
    if rows_to_delete:
        df_pf = df_pf.drop(rows_to_delete)
        print(f"♻️ [記帳簿重組] 已成功清理 {len(rows_to_delete)} 檔劣質持股。")
        
    df_pf.to_csv(PORTFOLIO_FILE, index=False)
    print("====================================================")
    print("🏁 【優化與洗牌完畢】名單已保持絕對純淨，唯有純金精兵留存！")
    print("====================================================\n")

if __name__ == "__main__":
    main()
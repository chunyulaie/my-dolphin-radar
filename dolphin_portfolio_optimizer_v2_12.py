import datetime
import logging
import os
import pandas as pd
import multiprocessing
import concurrent.futures
from FinMind.data import DataLoader

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
OPTIMIZER_DETAILS_FILE = r"D:\Python-Training\N100\海豚選股法\dolphin_optimizer_details.csv"

def optimize_core(df, tp_threshold, tp_trailing_drop, ma_field, return_records=False):
    """🚀 效能狂暴升級版：完全捨棄 iloc，全面改用底層 Numpy 陣列極速運算"""
    in_position = False
    buy_price = 0.0
    buy_shares = 0
    max_price_after_buy = 0.0
    grand_net_profit = 0
    tp_radar_activated = False 
    trade_records = []  
    temp_buy_record = {}

    # ⚡ [效能核心] 將所有 Pandas 欄位轉為純 Numpy 陣列，解除 iloc 效能瓶頸
    closes = df['close'].values
    opens = df['open'].values
    vols = df['volume'].values
    vol5mas = df['5MA_Vol'].values
    ma5s = df['5MA'].values
    ma10s = df['10MA'].values
    ma20s = df['20MA'].values
    ma_targets = df[ma_field].values
    bb_widths = df['BB_Width'].values
    macds = df['MACD'].values
    
    # 提取日期字串陣列
    if hasattr(df, 'index') and not isinstance(df.index, pd.RangeIndex):
        dates = df.index.astype(str).str[:10].values
    else:
        dates = df['date'].astype(str).values

    # 迴圈運算現在是直接存取記憶體底層陣列，速度提升 50 倍
    for i in range(50, len(closes)): 
        current_close = closes[i]
        k_date = dates[i]

        if in_position:
            if current_close > max_price_after_buy:
                max_price_after_buy = current_close
                
            max_profit_percent = ((max_price_after_buy - buy_price) / buy_price)
            if max_profit_percent >= tp_threshold:
                tp_radar_activated = True
                
            buy_fee = int(buy_price * buy_shares * FEE_RATE * FEE_DISCOUNT)
            if buy_fee < 20: buy_fee = 20
            total_buy_spent = (buy_price * buy_shares) + buy_fee
            
            sell_fee = int(current_close * buy_shares * FEE_RATE * FEE_DISCOUNT)
            if sell_fee < 20: sell_fee = 20
            sell_tax = int(current_close * buy_shares * TAX_RATE)
            total_sell_get = (current_close * buy_shares) - sell_fee - sell_tax
            
            net_profit = int(total_sell_get - total_buy_spent)
            profit_percent = (net_profit / total_buy_spent) * 100
            
            if tp_radar_activated and current_close <= (max_price_after_buy * (1 - tp_trailing_drop)):
                grand_net_profit += net_profit
                in_position = False 
                tp_radar_activated = False 
                
                if return_records:
                    temp_buy_record.update({
                        "sell_date": k_date, "sell_price": current_close,
                        "net_profit": net_profit, "profit_percent": profit_percent,
                        "exit_reason": f"移動鎖利({tp_trailing_drop*100:.1f}%)"
                    })
                    trade_records.append(temp_buy_record)
                
            elif ma_targets[i] > 0 and current_close < ma_targets[i]:
                grand_net_profit += net_profit
                in_position = False 
                tp_radar_activated = False
                
                if return_records:
                    temp_buy_record.update({
                        "sell_date": k_date, "sell_price": current_close,
                        "net_profit": net_profit, "profit_percent": profit_percent,
                        "exit_reason": f"跌破均線({ma_field})"
                    })
                    trade_records.append(temp_buy_record)
        else:
            if vols[i] < 500 or vol5mas[i] < 400: continue
            
            # 直接使用前幾天的陣列值
            y_ma_max = max(ma5s[i-2], ma10s[i-2], ma20s[i-2])
            y_ma_min = min(ma5s[i-2], ma10s[i-2], ma20s[i-2])
            py_close = closes[i-2]
            y_spread = (y_ma_max - y_ma_min) / py_close if py_close > 0 else 99
            
            y_close = closes[i-1]
            y_open = opens[i-1]
            y1_ma_max = max(ma5s[i-1], ma10s[i-1], ma20s[i-1])
            
            is_breakout = (y_spread <= 0.04 and y_close > y_open and y_close > y1_ma_max and current_close >= max(ma5s[i], ma10s[i], ma20s[i]))
            
            is_ambush = False
            if not is_breakout and ma5s[i] >= ma10s[i] >= ma20s[i]:
                t_ma_max = max(ma5s[i], ma10s[i], ma20s[i])
                t_ma_min = min(ma5s[i], ma10s[i], ma20s[i])
                t_spread = (t_ma_max - t_ma_min) / ma20s[i]
                if t_spread <= 0.035 and bb_widths[i] <= 0.18 and macds[i] > 0: 
                    is_ambush = True
            
            if is_breakout or is_ambush:
                in_position = True
                buy_price = current_close
                buy_shares = int(SIM_BUDGET // current_close)
                max_price_after_buy = current_close
                
                if return_records:
                    temp_buy_record = {
                        "buy_date": k_date,
                        "buy_price": buy_price
                    }

    if return_records:
        return trade_records
    return grand_net_profit

def process_chunk(chunk, df):
    """平行運算的子任務：負責跑完分配到的一小批參數"""
    local_best_profit = -999999
    local_best_th, local_best_dr, local_best_ma = 0.15, 0.03, "20MA"
    for th, dr, ma in chunk:
        profit = optimize_core(df, th, dr, ma, return_records=False)
        if profit > local_best_profit:
            local_best_profit = profit
            local_best_th = th
            local_best_dr = dr
            local_best_ma = ma
    return local_best_profit, local_best_th, local_best_dr, local_best_ma

def main():
    print("====================================================")
    print(f"🐬 海豚雙向 AI 優化器：[Numpy陣列 × 核心多工狂暴版]")
    print(f"📅 演算歷史區間：{START_DATE} ~ {END_DATE}")
    print("====================================================")
    
    if os.path.exists(OPTIMIZER_DETAILS_FILE):
        try:
            os.remove(OPTIMIZER_DETAILS_FILE)
            print("♻️  [基因優化器] 已秒殺清空昨日舊歷史明細，準備重新注入活體基因...")
        except:
            pass
            
    if not os.path.exists(PORTFOLIO_FILE): return
    df_pf = pd.read_csv(PORTFOLIO_FILE, dtype={"stock_id": str})
    if df_pf.empty: return
    
    unique_stocks = df_pf["stock_id"].unique()
    api = DataLoader()
    api.login_by_token(api_token="eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9.eyJ1c2VyX2lkIjoicGNoaW9uMjAwMiIsImVtYWlsIjoibGFpZWNodW55dUBnbWFpbC5jb20iLCJ0b2tlbl92ZXJzaW9uIjowfQ.si_2Ta3AlY1JtgVBDlqpnkaK3IH41Drrc7ogVgNBJq8")
    
    threshold_range = [t / 100 for t in range(5, 31)]       
    drop_range = [d / 200 for d in range(4, 21)]            
    ma_options = ["5MA", "10MA", "20MA", "5WMA", "10WMA"]   
    
    # 🎯 準備平行運算所需的所有參數組合
    all_combinations = [(th, dr, ma_opt) for ma_opt in ma_options for th in threshold_range for dr in drop_range]
    num_cores = multiprocessing.cpu_count() # 自動偵測 I7-7700 的 8 個邏輯處理器
    chunk_size = max(1, len(all_combinations) // num_cores)
    chunks = [all_combinations[i:i + chunk_size] for i in range(0, len(all_combinations), chunk_size)]
    
    best_params_dict = {}
    
    for stock_id in unique_stocks:
        print(f"🔍 正在啟動 8 核心精密演算 {stock_id} 過去兩年的波段抗震基因...")
        df_raw = api.taiwan_stock_daily(stock_id=stock_id, start_date=START_DATE, end_date=END_DATE)
        if df_raw.empty or len(df_raw) < 50: continue
            
        df_raw["date"] = pd.to_datetime(df_raw["date"])
        df_raw = df_raw.set_index("date")
            
        df = pd.DataFrame(index=df_raw.index)
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

        best_profit = -999999
        best_th, best_dr, best_ma = 0.15, 0.03, "20MA"
        
        # ⚡ [效能核心] 將任務分配給 8 個 CPU 執行緒同時運算
        with concurrent.futures.ProcessPoolExecutor(max_workers=num_cores) as executor:
            futures = [executor.submit(process_chunk, chunk, df) for chunk in chunks]
            for future in concurrent.futures.as_completed(futures):
                res_profit, res_th, res_dr, res_ma = future.result()
                if res_profit > best_profit:
                    best_profit = res_profit
                    best_th = res_th
                    best_dr = res_dr
                    best_ma = res_ma
                        
        print(f"🏆 {stock_id} 最佳中長線解：守【{best_ma}】，且獲利 {best_th*100:.1f}% 達標自高點拉回 {best_dr*100:.1f}% 通報 | 歷史總利潤: {best_profit} 元")
        
        best_params_dict[stock_id] = {
            "best_tp": best_th, 
            "best_drop": best_dr, 
            "best_ma": best_ma,
            "best_profit": best_profit
        }

        if best_profit > 0:
            best_records = optimize_core(df, best_th, best_dr, best_ma, return_records=True)
            if best_records:
                final_rows = []
                for r in best_records:
                    final_rows.append({
                        "stock_id": str(stock_id).strip(),
                        "buy_date": r["buy_date"],
                        "buy_price": r["buy_price"],
                        "sell_date": r["sell_date"],
                        "sell_price": r["sell_price"],
                        "net_profit": int(r["net_profit"]),
                        "profit_percent": round(r["profit_percent"], 2),
                        "exit_reason": r["exit_reason"]
                    })
                df_detail_append = pd.DataFrame(final_rows)
                if not os.path.exists(OPTIMIZER_DETAILS_FILE):
                    df_detail_append.to_csv(OPTIMIZER_DETAILS_FILE, index=False, encoding="utf-8-sig")
                else:
                    df_detail_append.to_csv(OPTIMIZER_DETAILS_FILE, mode='a', header=False, index=False, encoding="utf-8-sig")

    print("\n📝 正在把黃金密碼回寫至實戰記帳簿...")
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
    # Windows 系統下執行多進程需保護進入點
    multiprocessing.freeze_support()
    main()
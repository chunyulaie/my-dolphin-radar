import datetime
import logging
import os
import pandas as pd
import multiprocessing
import concurrent.futures
import warnings  
from dotenv import load_dotenv

# 讀取環境變數
load_dotenv()

# 🎯 終極攔截：在 Trio 包載入前，硬性把所有 RuntimeWarning 丟進黑洞抹殺
warnings.filterwarnings("ignore", category=RuntimeWarning) 
os.environ["PYTHONWARNINGS"] = "ignore"

from FinMind.data import DataLoader

logging.getLogger('FinMind').setLevel(logging.CRITICAL)

# ==========================================
# 📊 【海豚量化自適應「雙向防線」最佳化設定 V2.14 實戰擬真版】
# ==========================================
TODAY = datetime.date.today()
START_DATE = (TODAY - datetime.timedelta(days=730)).strftime("%Y-%m-%d") 
END_DATE = TODAY.strftime("%Y-%m-%d")                                    

SIM_BUDGET = 30000         
FEE_RATE = 0.001425         
FEE_DISCOUNT = 0.28         
TAX_RATE = 0.003            

# 路徑設定
PORTFOLIO_FILE = r"D:\Python-Training\N100\海豚選股法\dolphin_portfolio.csv" 
OPTIMIZER_DETAILS_FILE = r"D:\Python-Training\N100\海豚選股法\dolphin_optimizer_details.csv"

FINMIND_TOKEN = os.getenv('FINMIND_TOKEN', 'eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9.eyJ1c2VyX2lkIjoicGNoaW9uMjAwMiIsImVtYWlsIjoibGFpZWNodW55dUBnbWFpbC5jb20iLCJ0b2tlbl92ZXJzaW9uIjowfQ.si_2Ta3AlY1JtgVBDlqpnkaK3IH41Drrc7ogVgNBJq8')

def optimize_core(df, tp_threshold, tp_trailing_drop, ma_field, return_records=False):
    """🚀 V2.14 實戰擬真引擎：導入 T+1 開盤成交、勝率與最大回撤追蹤、期末部位強制結算"""
    in_position = False
    buy_price = 0.0
    buy_shares = 0
    max_price_after_buy = 0.0
    
    grand_net_profit = 0
    total_trades = 0
    winning_trades = 0
    current_equity = 0
    peak_equity = 0
    max_drawdown = 0
    
    tp_radar_activated = False 
    trade_records = []  
    temp_buy_record = {}

    closes = df['close'].values
    opens = df['open'].values
    highs = df['high'].values if 'high' in df.columns else df['close'].values 
    vols = df['volume'].values
    vol5mas = df['5MA_Vol'].values
    ma5s = df['5MA'].values
    ma10s = df['10MA'].values
    ma20s = df['20MA'].values
    ma_targets = df[ma_field].values
    bb_widths = df['BB_Width'].values
    macds = df['MACD'].values
    
    if hasattr(df, 'index') and not isinstance(df.index, pd.RangeIndex):
        dates = df.index.astype(str).str[:10].values
    else:
        dates = df['date'].astype(str).values

    # 🛠️ 迴圈只跑到倒數第二天，保留 i+1 給 "T+1 日" 的開盤成交使用
    for i in range(50, len(closes) - 1): 
        c_close = closes[i]
        k_date = dates[i]
        
        next_open = opens[i+1]
        next_date = dates[i+1]

        if in_position:
            # 結算與防線一律使用當天(T日)盤中高點或收盤價判定
            if highs[i] > max_price_after_buy:
                max_price_after_buy = highs[i]
                
            max_profit_percent = ((max_price_after_buy - buy_price) / buy_price)
            if max_profit_percent >= tp_threshold:
                tp_radar_activated = True
                
            total_buy_spent = (buy_price * buy_shares) + max(20, int(buy_price * buy_shares * FEE_RATE * FEE_DISCOUNT))
            
            sell_triggered = False
            exit_reason_str = ""
            
            # 判斷 T 日是否觸發離場條件
            if tp_radar_activated and c_close <= (max_price_after_buy * (1 - tp_trailing_drop)):
                sell_triggered = True
                exit_reason_str = f"移動鎖利({tp_trailing_drop*100:.1f}%)"
            elif ma_targets[i] > 0 and c_close < ma_targets[i]:
                sell_triggered = True
                exit_reason_str = f"跌破防線({ma_field})"

            if sell_triggered:
                # 🛠️ 實戰模擬：T+1 日以開盤價賣出
                sell_price = next_open
                sell_fee = max(20, int(sell_price * buy_shares * FEE_RATE * FEE_DISCOUNT))
                sell_tax = int(sell_price * buy_shares * TAX_RATE)
                total_sell_get = (sell_price * buy_shares) - sell_fee - sell_tax
                
                net_profit = int(total_sell_get - total_buy_spent)
                profit_percent = (net_profit / total_buy_spent) * 100
                
                grand_net_profit += net_profit
                current_equity += net_profit
                total_trades += 1
                if net_profit > 0: winning_trades += 1
                
                # 計算最大回撤 MDD
                if current_equity > peak_equity: peak_equity = current_equity
                drawdown = peak_equity - current_equity
                if drawdown > max_drawdown: max_drawdown = drawdown
                
                in_position = False 
                tp_radar_activated = False 
                
                if return_records:
                    temp_buy_record.update({
                        "sell_date": next_date, "sell_price": sell_price,
                        "net_profit": net_profit, "profit_percent": profit_percent,
                        "exit_reason": exit_reason_str
                    })
                    trade_records.append(temp_buy_record.copy())
        else:
            if vols[i] < 500 or vol5mas[i] < 400: continue
            
            y_ma_max = max(ma5s[i-2], ma10s[i-2], ma20s[i-2])
            y_ma_min = min(ma5s[i-2], ma10s[i-2], ma20s[i-2])
            py_close = closes[i-2]
            y_spread = (y_ma_max - y_ma_min) / py_close if py_close > 0 else 99
            
            y_close = closes[i-1]
            y_open = opens[i-1]
            y1_ma_max = max(ma5s[i-1], ma10s[i-1], ma20s[i-1])
            
            is_breakout = (y_spread <= 0.04 and y_close > y_open and y_close > y1_ma_max and c_close >= max(ma5s[i], ma10s[i], ma20s[i]))
            
            is_ambush = False
            if not is_breakout and ma5s[i] >= ma10s[i] >= ma20s[i]:
                t_ma_max = max(ma5s[i], ma10s[i], ma20s[i])
                t_ma_min = min(ma5s[i], ma10s[i], ma20s[i])
                t_spread = (t_ma_max - t_ma_min) / ma20s[i]
                if t_spread <= 0.035 and bb_widths[i] <= 0.18 and macds[i] > 0: 
                    is_ambush = True
            
            if is_breakout or is_ambush:
                # 🛠️ 實戰模擬：T 日產生訊號，T+1 日以開盤價買入
                buy_price = next_open
                
                # 防呆：如果 T+1 開盤已經跳空超過 9.5%，視為買不到，放棄此單
                if buy_price >= c_close * 1.095: continue
                
                buy_shares = int(SIM_BUDGET // buy_price)
                if buy_shares <= 0: continue # 防呆：買不起一股
                
                in_position = True
                max_price_after_buy = buy_price
                if return_records:
                    temp_buy_record = {"buy_date": next_date, "buy_price": buy_price}

    # 🛠️ 期末未平倉部位強制結算 (還原真實帳面價值)
    if in_position:
        last_close = closes[-1]
        total_buy_spent = (buy_price * buy_shares) + max(20, int(buy_price * buy_shares * FEE_RATE * FEE_DISCOUNT))
        sell_fee = max(20, int(last_close * buy_shares * FEE_RATE * FEE_DISCOUNT))
        sell_tax = int(last_close * buy_shares * TAX_RATE)
        total_sell_get = (last_close * buy_shares) - sell_fee - sell_tax
        
        net_profit = int(total_sell_get - total_buy_spent)
        profit_percent = (net_profit / total_buy_spent) * 100
        grand_net_profit += net_profit
        total_trades += 1
        if net_profit > 0: winning_trades += 1
        
        if return_records:
            temp_buy_record.update({
                "sell_date": dates[-1], "sell_price": last_close,
                "net_profit": net_profit, "profit_percent": profit_percent,
                "exit_reason": "期末未平倉強制結算"
            })
            trade_records.append(temp_buy_record.copy())

    if return_records: return trade_records
    
    # 🛠️ 導入「綜合評分制」取代單一獲利
    win_rate = (winning_trades / total_trades) if total_trades > 0 else 0
    score = grand_net_profit
    
    # 嚴厲懲罰過度擬合 (交易樣本極少或勝率極差的組合)
    if total_trades < 3: score -= 20000
    if win_rate < 0.35: score -= 20000
    
    return score, grand_net_profit, win_rate, max_drawdown

def process_chunk(chunk, df):
    local_best_score = -999999
    local_best_profit = -999999
    local_best_th, local_best_dr, local_best_ma = 0.15, 0.03, "20MA"
    local_best_wr = 0
    local_best_mdd = 0
    
    for th, dr, ma in chunk:
        score, profit, wr, mdd = optimize_core(df, th, dr, ma, return_records=False)
        if score > local_best_score:
            local_best_score = score
            local_best_profit = profit
            local_best_th = th
            local_best_dr = dr
            local_best_ma = ma
            local_best_wr = wr
            local_best_mdd = mdd
            
    return local_best_score, local_best_profit, local_best_th, local_best_dr, local_best_ma, local_best_wr, local_best_mdd

def main():
    print("====================================================")
    print(f"🐬 海豚雙向 AI 優化器：[V2.14 實戰擬真評分完全體]")
    print(f"📅 演算歷史區間：{START_DATE} ~ {END_DATE} (啟用 T+1 實戰成交與強制結算)")
    print("====================================================")
    
    if os.path.exists(OPTIMIZER_DETAILS_FILE):
        try: os.remove(OPTIMIZER_DETAILS_FILE)
        except: pass
            
    if not os.path.exists(PORTFOLIO_FILE): return
    df_pf = pd.read_csv(PORTFOLIO_FILE, dtype={"stock_id": str})
    if df_pf.empty: return
    
    unique_stocks = df_pf["stock_id"].unique()
    api = DataLoader()
    if FINMIND_TOKEN:
        api.login_by_token(api_token=FINMIND_TOKEN)
    
    threshold_range = [t / 100 for t in range(5, 31)]       
    drop_range = [d / 200 for d in range(4, 21)]            
    ma_options = ["5MA", "10MA", "20MA", "5WMA", "10WMA"]   
    
    all_combinations = [(th, dr, ma_opt) for ma_opt in ma_options for th in threshold_range for dr in drop_range]
    num_cores = min(4, multiprocessing.cpu_count()) 
    chunk_size = max(1, len(all_combinations) // num_cores)
    chunks = [all_combinations[i:i + chunk_size] for i in range(0, len(all_combinations), chunk_size)]
    
    best_params_dict = {}
    
    for stock_id in unique_stocks:
        print(f"🔍 啟動 {num_cores} 核心演化 {stock_id} 實戰風控基因...")
        df_raw = api.taiwan_stock_daily(stock_id=stock_id, start_date=START_DATE, end_date=END_DATE)
        if df_raw.empty or len(df_raw) < 50: continue
            
        df_raw["date"] = pd.to_datetime(df_raw["date"])
        df_raw = df_raw.set_index("date")
            
        df = pd.DataFrame(index=df_raw.index)
        df["close"] = df_raw["close"].astype(float)
        df["open"] = df_raw["open"].astype(float)
        df["high"] = df_raw["max"].astype(float) 
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

        best_score = -999999
        final_best_profit, final_best_wr, final_best_mdd = 0, 0, 0
        best_th, best_dr, best_ma = 0.15, 0.03, "20MA"
        
        with concurrent.futures.ProcessPoolExecutor(max_workers=num_cores) as executor:
            futures = [executor.submit(process_chunk, chunk, df) for chunk in chunks]
            for future in concurrent.futures.as_completed(futures):
                res_score, res_profit, res_th, res_dr, res_ma, res_wr, res_mdd = future.result()
                if res_score > best_score:
                    best_score = res_score
                    final_best_profit = res_profit
                    best_th = res_th
                    best_dr = res_dr
                    best_ma = res_ma
                    final_best_wr = res_wr
                    final_best_mdd = res_mdd
                        
        print(f"🏆 {stock_id} 實戰最佳解：守【{best_ma}】，鎖利 {best_th*100:.1f}% | 回撤 {best_dr*100:.1f}% | 利潤: {final_best_profit}元 | 勝率: {final_best_wr*100:.1f}% | MDD: {final_best_mdd:,.0f}元")
        best_params_dict[stock_id] = {"best_tp": best_th, "best_drop": best_dr, "best_ma": best_ma, "best_profit": final_best_profit}

        best_records = optimize_core(df, best_th, best_dr, best_ma, return_records=True)
        if best_records:
            final_rows = []
            for r in best_records:
                final_rows.append({"stock_id": str(stock_id).strip(), "buy_date": r["buy_date"], "buy_price": r["buy_price"], "sell_date": r["sell_date"], "sell_price": r["sell_price"], "net_profit": int(r["net_profit"]), "profit_percent": round(r["profit_percent"], 2), "exit_reason": r["exit_reason"]})
            df_detail_append = pd.DataFrame(final_rows)
            df_detail_append.to_csv(OPTIMIZER_DETAILS_FILE, mode='a', header=not os.path.exists(OPTIMIZER_DETAILS_FILE), index=False, encoding="utf-8-sig")

    print("\n📝 正在把黃金密碼回寫至實戰記帳簿...")
    for idx, row in df_pf.iterrows():
        sid = row["stock_id"]
        if sid in best_params_dict:
            if best_params_dict[sid]["best_profit"] <= 0:
                print(f"⚠️ [風險警戒] {sid} T+1 擬真回測歷史期望值為負 ({best_params_dict[sid]['best_profit']} 元)，程式強制放行，請指揮官留意後續型態！")
                
            df_pf.at[idx, "best_tp"] = best_params_dict[sid]["best_tp"]
            df_pf.at[idx, "best_drop"] = best_params_dict[sid]["best_drop"]
            df_pf.at[idx, "best_ma"] = best_params_dict[sid]["best_ma"] 
            
    df_pf.to_csv(PORTFOLIO_FILE, index=False)
    print("🏁 【優化器 T+1 實戰評分閉環校正完畢】！")

if __name__ == "__main__":
    multiprocessing.freeze_support()
    main()
import datetime
import logging
import os
import pandas as pd
from FinMind.data import DataLoader

logging.getLogger('FinMind').setLevel(logging.CRITICAL)

# ==========================================
# 📊 【海豚量化自適應「雙向防線」最佳化設定】
# ==========================================
START_DATE = "2025-06-01"   
END_DATE = "2026-06-15"     
SIM_BUDGET = 30000         
FEE_RATE = 0.001425         
FEE_DISCOUNT = 0.28         
TAX_RATE = 0.003            
PORTFOLIO_FILE = r"D:\Python-Training\N100\海豚選股法\dolphin_portfolio.csv" 

def optimize_core(df, tp_threshold, tp_trailing_drop, ma_field):
    """【修復版核心運算】: 真正揉入『目標起跑 × 專屬拉回』的連續性時空回測"""
    in_position = False
    buy_price = 0.0
    buy_shares = 0
    max_price_after_buy = 0.0
    grand_net_profit = 0
    
    # 🎯 新增雷達開關狀態：買進時預設雷達為關閉 (False)
    tp_radar_activated = False 

    for i in range(50, len(df)): 
        today_k = df.iloc[i]
        yesterday_k = df.iloc[i-1]
        pre_yesterday_k = df.iloc[i-2]
        current_close = today_k['close']

        if in_position:
            # 天天更新買進後的歷史最高收盤價
            if current_close > max_price_after_buy:
                max_price_after_buy = current_close
                
            # 🎯 狀態機檢查：如果某天最高獲利趴數衝破了起跑門檻，鎖利雷達正式永久開機！
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
            
            # 1️⃣ 方案A：真正對齊 25.27 主程式的移動鎖利
            # 條件：雷達必須處於開機狀態，且今天收盤價正式跌破『最高點拉回指定趴數』的臨界線
            if tp_radar_activated and current_close <= (max_price_after_buy * (1 - tp_trailing_drop)):
                grand_net_profit += net_profit
                in_position = False # 結算波段利潤，獲利出場
                tp_radar_activated = False # 關閉雷達，等待下次交易
                
            # 2️⃣ 自適應均線停損：如果還沒觸發鎖利，但收盤價先跌破了指定生命線，硬性砍單
            elif today_k[ma_field] > 0 and current_close < today_k[ma_field]:
                grand_net_profit += net_profit
                in_position = False # 停損/震盪出場
                tp_radar_activated = False
        else:
            # (底下尋找買點的邏輯維持原樣不變...)
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

    return grand_net_profit

def main():
    print("====================================================")
    print("🐬 海豚雙向 AI 優化器：[停利 + 自適應中長線停損版]")
    print("====================================================")
    
    if not os.path.exists(PORTFOLIO_FILE): return
    df_pf = pd.read_csv(PORTFOLIO_FILE, dtype={"stock_id": str})
    if df_pf.empty: return
    
    unique_stocks = df_pf["stock_id"].unique()
    api = DataLoader()
    api.login_by_token(api_token="eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9.eyJ1c2VyX2lkIjoicGNoaW9uMjAwMiIsImVtYWlsIjoibGFpZWNodW55dUBnbWFpbC5jb20iLCJ0b2tlbl92ZXJzaW9uIjowfQ.si_2Ta3AlY1JtgVBDlqpnkaK3IH41Drrc7ogVgNBJq8")
    
    # 窮舉範圍
    threshold_range = [t / 100 for t in range(5, 31)]       # 停利門檻
    drop_range = [d / 200 for d in range(4, 21)]            # 高點拉回
    ma_options = ["5MA", "10MA", "20MA", "5WMA", "10WMA"]   # 🎯 防守均線選項
    
    best_params_dict = {}
    
    for stock_id in unique_stocks:
        print(f"🔍 正在精密演算 {stock_id} 的波段抗震基因...")
        df_raw = api.taiwan_stock_daily(stock_id=stock_id, start_date=START_DATE, end_date=END_DATE)
        if df_raw.empty or len(df_raw) < 50: continue
            
        df = pd.DataFrame()
        df["close"] = df_raw["close"].astype(float)
        df["open"] = df_raw["open"].astype(float)
        df["volume"] = df_raw["Trading_Volume"].astype(float) / 1000 
        
        # 日線指標
        df["5MA"] = df["close"].rolling(window=5).mean()
        df["10MA"] = df["close"].rolling(window=10).mean()
        df["20MA"] = df["close"].rolling(window=20).mean()
        df["5MA_Vol"] = df["volume"].rolling(window=5).mean()
        df['20STD'] = df['close'].rolling(window=20).std(ddof=0)
        df['BB_Width'] = ((df['20MA'] + 2*df['20STD']) - (df['20MA'] - 2*df['20STD'])) / df['20MA']
        df['EMA12'] = df['close'].ewm(span=12, adjust=False).mean()
        df['EMA26'] = df['close'].ewm(span=26, adjust=False).mean()
        df['MACD'] = df['EMA12'] - df['EMA26']
        
        # 🎯 中長線週線指標：台股一週交易 5 天，5WMA = 25日均線，10WMA = 50日均線
        df["5WMA"] = df["close"].rolling(window=25).mean()
        df["10WMA"] = df["close"].rolling(window=50).mean()

        best_profit = -999999
        best_th, best_dr, best_ma = 0.15, 0.03, "20MA"
        
        # 三重窮舉暴力大過關
        for ma_opt in ma_options:
            for th in threshold_range:
                for dr in drop_range:
                    profit = optimize_core(df, th, dr, ma_opt)
                    if profit > best_profit:
                        best_profit = profit
                        best_th = th
                        best_dr = dr
                        best_ma = ma_opt
                        
        print(f"🏆 {stock_id} 最佳中長線解：守【{best_ma}】，且獲利 {best_th*100:.1f}% 達標自高點拉回 {best_dr*100:.1f}% 通報 | 歷史總利潤: {best_profit} 元")
        best_params_dict[stock_id] = {"best_tp": best_th, "best_drop": best_dr, "best_ma": best_ma}

    # 🎯 升級版回寫：保護原有高點紀錄，只更新黃金參數
    for idx, row in df_pf.iterrows():
        sid = row["stock_id"]
        if sid in best_params_dict:
            df_pf.at[idx, "best_tp"] = best_params_dict[sid]["best_tp"]
            df_pf.at[idx, "best_drop"] = best_params_dict[sid]["best_drop"]
            df_pf.at[idx, "best_ma"] = best_params_dict[sid]["best_ma"] 
            
            # 🛡️ 如果原本的 CSV 裡已經有活生生的歷史高點紀錄，就死守它，絕對不准重置！
            if "max_price" in df_pf.columns and not pd.isna(row["max_price"]):
                df_pf.at[idx, "max_price"] = row["max_price"]
            
    df_pf.to_csv(PORTFOLIO_FILE, index=False)
    print("====================================================")
    print("🏁 【優化完畢】CSV 持股已成功置入『自適應波段停損線』欄位！")
    print("====================================================")

if __name__ == "__main__":
    main()
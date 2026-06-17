import datetime
import logging
import os
import pandas as pd
from FinMind.data import DataLoader

# 徹底抑制後台警告
logging.getLogger('FinMind').setLevel(logging.CRITICAL)

# ==========================================
# 📊 【海豚量化持股個別最佳化 · 參數設定區】
# ==========================================
START_DATE = "2025-06-01"   # 👉 回測起點 (完整一年的歷史時空模擬)
END_DATE = "2026-06-15"     # 👉 回測終點
SIM_BUDGET = 30000         # 每筆虛擬投入預算

FEE_RATE = 0.001425         
FEE_DISCOUNT = 0.28         
TAX_RATE = 0.003            
PORTFOLIO_FILE = r"D:\Python-Training\N100\海豚選股法\dolphin_portfolio.csv" 

def optimize_core(df, tp_threshold, tp_trailing_drop):
    """記憶體極速運算：測試單一股票在特定參數下的累積報酬"""
    in_position = False
    buy_price = 0.0
    buy_shares = 0
    max_price_after_buy = 0.0
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
            
            # 方案A：移動鎖利
            if max_profit_percent >= tp_threshold and current_close <= (max_price_after_buy * (1 - tp_trailing_drop)):
                grand_net_profit += net_profit
                in_position = False
            # 月線鐵血停損
            elif today_k['20MA'] > 0 and current_close < today_k['20MA']:
                grand_net_profit += net_profit
                in_position = False
        else:
            if today_k["volume"] < 500 or today_k["5MA_Vol"] < 400:
                continue
            # 正飆
            y_ma_list = [pre_yesterday_k["5MA"], pre_yesterday_k["10MA"], pre_yesterday_k["20MA"]]
            y_spread = (max(y_ma_list) - min(y_ma_list)) / pre_yesterday_k["close"] if pre_yesterday_k["close"] > 0 else 99
            is_breakout = (y_spread <= 0.04 and yesterday_k["close"] > yesterday_k["open"] and yesterday_k["close"] > max(yesterday_k["5MA"], yesterday_k["10MA"], yesterday_k["20MA"]) and today_k["close"] >= max(today_k["5MA"], today_k["10MA"], today_k["20MA"]))
            # 起飆
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

    return grand_net_profit

def main():
    print("====================================================")
    print("🐬 海豚持股 AI 參數優化外掛：[個別自適應停利版] 啟動...")
    print("====================================================")
    
    if not os.path.exists(PORTFOLIO_FILE):
        print(f"❌ 找不到實戰記帳簿檔案 ({PORTFOLIO_FILE})")
        return
        
    df_pf = pd.read_csv(PORTFOLIO_FILE, dtype={"stock_id": str})
    if df_pf.empty:
        print("📭 記帳簿目前沒有任何持股。")
        return
        
    unique_stocks = df_pf["stock_id"].unique()
    print(f"📥 成功讀取現有持股：{list(unique_stocks)}，準備開啟 500 倍暴風平行運算...")
    
    api = DataLoader()
    api.login_by_token(api_token="eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9.eyJ1c2VyX2lkIjoicGNoaW9uMjAwMiIsImVtYWlsIjoibGFpZWNodW55dUBnbWFpbC5jb20iLCJ0b2tlbl92ZXJzaW9uIjowfQ.si_2Ta3AlY1JtgVBDlqpnkaK3IH41Drrc7ogVgNBJq8")
    
    # 定義窮舉範圍
    threshold_range = [t / 100 for t in range(5, 31)]       # 5% ~ 30%
    drop_range = [d / 200 for d in range(4, 21)]            # 2% ~ 10%
    
    # 用來儲存每隻股票算出來的最強黃金參數
    best_params_dict = {}
    
    for stock_id in unique_stocks:
        print(f"\n🔍 正在破解 {stock_id} 的歷史基因...")
        df_raw = api.taiwan_stock_daily(stock_id=stock_id, start_date=START_DATE, end_date=END_DATE)
        if df_raw.empty or len(df_raw) < 35:
            print(f"⚠️ {stock_id} 數據不足，跳過。")
            continue
            
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

        best_profit = -999999
        best_th = 0.15 # 預設防呆
        best_dr = 0.03 # 預設防呆
        
        for th in threshold_range:
            for dr in drop_range:
                profit = optimize_core(df, th, dr)
                if profit > best_profit:
                    best_profit = profit
                    best_th = th
                    best_dr = dr
                    
        print(f"🏆 {stock_id} 最佳解：獲利門檻 {best_th*100:.1f}%, 高點拉回 {best_dr*100:.1f}% | 歷史累積獲利: {best_profit} 元")
        best_params_dict[stock_id] = {"best_tp": best_th, "best_drop": best_dr}

    # 🎯 核心神級改造：把算出來的黃金參數，直接無傷寫回原本的持股 CSV！
    print("\n📝 正在把黃金密碼回寫至實戰記帳簿...")
    for idx, row in df_pf.iterrows():
        sid = row["stock_id"]
        if sid in best_params_dict:
            df_pf.at[idx, "best_tp"] = best_params_dict[sid]["best_tp"]
            df_pf.at[idx, "best_drop"] = best_params_dict[sid]["best_drop"]
            
    df_pf.to_csv(PORTFOLIO_FILE, index=False)
    print("====================================================")
    print("🏁 🏆 【優化完畢】原本的 CSV 持股已經成功升級為「自適應參數版」！")
    print("====================================================\n")

if __name__ == "__main__":
    main()
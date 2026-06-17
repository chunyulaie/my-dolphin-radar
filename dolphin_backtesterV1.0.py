import datetime
import logging
import os
import pandas as pd
from FinMind.data import DataLoader

# 徹底抑制後台警告
logging.getLogger('FinMind').setLevel(logging.CRITICAL)

# ==========================================
# 📊 【海豚量化多持股回測沙盒 · 參數設定區】
# ==========================================
START_DATE = "2025-06-01"   # 👉 回測起點 (完整一年的歷史時空模擬)
END_DATE = "2026-06-15"     # 👉 回測終點

SIM_BUDGET = 30000         # 每筆虛擬投入預算：30,000 元
TP_THRESHOLD = 0.15        # 方案A：獲利超過 15% 啟動移動鎖利
TP_TRAILING_DROP = 0.03    # 方案A：自波段高點拉回 3% 強制停利

FEE_RATE = 0.001425         
FEE_DISCOUNT = 0.28         # 券商手續費折讓（28折）
TAX_RATE = 0.003            
# 🎯 請改成你的 Windows 絕對路徑，前面記得加個 r 喔！
PORTFOLIO_FILE = r"D:\Python-Training\N100\海豚選股法\dolphin_portfolio.csv"

def backtest_one_stock(api, stock_id, stock_name):
    """核心連續回測引擎：負責幫單一標的跑完一整年的時空流動"""
    df_raw = api.taiwan_stock_daily(stock_id=stock_id, start_date=START_DATE, end_date=END_DATE)
    if df_raw.empty or len(df_raw) < 35:
        return 0, 0, 0 # 賺賠金額, 總交易次數, 勝次

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

    in_position = False
    buy_price = 0.0
    buy_shares = 0
    max_price_after_buy = 0.0
    
    s_profit = 0
    s_trades = 0
    s_wins = 0

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
            if max_profit_percent >= TP_THRESHOLD and current_close <= (max_price_after_buy * (1 - TP_TRAILING_DROP)):
                s_trades += 1
                if net_profit > 0: s_wins += 1
                s_profit += net_profit
                in_position = False
                
            # 月線鐵血停損
            elif today_k['20MA'] > 0 and current_close < today_k['20MA']:
                s_trades += 1
                if net_profit > 0: s_wins += 1
                s_profit += net_profit
                in_position = False

        else:
            if today_k["volume"] < 500 or today_k["5MA_Vol"] < 400:
                continue
            # 正飆股
            y_ma_list = [pre_yesterday_k["5MA"], pre_yesterday_k["10MA"], pre_yesterday_k["20MA"]]
            y_spread = (max(y_ma_list) - min(y_ma_list)) / pre_yesterday_k["close"] if pre_yesterday_k["close"] > 0 else 99
            is_breakout = (y_spread <= 0.04 and yesterday_k["close"] > yesterday_k["open"] and yesterday_k["close"] > max(yesterday_k["5MA"], yesterday_k["10MA"], yesterday_k["20MA"]) and today_k["close"] >= max(today_k["5MA"], today_k["10MA"], today_k["20MA"]))
            # 起飆股
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

    return s_profit, s_trades, s_wins

def main():
    print("====================================================")
    print("🐬 海豚投資組合回測沙盒：[全持股一次判定版] 啟動...")
    print("====================================================")
    
    if not os.path.exists(PORTFOLIO_FILE):
        print(f"❌ 找不到實戰記帳簿檔案 ({PORTFOLIO_FILE})，請確認檔案路徑。")
        return
        
    df_pf = pd.read_csv(PORTFOLIO_FILE, dtype={"stock_id": str})
    if df_pf.empty:
        print("📭 你的模擬記帳簿目前空空如也，沒有持股可以回測。")
        return
        
    # 去重，避免同檔股票重複回測
    unique_stocks = df_pf.drop_duplicates(subset=["stock_id"])
    print(f"📥 成功讀取實戰持股名單！偵測到 {len(unique_stocks)} 檔精兵進行大歷史檢驗。")
    print("⏳ 正在打通網路，向 FinMind 調閱完整一年的歷史數據庫...")
    
    api = DataLoader()
    # 🎯 使用完全乾淨的正牌登入通行證
    api.login_by_token(api_token="eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9.eyJ1c2VyX2lkIjoicGNoaW9uMjAwMiIsImVtYWlsIjoibGFpZWNodW55dUBnbWFpbC5jb20iLCJ0b2tlbl92ZXJzaW9uIjowfQ.si_2Ta3AlY1JtgVBDlqpnkaK3IH41Drrc7ogVgNBJq8")
    
    total_portfolio_profit = 0
    total_portfolio_trades = 0
    total_portfolio_wins = 0
    
    print("\n🎬 各個部位歷史戰況回放開始：")
    print("────────────────────────────────────────────────────")
    
    for idx, row in unique_stocks.iterrows():
        sid = row["stock_id"]
        sname = row["stock_name"]
        
        # 呼叫每檔股票的背景時空回測
        profit, trades, wins = backtest_one_stock(api, sid, sname)
        
        total_portfolio_profit += profit
        total_portfolio_trades += trades
        total_portfolio_wins += wins
        
        w_rate = (wins / trades * 100) if trades > 0 else 0.0
        sign = "+" if profit >= 0 else ""
        print(f"📈 標的: {sid} {sname:<5} | 總交易次數: {trades:>2} 次 | 勝率: {w_rate:>5.1f}% | 累積淨損益: {sign}{profit:>6} 元")
        
    print("────────────────────────────────────────────────────")
    print("====================================================")
    print("🏁 🏆 【海豚聯軍 · 全部位資產組合歷史回測總結報告】")
    print("====================================================")
    print(f"📅 模擬歷史區間：{START_DATE} ~ {END_DATE}")
    print(f"💰 每檔個股配置：固定投入台幣 {SIM_BUDGET} 元零股")
    print(f"🔄 聯軍總交易次數：{total_portfolio_trades} 次")
    
    if total_portfolio_trades > 0:
        portfolio_win_rate = (total_portfolio_wins / total_portfolio_trades) * 100
        print(f"🎯 投資組合總勝率：{portfolio_win_rate:.2f} %")
        sign = "+" if total_portfolio_profit >= 0 else ""
        print(f"💵 聯軍全數大加總（總淨賺賠）：{sign}{total_portfolio_profit} 元台幣")
    else:
        print("📭 殘念！這幾檔股票在過去一年的歷史中，完全沒有出現任何符合海豚邏輯的買點。")
    print("====================================================\n")

if __name__ == "__main__":
    main()
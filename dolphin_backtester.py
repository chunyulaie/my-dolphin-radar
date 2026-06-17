import datetime
import logging
import pandas as pd
from FinMind.data import DataLoader

# 徹底抑制後台警告
logging.getLogger('FinMind').setLevel(logging.CRITICAL)

# ==========================================
# 📊 【海豚量化歷史回測沙盒 · 參數設定區】
# ==========================================
BACKTEST_STOCK = "2330"     # 👉 想單獨回測的股票代號 (例如: 2368 金像電, 2027 大成鋼)
START_DATE = "2025-06-01"   # 👉 回測起點 (抓完整一年進行時空模擬)
END_DATE = "2026-06-15"     # 👉 回測終點

SIM_BUDGET = 30000         # 每筆虛擬投入預算：30,000 元
TP_THRESHOLD = 0.10        # 方案A：獲利超過 10% 啟動移動鎖利雷達
TP_TRAILING_DROP = 0.05    # 方案A：自波段高點拉回 5% 強制停利

FEE_RATE = 0.001425         
FEE_DISCOUNT = 0.28         # 你的券商手續費折讓（28折）
TAX_RATE = 0.003            

def run_single_stock_backtest():
    print("====================================================")
    print(f"🔬 海豚量化沙盒：股票 {BACKTEST_STOCK} 歷史連續回測啟動...")
    print(f"📅 回測區間：{START_DATE} ~ {END_DATE}")
    print("====================================================")
    
    # 串接 FinMind 下載一整年歷史數據
    api = DataLoader()
    api.login_by_token(api_token="eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9.eyJ1c2VyX2lkIjoicGNoaW9uMjAwMiIsImVtYWlsIjoibGFpZWNodW55dUBnbWFpbC5jb20iLCJ0b2tlbl92ZXJzaW9uIjowfQ.si_2Ta3AlY1JtgVBDlqpnkaK3IH41Drrc7ogVgNBJq8")
    
    df_raw = api.taiwan_stock_daily(stock_id=BACKTEST_STOCK, start_date=START_DATE, end_date=END_DATE)
    if df_raw.empty or len(df_raw) < 35:
        print("❌ 抓取歷史數據失敗或資料量不足，請檢查代號或日期。")
        return

    # 1. 工業級技術指標大陣列運算
    df = pd.DataFrame()
    df["date"] = df_raw["date"].astype(str)
    df["open"] = df_raw["open"].astype(float)
    df["close"] = df_raw["close"].astype(float)
    df["volume"] = df_raw["Trading_Volume"].astype(float) / 1000 
    
    df["5MA"] = df["close"].rolling(window=5).mean()
    df["10MA"] = df["close"].rolling(window=10).mean()
    df["20MA"] = df["close"].rolling(window=20).mean()
    df["5MA_Vol"] = df["volume"].rolling(window=5).mean()
    
    df['20STD'] = df['close'].rolling(window=20).std(ddof=0)
    df['BB_Upper'] = df['20MA'] + 2 * df['20STD']
    df['BB_Lower'] = df['20MA'] - 2 * df['20STD']
    df['BB_Width'] = (df['BB_Upper'] - df['BB_Lower']) / df['20MA']
    
    df['EMA12'] = df['close'].ewm(span=12, adjust=False).mean()
    df['EMA26'] = df['close'].ewm(span=26, adjust=False).mean()
    df['MACD'] = df['EMA12'] - df['EMA26']

    # 2. 初始化沙盒記憶體帳簿 (不影響現有 CSV 檔案)
    in_position = False
    buy_price = 0.0
    buy_date = ""
    buy_shares = 0
    max_price_after_buy = 0.0
    
    total_trades = 0
    win_trades = 0
    grand_net_profit = 0

    print("⏳ 正在穿越時空，逐日掃描指標與價格流動...")
    print("----------------------------------------------------")

    # 從第 35 天開始，一根一根 K 線模擬時間前進 (i 代表「回測當天」)
    for i in range(35, len(df)):
        today_k = df.iloc[i]
        yesterday_k = df.iloc[i-1]
        pre_yesterday_k = df.iloc[i-2] # 用來回溯起漲前一日
        
        current_close = today_k['close']
        current_date = today_k['date']

        # ── 💸 狀況 A：手上有部位，天天監控移動出場 ──
        if in_position:
            # 更新買進後的歷史最高收盤價
            if current_close > max_price_after_buy:
                max_price_after_buy = current_close
                
            # 計算當前考慮交易成本的真實損益
            buy_fee = int(buy_price * buy_shares * FEE_RATE * FEE_DISCOUNT)
            if buy_fee < 20: buy_fee = 20
            total_buy_spent = (buy_price * buy_shares) + buy_fee
            
            sell_fee = int(current_close * buy_shares * FEE_RATE * FEE_DISCOUNT)
            if sell_fee < 20: sell_fee = 20
            sell_tax = int(current_close * buy_shares * TAX_RATE)
            total_sell_get = (current_close * buy_shares) - sell_fee - sell_tax
            
            net_profit = int(total_sell_get - total_buy_spent)
            profit_percent = (net_profit / total_buy_spent) * 100
            
            # 檢查最大可能報酬率 (用歷史最高價算)
            max_profit_percent = ((max_price_after_buy - buy_price) / buy_price)
            
            # 1️⃣ 檢查是否觸發【方案A：高點拉回 5% 移動鎖利】
            if max_profit_percent >= TP_THRESHOLD and current_close <= (max_price_after_buy * (1 - TP_TRAILING_DROP)):
                sign = "+" if net_profit >= 0 else ""
                print(f"🎉 [時空鎖利] {current_date} 出場價: {current_close} (曾最高 {max_price_after_buy}) | 最終損益: {sign}{net_profit}元 ({sign}{profit_percent:.2f}%)")
                
                total_trades += 1
                if net_profit > 0: win_trades += 1
                grand_net_profit += net_profit
                in_position = False # 釋放部位，結算出場
                
            # 2️⃣ 檢查是否觸發【原本的鐵血月線停損】
            elif today_k['20MA'] > 0 and current_close < today_k['20MA']:
                sign = "+" if net_profit >= 0 else ""
                print(f"⚠️ [時空停損] {current_date} 出場價: {current_close} (跌破20MA {today_k['20MA']:.2f}) | 最終損益: {sign}{net_profit}元 ({sign}{profit_percent:.2f}%)")
                
                total_trades += 1
                if net_profit > 0: win_trades += 1
                grand_net_profit += net_profit
                in_position = False # 釋放部位，結算出場

        # ── 🛒 狀況 B：手上沒部位，每天雷達伺候尋找買點 ──
        else:
            # 雙重成交量基本過關門檻
            if today_k["volume"] < 500 or today_k["5MA_Vol"] < 400:
                continue
                
            # 判斷流派二：【海豚正飆股(0天剛發動)】
            y_ma_list = [pre_yesterday_k["5MA"], pre_yesterday_k["10MA"], pre_yesterday_k["20MA"]]
            y_spread = (max(y_ma_list) - min(y_ma_list)) / pre_yesterday_k["close"] if pre_yesterday_k["close"] > 0 else 99
            
            cond_was_compressed = y_spread <= 0.04
            cond_red_k = yesterday_k["close"] > yesterday_k["open"]
            cond_breakout = yesterday_k["close"] > max(yesterday_k["5MA"], yesterday_k["10MA"], yesterday_k["20MA"])
            
            is_breakout_active = (cond_was_compressed and cond_red_k and cond_breakout and today_k["close"] >= max(today_k["5MA"], today_k["10MA"], today_k["20MA"]))
            
            # 判斷流派一：【3星起飆股】
            is_ambush_3star = False
            if not is_breakout_active:
                if today_k["5MA"] >= today_k["10MA"] >= today_k["20MA"]:
                    t_ma_list = [today_k["5MA"], today_k["10MA"], today_k["20MA"]]
                    t_spread = (max(t_ma_list) - min(t_ma_list)) / today_k["20MA"]
                    if t_spread <= 0.035:
                        star_count = 1
                        if today_k["BB_Width"] <= 0.18: star_count += 1
                        if today_k["MACD"] > 0: star_count += 1
                        if star_count == 3:
                            is_ambush_3star = True
            
            # 🎯 只要符合任一流派，當天收盤直接模擬定額 3 萬元建倉
            if is_breakout_active or is_ambush_3star:
                in_position = True
                buy_price = current_close
                buy_date = current_date
                buy_shares = int(SIM_BUDGET // current_close)
                max_price_after_buy = current_close
                b_type = "正飆股(0天)" if is_breakout_active else "3星起飆股"
                
                if buy_shares > 0:
                    print(f"🛒 [時空買進] {buy_date} 價格: {buy_price} | 類型: {b_type} | 成功購買 {buy_shares} 股")

    # 3. 輸出終極數據回測結算報表
    print("----------------------------------------------------")
    print("====================================================")
    print(f"📊 🏁 【海豚選股策略 · 歷史量化回測結算報告】")
    print("====================================================")
    print(f"📈 測試標的：{BACKTEST_STOCK}")
    print(f"🔄 總交易次數：{total_trades} 次")
    if total_trades > 0:
        win_rate = (win_trades / total_trades) * 100
        print(f"🎯 獲利勝率：{win_rate:.2f} %")
        sign = "+" if grand_net_profit >= 0 else ""
        print(f"💰 累積淨賺賠 (扣除全部手續費證交稅)：{sign}{grand_net_profit} 元台幣")
    else:
        print("📭 在此回測區間內，該股無任何符合海豚定義的起漲買點。")
    print("====================================================\n")

if __name__ == "__main__":
    run_single_stock_backtest()
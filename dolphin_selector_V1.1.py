import datetime
import time
import pandas as pd
from FinMind.data import DataLoader

# 初始化免費的 DataLoader
api = DataLoader()

# ==========================================
# 4.0 版：地獄級嚴苛參數設定區
# ==========================================
MA_SPREAD_LIMIT = 0.020  # 【嚴格】均線糾結度壓低到 2.0% 以內 (極致壓縮)
BUY_DAYS_NEEDED = 4      # 【嚴格】近 5 個交易日中，法人必須買超 4 天以上 (強烈連續性)
VOLUME_FILTER = 1000     # 【新增】最新一天成交量必須大於 1000 張 (踢除無流動性的殭屍股)


def check_chip_and_tech_strict(stock_id):
    """一網打盡版：同時嚴格檢查籌碼面與技術面，不符合立刻 Fail-Fast"""
    
    # 0. 踢除 ETF 的防禦邏輯
    if stock_id.startswith("00"):
        return False, "剔除 ETF"

    end_date = datetime.date.today().strftime("%Y-%m-%d")
    start_date = (datetime.date.today() - datetime.timedelta(days=60)).strftime("%Y-%m-%d")

    try:
        # 一次性把日K資料撈回來
        df_k = api.taiwan_stock_daily(stock_id=stock_id, start_date=start_date, end_date=end_date)
        if df_k.empty or len(df_k) < 20:
            return False, "K線資料不足"

        latest_k = df_k.iloc[-1]
        
        # 條件一：流動性檢查 (最新一天成交量低於設定張數就淘汰)
        # 註：FinMind 的 trading_volume 單位通常是股數，所以要除以 1000 變成張數
        latest_volume_sheets = latest_k["Trading_Volume"] / 1000
        if latest_volume_sheets < VOLUME_FILTER:
            return False, f"流動性不足 ({int(latest_volume_sheets)}張 < {VOLUME_FILTER}張)"

        # 條件二：技術面 - 均線極致糾結 (5MA, 10MA, 20MA)
        df_k["5MA"] = df_k["close"].rolling(window=5).mean()
        df_k["10MA"] = df_k["close"].rolling(window=10).mean()
        df_k["20MA"] = df_k["close"].rolling(window=20).mean()

        latest_ma = df_k.iloc[-1]
        ma_list = [latest_ma["5MA"], latest_ma["10MA"], latest_ma["20MA"]]
        spread = (max(ma_list) - min(ma_list)) / latest_ma["close"]

        if spread > MA_SPREAD_LIMIT:
            return False, f"技術面未過 (糾結度 {spread*100:.2f}% > {MA_SPREAD_LIMIT*100}%)"

        # 條件三：籌碼面 - 法人連續強烈吃貨
        df_chip = api.taiwan_stock_institutional_investors(stock_id=stock_id, start_date=start_date, end_date=end_date)
        if df_chip.empty:
            return False, "無法人籌碼資料"

        df_target = df_chip[df_chip["name"].isin(["Foreign_Investor", "Investment_Trust"])].copy()
        if df_target.empty:
            return False, "無外資投信交易"

        df_daily = df_target.groupby("date")[["buy", "sell"]].sum().reset_index()
        df_daily["net_buy"] = df_daily["buy"] - df_daily["sell"]
        df_daily = df_daily.sort_values("date").tail(5)

        if len(df_daily) < 5:
            return False, "籌碼天數不足"

        buy_days = (df_daily["net_buy"] > 0).sum()
        latest_net = df_daily.iloc[-1]["net_buy"]

        # 必須符合買超天數，且最新一天大戶還在買
        if buy_days < BUY_DAYS_NEEDED or latest_net <= 0:
            return False, f"籌碼未過 (近5日僅買超 {buy_days} 天)"

        return True, f"🎯 完美過關！糾結度: {spread*100:.2f}%, 近5日買超 {buy_days} 天, 成交量: {int(latest_volume_sheets)}張"

    except Exception as e:
        return False, f"檢查出錯: {e}"


# ==========================================
# 主程式執行流
# ==========================================
if __name__ == "__main__":
    print("====================================================")
    print("🚀 海豚選股 4.0：[地獄級嚴苛過濾] 雙重指標啟動...")
    print("====================================================")

    # 這裡繼續沿用你的測試清單 (1101~1524 左右)
    # 假設你已經從 get_all_taiwan_stock_ids() 拿到 stock_list
    # 為了方便示範，我讓它自動去抓
    try:
        df_info = api.taiwan_stock_info()
        df_info["stock_id"] = df_info["stock_id"].astype(str).str.strip()
        df_filtered = df_info[(df_info["stock_id"].str.len() == 4) & (df_info["stock_id"].str.isdigit())]
        STOCK_POOL = sorted(list(df_filtered["stock_id"].unique()))[:150] # 依然是你的前150檔
    except:
        STOCK_POOL = ["1101", "1102", "1216", "2330"] # 備用

    print(f"📋 載入目標清單共: {len(STOCK_POOL)} 檔個股")
    
    selected_stocks = []
    
    for stock in STOCK_POOL:
        is_passed, msg = check_chip_and_tech_strict(stock)
        
        # 只有真正過關的股票才印出詳細訊息，其餘默默跳過
        if is_passed:
            print(f"\n🔥 發現黃金標的：【{stock}】")
            print(f"   {msg}")
            print("-" * 52)
            selected_stocks.append(stock)
            time.sleep(1)

    print("\n====================================================")
    print("🎉 【地獄級篩選結束】")
    print(f"💡 最終符合「大戶強烈吃貨 + 均線極致壓縮 + 有成交量」的黃金清單：{selected_stocks}")
    print("====================================================")
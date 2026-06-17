import datetime
import time
import pandas as pd
from FinMind.data import DataLoader

# 初始化免費的 DataLoader
api = DataLoader()

# ==========================================
# 設定區：填入你想掃描的台股口袋名單
# ==========================================
STOCK_POOL = ["2330", "2317", "2603", "2609", "3231", "2356", "2382", "2454"]
MA_SPREAD_LIMIT = 0.035  # 均線糾結度限制在 3.5% 以內


def check_chip_institutional_investors(stock_id):
    """【籌碼面】檢查近 5 天內，外資或投信是否合計連續買超大於 3 天"""
    end_date = datetime.date.today().strftime("%Y-%m-%d")
    start_date = (datetime.date.today() - datetime.timedelta(days=15)).strftime(
        "%Y-%m-%d"
    )

    try:
        # 撈取三大法人買賣超資料
        df_chip = api.taiwan_stock_institutional_investors(
            stock_id=stock_id, start_date=start_date, end_date=end_date
        )

        if df_chip.empty:
            return False, "無法人籌碼資料"

        # 篩選外資與投信
        df_target = df_chip[
            df_chip["name"].isin(["Foreign_Investor", "Investment_Trust"])
        ].copy()

        if df_target.empty:
            return False, "近幾日無外資或投信交易紀錄"

        # 【修正後的正確寫法】先用 groupby 求每日買賣總和，再轉成 DataFrame 計算淨買超
        df_daily = df_target.groupby("date")[["buy", "sell"]].sum().reset_index()
        df_daily["net_buy"] = df_daily["buy"] - df_daily["sell"]
        
        # 取最近 5 個交易日
        df_daily = df_daily.sort_values("date").tail(5)

        if len(df_daily) < 3:
            return False, "籌碼交易天數不足"

        # 計算最近 5 天有幾天是買超 (net_buy > 0)
        buy_days = (df_daily["net_buy"] > 0).sum()
        latest_net = df_daily.iloc[-1]["net_buy"]

        # 籌碼過關條件：近5天法人買超天數 >= 3天，且最新一天是買超
        if buy_days >= 3 and latest_net > 0:
            return (
                True,
                f"👍 籌碼過關！近5日法人買超 {buy_days} 天，主力默默吃貨中。",
            )
        else:
            return False, f"👎 籌碼淘汰。近5日法人僅買超 {buy_days} 天。"

    except Exception as e:
        return False, f"💥 籌碼檢查失敗: {e}"


def check_technical_analysis(stock_id):
    """【技術面】檢查短中期均線糾結度 (5MA, 10MA, 20MA)"""
    end_date = datetime.date.today().strftime("%Y-%m-%d")
    start_date = (datetime.date.today() - datetime.timedelta(days=60)).strftime(
        "%Y-%m-%d"
    )

    try:
        # 撈取日K線資料
        df_k = api.taiwan_stock_daily(
            stock_id=stock_id, start_date=start_date, end_date=end_date
        )

        if df_k.empty or len(df_k) < 20:
            return False, "K線資料不足"

        # 計算移動平均線
        df_k["5MA"] = df_k["close"].rolling(window=5).mean()
        df_k["10MA"] = df_k["close"].rolling(window=10).mean()
        df_k["20MA"] = df_k["close"].rolling(window=20).mean()

        latest = df_k.iloc[-1]
        close_price = latest["close"]

        ma_list = [latest["5MA"], latest["10MA"], latest["20MA"]]
        spread = (max(ma_list) - min(ma_list)) / close_price

        msg = f"收盤價: {close_price} | 三線糾結度: {spread*100:.2f}%"

        if spread <= MA_SPREAD_LIMIT:
            return True, f"👍 技術面過關！{msg}"
        else:
            return False, f"👎 技術面淘汰。波動過大，{msg}"

    except Exception as e:
        return False, f"💥 技術面檢查失敗: {e}"


# ==========================================
# 主程式執行流
# ==========================================
if __name__ == "__main__":
    print("====================================================")
    print("🚀 海豚選股完全體：[籌碼面 + 技術面] 雙重濾網啟動...")
    print("====================================================")

    selected_stocks = []

    for stock in STOCK_POOL:
        print(f"🔍 正在嚴檢個股：【{stock}】")

        # 第一關：檢查籌碼面 (法人吃貨)
        chip_pass, chip_msg = check_chip_institutional_investors(stock)
        print(f"   [籌碼] {chip_msg}")

        # 第二關：籌碼過了才檢查技術面 (均線糾結)
        if chip_pass:
            tech_pass, tech_msg = check_technical_analysis(stock)
            print(f"   [技術] {tech_msg}")

            if tech_pass:
                print(f"🎯 恭喜！【{stock}】雙重指標完美符合海豚選股法！")
                selected_stocks.append(stock)

        print("-" * 52)
        time.sleep(2)  # 免費版 API 防護冷卻

    print("\n🎉 【全自動雙重篩選結束】")
    print(f"💡 最終符合「大戶吃貨 + 均線糾結」的潛在飆股：{selected_stocks}")
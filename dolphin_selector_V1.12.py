import datetime
import time
import requests
import pandas as pd
from FinMind.data import DataLoader

# 初始化免費的 DataLoader
api = DataLoader()

# ==========================================
# 6.2 完全體參數設定區 (平衡實戰版)
# ==========================================
MA_SPREAD_LIMIT = 0.020  # 均線糾結度 2.0% 以內 (極致壓縮)
BUY_DAYS_NEEDED = 3      # 🎯 調整回更符合實戰的 3 天 (近5日法人買超天數)
VOLUME_FILTER = 1000     # 最新成交量大於 1000 張


def get_all_taiwan_stock_ids_from_official():
    """【全自動清單】自動爬取最新的完整上市櫃 4 碼純股票"""
    try:
        twse_url = "https://isin.twse.com.tw/isin/C_public.jsp?strMode=2"
        tpex_url = "https://isin.twse.com.tw/isin/C_public.jsp?strMode=4"
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
        
        stock_ids = []
        for url in [twse_url, tpex_url]:
            res = requests.get(url, headers=headers, timeout=10)
            res.encoding = 'big5'
            dfs = pd.read_html(res.text)
            df = dfs[0]
            df.columns = df.iloc[0]
            df = df.iloc[1:]
            
            for raw_name in df['有價證券代號及名稱'].dropna().tolist():
                parts = raw_name.split()
                if len(parts) >= 1:
                    code = parts[0].strip()
                    if len(code) == 4 and code.isdigit():
                        stock_ids.append(code)
                        
        stock_ids = sorted(list(set(stock_ids)))
        print(f"📋 【載入成功】已自動獲取全台股共 {len(stock_ids)} 檔有效純股票標的！")
        return stock_ids
    except Exception as e:
        print("💥 抓取官方全市場清單致命失敗！請檢查網路。")
        raise e


def check_technical_via_official(stock_id):
    """【第一階段】高速過濾技術面與流動性，失敗直接 Fail-Fast"""
    current_month = datetime.date.today().strftime("%Y%m%d")
    if datetime.date.today().day < 5:
        current_month = (datetime.date.today() - datetime.timedelta(days=10)).strftime("%Y%m") + "01"
        
    url = f"https://www.twse.com.tw/exchangeReport/STOCK_DAY?response=json&date={current_month}&stockNo={stock_id}"
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}

    try:
        response = requests.get(url, headers=headers, timeout=4)
        data = response.json()
        if "data" not in data or not data["data"]:
            return False, 0, 0

        raw_df = pd.DataFrame(data["data"])
        df = pd.DataFrame()
        df["close"] = raw_df[6].str.replace(",", "").astype(float, errors="ignore")
        df["volume"] = raw_df[1].str.replace(",", "").astype(float, errors="ignore") / 1000 

        if len(df) < 20:
            return False, 0, 0

        latest_k = df.iloc[-1]
        if latest_k["volume"] < VOLUME_FILTER:
            return False, 0, 0

        df["5MA"] = df["close"].rolling(window=5).mean()
        df["10MA"] = df["close"].rolling(window=10).mean()
        df["20MA"] = df["close"].rolling(window=20).mean()

        latest_ma = df.iloc[-1]
        ma_list = [latest_ma["5MA"], latest_ma["10MA"], latest_ma["20MA"]]
        spread = (max(ma_list) - min(ma_list)) / latest_ma["close"]

        if spread <= MA_SPREAD_LIMIT:
            return True, spread, latest_k["volume"]
        return False, 0, 0
    except:
        return False, 0, 0


def check_chip_via_finmind(stock_id):
    """【第二階段】精准籌碼比對"""
    end_date = datetime.date.today().strftime("%Y-%m-%d")
    start_date = (datetime.date.today() - datetime.timedelta(days=60)).strftime("%Y-%m-%d")

    try:
        df_chip = api.taiwan_stock_institutional_investors(stock_id=stock_id, start_date=start_date, end_date=end_date)
        if df_chip.empty:
            return False

        df_target = df_chip[df_chip["name"].isin(["Foreign_Investor", "Investment_Trust"])].copy()
        if df_target.empty:
            return False

        df_daily = df_target.groupby("date")[["buy", "sell"]].sum().reset_index()
        df_daily["net_buy"] = df_daily["buy"] - df_daily["sell"]
        df_daily = df_daily.sort_values("date").tail(5)

        buy_days = (df_daily["net_buy"] > 0).sum()
        latest_net = df_daily.iloc[-1]["net_buy"]

        if buy_days >= BUY_DAYS_NEEDED and latest_net > 0:
            return True
        return False
    except:
        return False


# ==========================================
# 主程式執行流
# ==========================================
if __name__ == "__main__":
    print("====================================================")
    print("🚀 海豚選股 6.2：[極靜流·平衡實戰版] 雙濾網啟動...")
    print("====================================================")

    ALL_MARKET_POOL = get_all_taiwan_stock_ids_from_official()
    
    # 🎯 你的 600 檔測試池。如果要衝全市場，直接把 [:600] 刪掉即可！
    STOCK_POOL = ALL_MARKET_POOL[:600]
    print(f"⚡ 測試模式：正在無聲清洗前 {len(STOCK_POOL)} 檔個股...")
    print("----------------------------------------------------")

    tech_passed_pool = []
    count = 0
    
    for stock in STOCK_POOL:
        count += 1
        is_tech_ok, spread, vol = check_technical_via_official(stock)
        
        if is_tech_ok:
            tech_passed_pool.append((stock, spread, vol))
            
        # 覆寫單行進度，絕不刷屏
        if count % 20 == 0 or count == len(STOCK_POOL):
            print(f"⏳ Phase 1 技術篩選進度: {count}/{len(STOCK_POOL)} 檔...", end="\r")
            
        time.sleep(0.15)

    print(f"\n✅ Phase 1 結束：從 {len(STOCK_POOL)} 檔中篩出 {len(tech_passed_pool)} 檔技術面合格股。")
    print("⏳ Phase 2 籌碼深度比對中 (已開啟強效靜音流)...")
    print("----------------------------------------------------")

    final_gold_list = []

    for stock, spread, vol in tech_passed_pool:
        is_chip_ok = check_chip_via_finmind(stock)
        
        # 🎯 徹底移除 ❌ 訊息！淘汰的股票完全不 print，直接 pass，不製造焦慮！
        if is_chip_ok:
            print(f"🔥 【{stock}】完美過關！糾結度: {spread*100:.2f}%, 今日成交: {int(vol)}張")
            print("   👉 符合大戶強烈吃貨 + 均線極致壓縮，請加入自選監控帶量突破！")
            print("-" * 52)
            final_gold_list.append(stock)
            
        # 為了避開 FinMind 免費版頻率黑名單，每查一檔籌碼安穩睡 1 秒
        time.sleep(1)

    print("\n====================================================")
    print("🎉 【全自動選股流程結束】")
    print(f"🎯 最終精選「真·黃金飆股」清單：{final_gold_list}")
    print("====================================================")
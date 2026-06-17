import asyncio
import datetime
import logging
import os
import time
import requests
from FinMind.data import DataLoader
import pandas as pd
from pyppeteer import launch

# 徹底抑制所有後台警告與 Log
logging.getLogger('pyppeteer').setLevel(logging.CRITICAL)
logging.getLogger('websockets').setLevel(logging.CRITICAL)
logging.getLogger('FinMind').setLevel(logging.CRITICAL)
try:
    import loguru
    loguru.logger.remove()
except:
    pass

# ==========================================
# 25.7 參數設定區 (量能純度·自動模擬記帳完全體)
# ==========================================
VOLUME_FILTER = 500        # 單日成交量基本防線：500 張
VOLUME_5MA_FILTER = 400    # 【量能純度防線】5日平均成交量需 > 400 張

# 🎯 流派一：【起飆股】(左側壓縮埋伏) 
MA_SPREAD_LIMIT = 0.035    # 均線糾結度 3.5% 以內
BB_COMPRESS_LIMIT = 0.18   # 布林通道壓縮防線 (18%以內)

# 🚀 流派二：【真·海豚正飆股】(大市值相容版) 
WAS_COMPRESSED_LIMIT = 0.04 # 起漲前一日糾結度需 <= 4%
LOOKBACK_WINDOW = 5         # 時空回溯天數

# 📊 【台股模擬交易成本設定】
FEE_RATE = 0.001425         # 法定手續費率 0.1425%
FEE_DISCOUNT = 0.28         # 👉 你的券商手續費折讓（例如：28折。若無折讓請設 1.0）
TAX_RATE = 0.003            # 證交稅率 0.3%
PORTFOLIO_FILE = "dolphin_portfolio.csv" # 模擬帳戶存檔名稱

# 🎯【LINE Messaging API 設定】
LINE_ACCESS_TOKEN = 'uyt/NqkAS3yCOhUAWGqey5HYGBe5mfct1n5MB1OQaV8Y1/X8HoypqNBwq/LOVXk5YnCknVCi8LEE5KZTXkbXT2V0CpOCAk0C/YRPJRA3Z2RREefQjAG41UQV0pbp1YQCnewazDskTwrpBsxHwRo4OQdB04t89/1O/w1cDnyilFU='
TARGET_USER_ID = 'Uf8818996f2c5846640e0ae8ae0360a72'

URL_1000_SHARES = "https://norway.twsthr.info/StockHoldersContinue.aspx?Show=1&continue=Y&weeks=4&growthrate=2&beforeweek=8&price=5000&valuerank=1-3000&display=0"
URL_400_SHARES  = "https://norway.twsthr.info/StockHoldersContinue.aspx?Show=2&continue=Y&weeks=4&growthrate=2&beforeweek=8&price=5000&valuerank=1-3000&display=0"

def calculate_costs(price, shares=1000):
    """計算買入與預估賣出的精確手續費與證交稅"""
    total_value = price * shares
    # 買入手續費 (未滿20元以20元計)
    buy_fee = int(total_value * FEE_RATE * FEE_DISCOUNT)
    if buy_fee < 20: buy_fee = 20
    # 預估賣出手續費
    sell_fee = int(total_value * FEE_RATE * FEE_DISCOUNT)
    if sell_fee < 20: sell_fee = 20
    # 預估證交稅
    sell_tax = int(total_value * TAX_RATE)
    
    total_cost = buy_fee + sell_fee + sell_tax
    return total_cost, buy_fee

def update_and_print_portfolio(api, today_str):
    """讀取帳戶、抓取今日最新收盤價，計算並列印出所有模擬持股的現況損益"""
    if not os.path.exists(PORTFOLIO_FILE):
        print("💼 [模擬帳戶] 目前尚無歷史模擬部位。")
        return ""
    
    print("\n====================================================")
    print("💼 📊 【海豚選股 · 模擬帳戶當前資產即時回報】")
    print("====================================================")
    
    df_pf = pd.read_csv(PORTFOLIO_FILE, dtype={"stock_id": str})
    if df_pf.empty:
        print("💼 [模擬帳戶] 目前帳戶內無任何股票。")
        return ""
    
    report_p_rows = []
    
    for idx, row in df_pf.iterrows():
        sid = row["stock_id"]
        sname = row["stock_name"]
        b_date = row["buy_date"]
        b_price = float(row["buy_price"])
        b_type = row["buy_type"]
        
        # 抓取這檔股票今天的最新收盤價
        try:
            df_now = api.taiwan_stock_daily(stock_id=sid, start_date=today_str, end_date=today_str)
            if not df_now.empty:
                current_price = float(df_now.iloc[-1]["close"])
            else:
                current_price = b_price # 沒開盤或抓不到時維持原價
        except:
            current_price = b_price
            
        # 計算現值與成本損益
        shares = 1000
        total_buy_spent = (b_price * shares) + int(max(20, (b_price * shares * FEE_RATE * FEE_DISCOUNT)))
        
        # 估算若今天以最新價賣出的總回收金額 (扣掉賣出手續費與證交稅)
        sell_fee = int(current_price * shares * FEE_RATE * FEE_DISCOUNT)
        if sell_fee < 20: sell_fee = 20
        sell_tax = int(current_price * shares * TAX_RATE)
        total_sell_get = (current_price * shares) - sell_fee - sell_tax
        
        # 淨損益
        net_profit = int(total_sell_get - total_buy_spent)
        profit_percent = (net_profit / total_buy_spent) * 100
        
        sign = "+" if net_profit >= 0 else ""
        color_stars = "📈" if net_profit >= 0 else "📉"
        
        p_msg = f"{color_stars} {sid} {sname} | 買入: {b_price} ({b_type}) -> 現價: {current_price} | 損益: {sign}{net_profit}元 ({sign}{profit_percent:.2f}%)"
        print(p_msg)
        report_p_rows.append(p_msg)
        
    print("====================================================\n")
    return "\n💼 【模擬部位當前淨損益回報】:\n" + "\n".join(report_p_rows) if report_p_rows else ""

def send_line_notify(message):
    url = 'https://api.line.me/v2/bot/message/push'
    headers = { 'Content-Type': 'application/json', 'Authorization': f'Bearer {LINE_ACCESS_TOKEN}' }
    payload = {'to': TARGET_USER_ID, 'messages': [{'type': 'text', 'text': message}]}
    try:
        requests.post(url, headers=headers, json=payload)
        print("📲 [系統通知] LINE 戰報推播成功！")
    except:
        pass

async def parse_page_codes(page, url, label):
    try:
        await page.goto(url, {'waitUntil': 'networkidle2', 'timeout': 30000})
        await asyncio.sleep(2) 
        codes = await page.evaluate('''() => {
            const rows = document.querySelectorAll('#details > tbody > tr');
            const result = [];
            rows.forEach(row => {
                const aTag = row.querySelector('a'); 
                const latestPercentTag = row.querySelector('td:nth-child(7) font p'); 
                if (aTag && latestPercentTag) {
                    const fullText = aTag.innerText ? aTag.innerText.trim() : "";
                    const percentText = latestPercentTag.innerText ? latestPercentTag.innerText.trim() : "0";
                    if (fullText.length >= 4) {
                        const potentialCode = fullText.substring(0, 4);
                        if (!isNaN(potentialCode) && potentialCode.trim().length === 4 && parseFloat(percentText) >= 50.0) {
                            result.push(potentialCode);
                        }
                    }
                }
            });
            return result;
        }''')
        print(f"📥 [{label}] 前端大戶篩選完成。")
        return set(codes)
    except:
        return set()

async def fetch_union_pyramid_pool():
    print("🌐 正在背景啟動 Chromium 無頭瀏覽器...")
    browser = await launch(headless=True, userDataDir='./pyppeteer_cache', args=['--no-sandbox', '--disable-setuid-sandbox'])
    try:
        page = await browser.newPage()
        await page.setUserAgent("Mozilla/5.0 (Windows NT 10.0; Win64; x64)")
        pool_1000 = await parse_page_codes(page, URL_1000_SHARES, "4週千張·核心大戶")
        pool_400 = await parse_page_codes(page, URL_400_SHARES, "4週四百張·波段主力")
        await browser.close()
        union_pool = sorted(list(pool_1000.union(pool_400)))
        print(f"🎯 絕對控盤大聯軍總數：{len(union_pool)} 檔\n")
        return union_pool
    except:
        return []

async def main():
    print("====================================================")
    print("🚀 海豚選股 25.7：[自動模擬記帳·完全體] 啟動...")
    print("====================================================")

    STOCK_POOL = await fetch_union_pyramid_pool()
    if not STOCK_POOL: return

    api = DataLoader()
    api.login_by_token(api_token="eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9.eyJ1c2VyX2lkIjoicGNoaW9uMjAwMiIsImVtYWlsIjoibGFpZWNodW55dUBnbWFpbC5jb20iLCJ0b2tlbl92ZXJzaW9uIjowfQ.si_2Ta3AlY1JtgVBDlqpnkaK3IH41Drrc7ogVgNBJq8")
    
    try:
        df_info = api.taiwan_stock_info()
        dynamic_name_dict = dict(zip(df_info["stock_id"], df_info["stock_name"]))
    except:
        dynamic_name_dict = {}

    today_str = datetime.date.today().strftime("%Y-%m-%d")
    start_str = (datetime.date.today() - datetime.timedelta(days=120)).strftime("%Y-%m-%d")

    print("⏳ 正在啟動時空回溯雷達，掃描海豚大聯軍...")
    print("----------------------------------------------------")
    
    raw_ambush_data = []
    raw_breakout_data = []
    
    # 讀取現有的模擬持股清單，避免重複買入同一隻股票
    sim_purchased_stocks = []
    if os.path.exists(PORTFOLIO_FILE):
        try:
            df_exist = pd.read_csv(PORTFOLIO_FILE, dtype={"stock_id": str})
            sim_purchased_stocks = df_exist["stock_id"].tolist()
        except:
            pass

    new_sim_buys = [] # 儲存今天新符合模擬買入資格的個股

    for stock in STOCK_POOL:
        try:
            c_name = dynamic_name_dict.get(stock, "")
            if "*" in c_name: continue

            df_raw = api.taiwan_stock_daily(stock_id=stock, start_date=start_str, end_date=today_str)
            if df_raw.empty or len(df_raw) < 35: continue
            
            display_title = f"{stock} {c_name}".strip() if c_name else stock
            
            df = pd.DataFrame()
            df["open"] = df_raw["open"].astype(float)
            df["close"] = df_raw["close"].astype(float)
            df["volume"] = df_raw["Trading_Volume"].astype(float) / 1000 
            
            if df.iloc[-1]["close"] == 0: continue

            # --- 技術指標運算 ---
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

            # 雙重成交量篩選
            if df.iloc[-1]["volume"] < VOLUME_FILTER or df.iloc[-1]["5MA_Vol"] < VOLUME_5MA_FILTER:
                continue

            latest_close = df.iloc[-1]["close"]

            # -------------------------------------------
            # 🚀 階段一：時空回溯判定【正飆股】
            # -------------------------------------------
            triggered_days_ago = None
            bo_spread = 0.0
            bo_bb = 0.0
            
            for i in range(1, LOOKBACK_WINDOW + 1):
                idx_today = -i
                idx_yesterday = -(i + 1)
                if len(df) + idx_yesterday < 0: break
                    
                t_close = df.iloc[idx_today]["close"]
                t_open = df.iloc[idx_today]["open"]
                t_5ma = df.iloc[idx_today]["5MA"]
                t_10ma = df.iloc[idx_today]["10MA"]
                t_20ma = df.iloc[idx_today]["20MA"]
                
                y_5ma = df.iloc[idx_yesterday]["5MA"]
                y_10ma = df.iloc[idx_yesterday]["10MA"]
                y_20ma = df.iloc[idx_yesterday]["20MA"]
                y_close = df.iloc[idx_yesterday]["close"]
                
                if y_close == 0: continue
                
                y_ma_list = [y_5ma, y_10ma, y_20ma]
                y_spread = (max(y_ma_list) - min(y_ma_list)) / y_close
                cond_was_compressed = y_spread <= WAS_COMPRESSED_LIMIT
                
                cond_red_k = t_close > t_open
                cond_breakout = t_close > max(t_5ma, t_10ma, t_20ma)
                
                if cond_was_compressed and cond_red_k and cond_breakout:
                    triggered_days_ago = i - 1
                    t_ma_list = [t_5ma, t_10ma, t_20ma]
                    bo_spread = (max(t_ma_list) - min(t_ma_list)) / t_close
                    bo_bb = df.iloc[idx_today]["BB_Width"]
                    break 
            
            is_breakout_active = False
            
            if triggered_days_ago is not None:
                if df.iloc[-1]["close"] >= max(df.iloc[-1]["5MA"], df.iloc[-1]["10MA"], df.iloc[-1]["20MA"]):
                    raw_breakout_data.append({
                        "stock_id": stock, "stock_name": c_name,
                        "title": display_title, "days_ago": triggered_days_ago,
                        "spread": bo_spread, "bb": bo_bb, "close": latest_close
                    })
                    is_breakout_active = True 
                    
                    # 🎯 條件A：【今天剛發動的正飆股】自動寫入模擬買入清單
                    if triggered_days_ago == 0 and stock not in sim_purchased_stocks:
                        new_sim_buys.append({"stock_id": stock, "stock_name": c_name, "buy_price": latest_close, "buy_type": "正飆股(0天)"})

            # -------------------------------------------
            # 🎯 階段二：今日狀態判定【起飆股】
            # -------------------------------------------
            if not is_breakout_active:
                f_5ma = df.iloc[-1]["5MA"]
                f_10ma = df.iloc[-1]["10MA"]
                f_20ma = df.iloc[-1]["20MA"]
                
                if f_5ma >= f_10ma >= f_20ma:
                    today_ma_list = [f_5ma, f_10ma, f_20ma]
                    today_spread = (max(today_ma_list) - min(today_ma_list)) / f_20ma
                    bb_width = df.iloc[-1]["BB_Width"]
                    macd_val = df.iloc[-1]["MACD"]
                    
                    if today_spread <= MA_SPREAD_LIMIT:
                        star_count = 1
                        if bb_width <= BB_COMPRESS_LIMIT: star_count += 1
                        if macd_val > 0: star_count += 1
                        
                        raw_ambush_data.append({
                            "stock_id": stock, "stock_name": c_name,
                            "stars": "⭐" * star_count, "title": display_title,
                            "spread": today_spread, "bb": bb_width, "macd": "水上" if macd_val > 0 else "水下", "close": latest_close
                        })
                        
                        # 🎯 條件B：【符合3顆星的起飆股】自動寫入模擬買入清單
                        if star_count == 3 and stock not in sim_purchased_stocks:
                            new_sim_buys.append({"stock_id": stock, "stock_name": c_name, "buy_price": latest_close, "buy_type": "3星起飆股"})
                
        except Exception as e:
            pass
        time.sleep(0.03)

    # ====================================================
    # 💾 模擬帳戶新交易寫入區
    # ====================================================
    if new_sim_buys:
        df_new = pd.DataFrame(new_sim_buys)
        df_new["buy_date"] = today_str
        if not os.path.exists(PORTFOLIO_FILE):
            df_new.to_csv(PORTFOLIO_FILE, index=False)
        else:
            df_new.to_csv(PORTFOLIO_FILE, mode='a', header=False, index=False)
        print(f"\n📝 [模擬記帳] 偵測到新菁英！今天自動買入並記錄：{', '.join([r['stock_name'] for r in new_sim_buys])}")

    # ====================================================
    # 📊 格式化與排序輸出區
    # ====================================================
    print("----------------------------------------------------")
    print("====================================================")
    
    final_breakout_list = []
    if raw_breakout_data:
        df_bo = pd.DataFrame(raw_breakout_data)
        df_bo = df_bo.sort_values(by="days_ago", ascending=True)
        for _, row in df_bo.iterrows():
            time_label = "今天剛發動" if row["days_ago"] == 0 else f"{row['days_ago']}天前發動"
            msg = f"🚀 [正飆] {row['title']} | 🔥 {time_label} | 均線: {row['spread']*100:.1f}% | 布林: {row['bb']*100:.1f}%"
            print(msg)
            final_breakout_list.append(f"🔥 {row['title']} ({time_label})\n   (均線糾結: {row['spread']*100:.1f}% | 布林: {row['bb']*100:.1f}%)")

    final_ambush_list = []
    if raw_ambush_data:
        df_am = pd.DataFrame(raw_ambush_data)
        df_am = df_am.sort_values(by="spread", ascending=True)
        for _, row in df_am.iterrows():
            msg = f"{row['stars']} [起飆] {row['title']} | 均線: {row['spread']*100:.1f}% | 布林: {row['bb']*100:.1f}%"
            print(msg)
            final_ambush_list.append(f"{row['stars']} {row['title']}\n   (均線糾結: {row['spread']*100:.1f}% | 布林: {row['bb']*100:.1f}% | MACD: {row['macd']})")

    # 執行持股損益動態回報機制
    portfolio_report_text = update_and_print_portfolio(api, today_str)

    if final_breakout_list or final_ambush_list:
        report_text = f"🐬 海豚選股 25.7 [模擬記帳完全體] 🐬\n"
        report_text += f"📅 數據日期：{today_str}\n"
        report_text += "=================\n\n"
        
        if final_breakout_list:
            report_text += "🚀 【正飆股 · 壓縮後強勢突破】\n"
            report_text += "\n".join(final_breakout_list) + "\n\n"
            
        if final_ambush_list:
            report_text += "🎯 【起飆股 · 沉睡鱷魚潛伏中】\n"
            report_text += "\n".join(final_ambush_list) + "\n\n"
            
        report_text += portfolio_report_text
        # send_line_notify(report_text)
    else:
        print("📭 今日無符合標的。")

    os._exit(0)

if __name__ == "__main__":
    asyncio.run(main())
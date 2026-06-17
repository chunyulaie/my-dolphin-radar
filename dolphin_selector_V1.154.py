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
# 25.2 參數設定區 (視覺優化·排重去雜版)
# ==========================================
VOLUME_FILTER = 500        # 單日成交量 500 張防線 

# 🎯 流派一：【起飆股】(左側壓縮埋伏) 
MA_SPREAD_LIMIT = 0.035    # 均線糾結度 3.5% 以內
BB_COMPRESS_LIMIT = 0.10   # 布林通道極致壓縮防線：10% 以內

# 🚀 流派二：【真·海豚正飆股】(大市值相容版) 
WAS_COMPRESSED_LIMIT = 0.04 # 起漲前一日糾結度需 <= 4%
LOOKBACK_WINDOW = 5         # 🕰️ 時空回溯天數：檢查過去 5 天內是否有爆發過

# 🎯【LINE Messaging API 設定】
LINE_ACCESS_TOKEN = 'uyt/NqkAS3yCOhUAWGqey5HYGBe5mfct1n5MB1OQaV8Y1/X8HoypqNBwq/LOVXk5YnCknVCi8LEE5KZTXkbXT2V0CpOCAk0C/YRPJRA3Z2RREefQjAG41UQV0pbp1YQCnewazDskTwrpBsxHwRo4OQdB04t89/1O/w1cDnyilFU='
TARGET_USER_ID = 'Uf8818996f2c5846640e0ae8ae0360a72'

URL_1000_SHARES = "https://norway.twsthr.info/StockHoldersContinue.aspx?Show=1&continue=Y&weeks=4&growthrate=2&beforeweek=8&price=5000&valuerank=1-3000&display=0"
URL_400_SHARES  = "https://norway.twsthr.info/StockHoldersContinue.aspx?Show=2&continue=Y&weeks=4&growthrate=2&beforeweek=8&price=5000&valuerank=1-3000&display=0"

def send_line_notify(message):
    url = 'https://api.line.me/v2/bot/message/push'
    headers = {
        'Content-Type': 'application/json',
        'Authorization': f'Bearer {LINE_ACCESS_TOKEN}'
    }
    payload = {'to': TARGET_USER_ID, 'messages': [{'type': 'text', 'text': message}]}
    try:
        requests.post(url, headers=headers, json=payload)
        print("📲 [系統通知] LINE 戰報推播成功！")
    except:
        pass

async def parse_page_codes(page, url, label):
    try:
        await page.goto(url, {'waitUntil': 'networkidle0', 'timeout': 0})
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
    print("🚀 海豚選股 25.2：[時空回溯·視覺終極優化版] 啟動...")
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

    for stock in STOCK_POOL:
        try:
            df_raw = api.taiwan_stock_daily(stock_id=stock, start_date=start_str, end_date=today_str)
            if df_raw.empty or len(df_raw) < 35: continue
            
            c_name = dynamic_name_dict.get(stock, "")
            display_title = f"{stock} {c_name}".strip() if c_name else stock
            
            df = pd.DataFrame()
            df["open"] = df_raw["open"].astype(float)
            df["close"] = df_raw["close"].astype(float)
            df["volume"] = df_raw["Trading_Volume"].astype(float) / 1000 
            
            if df.iloc[-1]["close"] == 0 or df.iloc[-1]["volume"] < VOLUME_FILTER:
                continue

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

            # -------------------------------------------
            # 🚀 階段一：時空回溯判定【正飆股】
            # -------------------------------------------
            triggered_days_ago = None
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
                    break 
            
            is_breakout_active = False
            latest_close = df.iloc[-1]["close"]
            
            if triggered_days_ago is not None:
                if df.iloc[-1]["close"] >= max(df.iloc[-1]["5MA"], df.iloc[-1]["10MA"], df.iloc[-1]["20MA"]):
                    raw_breakout_data.append({
                        "title": display_title,
                        "days_ago": triggered_days_ago,
                        "price": latest_close
                    })
                    is_breakout_active = True # 標記為正飆股，不再進入起飆名單

            # -------------------------------------------
            # 🎯 階段二：今日狀態判定【起飆股】(若已正飆則自動排除)
            # -------------------------------------------
            if not is_breakout_active:
                today_ma_list = [df.iloc[-1]["5MA"], df.iloc[-1]["10MA"], df.iloc[-1]["20MA"]]
                today_spread = (max(today_ma_list) - min(today_ma_list)) / latest_close
                bb_width = df.iloc[-1]["BB_Width"]
                macd_val = df.iloc[-1]["MACD"]
                
                if today_spread <= MA_SPREAD_LIMIT:
                    star_count = 1
                    if bb_width <= BB_COMPRESS_LIMIT: star_count += 1
                    if macd_val > 0: star_count += 1
                    
                    raw_ambush_data.append({
                        "stars": "⭐" * star_count,
                        "title": display_title,
                        "spread": today_spread,
                        "bb": bb_width,
                        "macd": "水上" if macd_val > 0 else "水下"
                    })
                
        except Exception as e:
            pass
        time.sleep(0.03)

    # ====================================================
    # 📊 格式化與排序輸出區
    # ====================================================
    print("----------------------------------------------------")
    print("====================================================")
    
    # 1. 處理正飆股：按照「發動天數」由近到遠排序 (0天前 > 1天前 > 2天前)
    final_breakout_list = []
    if raw_breakout_data:
        df_bo = pd.DataFrame(raw_breakout_data)
        df_bo = df_bo.sort_values(by="days_ago", ascending=True)
        for _, row in df_bo.iterrows():
            time_label = "今天剛發動" if row["days_ago"] == 0 else f"{row['days_ago']}天前發動"
            msg = f"🚀 [正飆] {row['title']} | 🔥 {time_label} | 目前股價: {row['price']}"
            print(msg)
            final_breakout_list.append(f"🔥 {row['title']} ({time_label})\n   (目前股價: {row['price']} | 均線發散追擊中)")

    # 2. 處理起飆股：按照「糾結度」由緊到鬆排序
    final_ambush_list = []
    if raw_ambush_data:
        df_am = pd.DataFrame(raw_ambush_data)
        df_am = df_am.sort_values(by="spread", ascending=True)
        for _, row in df_am.iterrows():
            msg = f"{row['stars']} [起飆] {row['title']} | 均線: {row['spread']*100:.1f}% | 布林: {row['bb']*100:.1f}%"
            print(msg)
            final_ambush_list.append(f"{row['stars']} {row['title']}\n   (均線糾結: {row['spread']*100:.1f}% | 布林: {row['bb']*100:.1f}% | MACD: {row['macd']})")

    # 3. 發送 LINE 漂亮戰報
    if final_breakout_list or final_ambush_list:
        report_text = f"🐬 海豚選股 25.2 [排重去雜優化版] 🐬\n"
        report_text += f"📅 數據日期：{today_str}\n"
        report_text += "=================\n\n"
        
        if final_breakout_list:
            report_text += "🚀 【正飆股 · 壓縮後強勢突破】\n"
            report_text += "👉 適合追高、強勢動能評估：\n"
            report_text += "\n".join(final_breakout_list) + "\n\n"
            
        if final_ambush_list:
            report_text += "🎯 【起飆股 · 沉睡鱷魚潛伏中】\n"
            report_text += "👉 適合左側安全埋伏：\n"
            report_text += "\n".join(final_ambush_list) + "\n\n"
            
        report_text += "💡 提示：今日剛發動之標的已自動歸類至[正飆股]，不再重複佔用起飆名單。"
        send_line_notify(report_text)
    else:
        print("📭 今日無符合標的。")

    os._exit(0)

if __name__ == "__main__":
    asyncio.run(main())
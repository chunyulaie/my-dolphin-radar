import asyncio
import datetime
import logging
import os
import time
import requests
from FinMind.data import DataLoader
import pandas as pd
from pyppeteer import launch

# 徹底抑制所有煩人的後台警告與 Log
logging.getLogger('pyppeteer').setLevel(logging.CRITICAL)
logging.getLogger('websockets').setLevel(logging.CRITICAL)
logging.getLogger('FinMind').setLevel(logging.CRITICAL)
try:
    import loguru
    loguru.logger.remove()
except:
    pass

# ==========================================
# 22.0 參數設定區 (雙刀流全配版)
# ==========================================
# 🛡️ 共通防線
VOLUME_FILTER = 500        # 單日成交量 500 張防線 (過濾死水股)

# 🎯 流派一：【起飆股】(左側埋伏) 參數
MA_SPREAD_LIMIT = 0.020    # 均線糾結度 2.0% 以內

# 🚀 流派二：【正飆股】(右側突破) 參數
VOL_BURST_RATIO = 2.0      # 爆量倍數：今日量必須是 5日均量的 2 倍以上
MIN_SURGE_PERCENT = 0.04   # 強勢表態：單日漲幅必須大於 4% 

# 🎯【LINE Messaging API 設定】
LINE_ACCESS_TOKEN = 'uyt/NqkAS3yCOhUAWGqey5HYGBe5mfct1n5MB1OQaV8Y1/X8HoypqNBwq/LOVXk5YnCknVCi8LEE5KZTXkbXT2V0CpOCAk0C/YRPJRA3Z2RREefQjAG41UQV0pbp1YQCnewazDskTwrpBsxHwRo4OQdB04t89/1O/w1cDnyilFU='
TARGET_USER_ID = 'Uf8818996f2c5846640e0ae8ae0360a72'

URL_1000_SHARES = "https://norway.twsthr.info/StockHoldersContinue.aspx?Show=1&continue=Y&weeks=4&growthrate=2&beforeweek=8&price=5000&valuerank=1-3000&display=0"
URL_400_SHARES  = "https://norway.twsthr.info/StockHoldersContinue.aspx?Show=2&continue=Y&weeks=4&growthrate=2&beforeweek=8&price=5000&valuerank=1-3000&display=0"

# ==========================================
# LINE 推播模組
# ==========================================
def send_line_notify(message):
    url = 'https://api.line.me/v2/bot/message/push'
    headers = {
        'Content-Type': 'application/json',
        'Authorization': f'Bearer {LINE_ACCESS_TOKEN}'
    }
    payload = {
        'to': TARGET_USER_ID,
        'messages': [{'type': 'text', 'text': message}]
    }
    try:
        response = requests.post(url, headers=headers, json=payload)
        if response.status_code == 200:
            print("📲 [系統通知] 雙刀流 LINE 戰報推播成功！")
        else:
            print(f"⚠️ [系統警告] LINE 推播失敗: {response.status_code} - {response.text}")
    except Exception as e:
        print(f"💥 [系統異常] LINE 推播發生錯誤: {e}")

# ==========================================
# 爬蟲與篩選模組
# ==========================================
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
                        const latestPercent = parseFloat(percentText);
                        if (!isNaN(potentialCode) && potentialCode.trim().length === 4 && latestPercent >= 50.0) {
                            result.push(potentialCode);
                        }
                    }
                }
            });
            return result;
        }''')
        print(f"📥 [{label}] 前端大戶篩選完成。")
        return set(codes)
    except Exception as e:
        return set()

async def fetch_union_pyramid_pool():
    print("🌐 正在背景啟動 Chromium 無頭瀏覽器...")
    browser = await launch(
        headless=True, userDataDir='./pyppeteer_cache', 
        args=['--no-sandbox', '--disable-setuid-sandbox', '--blink-settings=imagesEnabled=false', '--disable-extensions']
    )
    try:
        page = await browser.newPage()
        await page.setUserAgent("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
        pool_1000 = await parse_page_codes(page, URL_1000_SHARES, "4週千張·核心大戶")
        pool_400 = await parse_page_codes(page, URL_400_SHARES, "4週四百張·波段主力")
        await page.close()
        await browser.close()
        union_pool = sorted(list(pool_1000.union(pool_400)))
        print(f"🎯 絕對控盤大聯軍總數：{len(union_pool)} 檔\n")
        return union_pool
    except Exception as e:
        try: await browser.close()
        except: pass
        return []

async def main():
    print("====================================================")
    print("🚀 海豚選股 22.0：[雙刀流·海陸全餐版] 啟動...")
    print("====================================================")

    STOCK_POOL = await fetch_union_pyramid_pool()
    if not STOCK_POOL:
        print("❌ 股票池為空，程式終止。")
        return

    api = DataLoader()
    # ⚠️ 這裡已經放好你的專屬 Token
    api.login_by_token(api_token="eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9.eyJ1c2VyX2lkIjoicGNoaW9uMjAwMiIsImVtYWlsIjoibGFpZWNodW55dUBnbWFpbC5jb20iLCJ0b2tlbl92ZXJzaW9uIjowfQ.si_2Ta3AlY1JtgVBDlqpnkaK3IH41Drrc7ogVgNBJq8")
    
    try:
        df_info = api.taiwan_stock_info()
        dynamic_name_dict = dict(zip(df_info["stock_id"], df_info["stock_name"]))
    except:
        dynamic_name_dict = {}

    today_str = datetime.date.today().strftime("%Y-%m-%d")
    start_str = (datetime.date.today() - datetime.timedelta(days=50)).strftime("%Y-%m-%d")

    print("⏳ 開始進行雙模組精準掃描：尋找【起飆股】與【正飆股】...")
    print("----------------------------------------------------")
    
    ambush_list = []   # 起飆股 (壓縮埋伏)
    breakout_list = [] # 正飆股 (帶量突破)

    for stock in STOCK_POOL:
        try:
            df_raw = api.taiwan_stock_daily(stock_id=stock, start_date=start_str, end_date=today_str)
            if df_raw.empty or len(df_raw) < 20:
                continue
            
            c_name = dynamic_name_dict.get(stock, "")
            display_title = f"{stock} {c_name}".strip() if c_name else stock
            
            # --- 基礎資料建構 ---
            df = pd.DataFrame()
            df["open"] = df_raw["open"].astype(float)
            df["close"] = df_raw["close"].astype(float)
            # 信任官方結算數據
            df["volume"] = df_raw["Trading_Volume"].astype(float) / 1000 
            
            latest_open = df.iloc[-1]["open"]
            latest_close = df.iloc[-1]["close"]
            yesterday_close = df.iloc[-2]["close"]
            latest_vol = df.iloc[-1]["volume"]
            
            if latest_close == 0 or yesterday_close == 0:
                continue
                
            # 共通第一道死線：剔除沒有量能的死水股
            if latest_vol < VOLUME_FILTER:
                continue

            # 計算均線與均量
            df["5MA"] = df["close"].rolling(window=5).mean()
            df["10MA"] = df["close"].rolling(window=10).mean()
            df["20MA"] = df["close"].rolling(window=20).mean()
            df["5MA_Vol"] = df["volume"].rolling(window=5).mean()

            latest_5ma = df.iloc[-1]["5MA"]
            latest_10ma = df.iloc[-1]["10MA"]
            latest_20ma = df.iloc[-1]["20MA"]
            latest_5ma_vol = df.iloc[-1]["5MA_Vol"]
            
            # --- 判斷邏輯 一：【起飆股】 (均線壓縮) ---
            ma_list = [latest_5ma, latest_10ma, latest_20ma]
            spread = (max(ma_list) - min(ma_list)) / latest_close
            
            if spread <= MA_SPREAD_LIMIT:
                msg = f"🎯 【起飆股】 {display_title} | 糾結度: {spread*100:.2f}% | 量能: {int(latest_vol)}張"
                print(msg)
                ambush_list.append(f"📌 {display_title} (糾結: {spread*100:.2f}%)")

            # --- 判斷邏輯 二：【正飆股】 (帶量長紅突破) ---
            cond_red_k = latest_close > latest_open
            cond_vol_burst = latest_vol >= (latest_5ma_vol * VOL_BURST_RATIO)
            surge_percent = (latest_close - yesterday_close) / yesterday_close
            cond_surge = surge_percent >= MIN_SURGE_PERCENT
            cond_breakout = latest_close > max(latest_5ma, latest_10ma, latest_20ma)

            if cond_red_k and cond_vol_burst and cond_surge and cond_breakout:
                msg = f"🚀 【正飆股】 {display_title} | 漲幅: {surge_percent*100:.1f}% | 爆量: {int(latest_vol)}張"
                print(msg)
                breakout_list.append(f"🔥 {display_title} (漲幅: {surge_percent*100:.1f}% | {int(latest_vol)}張)")
                
        except Exception as e:
            pass
        time.sleep(0.02) # 有了 Token，延遲可以縮短，跑得更順暢

    print("----------------------------------------------------")
    print("====================================================")
    
    # 🎯 執行 LINE 推播整合
    if ambush_list or breakout_list:
        report_text = "🐬 海豚選股 22.0 [雙刀流戰報] 🐬\n"
        report_text += "=================\n"
        
        if breakout_list:
            report_text += "🚀 【正飆股】帶量突破：\n"
            report_text += "\n".join(breakout_list) + "\n\n"
            
        if ambush_list:
            report_text += "🎯 【起飆股】極致壓縮：\n"
            report_text += "\n".join(ambush_list) + "\n\n"
            
        report_text += "💡 系統提示：名單均符合大戶持股 >=50% 與單日 >500 張防線。祝獵殺順利！"
        
        send_line_notify(report_text)
    else:
        print("📭 今日大聯軍無符合【起飆】或【正飆】之標的，LINE 不發送推播。")

    os._exit(0)

if __name__ == "__main__":
    asyncio.run(main())
import asyncio
import datetime
import logging
import os
import time
import requests
from FinMind.data import DataLoader
import pandas as pd
from pyppeteer import launch

# 徹底抑制所有煩人的後台警告與 Log，保持終端機絕對乾淨
logging.getLogger('pyppeteer').setLevel(logging.CRITICAL)
logging.getLogger('websockets').setLevel(logging.CRITICAL)
logging.getLogger('FinMind').setLevel(logging.CRITICAL)
try:
    import loguru
    loguru.logger.remove()
except:
    pass

# ==========================================
# 19.9 參數設定區 (最終實戰版)
# ==========================================
MA_SPREAD_LIMIT = 0.020  # 均線糾結度 2.0% 以內
VOLUME_FILTER = 500      # 嚴格 500 張防線 (抓捕主力尾盤動作)

# 🎯【LINE Messaging API 設定】
LINE_ACCESS_TOKEN = 'uyt/NqkAS3yCOhUAWGqey5HYGBe5mfct1n5MB1OQaV8Y1/X8HoypqNBwq/LOVXk5YnCknVCi8LEE5KZTXkbXT2V0CpOCAk0C/YRPJRA3Z2RREefQjAG41UQV0pbp1YQCnewazDskTwrpBsxHwRo4OQdB04t89/1O/w1cDnyilFU='
TARGET_USER_ID = 'Uf8818996f2c5846640e0ae8ae0360a72'

URL_1000_SHARES = "https://norway.twsthr.info/StockHoldersContinue.aspx?Show=1&continue=Y&weeks=4&growthrate=2&beforeweek=8&price=5000&valuerank=1-3000&display=0"
URL_400_SHARES  = "https://norway.twsthr.info/StockHoldersContinue.aspx?Show=2&continue=Y&weeks=4&growthrate=2&beforeweek=8&price=5000&valuerank=1-3000&display=0"

# ==========================================
# LINE 推播模組
# ==========================================
def send_line_notify(message):
    """使用 LINE Messaging API 傳送推播訊息給指定 User ID"""
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
            print("📲 [系統通知] LINE 戰報推播成功！")
        else:
            print(f"⚠️ [系統警告] LINE 推播失敗: {response.status_code} - {response.text}")
    except Exception as e:
        print(f"💥 [系統異常] LINE 推播發生錯誤: {e}")

# ==========================================
# 爬蟲與篩選模組
# ==========================================
async def parse_page_codes(page, url, label):
    """前端網頁解析：嚴格把關大戶持股 >= 50%"""
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
    print("🚀 海豚選股 19.9：[絕對獵殺·實戰推播終極版] 啟動...")
    print("====================================================")

    STOCK_POOL = await fetch_union_pyramid_pool()
    if not STOCK_POOL:
        print("❌ 股票池為空，程式終止。")
        return

    api = DataLoader()
    api.login_by_token(api_token="eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9.eyJ1c2VyX2lkIjoicGNoaW9uMjAwMiIsImVtYWlsIjoibGFpZWNodW55dUBnbWFpbC5jb20iLCJ0b2tlbl92ZXJzaW9uIjowfQ.si_2Ta3AlY1JtgVBDlqpnkaK3IH41Drrc7ogVgNBJq8")
    try:
        df_info = api.taiwan_stock_info()
        dynamic_name_dict = dict(zip(df_info["stock_id"], df_info["stock_name"]))
    except:
        dynamic_name_dict = {}

    today_str = datetime.date.today().strftime("%Y-%m-%d")
    start_str = (datetime.date.today() - datetime.timedelta(days=50)).strftime("%Y-%m-%d")

    print("⏳ 開始進行第二階段：量能與技術面精準掃描...")
    print("----------------------------------------------------")
    
    final_gold_list = []
    report_lines = [] # 用來收集要發給 LINE 的清單細節

    for stock in STOCK_POOL:
        try:
            df_raw = api.taiwan_stock_daily(stock_id=stock, start_date=start_str, end_date=today_str)
            if df_raw.empty or len(df_raw) < 20:
                continue
            
            c_name = dynamic_name_dict.get(stock, "")
            display_title = f"{stock} {c_name}".strip() if c_name else stock
            
            latest_row = df_raw.iloc[-1]
            close_price = float(latest_row.get("close", 0))
            
            # 🎯 安全防護：避免股價為 0 導致分母為零的計算錯誤
            if close_price == 0:
                continue
                
            # 🎯 信任官方結算數據：直接將股數轉張數，精準捕捉尾盤大戶動作
            raw_volume_shares = float(latest_row.get("Trading_Volume", 0))
            volume_sheets = raw_volume_shares / 1000
            
            # 🎯 第一道死線：剔除沒有量能的純殭屍股
            if volume_sheets < VOLUME_FILTER:
                continue

            # 🎯 第二道死線：技術面均線極致壓縮
            df = pd.DataFrame()
            df["close"] = df_raw["close"].astype(float)
            df["5MA"] = df["close"].rolling(window=5).mean()
            df["10MA"] = df["close"].rolling(window=10).mean()
            df["20MA"] = df["close"].rolling(window=20).mean()

            latest_ma = df.iloc[-1]
            ma_list = [latest_ma["5MA"], latest_ma["10MA"], latest_ma["20MA"]]
            spread = (max(ma_list) - min(ma_list)) / close_price

            if spread <= MA_SPREAD_LIMIT:
                msg = f"🔥 【{display_title}】 糾結度: {spread*100:.2f}% | 成交量: {int(volume_sheets)}張"
                print(msg)
                final_gold_list.append(display_title)
                report_lines.append(f"📌 {display_title}\n   (糾結: {spread*100:.2f}% | 量能: {int(volume_sheets)}張)")
                
        except Exception as e:
            pass
        time.sleep(0.02)

    print("----------------------------------------------------")
    print(f"🎯 最終黃金飆股清單：{final_gold_list}")
    print("====================================================")
    
    # 🎯 執行 LINE 推播
    if final_gold_list:
        report_text = "🐬 海豚選股 19.9 戰報 🐬\n"
        report_text += "===============\n"
        report_text += "【絕對控盤 + 均線壓縮起漲點】\n\n"
        report_text += "\n".join(report_lines)
        report_text += "\n\n💡 系統提示：名單內均符合大戶持股 >=50%、4週吸籌與單日大於500張防線，請依盤面訊號扣板機！"
        
        send_line_notify(report_text)
    else:
        print("📭 今日無符合條件的標的，LINE 不發送推播。")

    os._exit(0)

if __name__ == "__main__":
    asyncio.run(main())
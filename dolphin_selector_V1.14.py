import asyncio
import datetime
import logging
import os
import time
from bs4 import BeautifulSoup
from FinMind.data import DataLoader
import pandas as pd
from pyppeteer import launch
import requests

# 徹底抑制所有煩人的後台警告與 FinMind 的 API 下載洗版 Log
logging.getLogger('pyppeteer').setLevel(logging.CRITICAL)
logging.getLogger('websockets').setLevel(logging.CRITICAL)
logging.getLogger('FinMind').setLevel(logging.CRITICAL)
try:
    import loguru
    loguru.logger.remove()  
except:
    pass

# ==========================================
# 19.3 參數設定區 (短線爆發 + 絕對控盤流)
# ==========================================
MA_SPREAD_LIMIT = 0.020  # 均線糾結度 2.0% 以內 (極致壓縮)
VOLUME_FILTER = 500      # 最新一天的成交量必須大於 500 張

# 🎯【LINE Messaging API 設定】保持你的專屬憑證
LINE_ACCESS_TOKEN = 'uyt/NqkAS3yCOhUAWGqey5HYGBe5mfct1n5MB1OQaV8Y1/X8HoypqNBwq/LOVXk5YnCknVCi8LEE5KZTXkbXT2V0CpOCAk0C/YRPJRA3Z2RREefQjAG41UQV0pbp1YQCnewazDskTwrpBsxHwRo4OQdB04t89/1O/w1cDnyilFU='
TARGET_USER_ID = 'Uf8818996f2c5846640e0ae8ae0360a72'

# 雙源頭金字塔網址設定 (4週短線爆發流)
URL_1000_SHARES = "https://norway.twsthr.info/StockHoldersContinue.aspx?Show=1&continue=Y&weeks=4&growthrate=2&beforeweek=8&price=5000&valuerank=1-3000&display=0"
URL_400_SHARES  = "https://norway.twsthr.info/StockHoldersContinue.aspx?Show=2&continue=Y&weeks=4&growthrate=2&beforeweek=8&price=5000&valuerank=1-3000&display=0"


def send_line_bot_push(msg_text):
    """外掛工具：利用 LINE Messaging API 將結果主動 Push 給指定用戶"""
    url = "https://api.line.me/v2/bot/message/push"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {LINE_ACCESS_TOKEN}"
    }
    payload = {
        "to": TARGET_USER_ID,
        "messages": [{"type": "text", "text": msg_text}]
    }
    try:
        response = requests.post(url, headers=headers, json=payload, timeout=5)
        if response.status_code == 200:
            print("✉️ 【LINE Bot 推播成功】選股結果已光速發送至您的手機！")
        else:
            print(f"⚠️ LINE Bot 推播失敗，代碼: {response.status_code}")
    except Exception as e:
        print(f"💥 LINE Bot 連線異常: {e}")


async def parse_page_codes_with_weight(page, url, label):
    """內部工具：精準定位每一列的 <a> 標籤與第 7 個 <td> 元素，強制過濾最新持股 < 50% 的股票"""
    print(f"🚀 潛航前進：正在攻入神秘金字塔 [{label}] 頁面...")
    try:
        await page.goto(url, {'waitUntil': 'networkidle0', 'timeout': 0})
        await asyncio.sleep(2.5) 
        
        # 🎯【終極修正】不再寫死 td:nth-child(2)，直接用遍歷防禦，100% 抓準股號與第 7 欄百分比！
        codes = await page.evaluate('''() => {
            const rows = document.querySelectorAll('#details > tbody > tr');
            const result = [];
            
            rows.forEach(row => {
                const aTag = row.querySelector('a'); // 直接盲抓這一列唯一的超連結 (例如: 1527 鑽全)
                const latestPercentTag = row.querySelector('td:nth-child(7) font p'); // 🎯 依據你提供的精準對齊規則：第 7 個 td
                
                if (aTag && latestPercentTag) {
                    const fullText = aTag.innerText ? aTag.innerText.trim() : "";
                    const percentText = latestPercentTag.innerText ? latestPercentTag.innerText.trim() : "0";
                    
                    if (fullText.length >= 4) {
                        const potentialCode = fullText.substring(0, 4);
                        const latestPercent = parseFloat(percentText);
                        
                        // 驗證股號為 4 碼純數字，且大股東持股總量必須「大於等於 50.0%」
                        if (!isNaN(potentialCode) && potentialCode.trim().length === 4 && latestPercent >= 50.0) {
                            result.push(potentialCode);
                        }
                    }
                }
            });
            return result;
        }''')
        print(f"📥 [{label}] 篩選完成！絕對大戶持股 >= 50% 的合格標的共: {len(set(codes))} 檔。")
        return set(codes)
    except Exception as e:
        print(f"💥 抓取 [{label}] 失敗: {e}")
        return set()


async def fetch_union_pyramid_pool():
    """【大聯軍強攻】雙網址聯集，並執行 50% 絕對持股防線清洗"""
    print("🌐 正在背景啟動 Chromium 無頭瀏覽器...")
    browser = await launch(
        headless=True,  
        userDataDir='./pyppeteer_cache', 
        args=['--no-sandbox', '--disable-setuid-sandbox', '--blink-settings=imagesEnabled=false', '--disable-extensions']
    )
    
    try:
        page = await browser.newPage()
        await page.setUserAgent("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, Gecko) Chrome/120.0.0.0 Safari/537.36")
        
        # 1. 抓取 4週千張大戶池（加入50%門檻）
        pool_1000 = await parse_page_codes_with_weight(page, URL_1000_SHARES, "4週千張·控盤組")
        
        # 2. 抓取 4週四百張大戶池（加入50%門檻）
        pool_400 = await parse_page_codes_with_weight(page, URL_400_SHARES, "4週四百張·主力組")
        
        await page.close()
        await browser.close()
        
        union_pool = sorted(list(pool_1000.union(pool_400)))
        
        print("\n====================================================")
        print(f"📊 【50%持股門檻·大聯軍組建成功】")
        print(f"   💡 4週千張(大於50%): {len(pool_1000)} 檔")
        print(f"   💡 4週四百張(大於50%): {len(pool_400)} 檔")
        print(f"   🎯 絕對控盤聯軍總數：{len(union_pool)} 檔")
        print("====================================================\n")
        
        return union_pool
        
    except Exception as e:
        print(f"💥 雙重股票池構建異常: {e}")
        try: await browser.close()
        except: pass
        return []


# ==========================================
# 主程式執行流 (FinMind 大數據清洗)
# ==========================================
async def main():
    print("====================================================")
    print("🚀 海豚選股 19.3：[校正回歸·絕對控盤完全體] 啟動...")
    print("====================================================")

    # 1. 抓取合併並過濾大戶持股比例後的黃金股票池
    STOCK_POOL = await fetch_union_pyramid_pool()
    
    if not STOCK_POOL:
        print("❌ 聯軍股票池為空，程式終止。")
        return

    print("📊 正在連接 FinMind 數據庫並動態下載全台股代號對照表...")
    api = DataLoader()
    
    try:
        df_info = api.taiwan_stock_info()
        dynamic_name_dict = dict(zip(df_info["stock_id"], df_info["stock_name"]))
    except Exception as e:
        print(f"⚠️ 下載對照表失敗 ({e})，啟動無股名備援機制。")
        dynamic_name_dict = {}

    today_str = datetime.date.today().strftime("%Y-%m-%d")
    start_str = (datetime.date.today() - datetime.timedelta(days=50)).strftime("%Y-%m-%d")

    print("\n⏳ 開始進行第二階段：量能與技術面地毯式健檢...")
    print("----------------------------------------------------")

    final_gold_list = []

    for stock in STOCK_POOL:
        try:
            df_raw = api.taiwan_stock_daily(
                stock_id=stock,
                start_date=start_str,
                end_date=today_str
            )
            
            if df_raw.empty or len(df_raw) < 20:
                print(f"   🔹 個股 【{stock}】檢驗結果 -> ❌ 歷史交易天數不足 20 天")
                continue
            
            c_name = dynamic_name_dict.get(stock, "")
            display_title = f"{stock} {c_name}".strip() if c_name else stock
            
            df = pd.DataFrame()
            df["close"] = df_raw["close"].astype(float)
            df["volume"] = df_raw["Trading_Volume"].astype(float) / 1000  
            
            df = df.tail(20)
            latest_k = df.iloc[-1]
            
            if latest_k["volume"] < VOLUME_FILTER:
                print(f"   🔹 個股 【{display_title}】檢驗結果 -> 👎 成交量過低 ({int(latest_k['volume'])}張 < {VOLUME_FILTER}張)")
                continue

            df["5MA"] = df["close"].rolling(window=5).mean()
            df["10MA"] = df["close"].rolling(window=10).mean()
            df["20MA"] = df["close"].rolling(window=20).mean()

            latest_ma = df.iloc[-1]
            ma_list = [latest_ma["5MA"], latest_ma["10MA"], latest_ma["20MA"]]
            spread = (max(ma_list) - min(ma_list)) / latest_ma["close"]

            if spread <= MA_SPREAD_LIMIT:
                print(f"🔥 【{display_title}】大戶絕對控盤 ＋ 均線糾結 完美飆股現形！")
                print(f"   📐 均線糾結度: {spread*100:.2f}% | 最新成交量: {int(latest_k['volume'])}張")
                print("-" * 52)
                final_gold_list.append(display_title)
            else:
                print(f"   🔹 個股 【{display_title}】檢驗結果 -> 👎 均線未糾結 (糾結度 {spread*100:.2f}% > {MA_SPREAD_LIMIT*100}%)")
                
        except Exception as e:
            print(f"   🔹 個股 【{stock}】檢驗結果 -> 💥 數據通道異常: {e}")
        
        time.sleep(0.05)

    print("\n====================================================")
    print("🎉 【聯軍選股流程結束】")
    print(f"🎯 最終符合[大戶持股>50%]＋[4週吃貨]＋[均線極致糾結]黃金飆股清單：{final_gold_list}")
    print("====================================================")
    
    # 推播到 LINE 官方帳號
    # line_report = f"🎯 最終符合[大戶持股>50%]＋[4週吃貨]＋[均線極致糾結]黃金飆股清單：{final_gold_list}"
    # send_line_bot_push(line_report)
    
    os._exit(0)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except SystemExit:
        pass
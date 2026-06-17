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
# 19.0 參數設定區 (保留你微調後的黃金密碼)
# ==========================================
MA_SPREAD_LIMIT = 0.020  # 均線糾結度 2.0% 以內 (極致壓縮)
VOLUME_FILTER = 500      # 最新一天的成交量必須大於 500 張 (依你微調後的標準)

# 🎯【LINE Messaging API 設定】已自動填入你的專屬憑證
LINE_ACCESS_TOKEN = 'uyt/NqkAS3yCOhUAWGqey5HYGBe5mfct1n5MB1OQaV8Y1/X8HoypqNBwq/LOVXk5YnCknVCi8LEE5KZTXkbXT2V0CpOCAk0C/YRPJRA3Z2RREefQjAG41UQV0pbp1YQCnewazDskTwrpBsxHwRo4OQdB04t89/1O/w1cDnyilFU='
TARGET_USER_ID = 'Uf8818996f2c5846640e0ae8ae0360a72'

# 🎯 雙源頭金字塔網址設定 (依你最新的微調參數)
URL_1000_SHARES = "https://norway.twsthr.info/StockHoldersContinue.aspx?Show=1&continue=Y&weeks=8&growthrate=2&beforeweek=8&price=5000&valuerank=1-3000&display=0"
URL_400_SHARES  = "https://norway.twsthr.info/StockHoldersContinue.aspx?Show=2&continue=Y&weeks=8&growthrate=2&beforeweek=8&price=5000&valuerank=1-3000&display=0"


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


async def parse_page_codes(page, url, label):
    """內部工具：控制瀏覽器前往指定網址並扒下股號"""
    print(f"🚀 潛航前進：正在攻入神秘金字塔 [{label}] 頁面...")
    try:
        await page.goto(url, {'waitUntil': 'networkidle0', 'timeout': 0})
        await asyncio.sleep(2.5) 
        
        codes = await page.evaluate('''() => {
            const anchors = document.querySelectorAll('#details td a');
            const result = [];
            anchors.forEach(a => {
                const fullText = a.innerText ? a.innerText.trim() : "";
                if (fullText.length >= 4) {
                    const potentialCode = fullText.substring(0, 4);
                    if (!isNaN(potentialCode) && potentialCode.trim().length === 4) {
                        result.push(potentialCode);
                    }
                }
            });
            return result;
        }''')
        print(f"📥 [{label}] 讀取完成！共抓到 {len(set(codes))} 檔標的。")
        return set(codes)
    except Exception as e:
        print(f"💥 抓取 [{label}] 失敗: {e}")
        return set()


async def fetch_union_pyramid_pool():
    """【大聯軍強攻】同時抓取 1000張 與 400張 籌碼池，並合併（聯集）擴大戰線"""
    print("🌐 正在背景啟動 Chromium 無頭瀏覽器...")
    browser = await launch(
        headless=True,  
        userDataDir='./pyppeteer_cache', 
        args=['--no-sandbox', '--disable-setuid-sandbox', '--blink-settings=imagesEnabled=false', '--disable-extensions']
    )
    
    try:
        page = await browser.newPage()
        await page.setUserAgent("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
        
        pool_1000 = await parse_page_codes(page, URL_1000_SHARES, "1000張核心大戶")
        pool_400 = await parse_page_codes(page, URL_400_SHARES, "400張波段主力")
        
        await page.close()
        await browser.close()
        
        union_pool = sorted(list(pool_1000.union(pool_400)))
        
        print("\n====================================================")
        print(f"📊 【巨型籌碼池大聯軍組建成功】")
        print(f"   💡 1000張大戶貢獻: {len(pool_1000)} 檔")
        print(f"   💡 400張主力貢獻: {len(pool_400)} 檔")
        print(f"   🎯 去重合體後（大聯軍總數）共: {len(union_pool)} 檔")
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
    print("🚀 海豚選股 19.0：[正統動態對照·LINE推播完全體] 啟動...")
    print("====================================================")

    # 1. 抓取合併後的巨型股票池
    STOCK_POOL = await fetch_union_pyramid_pool()
    
    if not STOCK_POOL:
        print("❌ 聯軍股票池為空，程式終止。")
        return

    print("📊 正在連接 FinMind 數據庫...")
    api = DataLoader()
    
    # 🎯【正統不作弊修正】從 FinMind 高速下載全台股代號對照表，就地建立動態字典
    print("📥 正在動態下載全台股代號對照表...")
    try:
        df_info = api.taiwan_stock_info()
        # 建立動態對照字典 (例如: {"1734": "杏輝"})
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
            
            # 🎯【動態查表】老老實實從剛才下載的對照表裡抓名字，100%不作弊
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
                print(f"🔥 【{display_title}】大戶主力強力吃貨 ＋ 均線糾結 完美飆股現形！")
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
    print(f"🎯 最終符合[千張或四百張吃貨]＋[均線極致糾結]黃金飆股清單：{final_gold_list}")
    print("====================================================")
    
    # 推播到 LINE 官方帳號
    line_report = f"🎯 最終符合[千張或四百張吃貨]＋[均線極致糾結]黃金飆股清單：{final_gold_list}"
    send_line_bot_push(line_report)
    
    os._exit(0)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except SystemExit:
        pass
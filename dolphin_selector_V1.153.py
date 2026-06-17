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
# 24.0 參數設定區 (真·海豚起漲限定版)
# ==========================================
VOLUME_FILTER = 500        # 單日成交量 500 張防線 

# 🎯 流派一：【起飆股】(左側壓縮埋伏) 
MA_SPREAD_LIMIT = 0.035    # 均線糾結放寬至 3.5%，靠星級來篩選極品
BB_COMPRESS_LIMIT = 0.10   # 布林通道極致壓縮防線：10% (0.10) 以內

# 🚀 流派二：【正飆股】(右側第一根起漲) 
# ⚠️ 新增「前置壓縮防線」：要求昨天的均線必須是壓縮狀態！
WAS_COMPRESSED_LIMIT = 0.04 # 容許起漲前微幅發散，昨日糾結度需 <= 4%
VOL_BURST_RATIO = 2.0       # 爆量倍數：2 倍
MIN_SURGE_PERCENT = 0.04    # 強勢表態：漲幅 4% 

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
    print("🚀 海豚選股 24.0：[真·海豚起漲第一根限定版] 啟動...")
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

    print("⏳ 尋找昨日壓縮、今日爆量突破之【真·海豚】...")
    print("----------------------------------------------------")
    
    ambush_list = []   
    breakout_list = [] 

    for stock in STOCK_POOL:
        try:
            df_raw = api.taiwan_stock_daily(stock_id=stock, start_date=start_str, end_date=today_str)
            if df_raw.empty or len(df_raw) < 30: continue
            
            c_name = dynamic_name_dict.get(stock, "")
            display_title = f"{stock} {c_name}".strip() if c_name else stock
            
            df = pd.DataFrame()
            df["open"] = df_raw["open"].astype(float)
            df["close"] = df_raw["close"].astype(float)
            df["volume"] = df_raw["Trading_Volume"].astype(float) / 1000 
            
            latest_open = df.iloc[-1]["open"]
            latest_close = df.iloc[-1]["close"]
            yesterday_close = df.iloc[-2]["close"]
            latest_vol = df.iloc[-1]["volume"]
            
            if latest_close == 0 or yesterday_close == 0 or latest_vol < VOLUME_FILTER:
                continue

            # --- 基礎均線運算 ---
            df["5MA"] = df["close"].rolling(window=5).mean()
            df["10MA"] = df["close"].rolling(window=10).mean()
            df["20MA"] = df["close"].rolling(window=20).mean()
            df["5MA_Vol"] = df["volume"].rolling(window=5).mean()
            
            # --- 布林與 MACD ---
            df['20STD'] = df['close'].rolling(window=20).std()
            df['BB_Upper'] = df['20MA'] + 2 * df['20STD']
            df['BB_Lower'] = df['20MA'] - 2 * df['20STD']
            df['BB_Width'] = (df['BB_Upper'] - df['BB_Lower']) / df['20MA']
            
            df['EMA12'] = df['close'].ewm(span=12, adjust=False).mean()
            df['EMA26'] = df['close'].ewm(span=26, adjust=False).mean()
            df['MACD'] = df['EMA12'] - df['EMA26']

            # 取出「今天」與「昨天」的數值
            latest_5ma = df.iloc[-1]["5MA"]
            latest_10ma = df.iloc[-1]["10MA"]
            latest_20ma = df.iloc[-1]["20MA"]
            latest_5ma_vol = df.iloc[-1]["5MA_Vol"]
            bb_width = df.iloc[-1]["BB_Width"]
            macd_val = df.iloc[-1]["MACD"]
            
            yesterday_5ma = df.iloc[-2]["5MA"]
            yesterday_10ma = df.iloc[-2]["10MA"]
            yesterday_20ma = df.iloc[-2]["20MA"]
            
            # -------------------------------------------
            # 🎯 判定：【起飆股】星級潛伏
            # -------------------------------------------
            today_ma_list = [latest_5ma, latest_10ma, latest_20ma]
            today_spread = (max(today_ma_list) - min(today_ma_list)) / latest_close
            
            if today_spread <= MA_SPREAD_LIMIT:
                star_count = 1
                if bb_width <= BB_COMPRESS_LIMIT: star_count += 1
                if macd_val > 0: star_count += 1
                
                stars = "⭐" * star_count
                macd_status = "水上" if macd_val > 0 else "水下"
                
                msg = f"{stars} [起飆] {display_title} | 均線: {today_spread*100:.1f}% | 布林: {bb_width*100:.1f}%"
                print(msg)
                ambush_list.append(f"{stars} {display_title}\n   (布林: {bb_width*100:.1f}% | MACD: {macd_status})")

            # -------------------------------------------
            # 🚀 判定：【真·海豚正飆股】(昨日壓縮，今日突破！)
            # -------------------------------------------
            # 條件1：計算「昨天」的均線糾結度 (必須 <= 4%)
            yesterday_ma_list = [yesterday_5ma, yesterday_10ma, yesterday_20ma]
            yesterday_spread = (max(yesterday_ma_list) - min(yesterday_ma_list)) / yesterday_close
            cond_was_compressed = yesterday_spread <= WAS_COMPRESSED_LIMIT
            
            # 條件2：今天的爆發動作
            cond_red_k = latest_close > latest_open
            cond_vol_burst = latest_vol >= (latest_5ma_vol * VOL_BURST_RATIO)
            surge_percent = (latest_close - yesterday_close) / yesterday_close
            cond_surge = surge_percent >= MIN_SURGE_PERCENT
            cond_breakout = latest_close > max(latest_5ma, latest_10ma, latest_20ma)

            # 五個條件同時成立，才是真正的海豚出水！
            if cond_was_compressed and cond_red_k and cond_vol_burst and cond_surge and cond_breakout:
                msg = f"🚀 [正飆(真海豚)] {display_title} | 漲幅: {surge_percent*100:.1f}% | 昨日糾結: {yesterday_spread*100:.1f}%"
                print(msg)
                breakout_list.append(f"🔥 {display_title}\n   (漲幅: {surge_percent*100:.1f}% | 爆量: {int(latest_vol)}張)")
                
        except Exception as e:
            pass
        time.sleep(0.02) 

    print("----------------------------------------------------")
    print("====================================================")
    
    if ambush_list or breakout_list:
        report_text = "🐬 海豚選股 24.0 [真·海豚戰報] 🐬\n"
        report_text += "=================\n"
        
        if breakout_list:
            report_text += "🚀 【正飆股】壓縮後帶量突破：\n"
            report_text += "\n".join(breakout_list) + "\n\n"
            
        if ambush_list:
            report_text += "🎯 【起飆股】星級潛伏：\n"
            report_text += "\n".join(ambush_list) + "\n\n"
            
        report_text += "💡 提示：正飆股已嚴格過濾，確保為昨日壓縮、今日剛發動之真海豚。"
        send_line_notify(report_text)
    else:
        print("📭 今日無符合標的。")

    os._exit(0)

if __name__ == "__main__":
    asyncio.run(main())
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

# ====================================================================
# 25.25 參數設定區 (單一腳本內嵌優化 · 完美因果完全體)
# ====================================================================
VOLUME_FILTER = 500        
VOLUME_5MA_FILTER = 400    

# 🎯 【手動模擬除名清單】
REMOVE_LIST = [] 

# 🎯 【每檔模擬投入預算】
SIM_BUDGET = 30000         

# 🎯 【全局預設移動停利參數】(當 CSV 中尚未被外掛寫入個別最佳化參數時，以此為基準)
GLOBAL_TP_THRESHOLD = 0.15   # 獲利超過 15% 啟動移動鎖利雷達
GLOBAL_TP_DROP = 0.03       # 自波段高點拉回 3% 觸發停利通知

# 🎯 流派一：【起飆股】
MA_SPREAD_LIMIT = 0.035    
BB_COMPRESS_LIMIT = 0.18   

# 🚀 流派二：【真·海豚正飆股】
WAS_COMPRESSED_LIMIT = 0.04 
LOOKBACK_WINDOW = 5         

# 📊 【台股模擬交易成本設定】
FEE_RATE = 0.001425         
FEE_DISCOUNT = 0.28         # 券商手續費折讓（28折）
TAX_RATE = 0.003            
PORTFOLIO_FILE = r"D:\Python-Training\N100\海豚選股法\dolphin_portfolio.csv" 

# 🎯【LINE Messaging API 設定】
LINE_ACCESS_TOKEN = 'uyt/NqkAS3yCOhUAWGqey5HYGBe5mfct1n5MB1OQaV8Y1/X8HoypqNBwq/LOVXk5YnCknVCi8LEE5KZTXkbXT2V0CpOCAk0C/YRPJRA3Z2RREefQjAG41UQV0pbp1YQCnewazDskTwrpBsxHwRo4OQdB04t89/1O/w1cDnyilFU='
TARGET_USER_ID = 'Uf8818996f2c5846640e0ae8ae0360a72'

URL_1000_SHARES = "https://norway.twsthr.info/StockHoldersContinue.aspx?Show=1&continue=Y&weeks=4&growthrate=2&beforeweek=8&price=5000&valuerank=1-3000&display=0"
URL_400_SHARES  = "https://norway.twsthr.info/StockHoldersContinue.aspx?Show=2&continue=Y&weeks=4&growthrate=2&beforeweek=8&price=5000&valuerank=1-3000&display=0"

def run_pre_backtest(api, stock_id):
    """【AI 預回測沙盒】: 在股票建倉寫入 CSV 前，強制在背景跑完過去一年的歷史，虧損則退貨"""
    bt_start = "2025-06-01"
    bt_end = datetime.date.today().strftime("%Y-%m-%d")
    
    try:
        df_raw = api.taiwan_stock_daily(stock_id=stock_id, start_date=bt_start, end_date=bt_end)
        if df_raw.empty or len(df_raw) < 50: return False  
        
        df = pd.DataFrame()
        df["close"] = df_raw["close"].astype(float)
        df["open"] = df_raw["open"].astype(float)
        df["volume"] = df_raw["Trading_Volume"].astype(float) / 1000 
        
        df["5MA"] = df["close"].rolling(window=5).mean()
        df["10MA"] = df["close"].rolling(window=10).mean()
        df["20MA"] = df["close"].rolling(window=20).mean()
        df["5MA_Vol"] = df["volume"].rolling(window=5).mean()
        df['20STD'] = df['close'].rolling(window=20).std(ddof=0)
        df['BB_Width'] = ((df['20MA'] + 2*df['20STD']) - (df['20MA'] - 2*df['20STD'])) / df['20MA']
        df['EMA12'] = df['close'].ewm(span=12, adjust=False).mean()
        df['EMA26'] = df['close'].ewm(span=26, adjust=False).mean()
        df['MACD'] = df['EMA12'] - df['EMA26']

        in_pos = False
        b_price = 0.0
        b_shares = 0
        m_price = 0.0
        total_net_profit = 0

        for i in range(35, len(df)):
            today_k = df.iloc[i]
            yesterday_k = df.iloc[i-1]
            pre_yesterday_k = df.iloc[i-2]
            c_close = today_k['close']

            if in_pos:
                if c_close > m_price: m_price = c_close
                b_fee = int(b_price * b_shares * FEE_RATE * FEE_DISCOUNT)
                if b_fee < 20: b_fee = 20
                s_fee = int(c_close * b_shares * FEE_RATE * FEE_DISCOUNT)
                if s_fee < 20: s_fee = 20
                s_tax = int(c_close * b_shares * TAX_RATE)
                
                net_p = int((c_close * b_shares - s_fee - s_tax) - (b_price * b_shares + b_fee))
                max_p_pct = ((m_price - b_price) / b_price)
                
                if max_p_pct >= GLOBAL_TP_THRESHOLD and c_close <= (m_price * (1 - GLOBAL_TP_DROP)):
                    total_net_profit += net_p
                    in_pos = False
                elif today_k['20MA'] > 0 and c_close < today_k['20MA']:
                    total_net_profit += net_p
                    in_pos = False
            else:
                if today_k["volume"] < 500 or today_k["5MA_Vol"] < 400: continue
                y_ma = [pre_yesterday_k["5MA"], pre_yesterday_k["10MA"], pre_yesterday_k["20MA"]]
                y_spread = (max(y_ma) - min(y_ma)) / pre_yesterday_k["close"] if pre_yesterday_k["close"] > 0 else 99
                is_bo = (y_spread <= 0.04 and yesterday_k["close"] > yesterday_k["open"] and yesterday_k["close"] > max(yesterday_k["5MA"], yesterday_k["10MA"], yesterday_k["20MA"]) and c_close >= max(today_k["5MA"], today_k["10MA"], today_k["20MA"]))
                
                is_amb = False
                if not is_bo and today_k["5MA"] >= today_k["10MA"] >= today_k["20MA"]:
                    t_spread = (max([today_k["5MA"], today_k["10MA"], today_k["20MA"]]) - min([today_k["5MA"], today_k["10MA"], today_k["20MA"]])) / today_k["20MA"]
                    if t_spread <= 0.035 and today_k["BB_Width"] <= 0.18 and today_k["MACD"] > 0: is_amb = True
                
                if is_bo or is_amb:
                    in_pos = True
                    b_price = c_close
                    b_shares = int(SIM_BUDGET // c_close)
                    m_price = c_close
                    
        return total_net_profit >= 0  
    except:
        return False

def update_and_print_portfolio(api, today_str):
    if not os.path.exists(PORTFOLIO_FILE):
        print("💼 [模擬帳戶] 目前尚無歷史模擬部位。")
        return "", ""
    
    # 🎯 重新讀取已被內部優化器更新完畢、塞滿黃金參數的 CSV
    df_pf = pd.read_csv(PORTFOLIO_FILE, dtype={"stock_id": str})
    if df_pf.empty:
        print("💼 [模擬帳戶] 目前帳戶內無任何股票。")
        return "", ""
    
    if REMOVE_LIST:
        initial_count = len(df_pf)
        df_pf = df_pf[~df_pf["stock_id"].isin(REMOVE_LIST)]
        if len(df_pf) < initial_count:
            print(f"♻️ [模擬記帳] 成功將手動指定股票 {REMOVE_LIST} 自模擬資料庫中移除。")
    
    print("\n====================================================")
    print(f"💼 📊 【海豚選股 · 模擬帳戶當前資產即時回報 ({SIM_BUDGET}元定額版)】")
    print("====================================================")
    
    survived_rows = []   
    report_p_rows = []   
    exit_p_rows = []     
    
    real_today_str = datetime.date.today().strftime("%Y-%m-%d")
    real_start_str = (datetime.date.today() - datetime.timedelta(days=90)).strftime("%Y-%m-%d")
    
    for idx, row in df_pf.iterrows():
        sid = row["stock_id"]
        sname = row["stock_name"]
        b_date = row["buy_date"]
        b_price = float(row["buy_price"])
        shares = int(row["buy_shares"])
        
        max_price = float(row["max_price"]) if "max_price" in row and not pd.isna(row["max_price"]) else b_price
        tp_th = float(row["best_tp"]) if "best_tp" in row and not pd.isna(row["best_tp"]) else GLOBAL_TP_THRESHOLD
        tp_dr = float(row["best_drop"]) if "best_drop" in row and not pd.isna(row["best_drop"]) else GLOBAL_TP_DROP
        target_ma_line = row["best_ma"] if "best_ma" in row and not pd.isna(row["best_ma"]) else "20MA"
        
        try:
            df_now = api.taiwan_stock_daily(stock_id=sid, start_date=real_start_str, end_date=real_today_str)
            if not df_now.empty and len(df_now) >= 50:
                current_price = float(df_now.iloc[-1]["close"])
                
                df_now["5MA"] = df_now["close"].astype(float).rolling(window=5).mean()
                df_now["10MA"] = df_now["close"].astype(float).rolling(window=10).mean()
                df_now["20MA"] = df_now["close"].astype(float).rolling(window=20).mean()
                df_now["5WMA"] = df_now["close"].astype(float).rolling(window=25).mean()  
                df_now["10WMA"] = df_now["close"].astype(float).rolling(window=50).mean() 
                
                active_stop_loss_value = float(df_now.iloc[-1][target_ma_line])
            else:
                current_price = b_price
                active_stop_loss_value = 0.0
        except:
            current_price = b_price
            active_stop_loss_value = 0.0
            
        if current_price > max_price:
            max_price = current_price
            
        buy_fee = int(b_price * shares * FEE_RATE * FEE_DISCOUNT)
        if buy_fee < 20: buy_fee = 20
        total_buy_spent = (b_price * shares) + buy_fee
        
        sell_fee = int(current_price * shares * FEE_RATE * FEE_DISCOUNT)
        if sell_fee < 20: sell_fee = 20
        sell_tax = int(current_price * shares * TAX_RATE)
        total_sell_get = (current_price * shares) - sell_fee - sell_tax
        
        net_profit = int(total_sell_get - total_buy_spent)
        profit_percent = (net_profit / total_buy_spent) * 100
        sign = "+" if net_profit >= 0 else ""
        
        max_profit_percent = ((max_price - b_price) / b_price)
        is_tp_triggered = False
        tp_alert_price = round(max_price * (1 - tp_dr), 2)
        
        if max_profit_percent >= tp_th and current_price <= tp_alert_price:
            exit_msg = f"🎉 停利通知：{sid} {sname} 曾最高創下 {max_price}，今日收 {current_price} 已跌破鎖利線 {tp_alert_price} (高點拉回 {tp_dr*100:.1f}%)！已滿足專屬停利條件！目前波段獲利: {sign}{net_profit}元 ({sign}{profit_percent:.2f}%)"
            print(exit_msg)
            exit_p_rows.append(exit_msg)
            is_tp_triggered = True 
            
        if active_stop_loss_value > 0.0 and current_price < active_stop_loss_value:
            exit_msg = f"⚠️ 停損出場：{sid} {sname} 昨收 {current_price} 跌破專屬停損線 {target_ma_line}({active_stop_loss_value:.2f})！零股 {shares} 股強制結算！最終損益: {sign}{net_profit}元 ({sign}{profit_percent:.2f}%)"
            print(exit_msg)
            exit_p_rows.append(exit_msg)
            continue 
            
        tp_status_tag = " 🔥(已滿足停利點!)" if is_tp_triggered else ""
        color_stars = "📈" if net_profit >= 0 else "📉"
        
        p_msg = f"{color_stars} {sid} {sname} | 買入: {b_date} | 成本: {b_price} ({shares}股) -> 現價: {current_price} [停利高點: {max_price} | 防守停損({target_ma_line}): {active_stop_loss_value:.2f}]{tp_status_tag} | 損益: {sign}{net_profit}元 ({sign}{profit_percent:.2f}%)"
        print(p_msg)
        report_p_rows.append(p_msg)
        
        row["max_price"] = max_price
        survived_rows.append(row)
        
    df_survived = pd.DataFrame(survived_rows)
    df_survived.to_csv(PORTFOLIO_FILE, index=False)
    
    print("====================================================\n")
    
    exit_report = "\n🚨 【海豚移動出場警報 · 執行鎖利通知(持股保留)/硬性停損宣示】:\n" + "\n".join(exit_p_rows) + "\n\n=================\n" if exit_p_rows else ""
    portfolio_report = "\n💼 【模擬部位當前淨損益回報】:\n" + "\n".join(report_p_rows) if report_p_rows else ""
    
    return exit_report, portfolio_report

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
    print("🚀 海豚選股 25.25：[單一腳本內嵌優化完全體] 啟動...")
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
    
    sim_purchased_stocks = []
    if os.path.exists(PORTFOLIO_FILE):
        try:
            df_exist = pd.read_csv(PORTFOLIO_FILE, dtype={"stock_id": str})
            sim_purchased_stocks = df_exist["stock_id"].tolist()
        except:
            pass

    new_sim_buys = [] 

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

            if df.iloc[-1]["volume"] < VOLUME_FILTER or df.iloc[-1]["5MA_Vol"] < VOLUME_5MA_FILTER:
                continue

            latest_close = df.iloc[-1]["close"]

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
                    
                    if triggered_days_ago == 0 and stock not in sim_purchased_stocks and stock not in REMOVE_LIST:
                        print(f"🔬 偵測到發動標的：{display_title}，強行啟動 AI 預回測基因體檢...")
                        if run_pre_backtest(api, stock):
                            calc_shares = int(SIM_BUDGET // latest_close)
                            if calc_shares > 0:
                                k_line_date = str(df_raw.iloc[-1]["date"])[:10]
                                new_sim_buys.append({
                                    "stock_id": stock, "stock_name": c_name, 
                                    "buy_price": latest_close, "buy_shares": calc_shares, 
                                    "buy_type": "正飆(0天)", "buy_date": k_line_date,
                                    "max_price": latest_close  
                                })
                                print(f"✅ [體檢過關] {display_title} 歷史總利潤為正，核准寫入帳簿！")
                        else:
                            print(f"❌ [體檢失敗] {display_title} 歷史模擬回測為虧損！直接黑名單封殺，拒絕建倉！")

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
                        
                        if star_count == 3 and stock not in sim_purchased_stocks and stock not in REMOVE_LIST:
                            print(f"🔬 偵測到滿星起飆：{display_title}，強行啟動 AI 預回測基因體檢...")
                            if run_pre_backtest(api, stock):
                                calc_shares = int(SIM_BUDGET // latest_close)
                                if calc_shares > 0:
                                    k_line_date = str(df_raw.iloc[-1]["date"])[:10]
                                    new_sim_buys.append({
                                        "stock_id": stock, "stock_name": c_name, 
                                        "buy_price": latest_close, "buy_shares": calc_shares, 
                                        "buy_type": "3星起飆", "buy_date": k_line_date,
                                        "max_price": latest_close  
                                    })
                                    print(f"✅ [體檢過關] {display_title} 歷史總利潤為正，核准寫入帳簿！")
                            else:
                                print(f"❌ [體檢失敗] {display_title} 歷史模擬回測為虧損！直接黑名單封殺，拒絕建倉！")
                
        except Exception as e:
            pass
        time.sleep(0.03)

    # 模擬帳戶新交易寫入
    if new_sim_buys:
        df_new = pd.DataFrame(new_sim_buys)
        cols = ["stock_id", "stock_name", "buy_price", "buy_shares", "buy_type", "buy_date", "max_price"]
        df_new = df_new[cols]
        if not os.path.exists(PORTFOLIO_FILE):
            df_new.to_csv(PORTFOLIO_FILE, index=False)
        else:
            df_new.to_csv(PORTFOLIO_FILE, mode='a', header=False, index=False)
        print(f"\n📝 [模擬記帳] 成功通過體檢並以定額 {SIM_BUDGET} 元建倉零股：{', '.join([r['stock_name'] + '(' + str(r['buy_shares']) + '股)' for r in new_sim_buys])}")

    # ────────────────────────────────────────────────────
    # 🎯 【25.25 核心進化：因果攔截點 · 現場外掛呼叫】
    # ────────────────────────────────────────────────────
    print("\n⚡ [因果攔截] 今日新股建倉完畢。正在同一資料夾內即時導入優化器外掛...")
    try:
        import dolphin_portfolio_optimizer_v2 as d_opt
        d_opt.main() # 👈 當場就地處決！直接幫包含新股票在內的所有持股算好黃金密碼！
        print("⚡ [因果攔截] 優化器解碼完畢。持股 CSV 參數已全部更新，重回主程式主線。")
    except Exception as opt_err:
        print(f"⚠️ [因果攔截] 自動導入優化器失敗（錯誤: {opt_err}），將以預設防呆參數繼續。")
    # ────────────────────────────────────────────────────

    print("----------------------------------------------------")
    print("====================================================")
    
    final_breakout_list = []
    if raw_breakout_data:
        df_bo = pd.DataFrame(raw_breakout_data)
        df_bo = df_bo.sort_values(by="days_ago", ascending=True)
        for _, row in df_bo.iterrows():
            time_label = "今天剛發動" if row["days_ago"] == 0 else f"{row['days_ago']}天前發動"
            final_breakout_list.append(f"▪️ {row['title']} ({time_label})\n  [均線糾結: {row['spread']*100:.1f}% | 布林: {row['bb']*100:.1f}%]")

    final_ambush_list = []
    if raw_ambush_data:
        df_am = pd.DataFrame(raw_ambush_data)
        df_am = df_am.sort_values(by="spread", ascending=True)
        for _, row in df_am.iterrows():
            final_ambush_list.append(f"{row['stars']} {row['title']}\n  [均線: {row['spread']*100:.1f}% | 布林: {row['bb']*100:.1f}% | MACD: {row['macd']}]")

    # 執行持股損益與自動停損/停利回報機制 (此時讀到的 df_pf 已經是最新優化好的了！)
    exit_report_text, portfolio_report_text = update_and_print_portfolio(api, today_str)

    if final_breakout_list or final_ambush_list or exit_report_text:
        report_chunks = []
        report_chunks.append(f"🐬 海豚選股 25.25 [內嵌優化完全體] 🐬")
        report_chunks.append(f"📅 數據日期：{today_str}")
        report_chunks.append(f"───────────────────")
        
        if exit_report_text:
            cleaned_exit = exit_report_text.strip()
            if cleaned_exit:
                report_chunks.append(cleaned_exit)
                report_chunks.append(f"───────────────────")
        
        if final_breakout_list:
            report_chunks.append(f"🚀【真·正飆股 · 動能突破擊潰區】")
            report_chunks.append("\n".join(final_breakout_list))
            report_chunks.append(f"───────────────────")
            
        if final_ambush_list:
            report_chunks.append(f"🎯【準·起飆股 · 鱷魚潛伏地底區】")
            report_chunks.append("\n".join(final_ambush_list))
            report_chunks.append(f"───────────────────")
            
        if portfolio_report_text:
            cleaned_portfolio = portfolio_report_text.strip()
            if cleaned_portfolio:
                report_chunks.append(cleaned_portfolio)
        
        report_text = "\n".join([chunk for chunk in report_chunks if chunk.strip()])
        send_line_notify(report_text)
    else:
        print("📭 今日無符合標的。")

    os._exit(0)

if __name__ == "__main__":
    asyncio.run(main())
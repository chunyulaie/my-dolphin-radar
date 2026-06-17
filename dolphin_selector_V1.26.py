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
# 25.50 參數設定區 (HTML 一頁式儀表板 × 2年自適應體檢完全體)
# ====================================================================
VOLUME_FILTER = 500        
VOLUME_5MA_FILTER = 400    

# 🎯 【手動模擬除名清單】
REMOVE_LIST = [] 

# 🎯 【每檔模擬投入預算】
SIM_BUDGET = 30000         

# 🎯 【全局預設移動停利參數】(當新股剛進場、尚未被優化器洗牌時，以此為防呆初始值)
GLOBAL_TP_THRESHOLD = 0.15   
GLOBAL_TP_DROP = 0.03        

# 🎯 流派一：【起飆股】
MA_SPREAD_LIMIT = 0.035    
BB_COMPRESS_LIMIT = 0.18   

# 🚀 流派二：【真·海豚正飆股】
WAS_COMPRESSED_LIMIT = 0.04 
LOOKBACK_WINDOW = 5        

# 📊 【台股模擬交易成本設定】
FEE_RATE = 0.001425        
FEE_DISCOUNT = 0.28         
TAX_RATE = 0.003            
PORTFOLIO_FILE = r"D:\Python-Training\N100\海豚選股法\dolphin_portfolio.csv" 
HTML_OUTPUT_FILE = r"D:\Python-Training\N100\海豚選股法\dolphin_dashboard.html" # 👉 HTML 儀表板輸出路徑

# 🎯【LINE Messaging API 設定】
LINE_ACCESS_TOKEN = 'uyt/NqkAS3yCOhUAWGqey5HYGBe5mfct1n5MB1OQaV8Y1/X8HoypqNBwq/LOVXk5YnCknVCi8LEE5KZTXkbXT2V0CpOCAk0C/YRPJRA3Z2RREefQjAG41UQV0pbp1YQCnewazDskTwrpBsxHwRo4OQdB04t89/1O/w1cDnyilFU='
TARGET_USER_ID = 'Uf8818996f2c5846640e0ae8ae0360a72'

URL_1000_SHARES = "https://norway.twsthr.info/StockHoldersContinue.aspx?Show=1&continue=Y&weeks=4&growthrate=2&beforeweek=8&price=5000&valuerank=1-3000&display=0"
URL_400_SHARES  = "https://norway.twsthr.info/StockHoldersContinue.aspx?Show=2&continue=Y&weeks=4&growthrate=2&beforeweek=8&price=5000&valuerank=1-3000&display=0"

def run_pre_backtest(api, stock_id):
    """【25.50版·2年動態自適應 AI 預回測體檢】: 拒絕寫死，直接揉入狀態機與兩年時空窮舉，利潤利潤 > 0 才放行"""
    today = datetime.date.today()
    bt_start = (today - datetime.timedelta(days=730)).strftime("%Y-%m-%d") # 👉 同步動態回溯兩年
    bt_end = today.strftime("%Y-%m-%d")
    
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
        df["5WMA"] = df["close"].rolling(window=25).mean()
        df["10WMA"] = df["close"].rolling(window=50).mean()

        # 窮舉篩選最佳利潤
        threshold_range = [t / 100 for t in range(5, 31)]       
        drop_range = [d / 200 for d in range(4, 21)]            
        ma_options = ["5MA", "10MA", "20MA", "5WMA", "10WMA"]
        
        max_possible_profit = -999999
        
        for ma_opt in ma_options:
            for th in threshold_range:
                for dr in drop_range:
                    # 狀態機內部回測
                    in_pos = False
                    b_price = 0.0
                    b_shares = 0
                    m_price = 0.0
                    grand_profit = 0
                    tp_radar_activated = False

                    for i in range(50, len(df)):
                        today_k = df.iloc[i]
                        yesterday_k = df.iloc[i-1]
                        pre_yesterday_k = df.iloc[i-2]
                        c_close = today_k['close']

                        if in_pos:
                            if c_close > m_price: m_price = c_close
                            if ((m_price - b_price) / b_price) >= th: tp_radar_activated = True
                            
                            b_fee = int(b_price * b_shares * FEE_RATE * FEE_DISCOUNT)
                            if b_fee < 20: b_fee = 20
                            s_fee = int(c_close * b_shares * FEE_RATE * FEE_DISCOUNT)
                            if s_fee < 20: s_fee = 20
                            s_tax = int(c_close * b_shares * TAX_RATE)
                            net_p = int((c_close * b_shares - s_fee - s_tax) - (b_price * b_shares + b_fee))
                            
                            if tp_radar_activated and c_close <= (m_price * (1 - dr)):
                                grand_profit += net_p
                                in_pos = False
                                tp_radar_activated = False
                            elif today_k[ma_opt] > 0 and c_close < today_k[ma_opt]:
                                grand_profit += net_p
                                in_pos = False
                                tp_radar_activated = False
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
                                tp_radar_activated = False
                                
                    if grand_profit > max_possible_profit:
                        max_possible_profit = grand_profit
                        
        return max_possible_profit > 0  # 兩年窮舉完，只要最優解能賺錢就放行！
    except:
        return False

def update_and_print_portfolio(api, today_str):
    if not os.path.exists(PORTFOLIO_FILE):
        print("💼 [模擬帳戶] 目前尚無歷史模擬部位。")
        return "", "", []
    
    df_pf = pd.read_csv(PORTFOLIO_FILE, dtype={"stock_id": str})
    if df_pf.empty:
        print("💼 [模擬帳戶] 目前帳戶內無任何股票。")
        return "", "", []
    
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
    html_portfolio_data = [] # 儲存給 HTML 渲染的結構化字典數據
    
    real_today_str = datetime.date.today().strftime("%Y-%m-%d")
    real_start_str = (datetime.date.today() - datetime.timedelta(days=90)).strftime("%Y-%m-%d")
    
    for idx, row in df_pf.iterrows():
        sid = row["stock_id"]
        sname = row["stock_name"]
        b_date = row["buy_date"]
        b_price = float(row["buy_price"])
        shares = int(row["buy_shares"])
        
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
        
        target_tp_price = round(b_price * (1 + tp_th), 2)
        max_price = float(row["max_price"]) if "max_price" in row and not pd.isna(row["max_price"]) else b_price
        if current_price > max_price:
            max_price = current_price
            
        dynamic_lock_price = round(max_price * (1 - tp_dr), 2)
        
        # 1️⃣ 檢查是否滿足動態移動鎖利通報
        if max_price >= target_tp_price and current_price <= dynamic_lock_price:
            exit_msg = f"🎉 鎖利通知：{sid} {sname} 曾創波段高點 {max_price} (已過起跑線 {target_tp_price})，今日收 {current_price} 已跌破黃金鎖利線 {dynamic_lock_price} (高點拉回 {tp_dr*100:.1f}%)！目前波段淨利: {sign}{net_profit}元 ({sign}{profit_percent:.2f}%)"
            print(exit_msg)
            exit_p_rows.append(exit_msg)
            continue # 被鎖利踢出的股票，不記入留存
            
        # 2️⃣ 檢查現價是否「跌破自適應波段停損線」
        if active_stop_loss_value > 0.0 and current_price < active_stop_loss_value:
            exit_msg = f"⚠️ 停損出場：{sid} {sname} 昨收 {current_price} 跌破專屬停損線 {target_ma_line}({active_stop_loss_value:.2f})！零股 {shares} 股強制結算！最終損益: {sign}{net_profit}元 ({sign}{profit_percent:.2f}%)"
            print(exit_msg)
            exit_p_rows.append(exit_msg)
            continue 
            
        tp_status_tag = " 🔥(鎖利雷達監控中!)" if max_price >= target_tp_price else ""
        color_stars = "📈" if net_profit >= 0 else "📉"
        
        p_msg = f"{color_stars} {sid} {sname} | 成本: {b_price} -> 現價: {current_price} [停利起跑價: {target_tp_price} | 當前鎖利線(最高{max_price}): {dynamic_lock_price} | 防守停損({target_ma_line}): {active_stop_loss_value:.2f}]{tp_status_tag} | 損益: {sign}{net_profit}元 ({sign}{profit_percent:.2f}%)"
        print(p_msg)
        report_p_rows.append(p_msg)
        
        # 收集 HTML 格式數據
        html_portfolio_data.append({
            "stock_id": sid, "stock_name": sname, "buy_date": b_date, "buy_price": b_price, "buy_shares": shares,
            "current_price": current_price, "target_tp_price": target_tp_price, "max_price": max_price,
            "dynamic_lock_price": dynamic_lock_price, "target_ma_line": target_ma_line, "stop_loss_value": active_stop_loss_value,
            "net_profit": net_profit, "profit_percent": profit_percent, "radar_active": max_price >= target_tp_price
        })
        
        row["max_price"] = max_price
        survived_rows.append(row)
        
    df_survived = pd.DataFrame(survived_rows)
    if not df_survived.empty:
        df_survived.to_csv(PORTFOLIO_FILE, index=False)
    else:
        # 如果空了，清空檔案
        pd.DataFrame(columns=df_pf.columns).to_csv(PORTFOLIO_FILE, index=False)
        
    print("====================================================\n")
    
    exit_report = "\n🚨 【海豚移動出場警報 · 鎖利目標達成(僅通報)/硬性停損宣示】:\n" + "\n".join(exit_p_rows) + "\n\n=================\n" if exit_p_rows else ""
    portfolio_report = "\n💼 【模擬部位當前淨損益回報】:\n" + "\n".join(report_p_rows) if report_p_rows else ""
    
    return exit_report, portfolio_report, html_portfolio_data

def generate_one_page_html(today_str, breakout_list, ambush_list, portfolio_data):
    """🎨 生成頂級工控美學的一頁式網頁儀表板"""
    
    # 計算持股總資產概況
    total_cost = sum([r['buy_price'] * r['buy_shares'] for r in portfolio_data])
    total_profit = sum([r['net_profit'] for r in portfolio_data])
    total_current_value = total_cost + total_profit
    total_profit_pct = (total_profit / total_cost * 100) if total_cost > 0 else 0.0
    profit_color_class = "text-success" if total_profit >= 0 else "text-danger"
    
    html_content = f"""<!DOCTYPE html>
<html lang="zh-TW">
<head>
    <meta charset="UTF-8">
    <title>海豚量化自適應指揮官儀表板</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
    <style>
        body {{ background-color: #12141c; color: #e4e6eb; font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; }}
        .navbar {{ background-color: #1a1f2c; border-bottom: 2px solid #00f2fe; }}
        .card {{ background-color: #1a1f2c; border: 1px solid #2d3548; border-radius: 12px; margin-bottom: 20px; }}
        .card-header {{ background-color: #22293a; border-bottom: 1px solid #2d3548; font-weight: bold; color: #00f2fe; }}
        .table {{ color: #e4e6eb; margin-bottom: 0; }}
        .table th {{ background-color: #22293a; color: #98a6ad; border-color: #2d3548; font-weight: 600; }}
        .table td {{ border-color: #2d3548; vertical-align: middle; background-color: #1a1f2c; }}
        .text-success {{ color: #2cf3a0 !important; }}
        .text-danger {{ color: #ff5b5b !important; }}
        .badge-breakout {{ background-color: #ff9f43; color: #12141c; font-weight: bold; }}
        .badge-ambush {{ background-color: #00f2fe; color: #12141c; font-weight: bold; }}
        .badge-radar {{ background-color: #ff5b5b; animation: blink 1.5s infinite; font-weight: bold; }}
        @keyframes blink {{ 0% {{ opacity: 0.4; }} 50% {{ opacity: 1; }} 100% {{ opacity: 0.4; }} }}
        .summary-box {{ background: linear-gradient(135deg, #1e2638 0%, #151b29 100%); border-radius: 10px; padding: 15px; border-left: 4px solid #00f2fe; }}
    </style>
</head>
<body>

<nav class="navbar navbar-dark px-4 py-3">
    <span class="navbar-brand mb-0 h1 fs-3">🐬 海豚量化自適應指揮官儀表板 <small class="fs-6 text-muted">v25.50 完全體</small></span>
    <span class="text-muted">📅 數據更新時間：{today_str}</span>
</nav>

<div class="container-fluid p-4">
    <div class="row mb-4">
        <div class="col-md-3">
            <div class="summary-box">
                <div class="text-muted small">當前持股總成本</div>
                <div class="fs-3 fw-bold text-info">${{total_cost:,.0f}} 元</div>
            </div>
        </div>
        <div class="col-md-3">
            <div class="summary-box" style="border-left-color: #2cf3a0;">
                <div class="text-muted small">持股現值估算</div>
                <div class="fs-3 fw-bold">${{total_current_value:,.0f}} 元</div>
            </div>
        </div>
        <div class="col-md-4">
            <div class="summary-box" style="border-left-color: ${{ '#2cf3a0' if total_profit >= 0 else '#ff5b5b' }};">
                <div class="text-muted small">模擬持股當前總淨損益</div>
                <div class="fs-3 fw-bold {profit_color_class}">{'+' if total_profit >= 0 else ''}${{total_profit:,.0f}} 元 ({'+' if total_profit >= 0 else ''}{{total_profit_pct:.2f}}%)</div>
            </div>
        </div>
    </div>

    <div class="row">
        <div class="col-12 col-xl-8">
            <div class="card">
                <div class="card-header fs-5">💼 實戰持股狀態機雙向防線即時雷達</div>
                <div class="table-responsive">
                    <table class="table table-hover">
                        <thead>
                            <tr>
                                <th>代號/名稱</th>
                                <th>買入日期</th>
                                <th>成本價</th>
                                <th>目前價</th>
                                <th>起跑門檻</th>
                                <th>鎖利線(最高)</th>
                                <th>生命均線(停損價)</th>
                                <th>當前損益</th>
                                <th>雷達狀態</th>
                            </tr>
                        </thead>
                        <tbody>
    """
    
    if not portfolio_data:
        html_content += '<tr><td colspan="9" class="text-center text-muted py-4">目前記帳簿內無任何持股。</td></tr>'
    else:
        for p in portfolio_data:
            p_sign = "+" if p['net_profit'] >= 0 else ""
            p_class = "text-success" if p['net_profit'] >= 0 else "text-danger"
            radar_badge = '<span class="badge badge-radar">🔥 監控中</span>' if p['radar_active'] else '<span class="text-muted small">未開啟</span>'
            
            html_content += f"""
                            <tr>
                                <td class="fw-bold">{p['stock_id']} {p['stock_name']}</td>
                                <td class="small text-muted">{p['buy_date']}</td>
                                <td>{p['buy_price']:.2f} <small class="text-muted">({p['buy_shares']}股)</small></td>
                                <td class="fw-bold text-warning">{p['current_price']:.2f}</td>
                                <td>{p['target_tp_price']:.2f}</td>
                                <td><span class="text-info">{p['dynamic_lock_price']:.2f}</span> <small class="text-muted">({p['max_price']:.2f})</small></td>
                                <td><span class="text-danger">{p['stop_loss_value']:.2f}</span> <small class="text-muted">({p['target_ma_line']})</small></td>
                                <td class="fw-bold {p_class}">{p_sign}{p['net_profit']:,}元<br><small>{p_sign}{p['profit_percent']:.2f}%</small></td>
                                <td>{radar_badge}</td>
                            </tr>
            """
            
    html_content += """
                        </tbody>
                    </table>
                </div>
            </div>
        </div>

        <div class="col-12 col-xl-4">
            <div class="card">
                <div class="card-header fs-5">🚀【真·正飆股 · 動能突破擊潰區】</div>
                <ul class="list-group list-group-flush" style="background-color: #1a1f2c;">
    """
    
    if not breakout_list:
        html_content += '<li class="list-group-item bg-transparent text-muted small py-3">今日無剛發動的動能飆股。</li>'
    else:
        for bo in breakout_list:
            html_content += f'<li class="list-group-item bg-transparent text-white border-secondary py-3">{bo.replace("▪️ ", "")}</li>'
            
    html_content += """
                </ul>
            </div>

            <div class="card">
                <div class="card-header fs-5">🎯【準·起飆股 · 鱷魚潛伏地底區】</div>
                <ul class="list-group list-group-flush" style="background-color: #1a1f2c;">
    """
    
    if not ambush_list:
        html_content += '<li class="list-group-item bg-transparent text-muted small py-3">今日無符合均線糾結壓縮的標的。</li>'
    else:
        for am in ambush_list:
            html_content += f'<li class="list-group-item bg-transparent text-white border-secondary py-3">{am}</li>'
            
    html_content += f"""
                </ul>
            </div>
        </div>
    </div>
</div>

<footer class="text-center py-4 text-muted small mt-4" style="border-top: 1px solid #2d3548;">
    海豚自動化管線系統 · 每日盤後自動化更新完成
</footer>

</body>
</html>
"""
    
    with open(HTML_OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write(html_content)
    print(f"🖥️  [儀表板升級] 頂級工控 HTML 儀表板已成功生成於：{HTML_OUTPUT_FILE}")

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
    print("🚀 海豚選股 25.50：[HTML一頁式儀表板完全體] 啟動...")
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
                        print(f"🔬 偵測到發動標的：{display_title}，強行啟動 2年AI體檢...")
                        if run_pre_backtest(api, stock):
                            calc_shares = int(SIM_BUDGET // latest_close)
                            if calc_shares > 0:
                                k_line_date = str(df_raw.iloc[-1]["date"])[:10]
                                new_sim_buys.append({
                                    "stock_id": stock, "stock_name": c_name, 
                                    "buy_price": latest_close, "buy_shares": calc_shares, 
                                    "buy_type": "正飆(0天)", "buy_date": k_line_date,
                                    "best_tp": GLOBAL_TP_THRESHOLD, "best_drop": GLOBAL_TP_DROP, "best_ma": "20MA", "max_price": latest_close # 先給預設
                                })
                                print(f"✅ [體檢過關] {display_title} 兩年最優期望值為正，核准寫入帳簿！")
                        else:
                            print(f"❌ [體檢失敗] {display_title} 兩年歷史最優解依然虧損！直接封殺拒絕建倉！")

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
                            print(f"🔬 偵測到滿星起飆：{display_title}，強行啟動 2年AI體檢...")
                            if run_pre_backtest(api, stock):
                                calc_shares = int(SIM_BUDGET // latest_close)
                                if calc_shares > 0:
                                    k_line_date = str(df_raw.iloc[-1]["date"])[:10]
                                    new_sim_buys.append({
                                        "stock_id": stock, "stock_name": c_name, 
                                        "buy_price": latest_close, "buy_shares": calc_shares, 
                                        "buy_type": "3星起飆", "buy_date": k_line_date,
                                        "best_tp": GLOBAL_TP_THRESHOLD, "best_drop": GLOBAL_TP_DROP, "best_ma": "20MA", "max_price": latest_close # 先給預設
                                    })
                                    print(f"✅ [體檢過關] {display_title} 兩年最優期望值為正，核准寫入帳簿！")
                            else:
                                print(f"❌ [體檢失敗] {display_title} 兩年歷史最優解依然虧損！直接封殺拒絕建倉！")
                
        except Exception as e:
            pass
        time.sleep(0.03)

    if new_sim_buys:
        df_new = pd.DataFrame(new_sim_buys)
        if not os.path.exists(PORTFOLIO_FILE):
            df_new.to_csv(PORTFOLIO_FILE, index=False)
        else:
            # 讀取現有欄位順序對齊寫入
            df_existing_cols = pd.read_csv(PORTFOLIO_FILE, nrows=1)
            for col in df_existing_cols.columns:
                if col not in df_new.columns:
                    df_new[col] = None
            df_new = df_new[df_existing_cols.columns]
            df_new.to_csv(PORTFOLIO_FILE, mode='a', header=False, index=False)
        print(f"\n📝 [模擬記帳] 成功通過體檢並建倉零股：{', '.join([r['stock_name'] for r in new_sim_buys])}")

    # ─── 現場優化器調度攔截 ───
    print("\n⚡ [因果攔截] 今日新股建倉完畢。正在同一資料夾內即時導入優化器外掛...")
    try:
        import dolphin_portfolio_optimizer_v2_2 as d_opt
        d_opt.main() 
        print("⚡ [因果攔截] 優化器解碼完畢。持股 CSV 參數已全部更新，重回主程式主線。")
    except Exception as opt_err:
        print(f"⚠️ [因果攔截] 自動導入優化器失敗（錯誤: {opt_err}），將以預設防呆參數繼續。")

    print("----------------------------------------------------")
    print("====================================================")
    
    # 建立 LINE 與 HTML 所需的選股清單
    final_breakout_list = []
    html_breakout_strings = []
    if raw_breakout_data:
        df_bo = pd.DataFrame(raw_breakout_data)
        df_bo = df_bo.sort_values(by="days_ago", ascending=True)
        for _, row in df_bo.iterrows():
            time_label = "今天剛發動" if row["days_ago"] == 0 else f"{row['days_ago']}天前發動"
            msg = f"▪️ {row['title']} ({time_label})\n  [均線糾結: {row['spread']*100:.1f}% | 布林: {row['bb']*100:.1f}%]"
            final_breakout_list.append(msg)
            
            html_msg = f'<span class="badge badge-breakout me-2">{time_label}</span> <strong>{row["title"]}</strong> <br> <span class="text-muted small">現價: {row["close"]} | 均線糾結: {row["spread"]*100:.1f}% | 布林寬度: {row["bb"]*100:.1f}%</span>'
            html_breakout_strings.append(html_msg)

    final_ambush_list = []
    html_ambush_strings = []
    if raw_ambush_data:
        df_am = pd.DataFrame(raw_ambush_data)
        df_am = df_am.sort_values(by="spread", ascending=True)
        for _, row in df_am.iterrows():
            msg = f"{row['stars']} {row['title']}\n  [均線: {row['spread']*100:.1f}% | 布林: {row['bb']*100:.1f}% | MACD: {row['macd']}]"
            final_ambush_list.append(msg)
            
            html_msg = f'<span class="badge badge-ambush me-2">{row["stars"]}潛伏</span> <strong>{row["title"]}</strong> <br> <span class="text-muted small">現價: {row["close"]} | 均線張開度: {row["spread"]*100:.1f}% | MACD: {row["macd"]}</span>'
            html_ambush_strings.append(html_msg)

    # 🎯 核心防線：在優化器洗牌滅殺之後，再呼叫一次，拿最新的大帳數據更新
    exit_report_text, portfolio_report_text, html_portfolio_data = update_and_print_portfolio(api, today_str)

    # 🎨 渲染並輸出網頁儀表板
    generate_one_page_html(today_str, html_breakout_strings, html_ambush_strings, html_portfolio_data)

    # 發送 LINE 通知
    if final_breakout_list or final_ambush_list or exit_report_text:
        report_chunks = [
            f"🐬 海豚選股 25.50 [雙向自適應移動鎖利完全體] 🐬",
            f"📅 數據日期：{today_str}",
            f"───────────────────"
        ]
        if exit_report_text:
            cleaned_exit = exit_report_text.strip()
            if cleaned_exit:
                report_chunks.extend([cleaned_exit, f"───────────────────"])
        if final_breakout_list:
            report_chunks.extend([f"🚀【真·正飆股 · 動能突破擊潰區】", "\n".join(final_breakout_list), f"───────────────────"])
        if final_ambush_list:
            report_chunks.extend([f"🎯【準·起飆股 · 鱷魚潛伏地底區】", "\n".join(final_ambush_list), f"───────────────────"])
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
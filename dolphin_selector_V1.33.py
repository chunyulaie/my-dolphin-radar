import asyncio, datetime, logging, os, time, requests, subprocess  
from FinMind.data import DataLoader
import pandas as pd
from pyppeteer import launch

logging.getLogger('pyppeteer').setLevel(logging.CRITICAL)
logging.getLogger('websockets').setLevel(logging.CRITICAL)
logging.getLogger('FinMind').setLevel(logging.CRITICAL)

# ====================================================================
# 26.02 參數設定區 (方案2落難老兵入榜 × 官方API校正完全體)
# ====================================================================
VOLUME_FILTER = 500; VOLUME_5MA_FILTER = 400; REMOVE_LIST = [] 
INIT_POOL_BUDGET = 250000; MIN_STOCK_BUDGET = 15000     
GLOBAL_TP_THRESHOLD = 0.15; GLOBAL_TP_DROP = 0.03        
MA_SPREAD_LIMIT = 0.035; BB_COMPRESS_LIMIT = 0.18   
WAS_COMPRESSED_LIMIT = 0.04; LOOKBACK_WINDOW = 5        
FEE_RATE = 0.001425; FEE_DISCOUNT = 0.28; TAX_RATE = 0.003            

PORTFOLIO_FILE = r"D:\Python-Training\N100\海豚選股法\dolphin_portfolio.csv" 
HTML_OUTPUT_FILE = r"D:\Python-Training\N100\海豚選股法\index.html" 
HISTORY_LEDGER_FILE = r"D:\Python-Training\N100\海豚選股法\dolphin_history_ledger.csv" 
OPTIMIZER_DETAILS_FILE = r"D:\Python-Training\N100\海豚選股法\dolphin_optimizer_details.csv"
WATCHLIST_FILE = r"D:\Python-Training\N100\海豚選股法\dolphin_watchlist.csv" 

LINE_ACCESS_TOKEN = 'uyt/NqkAS3yCOhUAWGqey5HYGBe5mfct1n5MB1OQaV8Y1/X8HoypqNBwq/LOVXk5YnCknVCi8LEE5KZTXkbXT2V0CpOCAk0C/YRPJRA3Z2RREefQjAG41UQV0pbp1YQCnewazDskTwrpBsxHwRo4OQdB04t89/1O/w1cDnyilFU='
TARGET_USER_ID = 'Uf8818996f2c5846640e0ae8ae0360a72'
URL_1000_SHARES = "https://norway.twsthr.info/StockHoldersContinue.aspx?Show=1&continue=Y&weeks=4&growthrate=2&beforeweek=8&price=5000&valuerank=1-3000&display=0"
URL_400_SHARES  = "https://norway.twsthr.info/StockHoldersContinue.aspx?Show=2&continue=Y&weeks=4&growthrate=2&beforeweek=8&price=5000&valuerank=1-3000&display=0"

def send_line_notify(message):
    url = 'https://api.line.me/v2/bot/message/push'
    headers = { 'Content-Type': 'application/json', 'Authorization': f'Bearer {LINE_ACCESS_TOKEN}' }
    payload = { 'to': TARGET_USER_ID, 'messages': [{'type': 'text', 'text': message}] }
    try:
        requests.post(url, headers=headers, json=payload)
        print("📲 [系統通知] LINE 戰報即時推播成功！")
    except Exception as line_err:
        print(f"⚠️ [系統通知] LINE 發送失敗（原因: {line_err}）")

def log_to_history_ledger(row, current_price, net_profit, profit_percent, exit_reason):
    new_entry = {
        "stock_id": str(row["stock_id"]).strip(), "stock_name": row["stock_name"], "buy_date": row["buy_date"],
        "buy_price": float(row["buy_price"]), "buy_shares": int(row["buy_shares"]),
        "sell_date": datetime.date.today().strftime("%Y-%m-%d"), "sell_price": current_price,
        "net_profit": int(net_profit), "profit_percent": round(profit_percent, 2), "exit_reason": exit_reason
    }
    df_new = pd.DataFrame([new_entry])
    df_new.to_csv(HISTORY_LEDGER_FILE, mode='a', header=not os.path.exists(HISTORY_LEDGER_FILE), index=False, encoding="utf-8-sig")

def run_pre_backtest(api, stock_id):
    today = datetime.date.today()
    df_raw = api.taiwan_stock_daily_adaptive(stock_id=stock_id, start_date=(today - datetime.timedelta(days=730)).strftime("%Y-%m-%d"), end_date=today.strftime("%Y-%m-%d"))
    if df_raw.empty or len(df_raw) < 50: return 0  
    df = pd.DataFrame()
    df["close"] = df_raw["close"].astype(float); df["open"] = df_raw["open"].astype(float)
    df["high"] = df_raw["max"].astype(float); df["volume"] = df_raw["Trading_Volume"].astype(float) / 1000 
    df["5MA"] = df["close"].rolling(5).mean(); df["10MA"] = df["close"].rolling(10).mean(); df["20MA"] = df["close"].rolling(20).mean()
    df["5MA_Vol"] = df["volume"].rolling(5).mean(); df['20STD'] = df['close'].rolling(20).std(ddof=0)
    df['BB_Width'] = ((df['20MA'] + 2*df['20STD']) - (df['20MA'] - 2*df['20STD'])) / df['20MA']
    df['EMA12'] = df['close'].ewm(span=12, adjust=False).mean(); df['EMA26'] = df['close'].ewm(span=26, adjust=False).mean()
    df['MACD'] = df['EMA12'] - df['EMA26']
    df["5WMA"] = df["close"].rolling(25).mean(); df["10WMA"] = df["close"].rolling(50).mean()

    max_possible_profit = 0
    for ma_opt in ["5MA", "10MA", "20MA", "5WMA", "10WMA"]:
        for th in [0.1, 0.15, 0.2, 0.25]:
            for dr in [0.02, 0.03, 0.04]:
                in_pos = False; b_price = 0.0; b_shares = 0; m_price = 0.0; grand_profit = 0; tp_radar = False
                for i in range(50, len(df)):
                    t_k = df.iloc[i]; y_k = df.iloc[i-1]; p_y_k = df.iloc[i-2]; c_close = t_k['close']
                    if in_pos:
                        if c_close > m_price: m_price = c_close
                        if ((m_price - b_price) / b_price) >= th: tp_radar = True
                        net_p = int((c_close * b_shares * (1 - TAX_RATE)) - (b_price * b_shares))
                        if tp_radar and c_close <= (m_price * (1 - dr)):
                            grand_profit += net_p; in_pos = False; tp_radar = False
                        elif t_k[ma_opt] > 0 and c_close < t_k[ma_opt]:
                            grand_profit += net_p; in_pos = False; tp_radar = False
                    else:
                        if t_k["volume"] < 500 or t_k["5MA_Vol"] < 400: continue
                        if p_y_k["close"] <= 0: continue
                        if (((y_k["close"] - p_y_k["close"]) / p_y_k["close"]) * 100) >= 9.8 and y_k["close"] == y_k["high"]: continue
                        y_ma = [p_y_k["5MA"], p_y_k["10MA"], p_y_k["20MA"]]
                        if (max(y_ma) - min(y_ma)) / p_y_k["close"] <= 0.04 and y_k["close"] > y_k["open"] and c_close >= max(t_k["5MA"], t_k["10MA"], t_k["20MA"]):
                            in_pos = True; b_price = c_close; b_shares = int(30000 // c_close); m_price = c_close; tp_radar = False
                if grand_profit > max_possible_profit: max_possible_profit = grand_profit
    return max_possible_profit

def update_and_print_portfolio(api, today_str):
    df_pf = pd.read_csv(PORTFOLIO_FILE, dtype={"stock_id": str})
    survived_rows = []; report_p_rows = []; exit_p_rows = []; html_portfolio_data = []
    real_today_str = datetime.date.today().strftime("%Y-%m-%d") if datetime.datetime.now().time() >= datetime.time(15, 0, 0) else (datetime.date.today() - datetime.timedelta(days=1)).strftime("%Y-%m-%d")
    real_start_str = (datetime.datetime.strptime(real_today_str, "%Y-%m-%d").date() - datetime.timedelta(days=150)).strftime("%Y-%m-%d")
    
    # 用於儲存今日因為方案2觸發「留校察看第1天」的老兵名單
    v134_落難老兵名單 = []

    for idx, row in df_pf.iterrows():
        sid = str(row["stock_id"]).strip(); sname = row["stock_name"]; b_date = row["buy_date"]; b_price = float(row["buy_price"]); shares = int(row["buy_shares"])
        break_days = int(row["break_days_count"]) if "break_days_count" in row and not pd.isna(row["break_days_count"]) else 0
        tp_th = float(row["best_tp"]) if "best_tp" in row and not pd.isna(row["best_tp"]) else GLOBAL_TP_THRESHOLD
        tp_dr = float(row["best_drop"]) if "best_drop" in row and not pd.isna(row["best_drop"]) else GLOBAL_TP_DROP
        target_ma_line = str(row["best_ma"]).strip() if "best_ma" in row and not pd.isna(row["best_ma"]) else "20MA"
        
        try:
            df_now = api.taiwan_stock_daily_adaptive(stock_id=sid, start_date=real_start_str, end_date=real_today_str)
            if df_now.empty or len(df_now) < 5:
                print(f"🛑 [API 警告] {sid} 回傳數據為空，跳過防線體檢。")
                survived_rows.append(row); continue
                
            current_price = float(df_now.iloc[-1]["close"]); today_high = float(df_now.iloc[-1]["max"])
            df_now = df_now.copy().reset_index(drop=True); df_now["close"] = df_now["close"].astype(float)
            df_now["5MA"] = df_now["close"].rolling(5).mean(); df_now["10MA"] = df_now["close"].rolling(10).mean(); df_now["20MA"] = df_now["close"].rolling(20).mean()
            df_now["5WMA"] = df_now["close"].rolling(25).mean(); df_now["10WMA"] = df_now["close"].rolling(50).mean()
            active_stop_loss_value = float(df_now.iloc[-1][target_ma_line])
        except Exception as e:
            print(f"🛑 [API 崩潰] {sid} 撈取失敗（錯誤: {e}），強制鎖定在倉狀態防禦誤殺。")
            survived_rows.append(row); continue
            
        buy_spent = (b_price * shares) + max(20, int(b_price * shares * FEE_RATE * FEE_DISCOUNT))
        sell_get = (current_price * shares) - max(20, int(current_price * shares * FEE_RATE * FEE_DISCOUNT)) - int(current_price * shares * TAX_RATE)
        net_profit = int(sell_get - buy_spent); profit_percent = (net_profit / buy_spent) * 100; sign = "+" if net_profit >= 0 else ""
        target_tp_price = round(b_price * (1 + tp_th), 2)
        max_price = max(today_high, float(row["max_price"]) if "max_price" in row and not pd.isna(row["max_price"]) else b_price)
        dynamic_lock_price = round(max_price * (1 - tp_dr), 2)
        
        if max_price >= target_tp_price and current_price <= dynamic_lock_price:
            exit_p_rows.append(f"🎉 鎖利通知：{sid} {sname} 今日收盤 {current_price} 跌破鎖利線 {dynamic_lock_price}，淨利: {sign}{net_profit}元")
            log_to_history_ledger(row, current_price, net_profit, profit_percent, f"移動鎖利({tp_dr*100:.1f}%)"); continue 
            
        if active_stop_loss_value > 0.0 and current_price < active_stop_loss_value:
            break_days += 1
            if break_days >= 2:
                exit_p_rows.append(f"⚠️ 停損出場：{sid} {sname} 連續2天收盤跌破 {target_ma_line} 防線，最終損益: {sign}{net_profit}元")
                log_to_history_ledger(row, current_price, net_profit, profit_percent, f"跌破均線({target_ma_line}·2日確認)"); continue
            else:
                exit_p_rows.append(f"⏳ [防線警戒] {sid} {sname} 今日收盤跌破 {target_ma_line}，進入留校察看第 1 天！")
                # 🎯 方案2：實打實捕獲跌破均線的老兵，準備送進觀察名單
                v134_落難老兵名單.append({"stock_id": sid, "stock_name": sname, "close": current_price})
        else:
            break_days = 0
            
        tp_tag = " 🔥(監控中)" if max_price >= target_tp_price else ""
        if break_days == 1: tp_tag += " ⏳(警戒)"
        report_p_rows.append(f"{'📈' if net_profit>=0 else '📉'} {sid} {sname} | 現價: {current_price} | 損益: {sign}{net_profit}元 ({sign}{profit_percent:.2f}%)")
        
        html_portfolio_data.append({
            "stock_id": sid, "stock_name": sname, "buy_date": b_date, "buy_price": b_price, "buy_shares": shares,
            "current_price": current_price, "target_tp_price": target_tp_price, "max_price": max_price,
            "dynamic_lock_price": dynamic_lock_price, "target_ma_line": target_ma_line, "stop_loss_value": active_stop_loss_value,
            "net_profit": net_profit, "profit_percent": profit_percent, "radar_active": max_price >= target_tp_price, "break_days": break_days
        })
        row["max_price"] = max_price; row["break_days_count"] = break_days; survived_rows.append(row)
        
    pd.DataFrame(survived_rows).to_csv(PORTFOLIO_FILE, index=False)
    
    # 將今日撈到的落難老兵名單，透過全域環境存取，等一下跟 3星新秀一起進行觀察名單的大對齊與去重
    global GLOBAL_V134_落難老兵; GLOBAL_V134_落難老兵 = v134_落難老兵名單
    
    return "\n".join(exit_p_rows), "\n".join(report_p_rows), html_portfolio_data

def generate_one_page_html(today_str, breakout_list, ambush_list, portfolio_data):
    total_cost = sum([r['buy_price'] * r['buy_shares'] for r in portfolio_data])
    total_profit = sum([r['net_profit'] for r in portfolio_data])
    total_current = total_cost + total_profit
    total_pct = (total_profit / total_cost * 100) if total_cost > 0 else 0.0
    
    profit_color_class = "text-taiwan-red" if total_profit >= 0 else "text-taiwan-green"
    hist_summary_html = ""; ledger_rows_html = ""
    if os.path.exists(HISTORY_LEDGER_FILE):
        try:
            df_h = pd.read_csv(HISTORY_LEDGER_FILE)
            hist_prof = df_h["net_profit"].sum(); hist_count = len(df_h)
            hist_win = len(df_h[df_h["net_profit"] > 0])
            hist_wr = (hist_win / hist_count * 100) if hist_count > 0 else 0.0
            hist_summary_html = f'<div class="col-md-2"><div class="summary-box" style="border-left-color: #ff9f43;"><div class="text-muted-custom small">歷史已結算戰績</div><div class="fs-4 fw-bold text-taiwan-red">{hist_prof:,.0f} 元</div></div></div><div class="col-md-2"><div class="summary-box" style="border-left-color: #00f2fe;"><div class="text-muted-custom small">歷史勝率/單數</div><div class="fs-4 fw-bold text-white">{hist_wr:.1f}% ({hist_count}單)</div></div></div>'
            for _, h_row in df_h.iloc[::-1].iterrows():
                ledger_rows_html += f"<tr><td>{h_row['stock_id']} {h_row['stock_name']}</td><td>{h_row['buy_date']} ~ {h_row['sell_date']}</td><td>{h_row['buy_price']:.2f} → {h_row['sell_price']:.2f}</td><td>{int(h_row['buy_shares'])} 股</td><td class='text-taiwan-red'>{h_row['net_profit']:,}元 ({h_row['profit_percent']:.1f}%)</td><td>{h_row['exit_reason']}</td></tr>"
        except: pass
    if not hist_summary_html: hist_summary_html = '<div class="col-md-4"><div class="summary-box"><div class="fs-4 text-muted-custom">尚無歷史數據</div></div></div>'
    if not ledger_rows_html: ledger_rows_html = '<tr><td colspan="6" class="text-center text-muted-custom py-3">暫無已清算戰績。</td></tr>'

    wl_rows = ""
    if os.path.exists(WATCHLIST_FILE):
        try:
            df_w = pd.read_csv(WATCHLIST_FILE, dtype={"stock_id": str})
            for _, w_r in df_w.iterrows():
                # 網頁 UI 特殊標記：如果是落難老兵，顯示為均線警戒，如果是新秀顯示為滿星新秀
                lbl_tag = "⚠️ 均線警戒" if "均線警戒" in str(w_r['評等']) else "⭐⭐⭐ 新秀"
                wl_rows += f"<tr><td class='text-info fw-bold'>{w_r['stock_id']} {w_r['stock_name']}</td><td>{lbl_tag}</td><td>{w_r['初次評選日']}</td><td>{w_r['當初潛伏價格']:.2f}</td><td class='text-warning fw-bold'>{w_r['目前最新收盤']:.2f}</td><td>觀測 {int(w_r['已觀測天數'])} 天</td></tr>"
        except: pass
    if not wl_rows: wl_rows = '<tr><td colspan="6" class="text-center text-muted-custom py-2 small">觀測哨站目前空棚。</td></tr>'

    portfolio_tbody = ""
    for p in portfolio_data:
        p_class = "text-taiwan-red" if p['net_profit'] >= 0 else "text-taiwan-green"
        w_pct = ((p['buy_price'] * p['buy_shares']) / 250000) * 100
        r_tag = '<span class="badge bg-warning text-dark">⏳ 留校察看</span>' if p['break_days'] == 1 else ('<span class="badge badge-radar">🔥 監控中</span>' if p['radar_active'] else '<span class="text-muted-custom small">未開啟</span>')
        portfolio_tbody += f"<tr><td><strong>{p['stock_id']} {p['stock_name']}</strong><br><small class='text-muted-custom'>(比重: {w_pct:.1f}%)</small></td><td>{p['buy_date']}</td><td>{p['buy_price']:.2f} ({p['buy_shares']}股)</td><td class='text-warning fw-bold'>{p['current_price']:.2f}</td><td>{p['target_tp_price']:.2f}</td><td>{p['dynamic_lock_price']:.2f} ({p['max_price']:.2f})</td><td class='text-danger'>{p['stop_loss_value']:.2f} ({p['target_ma_line']})</td><td class='fw-bold {p_class}'>{p['net_profit']:,}元<br><small>{p['profit_percent']:.2f}%</small></td><td>{r_tag}</td></tr>"

    html_content = f"""<!DOCTYPE html>
<html lang="zh-TW"><head><meta charset="UTF-8"><title>海豚自適應指揮官儀表板</title><link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet"><script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/js/bootstrap.bundle.min.js"></script><style>body {{ background-color: #12141c; color: #e4e6eb; font-family: sans-serif; }} .navbar {{ background-color: #1a1f2c; border-bottom: 2px solid #ff4a4a; }} .card {{ background-color: #1a1f2c; border: 1px solid #2d3548; border-radius: 12px; margin-bottom: 20px; }} .card-header {{ background-color: #22293a; border-bottom: 1px solid #2d3548; font-weight: bold; color: #00f2fe; }} .table-custom-dark th {{ background-color: #22293a !important; color: #00f2fe !important; }} .table-custom-dark td {{ background-color: #1a1f2c !important; color: #fff !important; border-color: #2d3548 !important; }} .text-taiwan-red {{ color: #ff4a4a !important; font-weight: bold; }} .text-taiwan-green {{ color: #2cf3a0 !important; font-weight: bold; }} .text-muted-custom {{ color: #a1a5b7 !important; }} .summary-box {{ background: #1e2638; border-radius: 10px; padding: 15px; border-left: 4px solid #00f2fe; }} .badge-radar {{ background-color: #ff4a4a; animation: blink 1.5s infinite; }} @keyframes blink {{ 0%, 100% {{ opacity: 0.4; }} 50% {{ opacity: 1; }} }}</style></head>
<body><nav class="navbar navbar-dark px-4 py-3"><span class="navbar-brand mb-0 h1 fs-3">🐬 海豚量化自適應指揮官儀表板 <small class="fs-6 text-muted-custom">v26.02 智能完全體版</small></span><span class="text-muted-custom">📅 更新時間：{today_str}</span></nav>
<div class="container-fluid p-4"><div class="row mb-4"><div class="col-md-2"><div class="summary-box"><div class="text-muted-custom small">當前持股成本</div><div class="fs-4 fw-bold text-info">${total_cost:,.0f} 元</div></div></div><div class="col-md-2"><div class="summary-box" style="border-left-color: #fff;"><div class="text-muted-custom small">持股現值估算</div><div class="fs-4 fw-bold text-white">${total_current:,.0f} 元</div></div></div><div class="col-md-4"><div class="summary-box" style="border-left-color: #ff4a4a;"><div class="text-muted-custom small">在倉持股總淨損益</div><div class="fs-4 fw-bold {profit_color_class}">{total_profit:,.0f} 元 ({total_pct:.2f}%)</div></div></div>{hist_summary_html}</div>
<div class="row"><div class="col-12 col-xl-8"><div class="card"><div class="card-header fs-5">💼 實戰持股狀態機雙向防線即時雷達</div><div class="table-responsive"><table class="table table-custom-dark mb-0"><thead><tr><th>代號/名稱</th><th>買入日期</th><th>成本價</th><th>目前價</th><th>起跑門檻</th><th>鎖利線(最高)</th><th>生命均線(停損)</th><th>當前損益</th><th>雷達狀態</th></tr></thead><tbody>{portfolio_tbody}</tbody></table></div></div>
<div class="card mt-4"><div class="card-header fs-5 text-info">🔍 📂 歷史評選 · 3星新秀與方案2落難老兵動態留校察看哨站</div><div class="table-responsive"><table class="table table-custom-dark mb-0 text-center small"><thead><tr><th>代號/名稱</th><th>狀態屬性</th><th>捕獲/警戒日</th><th>當初潛伏/防線價</th><th>目前最新收盤</th><th>生命流狀態</th></tr></thead><tbody>{wl_rows}</tbody></table></div></div>
<div class="card mt-4"><div class="card-header fs-5 bg-dark"><button class="btn btn-link text-decoration-none fw-bold fs-5 w-100 text-start p-0 text-info" type="button" data-bs-toggle="collapse" data-bs-target="#ledgerCollapse">📋 📂 [點擊展開] 📊 歷史戰績移動清算回顧與策略檢討本本</button></div><div class="collapse" id="ledgerCollapse"><div class="table-responsive"><table class="table table-custom-dark mb-0 text-center small"><thead><tr style="color: #ff9f43;"><th>代號/名稱</th><th>實戰交易時空區間</th><th>進場 → 出場價</th><th>結算股數</th><th>實打實淨損益</th><th>💀 戰略離場檢討原因</th></tr></thead><tbody>{ledger_rows_html}</tbody></table></div></div></div></div>
<div class="col-12 col-xl-4"><div class="card"><div class="card-header fs-5">🚀【真·正飆股 · 動能突破擊潰區】</div><ul class="list-group list-group-flush">"""
    for bo in breakout_list if breakout_list else ['<li class="list-group-item bg-transparent text-muted-custom small py-3">今日無剛發動標的。</li>']:
        html_content += f'<li class="list-group-item bg-transparent text-white border-secondary py-3">{bo}</li>'
    html_content += """</ul></div><div class="card"><div class="card-header fs-5">🎯【準·起飆股 · 鱷魚潛伏地底區】</div><ul class="list-group list-group-flush">"""
    for am in ambush_list if ambush_list else ['<li class="list-group-item bg-transparent text-white border-secondary py-3">今日無糾結壓縮標的。</li>']:
        html_content += f'<li class="list-group-item bg-transparent text-white border-secondary py-3">{am}</li>'
    html_content += """</ul></div></div></div></div><footer class="text-center py-4 text-muted-custom small mt-4" style="border-top: 1px solid #2d3548;">海豚自動化管線系統 · 每日盤後自動化更新完成</footer></body></html>"""
    
    with open(HTML_OUTPUT_FILE, "w", encoding="utf-8") as f: f.write(html_content)

async def parse_page_codes(page, url, label):
    try:
        await page.goto(url, {'waitUntil': 'networkidle2', 'timeout': 30000}); await asyncio.sleep(2) 
        return await page.evaluate('''() => {
            const rows = document.querySelectorAll('#details > tbody > tr'); const result = [];
            rows.forEach(row => {
                const a = row.querySelector('a'); const pctTag = row.querySelector('td:nth-child(7) font p'); 
                if (a && pctTag) {
                    const fullText = a.innerText ? a.innerText.trim() : ""; const pctText = pctTag.innerText ? pctTag.innerText.trim() : "0";
                    if (fullText.length >= 4) {
                        const code = fullText.substring(0, 4);
                        if (!isNaN(code) && code.trim().length === 4 && parseFloat(pctText) >= 50.0) result.push(code);
                    }
                }
            }); return result;
        }''')
    except: return []

async def fetch_union_pyramid_pool():
    print("🌐 正在背景啟動 Chromium 無頭瀏覽器...")
    browser = await launch(headless=True, userDataDir='./pyppeteer_cache', args=['--no-sandbox', '--disable-setuid-sandbox'])
    try:
        page = await browser.newPage(); await page.setUserAgent("Mozilla/5.0")
        p1000 = await parse_page_codes(page, URL_1000_SHARES, "核心大戶")
        p400 = await parse_page_codes(page, URL_400_SHARES, "波段主力")
        await browser.close(); union_pool = sorted(list(set(p1000).union(set(p400))))
        print(f"🎯 絕對控盤大聯軍總數：{len(union_pool)} 檔\n")
        return union_pool
    except: return []

async def main():
    print("====================================================")
    print("🚀 海豚選股 26.01：[方案2落難老兵自動入榜完全體] 啟動...")
    print("====================================================")
    STOCK_POOL = await fetch_union_pyramid_pool()
    if not STOCK_POOL: return

    api = DataLoader()
    api.login_by_token(api_token="eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9.eyJ1c2VyX2lkIjoicGNoaW9uMjAwMiIsImVtYWlsIjoibGFpZWNodW55dUBnbWFpbC5jb20iLCJ0b2tlbl92ZXJzaW9uIjowfQ.si_2Ta3AlY1JtgVBDlqpnkaK3IH41Drrc7ogVgNBJq8")
    try:
        df_info = api.taiwan_stock_info()
        dynamic_name_dict = dict(zip(df_info["stock_id"], df_info["stock_name"]))
    except: dynamic_name_dict = {}

    today_str = datetime.date.today().strftime("%Y-%m-%d"); start_str = (datetime.date.today() - datetime.timedelta(days=120)).strftime("%Y-%m-%d")
    historical_net_sum = 0
    if os.path.exists(HISTORY_LEDGER_FILE):
        try:
            df_ledger = pd.read_csv(HISTORY_LEDGER_FILE)
            if not df_ledger.empty and "net_profit" in df_ledger.columns: historical_net_sum = df_ledger["net_profit"].sum()
        except: pass

    DYNAMIC_POOL_BUDGET = INIT_POOL_BUDGET + historical_net_sum
    current_occupied_cash = 0; sim_purchased_stocks = []
    if os.path.exists(PORTFOLIO_FILE):
        try:
            df_exist = pd.read_csv(PORTFOLIO_FILE, dtype={"stock_id": str})
            sim_purchased_stocks = df_exist["stock_id"].tolist()
            current_occupied_cash = sum(df_exist["buy_price"] * df_exist["buy_shares"])
        except: pass

    available_cash = max(0, DYNAMIC_POOL_BUDGET - current_occupied_cash)
    print(f"💰 [複利總資產池] 當前總水位: {DYNAMIC_POOL_BUDGET:,.0f} 元 | 剩餘可用現金: {available_cash:,.0f} 元")
    raw_ambush_data = []; raw_breakout_data = []; candidate_buys = []; current_3star_new = []

    for stock in STOCK_POOL:
        try:
            c_name = dynamic_name_dict.get(stock, "")
            if "*" in c_name or stock in sim_purchased_stocks: 
                continue
                
            df_raw = api.taiwan_stock_daily_adaptive(stock_id=stock, start_date=start_str, end_date=today_str)
            if df_raw.empty or len(df_raw) < 35: 
                continue
            
            display_title = f"{stock} {c_name}".strip()
            df = pd.DataFrame()
            df["open"] = df_raw["open"].astype(float); df["close"] = df_raw["close"].astype(float); df["volume"] = df_raw["Trading_Volume"].astype(float) / 1000 
            if df.iloc[-1]["close"] == 0: continue
            
            today_k = df_raw.iloc[-1]; yesterday_k = df_raw.iloc[-2] if len(df_raw) >= 2 else today_k
            if yesterday_k["close"] <= 0: continue 
            
            today_change_pct = ((today_k["close"] - yesterday_k["close"]) / yesterday_k["close"]) * 100
            if today_change_pct >= 9.8 and today_k["close"] == today_k["max"]:
                print(f"🚫 [漲停攔截] {display_title} 鎖死漲停，實戰買不到，跳過！"); continue

            df["5MA"] = df["close"].rolling(5).mean(); df["10MA"] = df["close"].rolling(10).mean(); df["20MA"] = df["close"].rolling(20).mean()
            df["5MA_Vol"] = df["volume"].rolling(5).mean(); df['20STD'] = df['close'].rolling(20).std(ddof=0)
            df['BB_Width'] = ((df['20MA'] + 2*df['20STD']) - (df['20MA'] - 2*df['20STD'])) / df['20MA']
            df['EMA12'] = df['close'].ewm(span=12, adjust=False).mean(); df['EMA26'] = df['close'].ewm(span=26, adjust=False).mean()
            df['MACD'] = df['EMA12'] - df['EMA26']

            if df.iloc[-1]["volume"] < VOLUME_FILTER or df.iloc[-1]["5MA_Vol"] < VOLUME_5MA_FILTER: continue
            latest_close = df.iloc[-1]["close"]; triggered_days_ago = None; bo_spread = 0.0; bo_bb = 0.0
            
            for i in range(1, LOOKBACK_WINDOW + 1):
                idx_t = -i; idx_y = -(i + 1)
                if len(df) + idx_y < 0 or df.iloc[idx_y]["close"] <= 0: break
                y_ma = [df.iloc[idx_y]["5MA"], df.iloc[idx_y]["10MA"], df.iloc[idx_y]["20MA"]]
                if (max(y_ma) - min(y_ma)) / df.iloc[idx_y]["close"] <= WAS_COMPRESSED_LIMIT and df.iloc[idx_t]["close"] > df.iloc[idx_t]["open"] and df.iloc[idx_t]["close"] > max(df.iloc[idx_t]["5MA"], df.iloc[idx_t]["10MA"], df.iloc[idx_t]["20MA"]):
                    triggered_days_ago = i - 1
                    t_ma = [df.iloc[idx_t]["5MA"], df.iloc[idx_t]["10MA"], df.iloc[idx_t]["20MA"]]
                    bo_spread = (max(t_ma) - min(t_ma)) / df.iloc[idx_t]["close"]
                    bo_bb = df.iloc[idx_t]["BB_Width"]; break 
            
            is_bo_active = False
            if triggered_days_ago is not None and df.iloc[-1]["close"] >= max(df.iloc[-1]["5MA"], df.iloc[-1]["10MA"], df.iloc[-1]["20MA"]):
                raw_breakout_data.append({"stock_id": stock, "stock_name": c_name, "title": display_title, "days_ago": triggered_days_ago, "spread": bo_spread, "bb": bo_bb, "close": latest_close})
                is_bo_active = True 
                if triggered_days_ago == 0:
                    print(f"🔬 偵測到發動標的：{display_title}，啟動 AI 體檢...")
                    hist_p = run_pre_backtest(api, stock)
                    if hist_p > 0:
                        candidate_buys.append({"stock_id": stock, "stock_name": c_name, "latest_close": latest_close, "buy_type": "正飆(0天)", "buy_date": str(df_raw.iloc[-1]["date"])[:10], "score": hist_p})
                        print(f"✅ [體檢過關] {display_title} 歷史期望值利潤：{hist_p} 元")
                    else: print(f"❌ [體檢失敗] {display_title} 回測期望值不佳，封殺！")

            if not is_bo_active and df.iloc[-1]["5MA"] >= df.iloc[-1]["10MA"] >= df.iloc[-1]["20MA"]:
                today_ma = [df.iloc[-1]["5MA"], df.iloc[-1]["10MA"], df.iloc[-1]["20MA"]]
                if (max(today_ma) - min(today_ma)) / df.iloc[-1]["20MA"] <= MA_SPREAD_LIMIT:
                    stars = 1 + (1 if df.iloc[-1]["BB_Width"] <= BB_COMPRESS_LIMIT else 0) + (1 if df.iloc[-1]["MACD"] > 0 else 0)
                    raw_ambush_data.append({"stock_id": stock, "stock_name": c_name, "stars": "⭐" * stars, "title": display_title, "spread": (max(today_ma) - min(today_ma)) / df.iloc[-1]["20MA"], "bb": df.iloc[-1]["BB_Width"], "macd": "水上" if df.iloc[-1]["MACD"] > 0 else "水下", "close": latest_close})
                    if stars == 3:
                        current_3star_new.append({"stock_id": stock, "stock_name": c_name, "close": latest_close})
                        print(f"🔬 偵測到 3星起飆新秀：{display_title}，啟動 AI 體檢...")
                        hist_p = run_pre_backtest(api, stock)
                        if hist_p > 0:
                            candidate_buys.append({"stock_id": stock, "stock_name": c_name, "latest_close": latest_close, "buy_type": "3星起飆", "buy_date": str(df_raw.iloc[-1]["date"])[:10], "score": hist_p})
                            print(f"✅ [體檢過關] {display_title} 歷史期望值利潤：{hist_p} 元")
                        else: print(f"❌ [體檢失敗] {display_title} 封殺！")
        except: pass
        time.sleep(0.01)

    new_sim_buys = []
    if candidate_buys:
        total_score = sum([c["score"] for c in candidate_buys])
        df_portfolio_mod = pd.read_csv(PORTFOLIO_FILE, dtype={"stock_id": str}) if os.path.exists(PORTFOLIO_FILE) else pd.DataFrame()
        
        win_dict = {}
        if os.path.exists(OPTIMIZER_DETAILS_FILE):
            try:
                df_temp = pd.read_csv(OPTIMIZER_DETAILS_FILE, dtype={"stock_id": str})
                for s_t, s_df in df_temp.groupby("stock_id"): win_dict[str(s_t).strip()] = sum([1 for r in s_df.to_dict(orient="records") if float(r.get("net_profit", 0)) > 0]) / len(s_df)
            except: pass

        for c in candidate_buys:
            new_sid = str(c["stock_id"]).strip(); new_wr = win_dict.get(new_sid, 0.55)
            allocated_budget = available_cash * (c["score"] / total_score)
            
            if allocated_budget < MIN_STOCK_BUDGET and not df_portfolio_mod.empty:
                print(f"⚠️ [可用資金不足] 啟動 i7-7700 陣容置換，尋找低勝率老兵開刀...")
                p_list = []
                for p_idx, p_r in df_portfolio_mod.iterrows(): p_list.append({"idx": p_idx, "stock_id": str(p_r["stock_id"]).strip(), "win_rate": win_dict.get(str(p_r["stock_id"]).strip(), 0.50), "value": float(p_r["buy_price"]) * int(p_r["buy_shares"])})
                df_rank = pd.DataFrame(p_list).sort_values(by="win_rate", ascending=True)
                
                for _, r_old in df_rank.iterrows():
                    if new_wr > r_old["win_rate"]:
                        t_idx = r_old["idx"]; gap = MIN_STOCK_BUDGET - allocated_budget
                        if r_old["value"] > gap:
                            red_s = int(gap // float(df_portfolio_mod.loc[t_idx, "buy_price"]))
                            if red_s > 0:
                                df_portfolio_mod.loc[t_idx, "buy_shares"] -= red_s
                                allocated_budget += red_s * float(df_portfolio_mod.loc[t_idx, "buy_price"])
                                available_cash += red_s * float(df_portfolio_mod.loc[t_idx, "buy_price"])
                                print(f"✂️ [智能置換] 老兵 {r_old['stock_id']} 進行減資，釋放子彈！")
                        else:
                            df_portfolio_mod = df_portfolio_mod.drop(t_idx)
                            allocated_budget += r_old["value"]; available_cash += r_old["value"]
                            print(f"💀 [老兵淘汰] 開除低勝率老兵 {r_old['stock_id']}，騰出大資產！")
                        if allocated_budget >= MIN_STOCK_BUDGET: break
            
            if allocated_budget >= MIN_STOCK_BUDGET:
                calc_shares = int(allocated_budget // c["latest_close"])
                if calc_shares > 0:
                    new_sim_buys.append({"stock_id": c["stock_id"], "stock_name": c["stock_name"], "buy_price": c["latest_close"], "buy_shares": calc_shares, "buy_type": c["buy_type"], "buy_date": c["buy_date"], "best_tp": GLOBAL_TP_THRESHOLD, "best_drop": GLOBAL_TP_DROP, "best_ma": "20MA", "max_price": c["latest_close"], "break_days_count": 0})
                    available_cash -= (c["latest_close"] * calc_shares)
                    print(f"💰 [置換入選] {c['stock_id']} 獲配預算: {allocated_budget:,.0f} 元")
                    
        if not df_portfolio_mod.empty: df_portfolio_mod.to_csv(PORTFOLIO_FILE, index=False)

    if new_sim_buys:
        df_new = pd.DataFrame(new_sim_buys)
        if not os.path.exists(PORTFOLIO_FILE) or pd.read_csv(PORTFOLIO_FILE).empty: df_new.to_csv(PORTFOLIO_FILE, index=False)
        else:
            df_exist_cols = pd.read_csv(PORTFOLIO_FILE, nrows=1)
            for col in df_exist_cols.columns:
                if col not in df_new.columns: df_new[col] = 0 if col == "break_days_count" else None
            df_new[df_exist_cols.columns].to_csv(PORTFOLIO_FILE, mode='a', header=False, index=False)

    try:
        import dolphin_portfolio_optimizer_v2_13 as d_opt; d_opt.main()
        print("⚡ [因果攔截] 優化器解碼更新完畢。")
    except Exception as e: print(f"⚠️ 優化器外掛調度失敗: {e}")

    # 執行部位與雷達狀態機更新
    exit_text, port_text, html_p_data = update_and_print_portfolio(api, today_str)
    
    # ====================================================================
    # 🎯 方案2：核心與新秀動態對齊與 CSV 觀察哨站更新邏輯 (焊入完全體)
    # ====================================================================
    df_wl_old = pd.read_csv(WATCHLIST_FILE, dtype={"stock_id": str}) if os.path.exists(WATCHLIST_FILE) else pd.DataFrame(columns=["stock_id", "stock_name", "初次評選日", "當初潛伏價格", "目前最新收盤", "已觀測天數", "評等"])
    
    # 讀取剛剛 update_and_print_portfolio 透過全域環境抓回來的落難老兵名單
    v134_落難老兵 = globals().get("GLOBAL_V134_落難老兵", [])
    
    wl_updated = []
    # A. 優先滾動處理「昨日留下來的舊名單」
    for _, wl_r in df_wl_old.iterrows():
        wl_sid = str(wl_r["stock_id"]).strip(); wl_days = int(wl_r["已觀測天數"]) + 1
        # 如果已經買入上車，或者觀測天數超過 3 天，直接功成身退剔除
        if wl_sid in sim_purchased_stocks or wl_days > 3: continue
        try:
            d_w = api.taiwan_stock_daily_adaptive(stock_id=wl_sid, start_date=start_str, end_date=today_str)
            c_p = float(d_w.iloc[-1]["close"])
            # 跌幅保護防線：自入榜日起跌幅超過 -5%，無情破壞機制，剔除
            if ((c_p - float(wl_r["當初潛伏價格"])) / float(wl_r["當初潛伏價格"])) * 100 <= -5.0: continue
            
            wl_updated.append({
                "stock_id": wl_sid, "stock_name": wl_r["stock_name"], "初次評選日": wl_r["初次評選日"],
                "當初潛伏價格": float(wl_r["當初潛伏價格"]), "目前最新收盤": c_p, "已觀測天數": wl_days, "評等": wl_r["評等"]
            })
        except: pass
        
    # B. 方案2注入：將今日「跌破均線留校察看第1天」的落難老兵塞入名單
    for old_soldier in v134_落難老兵:
        if old_soldier["stock_id"] not in [r["stock_id"] for r in wl_updated]:
            wl_updated.append({
                "stock_id": old_soldier["stock_id"], "stock_name": old_soldier["stock_name"],
                "初次評選日": today_str, "當初潛伏價格": old_soldier["close"], "目前最新收盤": old_soldier["close"],
                "已觀測天數": 1, "評等": "⚠️ 均線警戒老兵"
            })
            
    # C. 新秀注入：將今日型態選中的「3星滿星起飆新秀」塞入名單
    for ne in current_3star_new:
        if ne["stock_id"] not in [r["stock_id"] for r in wl_updated]:
            wl_updated.append({
                "stock_id": ne["stock_id"], "stock_name": ne["stock_name"],
                "初次評選日": today_str, "當初潛伏價格": ne["close"], "currently_price": ne["close"],
                "已觀測天數": 1, "評等": "⭐⭐⭐ 滿星新秀"
            })
            
    df_wl_f = pd.DataFrame(wl_updated)
    if not df_wl_f.empty:
        df_wl_f.columns = ["stock_id", "stock_name", "初次評選日", "當初潛伏價格", "currently_price", "已觀測天數", "評等"]
        df_wl_f.columns = ["stock_id", "stock_name", "初次評選日", "當初潛伏價格", "目前最新收盤", "已觀測天數", "評等"]
        df_wl_f.to_csv(WATCHLIST_FILE, index=False, encoding="utf-8-sig")
    else:
        pd.DataFrame(columns=["stock_id", "stock_name", "初次評選日", "當初潛伏價格", "目前最新收盤", "已觀測天數", "評等"]).to_csv(WATCHLIST_FILE, index=False, encoding="utf-8-sig")

    # 🎯 26.04 視覺修復：把底層的 Dict 陣列，渲染回精美的 HTML 標籤
    h_bo_str = []
    for r in raw_breakout_data:
        lbl = "今天發動" if r["days_ago"]==0 else f"{r['days_ago']}天前"
        h_bo_str.append(f'<span class="badge bg-danger me-2">{lbl}</span> <strong>{r["title"]}</strong> <span class="text-muted-custom small ms-2">| 均線壓縮: {r["spread"]*100:.1f}% | 布林帶寬: {r["bb"]:.2f}</span>')
        
    h_am_str = []
    for r in raw_ambush_data:
        h_am_str.append(f'<span class="badge bg-success me-2">{r["stars"]} 潛伏</span> <strong>{r["title"]}</strong> <span class="text-muted-custom small ms-2">| 均線壓縮: {r["spread"]*100:.1f}% | 布林帶寬: {r["bb"]:.2f}</span>')

    generate_one_page_html(today_str, h_bo_str, h_am_str, html_p_data)

    try:
        p_dir = os.path.dirname(PORTFOLIO_FILE)
        subprocess.run(["git", "add", "."], cwd=p_dir, check=True, stdout=subprocess.DEVNULL)
        subprocess.run(["git", "commit", "-m", f"📋 雷達自動更新: {today_str}"], cwd=p_dir, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        subprocess.run(["git", "push", "origin", "main"], cwd=p_dir, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        print("✅ [雲端同步] 成功！")
    except: pass

    # ====================================================================
    # 📲 🎯 【26.03 指揮官專屬 · 實戰極簡精美 LINE 戰報引擎完全體】
    # ====================================================================
    line_report_chunks = []

    if new_sim_buys:
        line_report_chunks.append("🚀【明日開盤預備建倉新秀】")
        for nb in new_sim_buys:
            line_report_chunks.append(f"▪️ {nb['stock_id']} {nb['stock_name']}\n  ➔ 設定價格：{nb['buy_price']:.2f} 元 買入建倉")
        line_report_chunks.append("───────────────────")

    if exit_text.strip():
        exit_rows = []
        for line in exit_text.split('\n'):
            line_clean = line.strip()
            if line_clean and ("鎖利通知" in line_clean or "停損出場" in line_clean):
                exit_rows.append(line_clean)
                
        if exit_rows:
            line_report_chunks.append("💀【在倉老兵即時清倉離場】")
            for er in exit_rows:
                line_report_chunks.append(f"▪️ {er}")
            line_report_chunks.append("───────────────────")

    if line_report_chunks:
        if line_report_chunks[-1] == "───────────────────":
            line_report_chunks.pop()
            
        header = [
            f"🐬 海豚選股 v26.03 決戰指標 🐬",
            f"📅 戰略日期：{today_str}",
            f"───────────────────"
        ]
        final_report_text = "\n".join(header + line_report_chunks)
        send_line_notify(final_report_text)
    else:
        print("📭 [實戰監控] 在倉股票安穩續抱中，且無新秀觸發，自動封鎖 LINE 雜訊不打擾。")

    os._exit(0)

if __name__ == "__main__":
    import nest_asyncio; nest_asyncio.apply()
    asyncio.run(main())
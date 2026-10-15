import asyncio, datetime, logging, os, time, requests, subprocess, shutil  
from FinMind.data import DataLoader
import pandas as pd
from pyppeteer import launch
from dotenv import load_dotenv

# 讀取環境變數 (請在同目錄建立 .env 檔案存放 Token)
load_dotenv()

logging.getLogger('pyppeteer').setLevel(logging.CRITICAL)
logging.getLogger('websockets').setLevel(logging.CRITICAL)
logging.getLogger('FinMind').setLevel(logging.CRITICAL)

# ====================================================================
# 26.08 參數設定區 (量化數值透視完全體版 + 終極拔管防護 V1.47)
# ====================================================================
VOLUME_FILTER = 500; VOLUME_5MA_FILTER = 400
FIXED_STOCK_BUDGET = 30000      # 每檔股票固定投入預算
MAX_PORTFOLIO_POSITIONS = 10    # 最大持股檔數上限，避免超額曝險
MAX_TOTAL_BUDGET = MAX_PORTFOLIO_POSITIONS * FIXED_STOCK_BUDGET # 總資金曝險上限

GLOBAL_TP_THRESHOLD = 0.15; GLOBAL_TP_DROP = 0.03
INITIAL_STOP_PCT = 0.06
PENDING_BUY_FILE = os.path.join(os.path.dirname(__file__), "dolphin_pending_buys_v147.csv")
PENDING_SELL_FILE = os.path.join(os.path.dirname(__file__), "dolphin_pending_sells_v147.csv")
ENABLE_LEGACY_OPTIMIZER = False  # 舊優化器規則不一致，暫停覆寫實戰參數        

# --- [指揮官極致海豚意念參數] ---
MA_SPREAD_LIMIT = 0.035        # 均線糾結門檻 (3.5%)
BB_COMPRESS_LIMIT = 0.10       # 布林帶寬極致壓縮門檻 (10%)
# ---------------------------------

WAS_COMPRESSED_LIMIT = 0.04; LOOKBACK_WINDOW = 5        
FEE_RATE = 0.001425; FEE_DISCOUNT = 0.28; TAX_RATE = 0.003            

# 路徑設定
PORTFOLIO_FILE = r"D:\Python-Training\N100\海豚選股法\dolphin_portfolio.csv" 
HTML_OUTPUT_FILE = r"D:\Python-Training\N100\海豚選股法\index.html" 
HISTORY_LEDGER_FILE = r"D:\Python-Training\N100\海豚選股法\dolphin_history_ledger.csv" 
OPTIMIZER_DETAILS_FILE = r"D:\Python-Training\N100\海豚選股法\dolphin_optimizer_details.csv" 
WATCHLIST_FILE = r"D:\Python-Training\N100\海豚選股法\dolphin_watchlist.csv" 

# 資安優化：改由環境變數讀取金鑰
LINE_ACCESS_TOKEN = os.getenv('LINE_ACCESS_TOKEN', 'uyt/NqkAS3yCOhUAWGqey5HYGBe5mfct1n5MB1OQaV8Y1/X8HoypqNBwq/LOVXk5YnCknVCi8LEE5KZTXkbXT2V0CpOCAk0C/YRPJRA3Z2RREefQjAG41UQV0pbp1YQCnewazDskTwrpBsxHwRo4OQdB04t89/1O/w1cDnyilFU=')
TARGET_USER_ID = os.getenv('TARGET_USER_ID', 'Uf8818996f2c5846640e0ae8ae0360a72')
FINMIND_TOKEN = os.getenv('FINMIND_TOKEN', 'eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9.eyJ1c2VyX2lkIjoicGNoaW9uMjAwMiIsImVtYWlsIjoibGFpZWNodW55dUBnbWFpbC5jb20iLCJ0b2tlbl92ZXJzaW9uIjowfQ.si_2Ta3AlY1JtgVBDlqpnkaK3IH41Drrc7ogVgNBJq8')

URL_1000_SHARES = "https://norway.twsthr.info/StockHoldersContinue.aspx?Show=1&continue=Y&weeks=4&growthrate=2&beforeweek=8&price=5000&valuerank=1-3000&display=0"
URL_400_SHARES  = "https://norway.twsthr.info/StockHoldersContinue.aspx?Show=2&continue=Y&weeks=4&growthrate=2&beforeweek=8&price=5000&valuerank=1-3000&display=0"

def send_line_notify(message):
    url = 'https://api.line.me/v2/bot/message/push'
    token_clean = str(LINE_ACCESS_TOKEN).strip().replace('"', '').replace("'", "")
    user_id_clean = str(TARGET_USER_ID).strip().replace('"', '').replace("'", "")
    
    headers = { 'Content-Type': 'application/json; charset=UTF-8', 'Authorization': f'Bearer {token_clean}' }
    payload = { 'to': user_id_clean, 'messages': [{'type': 'text', 'text': message}] }
    try:
        response = requests.post(url, headers=headers, json=payload, timeout=10)
        if response.status_code == 200:
            print("📲 [系統通知] LINE 戰報即時推播成功！")
        else:
            print(f"⚠️ [系統通知] LINE 發送失敗，伺服器回傳: {response.status_code} - {response.text}")
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
    df_raw = api.taiwan_stock_daily(stock_id=stock_id, start_date=(today - datetime.timedelta(days=730)).strftime("%Y-%m-%d"), end_date=today.strftime("%Y-%m-%d"))
    if df_raw.empty or len(df_raw) < 50: return 0, []
    
    df = pd.DataFrame()
    df["close"] = df_raw["close"].astype(float); df["open"] = df_raw["open"].astype(float)
    df["high"] = df_raw["max"].astype(float); df["volume"] = df_raw["Trading_Volume"].astype(float) / 1000 
    df["5MA"] = df["close"].rolling(5).mean(); df["10MA"] = df["close"].rolling(10).mean(); df["20MA"] = df["close"].rolling(20).mean()
    df["5MA_Vol"] = df["volume"].rolling(5).mean()
    
    closes = df['close'].values; opens = df['open'].values; highs = df['high'].values
    vols = df['volume'].values; vol5mas = df['5MA_Vol'].values
    ma5s = df['5MA'].values; ma10s = df['10MA'].values; ma20s = df['20MA'].values
    ma5ws = df["close"].rolling(25).mean().values; ma10ws = df["close"].rolling(50).mean().values
    dates = df_raw['date'].astype(str).str[:10].values

    max_possible_profit = -999999
    best_records = []
    ma_arrays = {"5MA": ma5s, "10MA": ma10s, "20MA": ma20s, "5WMA": ma5ws, "10WMA": ma10ws}
    
    for ma_opt in ["5MA", "10MA", "20MA", "5WMA", "10WMA"]:
        ma_targets = ma_arrays[ma_opt]
        for th in [0.1, 0.15, 0.2, 0.25]:
            for dr in [0.02, 0.03, 0.04]:
                in_pos = False; b_price = 0.0; b_shares = 0; m_price = 0.0; grand_profit = 0; tp_radar = False
                temp_records = []; temp_buy = {}
                for i in range(50, len(closes)):
                    c_close = closes[i]; k_date = dates[i]
                    if in_pos:
                        if c_close > m_price: m_price = c_close
                        if ((m_price - b_price) / b_price) >= th: tp_radar = True
                        
                        b_fee = max(20, int(b_price * b_shares * FEE_RATE * FEE_DISCOUNT))
                        s_fee = max(20, int(c_close * b_shares * FEE_RATE * FEE_DISCOUNT))
                        s_tax = int(c_close * b_shares * TAX_RATE)
                        net_p = int((c_close * b_shares) - s_fee - s_tax - (b_price * b_shares) - b_fee)
                        
                        if tp_radar and c_close <= (m_price * (1 - dr)):
                            grand_profit += net_p; in_pos = False; tp_radar = False
                            temp_buy.update({"sell_date": k_date, "sell_price": c_close, "net_profit": net_p, "profit_percent": (net_p/((b_price*b_shares)+b_fee))*100, "exit_reason": f"移動鎖利({dr*100:.1f}%)"})
                            temp_records.append(temp_buy.copy())
                        elif ma_targets[i] > 0 and c_close < ma_targets[i]:
                            grand_profit += net_p; in_pos = False; tp_radar = False
                            temp_buy.update({"sell_date": k_date, "sell_price": c_close, "net_profit": net_p, "profit_percent": (net_p/((b_price*b_shares)+b_fee))*100, "exit_reason": f"跌破均線({ma_opt})"})
                            temp_records.append(temp_buy.copy())
                    else:
                        if vols[i] < 500 or vol5mas[i] < 400: continue
                        y_close = closes[i-1]
                        if y_close > 0 and ((c_close - y_close) / y_close * 100) >= 9.8 and c_close == highs[i]: continue
                        
                        y_ma = [ma5s[i-2], ma10s[i-2], ma20s[i-2]]
                        if closes[i-2] > 0 and (max(y_ma) - min(y_ma)) / closes[i-2] <= 0.04 and closes[i-1] > opens[i-1] and c_close >= max(ma5s[i], ma10s[i], ma20s[i]):
                            in_pos = True; b_price = c_close; b_shares = int(FIXED_STOCK_BUDGET // c_close); m_price = c_close; tp_radar = False
                            temp_buy = {"buy_date": k_date, "buy_price": b_price}
                            
                if grand_profit > max_possible_profit:
                    max_possible_profit = grand_profit
                    best_records = temp_records
                    
    return max_possible_profit, best_records

def _read_csv(path):
    if not os.path.exists(path):
        return pd.DataFrame()
    try:
        return pd.read_csv(path, dtype={"stock_id": str})
    except pd.errors.EmptyDataError:
        return pd.DataFrame()


def _save_csv(df, path):
    # 原子替換，避免寫入中斷破壞帳本
    tmp = path + ".tmp"
    df.to_csv(tmp, index=False, encoding="utf-8-sig")
    os.replace(tmp, path)


def _net_result(buy_price, shares, sell_price):
    cost = buy_price * shares + max(20, int(buy_price * shares * FEE_RATE * FEE_DISCOUNT))
    proceeds = sell_price * shares - max(20, int(sell_price * shares * FEE_RATE * FEE_DISCOUNT)) - int(sell_price * shares * TAX_RATE)
    pnl = int(proceeds - cost)
    return pnl, pnl / cost * 100 if cost else 0


def settle_pending_orders(api, today_str):
    """隔一個交易日才以開盤價模擬成交；無行情則保持待處理。"""
    notifications = []
    pf = _read_csv(PORTFOLIO_FILE)
    if pf.empty:
        pf = pd.DataFrame(columns=["stock_id", "stock_name", "buy_date", "buy_price", "buy_shares", "buy_type", "best_tp", "best_drop", "best_ma", "max_price", "break_days_count", "strategy_stars"])
    buys, sells = _read_csv(PENDING_BUY_FILE), _read_csv(PENDING_SELL_FILE)
    start = (datetime.date.today() - datetime.timedelta(days=15)).strftime('%Y-%m-%d')
    cache = {}
    def next_bar(sid, signal_date):
        if sid not in cache:
            raw = api.taiwan_stock_daily(stock_id=sid, start_date=start, end_date=today_str)
            cache[sid] = raw.sort_values('date') if not raw.empty else raw
        df = cache[sid]
        if df.empty: return None
        future = df[df['date'].astype(str).str[:10] > str(signal_date)[:10]]
        return future.iloc[0] if not future.empty else None

    remaining_sells = []
    for _, order in sells.iterrows():
        sid = str(order['stock_id']).strip()
        matches = pf[pf['stock_id'].astype(str).str.strip() == sid]
        if matches.empty: continue
        try:
            bar = next_bar(sid, order['signal_date'])
            if bar is None or float(bar['open']) <= 0:
                remaining_sells.append(order.to_dict()); continue
            held = matches.iloc[0]
            price = float(bar['open'])
            pnl, pct = _net_result(float(held['buy_price']), int(held['buy_shares']), price)
            # 記帳日期採用真正的模擬成交日
            ledger_row = held.copy()
            entry = {"stock_id": sid, "stock_name": held['stock_name'], "buy_date": held['buy_date'],
                     "buy_price": float(held['buy_price']), "buy_shares": int(held['buy_shares']),
                     "sell_date": str(bar['date'])[:10], "sell_price": price,
                     "net_profit": pnl, "profit_percent": round(pct, 2), "exit_reason": str(order['reason'])}
            pd.DataFrame([entry]).to_csv(HISTORY_LEDGER_FILE, mode='a', header=not os.path.exists(HISTORY_LEDGER_FILE), index=False, encoding='utf-8-sig')
            pf = pf[pf['stock_id'].astype(str).str.strip() != sid]
            notifications.append(f"✅ 模擬賣出 {sid} {held['stock_name']}｜{price:.2f} 元｜{pnl:+,} 元 ({pct:+.2f}%)")
        except Exception as exc:
            print(f"⚠️ 待賣單 {sid} 未結算：{exc}")
            remaining_sells.append(order.to_dict())
    _save_csv(pd.DataFrame(remaining_sells, columns=['stock_id','signal_date','reason']), PENDING_SELL_FILE)

    remaining_buys = []
    for _, order in buys.iterrows():
        sid = str(order['stock_id']).strip()
        if sid in pf['stock_id'].astype(str).str.strip().tolist(): continue
        try:
            bar = next_bar(sid, order['signal_date'])
            if bar is None or float(bar['open']) <= 0:
                remaining_buys.append(order.to_dict()); continue
            price = float(bar['open'])
            ref = float(order['signal_close'])
            if price >= ref * 1.095:
                notifications.append(f"⏭️ {sid} {order['stock_name']} 跳空超過 9.5%，取消模擬買進")
                continue
            if len(pf) >= MAX_PORTFOLIO_POSITIONS:
                notifications.append(f"⏭️ {sid} {order['stock_name']} 持股滿額，取消模擬買進")
                continue
            shares = int(FIXED_STOCK_BUDGET // price)
            while shares > 0 and price * shares + max(20, int(price * shares * FEE_RATE * FEE_DISCOUNT)) > FIXED_STOCK_BUDGET:
                shares -= 1
            if shares < 1: continue
            item = {"stock_id": sid, "stock_name": order['stock_name'], "buy_price": price,
                    "buy_shares": shares, "buy_type": order['buy_type'], "buy_date": str(bar['date'])[:10],
                    "best_tp": GLOBAL_TP_THRESHOLD, "best_drop": GLOBAL_TP_DROP, "best_ma": "20MA",
                    "max_price": price, "break_days_count": 0, "strategy_stars": order['stars_display']}
            pf = pd.concat([pf, pd.DataFrame([item])], ignore_index=True)
            notifications.append(f"✅ 模擬買入 {sid} {order['stock_name']}｜{price:.2f} 元 × {shares} 股")
        except Exception as exc:
            print(f"⚠️ 待買單 {sid} 未結算：{exc}")
            remaining_buys.append(order.to_dict())
    _save_csv(pd.DataFrame(remaining_buys, columns=['stock_id','stock_name','signal_date','signal_close','buy_type','stars_display']), PENDING_BUY_FILE)
    _save_csv(pf, PORTFOLIO_FILE)
    return notifications


def update_and_print_portfolio(api, today_str):
    df_pf = _read_csv(PORTFOLIO_FILE)
    survived_rows, report_p_rows, exit_p_rows, html_portfolio_data = [], [], [], []
    pending = _read_csv(PENDING_SELL_FILE)
    pending_ids = set(pending['stock_id'].astype(str).str.strip()) if not pending.empty else set()
    market_start = (datetime.date.today() - datetime.timedelta(days=150)).strftime('%Y-%m-%d')
    market_latest = None
    try:
        benchmark = api.taiwan_stock_daily(stock_id='0050', start_date=market_start, end_date=today_str)
        if not benchmark.empty: market_latest = str(benchmark.iloc[-1]['date'])[:10]
    except Exception as exc:
        print(f'⚠️ 大盤日期無法確認：{exc}')
    for _, row in df_pf.iterrows():
        sid, name = str(row['stock_id']).strip(), str(row['stock_name'])
        price_buy, shares = float(row['buy_price']), int(row['buy_shares'])
        try:
            raw = api.taiwan_stock_daily(stock_id=sid, start_date=market_start, end_date=today_str)
            if raw.empty or len(raw) < 60:
                exit_p_rows.append(f'⚠️ {sid} {name} 行情不足，保留持股，請人工確認')
                survived_rows.append(row); continue
            raw = raw.sort_values('date').reset_index(drop=True)
            last_date = str(raw.iloc[-1]['date'])[:10]
            if market_latest and last_date < market_latest:
                exit_p_rows.append(f'⚠️ {sid} {name} 行情停留在 {last_date}，保留持股，勿假設已成交')
                survived_rows.append(row); continue
            df = raw.copy()
            df['close'] = df['close'].astype(float)
            df['5MA'] = df['close'].rolling(5).mean()
            df['10MA'] = df['close'].rolling(10).mean()
            df['20MA'] = df['close'].rolling(20).mean()
            df['5WMA'] = df['close'].rolling(25).mean()
            df['10WMA'] = df['close'].rolling(50).mean()
            df['20STD'] = df['close'].rolling(20).std(ddof=0)
            df['BB_Width'] = 4 * df['20STD'] / df['20MA']
            df['MACD'] = df['close'].ewm(span=12, adjust=False).mean() - df['close'].ewm(span=26, adjust=False).mean()
            last = df.iloc[-1]
            close = float(last['close'])
            # 只採用買進日期之後的高價，不納入買入當天開盤之前的高點
            max_price = max(price_buy, float(row['max_price']) if 'max_price' in row and pd.notna(row['max_price']) else price_buy)
            if last_date > str(row['buy_date'])[:10]: max_price = max(max_price, float(last['max']))
            ma_name = str(row.get('best_ma', '20MA')) if pd.notna(row.get('best_ma', '20MA')) else '20MA'
            if ma_name not in df.columns: ma_name = '20MA'
            ma_value = float(last[ma_name])
            highest_gain = (max_price / price_buy) - 1
            initial_stop = price_buy * (1 - INITIAL_STOP_PCT)
            stop = max(initial_stop, ma_value)
            reason = '初始停損/均線防線'
            if highest_gain >= .05:
                stop = max(stop, price_buy * 1.01); reason = '5%保本防線'
            if highest_gain >= .10:
                stop = max(stop, max_price * .95); reason = '10%階段鎖利'
            if highest_gain >= .15:
                stop = max(stop, max_price * .97); reason = '15%移動鎖利'
            # 不允許同一天重複觸發；歷史日不新建委託
            is_fresh = last_date == today_str
            triggered = is_fresh and close < stop
            if sid in pending_ids:
                exit_p_rows.append(f'⏳ {sid} {name} 已有待賣訊號，等待下一交易日開盤模擬成交')
            elif triggered:
                order = pd.DataFrame([{'stock_id':sid, 'signal_date':last_date, 'reason':reason}])
                pending = pd.concat([pending,order],ignore_index=True)
                pending_ids.add(sid)
                exit_p_rows.append(f'🚨 明日待賣：{sid} {name}｜收盤 {close:.2f} 跌破 {reason} {stop:.2f}，下個交易日開盤模擬成交')
            pnl, pct = _net_result(price_buy, shares, close)
            ma = [float(last['5MA']),float(last['10MA']),float(last['20MA'])]
            spread = (max(ma)-min(ma))/float(last['20MA'])*100
            bw = float(last['BB_Width'])*100
            macd = float(last['MACD'])
            stars = '⭐' * (1 + int(bw <= 10) + int(macd > 0)) if spread <= 3.5 else '🚀'
            strategy_stars = f'{stars} | 糾結:{spread:.1f}% | 帶寬:{bw:.1f}% | MACD:{macd:+.2f}'
            html_portfolio_data.append({'stock_id':sid,'stock_name':name,'buy_date':row['buy_date'],
                'buy_price':price_buy,'buy_shares':shares,'current_price':close,'target_tp_price':price_buy*1.15,
                'max_price':max_price,'dynamic_lock_price':max_price*.97,'target_ma_line':reason,
                'stop_loss_value':stop,'net_profit':pnl,'profit_percent':pct,'radar_active':highest_gain>=.15,
                'break_days':1 if sid in pending_ids else 0,'strategy_stars':strategy_stars})
            report_p_rows.append(f'{sid} {name}｜{close:.2f}｜{pnl:+,}元 ({pct:+.2f}%)')
            row['max_price'] = max_price
            row['strategy_stars'] = strategy_stars
            survived_rows.append(row)
        except Exception as exc:
            print(f'⚠️ 持股 {sid} 更新失敗，保留原紀錄：{exc}')
            survived_rows.append(row)
    _save_csv(pd.DataFrame(survived_rows, columns=df_pf.columns), PORTFOLIO_FILE)
    _save_csv(pending, PENDING_SELL_FILE)
    global GLOBAL_V134_落難老兵
    GLOBAL_V134_落難老兵 = []
    return '\n'.join(exit_p_rows), '\n'.join(report_p_rows), html_portfolio_data

# ====================================================================
# 網頁渲染引擎
# ====================================================================
def generate_one_page_html(today_str, h_bo_str, h_am_str, portfolio_data, raw_breakout_data, raw_ambush_data, raw_limit_up_data):
    total_cost = sum([r['buy_price'] * r['buy_shares'] for r in portfolio_data])
    total_profit = sum([r['net_profit'] for r in portfolio_data])
    total_current_value = total_cost + total_profit
    total_profit_pct = (total_profit / total_cost * 100) if total_cost > 0 else 0.0
    profit_color_class = "text-taiwan-red" if total_profit >= 0 else "text-taiwan-green"
    
    history_summary_html = ""; ledger_rows_html = ""
    if os.path.exists(HISTORY_LEDGER_FILE):
        try:
            df_hist = pd.read_csv(HISTORY_LEDGER_FILE)
            hist_total_profit = df_hist["net_profit"].sum()
            hist_trades_count = len(df_hist)
            hist_win_count = len(df_hist[df_hist["net_profit"] > 0])
            hist_win_rate = (hist_win_count / hist_trades_count * 100) if hist_trades_count > 0 else 0.0
            hist_color = "text-taiwan-red" if hist_total_profit >= 0 else "text-taiwan-green"
            
            history_summary_html = f"""
            <div class="col-md-2">
                <div class="summary-box" style="border-left-color: #ff9f43;">
                    <div class="text-muted-custom small">歷史已結算戰績</div>
                    <div class="fs-4 fw-bold {hist_color}">{'+' if hist_total_profit>=0 else ''}{hist_total_profit:,.0f} 元</div>
                </div>
            </div>
            <div class="col-md-2">
                <div class="summary-box" style="border-left-color: #00f2fe;">
                    <div class="text-muted-custom small">歷史勝率 / 總單數</div>
                    <div class="fs-4 fw-bold text-white">{hist_win_rate:.1f}% <small class="text-muted-custom">({hist_trades_count}單)</small></div>
                </div>
            </div>
            """
            for _, h_row in df_hist.iloc[::-1].iterrows():
                h_prof = float(h_row['net_profit'])
                h_class_td = "text-taiwan-red" if h_prof >= 0 else "text-taiwan-green"
                h_sign = "+" if h_prof >= 0 else ""
                ledger_rows_html += f"<tr><td>{h_row['stock_id']} {h_row['stock_name']}</td><td>{h_row['buy_date']} ~ {h_row['sell_date']}</td><td>{h_row['buy_price']:.2f} → {h_row['sell_price']:.2f}</td><td>{int(h_row['buy_shares'])} 股</td><td class='{h_class_td} fw-bold'>{h_sign}{h_prof:,.0f}元 ({h_sign}{h_row['profit_percent']:.1f}%)</td><td>{h_row['exit_reason']}</td></tr>"
        except: pass
    if not history_summary_html:
        history_summary_html = '<div class="col-md-4"><div class="summary-box" style="border-left-color: #a1a5b7;"><div class="text-muted-custom small">歷史已結算戰績</div><div class="fs-4 fw-bold text-muted-custom">尚無歷史出清數據</div></div></div>'
    if not ledger_rows_html: ledger_rows_html = '<tr><td colspan="6" class="text-center text-muted-custom py-3">暫無已清算戰績。</td></tr>'

    wl_rows = ""
    if os.path.exists(WATCHLIST_FILE):
        try:
            df_w = pd.read_csv(WATCHLIST_FILE, dtype={"stock_id": str})
            for _, w_r in df_w.iterrows():
                lbl_tag = "⚠️ 均線警戒" if "均線警戒" in str(w_r['評等']) else "⭐⭐⭐ 新秀"
                wl_rows += f"<tr><td class='text-info fw-bold'>{w_r['stock_id']} {w_r['stock_name']}</td><td>{lbl_tag}</td><td>{w_r['初次評選日']}</td><td>{w_r['當初潛伏價格']:.2f}</td><td class='text-warning fw-bold'>{w_r['目前最新收盤']:.2f}</td><td>觀測 {int(w_r['已觀測天數'])} 天</td></tr>"
        except: pass
    if not wl_rows: wl_rows = '<tr><td colspan="6" class="text-center text-muted-custom py-2 small">觀測哨站目前空棚。</td></tr>'

    accordion_items = {}
    for p in portfolio_data: accordion_items[str(p['stock_id']).strip()] = {"name": p['stock_name'], "tag": "💼 實戰持股"}
    for r in raw_breakout_data:
        sid = str(r['stock_id']).strip()
        if sid not in accordion_items: accordion_items[sid] = {"name": r['stock_name'], "tag": "🚀 雷達發動標的"}
    for r in raw_ambush_data:
        sid = str(r['stock_id']).strip()
        if sid not in accordion_items: accordion_items[sid] = {"name": r['stock_name'], "tag": "🎯 雷達潛伏標的"}

    opt_details_dict = {}
    if os.path.exists(OPTIMIZER_DETAILS_FILE):
        try:
            df_opt_det = pd.read_csv(OPTIMIZER_DETAILS_FILE, dtype={"stock_id": str})
            for sid, sub_df in df_opt_det.groupby("stock_id"): opt_details_dict[str(sid).strip()] = sub_df.to_dict(orient="records")
        except: pass

    limit_up_html = ""
    if not raw_limit_up_data:
        limit_up_html = '<li class="list-group-item bg-transparent text-muted-custom small py-3">今日無漲停鎖死標的。</li>'
    else:
        for lu in raw_limit_up_data:
            limit_up_html += f'<li class="list-group-item bg-transparent text-white border-secondary py-3"><span class="badge bg-danger me-2">🔥 漲停鎖死</span> <strong>{lu["title"]}</strong></li>'

    html_content = f"""<!DOCTYPE html>
<html lang="zh-TW">
<head>
    <meta charset="UTF-8">
    <title>海豚量化自適應指揮官儀表板</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
    <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/js/bootstrap.bundle.min.js"></script>
    <style>
        body {{ background-color: #12141c; color: #e4e6eb; font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; }}
        .navbar {{ background-color: #1a1f2c; border-bottom: 2px solid #ff4a4a; }}
        .card {{ background-color: #1a1f2c; border: 1px solid #2d3548; border-radius: 12px; margin-bottom: 20px; }}
        .card-header {{ background-color: #22293a; border-bottom: 1px solid #2d3548; font-weight: bold; color: #00f2fe; }}
        .table-custom-dark {{ color: #ffffff !important; }}
        .table-custom-dark th {{ background-color: #22293a !important; color: #00f2fe !important; border-color: #2d3548 !important; }}
        .table-custom-dark td {{ background-color: #1a1f2c !important; color: #ffffff; border-color: #2d3548 !important; }}
        .text-muted-custom {{ color: #a1a5b7 !important; }}
        .text-taiwan-red {{ color: #ff4a4a !important; font-weight: bold; }}     
        .text-taiwan-green {{ color: #2cf3a0 !important; font-weight: bold; }}   
        .badge-breakout {{ background-color: #ff9f43; color: #12141c; font-weight: bold; }}
        .badge-ambush {{ background-color: #00f2fe; color: #12141c; font-weight: bold; }}
        .badge-radar {{ background-color: #ff4a4a; animation: blink 1.5s infinite; font-weight: bold; padding: 4px 8px; border-radius: 4px; color: white; }}
        @keyframes blink {{ 0% {{ opacity: 0.4; }} 50% {{ opacity: 1; }} 100% {{ opacity: 0.4; }} }}
        .summary-box {{ background: linear-gradient(135deg, #1e2638 0%, #151b29 100%); border-radius: 10px; padding: 15px; border-left: 4px solid #00f2fe; }}
        .accordion-button {{ background-color: #22293a !important; color: #00f2fe !important; border: 1px solid #2d3548; }}
        .accordion-button:not(.collapsed) {{ background-color: #ff4a4a !important; color: white !important; }}
        .accordion-body {{ background-color: #151b29; border: 1px solid #2d3548; color: #ffffff; }}
        .star-tag {{ color: #a1a5b7; font-size: 0.85rem; font-weight: 500; letter-spacing: 0.5px; }}
    </style>
</head>
<body>
<nav class="navbar navbar-dark px-4 py-3">
    <span class="navbar-brand mb-0 h1 fs-3">🐬 海豚量化自適應指揮官儀表板 <small class="fs-6 text-muted-custom">v1.47 終極拔管版</small></span>
    <span class="text-muted-custom">📅 數據更新時間：{today_str}</span>
</nav>
<div class="container-fluid p-4">
    <div class="row mb-4">
        <div class="col-md-2">
            <div class="summary-box">
                <div class="text-muted-custom small">當前持股總成本</div>
                <div class="fs-4 fw-bold text-info">${total_cost:,.0f} 元</div>
            </div>
        </div>
        <div class="col-md-2">
            <div class="summary-box" style="border-left-color: #ffffff;">
                <div class="text-muted-custom small">持股現值估算</div>
                <div class="fs-4 fw-bold text-white">${total_current_value:,.0f} 元</div>
            </div>
        </div>
        <div class="col-md-4">
            <div class="summary-box" style="border-left-color: {'#ff4a4a' if total_profit >= 0 else '#2cf3a0'};">
                <div class="text-muted-custom small">在倉持股總淨損益</div>
                <div class="fs-4 fw-bold {profit_color_class}">{'+' if total_profit >= 0 else ''}{total_profit:,.0f} 元 ({'+' if total_profit >= 0 else ''}{total_profit_pct:.2f}%)</div>
            </div>
        </div>
        {history_summary_html}
    </div>
    
    <div class="row">
        <div class="col-12 col-xl-8">
            <div class="card">
                <div class="card-header fs-5">💼 實戰持股狀態機雙向防線即時雷達</div>
                <div class="table-responsive">
                    <table class="table table-custom-dark mb-0">
                        <thead>
                            <tr>
                                <th>代號/名稱</th><th>買入日期</th><th>參考進場價</th><th>目前價</th><th>起跑門檻</th>
                                <th>鎖利線(最高)</th><th>生命均線(停損價)</th><th>當前損益</th><th>雷達狀態</th>
                            </tr>
                        </thead>
                        <tbody>
    """
    if not portfolio_data: html_content += '<tr><td colspan="9" class="text-center text-muted-custom py-4">目前記帳簿內無任何持股。</td></tr>'
    else:
        for p in portfolio_data:
            p_sign = "+" if p['net_profit'] >= 0 else ""
            p_class = "text-taiwan-red" if p['net_profit'] >= 0 else "text-taiwan-green"
            w_pct = ((p['buy_price'] * p['buy_shares']) / total_cost) * 100 if total_cost > 0 else 0
            radar_badge = '<span class="badge bg-warning text-dark">⏳ 留校察看</span>' if p['break_days'] == 1 else ('<span class="badge badge-radar">🔥 監控中</span>' if p['radar_active'] else '<span class="text-muted-custom small">未開啟</span>')
            
            html_content += f"""
                            <tr>
                                <td>
                                    <strong class="text-white">{p['stock_id']} {p['stock_name']}</strong><br>
                                    <span class="star-tag">{p['strategy_stars']}</span><br>
                                    <small class='text-muted-custom fw-normal'>(比重: {w_pct:.1f}%)</small>
                                </td>
                                <td class="small text-muted-custom">{p['buy_date']}</td>
                                <td class="text-white">{p['buy_price']:.2f} <small class="text-muted-custom">({p['buy_shares']}股)</small></td>
                                <td class="fw-bold text-warning">{p['current_price']:.2f}</td>
                                <td class="text-white">{p['target_tp_price']:.2f}</td>
                                <td><span class="text-info">{p['dynamic_lock_price']:.2f}</span> <small class="text-muted-custom">({p['max_price']:.2f})</small></td>
                                <td><span class="text-danger">{p['stop_loss_value']:.2f}</span> <small class="text-muted-custom">({p['target_ma_line']})</small></td>
                                <td class="fw-bold {p_class}">{p_sign}{p['net_profit']:,}元<br><small>{p_sign}{p['profit_percent']:.2f}%</small></td>
                                <td>{radar_badge}</td>
                            </tr>
            """
            
    html_content += f"""
                        </tbody>
                    </table>
                </div>
            </div>
            
            <div class="card mt-4">
                <div class="card-header fs-5 text-info">🔍 📂 歷史評選 · 3星新秀與方案2落難老兵動態留校察看哨站</div>
                <div class="table-responsive">
                    <table class="table table-custom-dark mb-0 text-center small">
                        <thead><tr><th>代號/名稱</th><th>狀態屬性</th><th>捕獲/警戒日</th><th>當初潛伏/防線價</th><th>目前最新收盤</th><th>生命流狀態</th></tr></thead>
                        <tbody>{wl_rows}</tbody>
                    </table>
                </div>
            </div>
            
            <div class="card mt-4">
                <div class="card-header fs-5 text-warning">🔍 舊版優化器歷史紀錄（不代表 V1.47 績效） (持股與雷達標的)</div>
                <div class="card-body p-3">
                    <div class="accordion" id="optimizerAccordion">
    """
    
    if not accordion_items: html_content += '<div class="text-muted-custom p-3 small">目前無在庫持股或雷達標的，無回測基因可供解析。</div>'
    else:
        for sid, info in accordion_items.items():
            sname = info["name"]; tag = info["tag"]; records = opt_details_dict.get(sid, [])
            total_rec_profit = sum([float(r.get("net_profit", 0)) for r in records])
            win_count = sum([1 for r in records if float(r.get("net_profit", 0)) > 0])
            win_rate = (win_count / len(records) * 100) if len(records) > 0 else 0
            r_sign = "+" if total_rec_profit >= 0 else ""; r_color = "#ff4a4a" if total_rec_profit >= 0 else "#2cf3a0"
            
            html_content += f"""
            <div class="accordion-item bg-transparent border-secondary">
                <h2 class="accordion-header" id="heading_{sid}">
                    <button class="accordion-button collapsed" type="button" data-bs-toggle="collapse" data-bs-target="#collapse_{sid}" aria-expanded="false" aria-controls="collapse_{sid}">
                        📊 [{tag}] {sid} {sname} — 2年最佳化策略回測歷史明細紀錄 (共 {len(records)} 筆)
                        <span style="margin-left: 20px; color: {r_color}; font-weight: bold; letter-spacing: 0.5px;">
                            [ 歷史總利潤: {r_sign}{total_rec_profit:,.0f} 元 | 勝率: {win_rate:.0f}% ]
                        </span>
                    </button>
                </h2>
                <div id="collapse_{sid}" class="accordion-collapse collapse" aria-labelledby="heading_{sid}" data-bs-parent="#optimizerAccordion">
                    <div class="accordion-body">
                        <div class="table-responsive">
                            <table class="table table-sm table-dark table-hover mb-0 text-center small">
                                <thead>
                                    <tr class="text-info">
                                        <th>交易序號</th><th>買入日期</th><th>買入價格</th><th>賣出日期</th>
                                        <th>持有天數</th><th>賣出價格</th><th>回測淨損益</th><th>報酬率 (%)</th><th>離場觸發原因</th>
                                    </tr>
                                </thead>
                                <tbody>
            """
            if not records: html_content += f'<tr><td colspan="9" class="text-muted-custom py-3">⚠️ 未偵測到明細資料，請確認 API 狀態 or 回測引擎是否順利完成。</td></tr>'
            else:
                for r_idx, r in enumerate(records):
                    r_prof = float(r.get("net_profit", 0)); r_pct = float(r.get("profit_percent", 0))
                    r_sign_td = "+" if r_prof >= 0 else ""; r_class_td = "text-taiwan-red" if r_prof >= 0 else "text-taiwan-green"
                    buy_date_str = str(r.get("buy_date", "無")); sell_date_str = str(r.get("sell_date", "無")); holding_days = 0
                    if buy_date_str != "無" and sell_date_str != "無":
                        try:
                            holding_days = (datetime.datetime.strptime(sell_date_str, "%Y-%m-%d") - datetime.datetime.strptime(buy_date_str, "%Y-%m-%d")).days
                        except: pass
                    holding_days_str = f"{holding_days} 天" if holding_days > 0 else "-"
                    
                    html_content += f"""
                                    <tr>
                                        <td>{r_idx + 1}</td><td>{buy_date_str}</td><td>{r.get("buy_price", 0)}</td>
                                        <td>{sell_date_str}</td><td class="text-warning">{holding_days_str}</td> <td>{r.get("sell_price", 0)}</td>
                                        <td class="{r_class_td} fw-bold">{r_sign_td}{r_prof:,.0f}元</td>
                                        <td class="{r_class_td} fw-bold">{r_sign_td}{r_pct:.2f}%</td>
                                        <td class="text-muted-custom">{r.get("exit_reason", "未知")}</td>
                                    </tr>
                    """
            html_content += """
                                </tbody>
                            </table>
                        </div>
                    </div>
                </div>
            </div>
            """
            
    html_content += f"""
                    </div>
                </div>
            </div>
            
            <div class="card mt-4">
                <div class="card-header fs-5 bg-dark">
                    <button class="btn btn-link text-decoration-none fw-bold fs-5 w-100 text-start p-0 text-info" 
                            type="button" data-bs-toggle="collapse" data-bs-target="#ledgerCollapse" 
                            onclick="document.getElementById('ledgerCollapse').classList.toggle('show')">
                        📋 📂 [點擊展開] 📊 大帳本：歷史戰績移動清算回顧與策略檢討
                    </button>
                </div>
                <div class="collapse" id="ledgerCollapse">
                    <div class="table-responsive">
                        <table class="table table-custom-dark mb-0 text-center small">
                            <thead><tr style="color: #ff9f43;"><th>代號/名稱</th><th>實戰交易時空區間</th><th>進場 → 出場價</th><th>結算股數</th><th>實打實淨損益</th><th>💀 戰略離場檢討原因</th></tr></thead>
                            <tbody>{ledger_rows_html}</tbody>
                        </table>
                    </div>
                </div>
            </div>
        </div>
        <div class="col-12 col-xl-4">
            <div class="card">
                <div class="card-header fs-5" style="color: #ff4a4a;">🔥【極端動能 · 鎖死漲停觀測區】</div>
                <ul class="list-group list-group-flush" style="background-color: #1a1f2c;">
                    {limit_up_html}
                </ul>
            </div>
            <div class="card">
                <div class="card-header fs-5">🚀【真·正飆股 · 動能突破擊潰區】</div>
                <ul class="list-group list-group-flush" style="background-color: #1a1f2c;">
    """
    if not h_bo_str: html_content += '<li class="list-group-item bg-transparent text-muted-custom small py-3">今日無剛發動標的。</li>'
    else:
        for bo in h_bo_str: html_content += f'<li class="list-group-item bg-transparent text-white border-secondary py-3">{bo}</li>'
    html_content += """
                </ul>
            </div>
            <div class="card">
                <div class="card-header fs-5">🎯【準·起飆股 · 鱷魚潛伏地底區】</div>
                <ul class="list-group list-group-flush" style="background-color: #1a1f2c;">
    """
    if not h_am_str: html_content += '<li class="list-group-item bg-transparent text-muted-custom small py-3">今日無糾結壓縮標的。</li>'
    else:
        for am in h_am_str: html_content += f'<li class="list-group-item bg-transparent text-white border-secondary py-3">{am}</li>'
    html_content += f"""
                </ul>
            </div>
        </div>
    </div>
</div>
<footer class="text-center py-4 text-muted-custom small mt-4" style="border-top: 1px solid #2d3548;">
    海豚自動化管線系統 · 每日盤後自動化更新完成
</footer>
</body>
</html>
"""
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
    print("🚀 海豚選股 V1.47：[終極拔管防護版] 啟動...")
    print("====================================================")
    STOCK_POOL = await fetch_union_pyramid_pool()
    if not STOCK_POOL:
        print("⚠️ 股票池為空，仍繼續處理既有持股與待成交委託")

    api = DataLoader()
    if FINMIND_TOKEN:
        api.login_by_token(api_token=FINMIND_TOKEN)

    today_str = datetime.date.today().strftime("%Y-%m-%d")
    start_str = (datetime.date.today() - datetime.timedelta(days=150)).strftime("%Y-%m-%d")

    settlement_messages = settle_pending_orders(api, today_str)
    for msg in settlement_messages: print(msg)

    try:
        df_info = api.taiwan_stock_info()
        dynamic_name_dict = dict(zip(df_info["stock_id"], df_info["stock_name"]))
    except: dynamic_name_dict = {}

    sim_purchased_stocks = []
    if os.path.exists(PORTFOLIO_FILE):
        try:
            df_exist = pd.read_csv(PORTFOLIO_FILE, dtype={"stock_id": str})
            sim_purchased_stocks = df_exist["stock_id"].tolist()
        except: pass

    current_positions_count = len(sim_purchased_stocks)
    print(f"💰 [風控設定] 最大部位檔數: {MAX_PORTFOLIO_POSITIONS} 檔 | 總預算上限: {MAX_TOTAL_BUDGET:,.0f} 元")

    raw_ambush_data = []; raw_breakout_data = []; candidate_buys = []; current_3star_new = []; raw_limit_up_data = [] 
    GLOBAL_RADAR_RECORDS = []

    for stock in STOCK_POOL:
        try:
            c_name = dynamic_name_dict.get(stock, "")
            if "*" in c_name or stock in sim_purchased_stocks: continue
                
            df_raw = api.taiwan_stock_daily(stock_id=stock, start_date=start_str, end_date=today_str)
            if df_raw.empty or len(df_raw) < 60: continue 
            
            display_title = f"{stock} {c_name}".strip()
            df = pd.DataFrame()
            df["open"] = df_raw["open"].astype(float); df["close"] = df_raw["close"].astype(float); df["volume"] = df_raw["Trading_Volume"].astype(float) / 1000 
            if df.iloc[-1]["close"] == 0: continue
            
            # 🛠️ 縮短為 3 日死魚股偵測 (加速釋放資金)
            recent_3_close = df["close"].iloc[-3:]
            if len(recent_3_close) >= 3 and recent_3_close.max() == recent_3_close.min() and df.iloc[-1]["volume"] < 100:
                continue

            today_k = df_raw.iloc[-1]; yesterday_k = df_raw.iloc[-2] if len(df_raw) >= 2 else today_k
            if yesterday_k["close"] <= 0: continue 
            
            today_k_date = str(today_k["date"])[:10]
            try:
                days_diff = (datetime.datetime.strptime(today_str, "%Y-%m-%d").date() - datetime.datetime.strptime(today_k_date, "%Y-%m-%d").date()).days
            except:
                days_diff = 0
            
            today_change_pct = ((today_k["close"] - yesterday_k["close"]) / yesterday_k["close"]) * 100
            
            if days_diff == 0 and today_change_pct >= 9.8 and today_k["close"] == today_k["max"]:
                print(f"⚠️ [漲停標記] {display_title} 鎖死漲停，強制收錄至網頁觀測區！")
                display_title = f"{display_title} (漲停鎖死)"
                raw_limit_up_data.append({"stock_id": stock, "stock_name": c_name, "title": display_title})

            df["5MA"] = df["close"].rolling(5).mean(); df["10MA"] = df["close"].rolling(10).mean()
            df["20MA"] = df["close"].rolling(20).mean(); df["60MA"] = df["close"].rolling(60).mean()
            df["5MA_Vol"] = df["volume"].rolling(5).mean(); df['20STD'] = df['close'].rolling(20).std(ddof=0)
            df['BB_Width'] = ((df['20MA'] + 2*df['20STD']) - (df['20MA'] - 2*df['20STD'])) / df['20MA']
            df['EMA12'] = df['close'].ewm(span=12, adjust=False).mean(); df['EMA26'] = df['close'].ewm(span=26, adjust=False).mean()
            df['MACD'] = df['EMA12'] - df['EMA26']

            if df.iloc[-1]["volume"] < VOLUME_FILTER or df.iloc[-1]["5MA_Vol"] < VOLUME_5MA_FILTER: continue

            # 🛠️ 防護盾一：20MA與60MA乖離過濾 (剔除高檔假糾結)
            bias_20_60 = abs(df.iloc[-1]["20MA"] - df.iloc[-1]["60MA"]) / df.iloc[-1]["60MA"]
            if bias_20_60 > 0.045: continue

            # 🛠️ 防護盾二：近40天波段漲幅過濾 (避免買在半山腰)
            past_40d_min = df["close"].iloc[-40:].min()
            runup_ratio = (df.iloc[-1]["close"] - past_40d_min) / past_40d_min
            if runup_ratio > 0.18: continue

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
                actual_days_ago = triggered_days_ago + days_diff
                raw_breakout_data.append({"stock_id": stock, "stock_name": c_name, "title": display_title, "days_ago": actual_days_ago, "spread": bo_spread, "bb": bo_bb, "close": latest_close})
                is_bo_active = True 
                
                if actual_days_ago == 0:
                    print(f"🔬 偵測到今日發動標的：{display_title}，納入實戰建倉評估...")
                    hist_p, b_recs = run_pre_backtest(api, stock)
                    if b_recs:
                        for r in b_recs: r["stock_id"] = str(stock).strip(); GLOBAL_RADAR_RECORDS.append(r)
                    safe_score = hist_p if hist_p > 0 else 1  
                    candidate_buys.append({"stock_id": stock, "stock_name": c_name, "latest_close": latest_close, "buy_type": "正飆(0天)", "buy_date": today_k_date, "score": safe_score, "stars_display": "🚀 真·正飆破"})

            if not is_bo_active and df.iloc[-1]["5MA"] >= df.iloc[-1]["10MA"] >= df.iloc[-1]["20MA"]:
                today_ma = [df.iloc[-1]["5MA"], df.iloc[-1]["10MA"], df.iloc[-1]["20MA"]]
                
                if (max(today_ma) - min(today_ma)) / df.iloc[-1]["20MA"] <= MA_SPREAD_LIMIT:
                    stars_count = 1  
                    if df.iloc[-1]["BB_Width"] <= BB_COMPRESS_LIMIT: stars_count += 1  
                    if df.iloc[-1]["MACD"] > 0: stars_count += 1  
                        
                    stars_string = "⭐" * stars_count
                    raw_ambush_data.append({"stock_id": stock, "stock_name": c_name, "stars": stars_string, "title": display_title, "spread": (max(today_ma) - min(today_ma)) / df.iloc[-1]["20MA"], "bb": df.iloc[-1]["BB_Width"], "macd": "水上" if df.iloc[-1]["MACD"] > 0 else "水下", "close": latest_close})
                    
                    if stars_count == 3 and days_diff == 0:
                        current_3star_new.append({"stock_id": stock, "stock_name": c_name, "close": latest_close})
                        print(f"🔬 偵測到 3星起飆新秀：{display_title}，納入實戰建倉評估...")
                        hist_p, b_recs = run_pre_backtest(api, stock)
                        if b_recs:
                            for r in b_recs: r["stock_id"] = str(stock).strip(); GLOBAL_RADAR_RECORDS.append(r)
                        safe_score = hist_p if hist_p > 0 else 1 
                        candidate_buys.append({"stock_id": stock, "stock_name": c_name, "latest_close": latest_close, "buy_type": "3星起飆", "buy_date": today_k_date, "score": safe_score, "stars_display": "⭐⭐⭐ 滿星潛伏"})
        except Exception as e:
            print(f"⚠️ 處理 {stock} 時發生錯誤: {e}")
            continue
        time.sleep(0.01)

    # V1.47: 今晚僅產生候選委託，隔日開盤才記入模擬持股。
    new_sim_buys = []
    existing_pending = _read_csv(PENDING_BUY_FILE)
    pending_ids = set(existing_pending['stock_id'].astype(str)) if not existing_pending.empty else set()
    candidate_buys.sort(key=lambda c: float(c.get('score', 0)), reverse=True)
    slots = max(0, MAX_PORTFOLIO_POSITIONS - current_positions_count - len(pending_ids))
    for c in candidate_buys:
        if slots <= 0: break
        if str(c['stock_id']) in pending_ids: continue
        new_sim_buys.append(c)
        pending_ids.add(str(c['stock_id']))
        slots -= 1
    if new_sim_buys:
        rows = [{'stock_id':str(c['stock_id']),'stock_name':c['stock_name'],
                 'signal_date':c['buy_date'],'signal_close':c['latest_close'],
                 'buy_type':c['buy_type'],'stars_display':c['stars_display']} for c in new_sim_buys]
        existing_pending = pd.concat([existing_pending, pd.DataFrame(rows)], ignore_index=True)
        _save_csv(existing_pending, PENDING_BUY_FILE)
    # 舊最佳化器策略與主程式不同，暫停覆寫 best_ma/best_tp/best_drop。
    if ENABLE_LEGACY_OPTIMIZER:
        print('⚠️ 舊優化器未同步 V1.47 交易規則，不建議啟用。')

    if GLOBAL_RADAR_RECORDS:
        df_radar = pd.DataFrame(GLOBAL_RADAR_RECORDS)
        df_radar = df_radar[["stock_id", "buy_date", "buy_price", "sell_date", "sell_price", "net_profit", "profit_percent", "exit_reason"]]
        df_radar.to_csv(OPTIMIZER_DETAILS_FILE, mode='a', header=not os.path.exists(OPTIMIZER_DETAILS_FILE), index=False, encoding="utf-8-sig")

    exit_text, port_text, html_p_data = update_and_print_portfolio(api, today_str)
    
    df_wl_old = pd.read_csv(WATCHLIST_FILE, dtype={"stock_id": str}) if os.path.exists(WATCHLIST_FILE) else pd.DataFrame(columns=["stock_id", "stock_name", "初次評選日", "當初潛伏價格", "目前最新收盤", "已觀測天數", "評等"])
    v134_落難老兵 = globals().get("GLOBAL_V134_落難老兵", [])
    
    wl_updated = []
    for _, wl_r in df_wl_old.iterrows():
        wl_sid = str(wl_r["stock_id"]).strip(); wl_days = int(wl_r["已觀測天數"]) + 1
        if wl_sid in sim_purchased_stocks or wl_days > 3: continue
        try:
            d_w = api.taiwan_stock_daily(stock_id=wl_sid, start_date=start_str, end_date=today_str)
            c_p = float(d_w.iloc[-1]["close"])
            if ((c_p - float(wl_r["當初潛伏價格"])) / float(wl_r["當初潛伏價格"])) * 100 <= -5.0: continue
            
            wl_updated.append({
                "stock_id": wl_sid, "stock_name": wl_r["stock_name"], "初次評選日": wl_r["初次評選日"],
                "當初潛伏價格": float(wl_r["當初潛伏價格"]), "目前最新收盤": c_p, "已觀測天數": wl_days, "評等": wl_r["評等"]
            })
        except: pass
        
    for old_soldier in v134_落難老兵:
        if old_soldier["stock_id"] not in [r["stock_id"] for r in wl_updated]:
            wl_updated.append({
                "stock_id": old_soldier["stock_id"], "stock_name": old_soldier["stock_name"],
                "初次評選日": today_str, "當初潛伏價格": old_soldier["close"], "currently_price": old_soldier["close"],
                "已觀測天數": 1, "評等": "⚠️ 均線警戒老兵"
            })
            
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
        pd.DataFrame(columns=["stock_id", "stock_name", "初次評選日", "當初潛伏價格", "currently_price", "已觀測天數", "評等"]).to_csv(WATCHLIST_FILE, index=False, encoding="utf-8-sig")

    h_bo_str = []
    for r in raw_breakout_data:
        lbl = "今天發動" if r["days_ago"]==0 else f"{r['days_ago']}天前"
        h_bo_str.append(f'<span class="badge bg-danger me-2">{lbl}</span> <strong>{r["title"]}</strong> <span class="text-muted-custom small ms-2">| 均線壓縮: {r["spread"]*100:.1f}% | 布林帶寬: {r["bb"]:.2f}</span>')
        
    h_am_str = []
    for r in raw_ambush_data:
        h_am_str.append(f'<span class="badge bg-success me-2">{r["stars"]} 潛伏</span> <strong>{r["title"]}</strong> <span class="text-muted-custom small ms-2">| 均線壓縮: {r["spread"]*100:.1f}% | 布林帶寬: {r["bb"]:.2f} | MACD: {r["macd"]}</span>')

    generate_one_page_html(today_str, h_bo_str, h_am_str, html_p_data, raw_breakout_data, raw_ambush_data, raw_limit_up_data)

    try:
        p_dir = os.path.dirname(PORTFOLIO_FILE)
        subprocess.run(["git", "add", "."], cwd=p_dir, check=True)
        
        commit_res = subprocess.run(
            ["git", "commit", "-m", f"📋 雷達自動更新: {today_str}"], 
            cwd=p_dir, capture_output=True, text=True, encoding="utf-8"
        )
        if commit_res.returncode == 0:
            print("📝 [Git 提交] 本地端 Commit 成功！")
        else:
            if "nothing to commit" in commit_res.stdout or "nothing to commit" in commit_res.stderr:
                print("📝 [Git 提示] 今日數據無任何變更，無需產生新 Commit。")
            else:
                print(f"⚠️ [Git 警告] Commit 異常: {commit_res.stderr.strip()}")
        
        push_res = subprocess.run(
            ["git", "push", "origin", "main"], 
            cwd=p_dir, capture_output=True, text=True, encoding="utf-8"
        )
        if push_res.returncode == 0:
            print("✅ [雲端同步] 成功推送到 GitHub 伺服器！")
        else:
            print(f"🛑 [雲端同步失敗] GitHub 拒絕推送！錯誤原因：\n{push_res.stderr}")
            
    except Exception as git_e:
        print(f"🛑 [Git 管線崩潰] 無法執行 Git 命令，原因: {git_e}")

    line_report_chunks = []
        
    if settlement_messages:
        line_report_chunks.append('📒【隔日開盤模擬成交回報】')
        line_report_chunks.extend(settlement_messages)
        line_report_chunks.append('───────────────────')
    if new_sim_buys:
        line_report_chunks.append('🚀【明日候選買進（尚未成交）】')
        line_report_chunks.append('⚠️ 明日開盤價確認後重新計算股數；跳空過高則放棄')
        for nb in new_sim_buys:
            estimate = int(FIXED_STOCK_BUDGET // float(nb['latest_close']))
            line_report_chunks.append(f"▪️ {nb['stock_id']} {nb['stock_name']} ({nb['stars_display']})\n  ➔ 參考收盤 {nb['latest_close']:.2f} 元｜估計約 {estimate} 股（非最終成交股數）")
        line_report_chunks.append('───────────────────')

    if exit_text.strip():
        exit_rows = []
        for line in exit_text.split('\n'):
            line_clean = line.strip()
            if line_clean and ("明日待賣" in line_clean or "待賣訊號" in line_clean or "行情" in line_clean):
                exit_rows.append(line_clean)
                
        if exit_rows:
            line_report_chunks.append("💀【在倉老兵即時清倉離場 / 警戒通知】")
            for er in exit_rows:
                line_report_chunks.append(f"▪️ {er}")
            line_report_chunks.append("───────────────────")

    if line_report_chunks:
        if line_report_chunks[-1] == "───────────────────":
            line_report_chunks.pop()
            
        header = [
            f"🐬 海豚選股 V1.47 決戰指標 🐬",
            f"📅 戰略日期：{today_str}",
            f"───────────────────"
        ]
        final_report_text = "\n".join(header + line_report_chunks)
        send_line_notify(final_report_text)
    else:
        print("📭 [實戰監控] 在倉股票安穩續抱中，且無新秀觸發，自動封鎖 LINE 雜訊不打擾。")

    return

if __name__ == "__main__":
    import nest_asyncio; nest_asyncio.apply()
    asyncio.run(main())
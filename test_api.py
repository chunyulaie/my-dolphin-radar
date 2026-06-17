import datetime
from FinMind.data import DataLoader

def test_finmind():
    api = DataLoader()
    api.login_by_token(api_token="eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9.eyJ1c2VyX2lkIjoicGNoaW9uMjAwMiIsImVtYWlsIjoibGFpZWNodW55dUBnbWFpbC5jb20iLCJ0b2tlbl92ZXJzaW9uIjowfQ.si_2Ta3AlY1JtgVBDlqpnkaK3IH41Drrc7ogVgNBJq8")
    
    # 設定抓取近 10 天的資料
    today_str = datetime.date.today().strftime("%Y-%m-%d")
    start_str = (datetime.date.today() - datetime.timedelta(days=10)).strftime("%Y-%m-%d")

    print("🔍 正在測試敲門 FinMind API...")
    
    try:
        # 拿護國神山 2330 來測試最準
        df_raw = api.taiwan_stock_daily(stock_id="2330", start_date=start_str, end_date=today_str)
        
        if df_raw.empty:
            print("⚠️ 連線成功，但回傳的是空資料！(可能遇到流量限制的軟封鎖)")
        else:
            print("✅ 恭喜！連線完全正常，你沒有被 Ban！")
            print("下面是抓到的最新一筆資料：")
            print(df_raw.iloc[-1])
            
    except Exception as e:
        print("❌ 破案了！你確實被 FinMind 封鎖 (或遇到連線異常)！")
        print(f"致命錯誤原因：{e}")

if __name__ == "__main__":
    test_finmind()
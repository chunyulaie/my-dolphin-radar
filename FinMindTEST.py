import datetime
from FinMind.data import DataLoader

def check_finmind_update():
    # 填入你的 Token
    TOKEN = "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9.eyJ1c2VyX2lkIjoicGNoaW9uNzcxMjA4MTIwOEBnbWFpbC5jb20iLCJlbWFpbCI6InBjaGlvbjc3MTIwODEyMDhAZ21haWwuY29tIiwidG9rZW5fdmVyc2lvbiI6MH0.Zw1f1denl7Uif0QAEpqYoIYSAPwP_vJTwSwckbdchKQ"
    
    api = DataLoader()
    api.login_by_token(api_token=TOKEN)
    
    # 設定時間：抓最近 7 天的資料就好，避免耗費資源
    today = datetime.date.today()
    today_str = today.strftime("%Y-%m-%d")
    start_str = (today - datetime.timedelta(days=7)).strftime("%Y-%m-%d")
    
    # 拿台股最具代表性的 0050 當作觀測站
    benchmark_stock = "0050" 
    
    print(f"📡 正在向 FinMind 伺服器發送探針...")
    try:
        df = api.taiwan_stock_daily(stock_id=benchmark_stock, start_date=start_str, end_date=today_str)
        
        if df.empty:
            print("❌ 伺服器無回應，可能是 Token 額度已滿或連線異常。")
            return False
            
        # 抓取回傳資料的最後一筆日期
        latest_date_in_db = str(df.iloc[-1]["date"])[:10]
        
        print("----------------------------------------------------")
        print(f"📅 系統今日日期：{today_str}")
        print(f"🗄️ FinMind 最新收盤日：{latest_date_in_db}")
        print("----------------------------------------------------")
        
        if latest_date_in_db == today_str:
            print("✅ 【綠燈】FinMind 今日盤後資料已全部更新完畢！你可以啟動海豚主程式了！")
            return True
        else:
            print("⏳ 【黃燈】資料尚未更新至今日，目前停留在昨天的收盤價，請稍後再試。")
            return False
            
    except Exception as e:
        print(f"⚠️ 發生錯誤：{e}")
        return False

if __name__ == "__main__":
    check_finmind_update()
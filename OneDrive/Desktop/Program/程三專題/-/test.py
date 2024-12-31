import yfinance as yf
import pandas as pd
from tabulate import tabulate
from FinMind.data import DataLoader
from linebot import LineBotApi, WebhookHandler
from linebot.v3.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage
from flask import Flask, request, abort
import logging
import os
from pyngrok import ngrok

app = Flask(__name__)

line_bot_api = LineBotApi('lUiTVUUL69HwuW7Ah3PYDR/J+LNo1IVXWTAOOW4HlMt53geLCAHEqD1L1D1ebEMKHErUYei6s4/yKn7Fvx1hG4hMJPiEd7xtXLZevsrpwELH+Qfpts59P95enqGopmTdV0lrrbnNi46t+8IQNwlLQAdB04t89/1O/w1cDnyilFU=')
handler = WebhookHandler('b57cad0a7f004c6e243d9779a14b4817')

# 設置日誌
logging.basicConfig(level=logging.INFO)

@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers['X-Line-Signature']
    body = request.get_data(as_text=True)
    logging.info(f"請求正文: {body}")
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    return 'OK'

@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    user_message = event.message.text.strip()
    logging.info(f"收到消息: {user_message}")
    
    if user_message.lower() == "hello":
        welcome_message = "您好，輸入股票代碼，即可為您服務"
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text=welcome_message)
        )
        return
    
    tickers = [ticker + '.TW' for ticker in user_message.split()]
    if not all(ticker.replace('.', '').isalnum() for ticker in tickers):
        error_message = "請輸入正確ETF代碼"
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text=error_message)
        )
        return
    
    try:
        analysis_table = create_analysis_table(tickers)
        response_text = tabulate(analysis_table, headers='keys', tablefmt='grid', showindex=False)
        if len(response_text) > 5000:
            response_text = response_text[:4997] + '...'
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text=response_text)
        )
        
        # 下載股票數據並保存到本地資料夾
        for ticker in tickers:
            df = get_stock_data(ticker)
            if df.empty:
                # 嘗試使用 .TWO
                ticker = ticker.replace('.TW', '.TWO')
                df = get_stock_data(ticker)
            file_path = os.path.join(os.getcwd(), f"{ticker}.csv")
            df.to_csv(file_path)
            logging.info(f"股票數據已保存至: {file_path}")
        
    except Exception as e:
        logging.error(f"處理消息時出錯: {e}")
        error_message = "伺服器內部錯誤，請稍後再試"
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text=error_message)
        )

def get_stock_data(ticker):
    stock_id = ticker.split('.')[0]
    dl = DataLoader()
    end_date = pd.Timestamp.today().strftime('%Y-%m-%d')
    df = dl.taiwan_stock_daily(stock_id=stock_id, start_date='2000-01-01', end_date=end_date)
    df.rename(columns={'close': 'Close'}, inplace=True)
    if 'adj_close' in df.columns:
        df.rename(columns={'adj_close': 'Adj Close'}, inplace=True)
    else:
        df['Adj Close'] = df['Close']
    return df

# 計算年化報酬率
def calculate_annual_return(df):
    if len(df) < 252:  # 確保有足夠的交易日數據
        return None
    start_price = df['Adj Close'].iloc[0]
    end_price = df['Adj Close'].iloc[-1]
    total_return = (end_price - start_price) / start_price
    # 年化報酬率公式: (1 + 總報酬率)^(252 / 交易日數) - 1
    annual_return = (1 + total_return) ** (252 / len(df)) - 1
    return annual_return

# 計算年化夏普比率
def calculate_sharpe_ratio(df, risk_free_rate=0.01):
    daily_returns = df['Adj Close'].pct_change().dropna()
    excess_returns = daily_returns - risk_free_rate / 252
    # 年化夏普比率公式: (平均超額報酬率 / 標準差) * sqrt(252)
    annual_sharpe_ratio = (excess_returns.mean() / excess_returns.std()) * (252 ** 0.5)
    return annual_sharpe_ratio

# 計算最大回落比率
def calculate_max_drawdown(df):
    cumulative_returns = (1 + df['Adj Close'].pct_change().dropna()).cumprod()
    peak = cumulative_returns.cummax()
    drawdown = (cumulative_returns - peak) / peak
    max_drawdown = drawdown.min()
    return abs(max_drawdown)  # 取絕對值

# 分析數據：計算移動平均線
def calculate_moving_averages(df):
    df['20日均線'] = df['Adj Close'].rolling(window=20).mean()
    return df

# 從CSV文件中讀取數據並計算年化報酬率、年化夏普比率和最大回落比率
def process_csv_data(file_path):
    df = pd.read_csv(file_path)
    df['20日均線'] = df['Adj Close'].rolling(window=20).mean()
    annual_return = calculate_annual_return(df)
    sharpe_ratio = calculate_sharpe_ratio(df)
    max_drawdown = calculate_max_drawdown(df)
    return df, annual_return, sharpe_ratio, max_drawdown

# 輸出分析表格
def create_analysis_table(tickers):
    analysis_table = pd.DataFrame(columns=['股票代碼', '收盤價', '20日均線', '年化報酬率', '年化夏普比率', '最大回落比率'])
    
    for ticker in tickers:
        df = get_stock_data(ticker)
        if df.empty:
            # 嘗試使用 .TWO
            ticker = ticker.replace('.TW', '.TWO')
            df = get_stock_data(ticker)
        if df.empty:
            continue
        file_path = os.path.join(os.getcwd(), f"{ticker}.csv")
        df.to_csv(file_path)
        logging.info(f"股票數據已保存至: {file_path}")
        
        df, annual_return, sharpe_ratio, max_drawdown = process_csv_data(file_path)
        
        latest_data = df.iloc[-1]
        annual_return_str = f"{annual_return:.2%}" if annual_return is not None else "無法計算"
        sharpe_ratio_str = f"{sharpe_ratio:.2f}" if sharpe_ratio is not None else "無法計算"
        max_drawdown_str = f"{max_drawdown:.2%}" if max_drawdown is not None else "無法計算"
        
        analysis_table = pd.concat([analysis_table, pd.DataFrame({
            '股票代碼': ticker,
            '收盤價': f"{latest_data['Close']} (TWD)",
            '20日均線': f"{latest_data['20日均線']} (TWD)",
            '年化報酬率': annual_return_str,
            '年化夏普比率': sharpe_ratio_str,
            '最大回落比率': max_drawdown_str
        })])
    
    return analysis_table

if __name__ == "__main__":
    # 啟動 ngrok
    public_url = ngrok.connect(5000).public_url
    print("ngrok public URL:", public_url)
    
    app.run(port=5000)

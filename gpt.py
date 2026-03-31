import ccxt
import pandas as pd
import numpy as np
import time
import requests
from itertools import product
from datetime import datetime, timezone
from sklearn.ensemble import RandomForestClassifier

# ======================
# 🔐 API
# ======================
API_KEY = "72428777-7fe7-4c3c-a51a-abc7d1b56ed0"
SECRET = "C153B5C7BBFDD64EF717DCE293DDF77E"
PASSPHRASE = "3364586@Fj"

# DeepSeek API
DEEPSEEK_API_KEY = "sk-87b06557c7354999966871a85cfb86b0"

exchange = ccxt.okx({
    'apiKey': API_KEY,
    'secret': SECRET,
    'password': PASSPHRASE,
    'enableRateLimit': True,
    'options': {'defaultType': 'swap'}
})

SYMBOLS = ['BTC/USDT:USDT','ETH/USDT:USDT','XAU/USDT:USDT']
TIMEFRAME = '5m'

# ======================
# 💰 资金 & 风控
# ======================
INITIAL_CAPITAL = 100
MAX_DRAWDOWN = 0.2
TARGET_VOL = 0.02
MAX_RISK_PER_TRADE = 0.02
MAX_POSITION_RATIO = 0.3
LEVERAGE = 5

peak_equity = INITIAL_CAPITAL

# ======================
# 📊 参数空间
# ======================
PARAM_GRID = {
    "sma_s": [10,20],
    "sma_l": [40,50],
    "bb_std": [1.5,2],
    "atr_mult": [1.0,1.5],
    "breakout": [15,20]
}

# ======================
# 📥 数据
# ======================
def get_data(symbol, tf, limit=500):
    ohlcv = exchange.fetch_ohlcv(symbol, tf, limit=limit)
    df = pd.DataFrame(ohlcv, columns=['ts','open','high','low','close','volume'])
    df['ret'] = df['close'].pct_change()
    return df

def get_multi_tf_data(symbol):
    df_15m = get_data(symbol, '15m')
    df_1h = get_data(symbol, '1h', 200)
    return df_15m, df_1h

# ======================
# 📈 指标
# ======================
def add_indicators(df, p):
    df['sma_s'] = df['close'].rolling(p['sma_s']).mean()
    df['sma_l'] = df['close'].rolling(p['sma_l']).mean()

    std = df['close'].rolling(20).std()
    ma = df['close'].rolling(20).mean()

    df['upper'] = ma + p['bb_std']*std
    df['lower'] = ma - p['bb_std']*std

    df['high_break'] = df['high'].rolling(p['breakout']).max()
    df['low_break'] = df['low'].rolling(p['breakout']).min()

    df['atr'] = (df['high'] - df['low']).rolling(14).mean()
    return df

# ======================
# 🤖 AI预测（本地）
# ======================
def ai_local(df):

    df = df.copy()
    df['ma'] = df['close'].rolling(10).mean()
    df['std'] = df['close'].rolling(10).std()
    df['ret1'] = df['close'].pct_change()

    df = df.dropna()

    if len(df) < 50:
        return 0

    X = df[['ma','std','ret1']]
    y = (df['close'].shift(-1) > df['close']).astype(int)

    model = RandomForestClassifier(n_estimators=50)
    model.fit(X[:-1], y[:-1])

    pred = model.predict(X.iloc[[-1]])[0]

    return 1 if pred==1 else -1

# ======================
# 🤖 DeepSeek API（权重调节）
# ======================
def ai_weight_adjust():

    try:
        url = "https://api.deepseek.com/v1/chat/completions"

        headers = {
            "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
            "Content-Type": "application/json"
        }

        prompt = "当前加密市场更偏向趋势、震荡还是高波动？只回答 TREND / RANGE / VOL"

        data = {
            "model": "deepseek-chat",
            "messages": [{"role": "user", "content": prompt}]
        }

        res = requests.post(url, headers=headers, json=data, timeout=5)
        text = res.json()['choices'][0]['message']['content']

        if "TREND" in text:
            return (0.6,0.2,0.2)
        elif "RANGE" in text:
            return (0.2,0.6,0.2)
        else:
            return (0.3,0.2,0.5)

    except:
        return (0.4,0.3,0.3)

# ======================
# 🧠 1H趋势
# ======================
def higher_tf_trend(df):
    sma_fast = df['close'].rolling(20).mean()
    sma_slow = df['close'].rolling(50).mean()
    return 1 if sma_fast.iloc[-1] > sma_slow.iloc[-1] else -1

# ======================
# 💰 仓位
# ======================
def kelly():
    win=0.55
    rr=2
    return max(0, win-(1-win)/rr)

def vol_control(df):
    v = df['ret'].std()
    if v==0: return 0
    return min(1, TARGET_VOL/v)

# ======================
# 📉 风控
# ======================
def get_balance():
    return exchange.fetch_balance()['total']['USDT']

def drawdown(eq):
    global peak_equity
    if eq>peak_equity:
        peak_equity=eq
    return (peak_equity-eq)/peak_equity

# ======================
# 🚀 下单（强化）
# ======================
def order(symbol, side, size, price, atr, p):

    stop_distance = p['atr_mult'] * atr
    risk_per_unit = stop_distance

    balance = get_balance()

    size = min(size, balance * MAX_POSITION_RATIO / price)

    max_loss = size * risk_per_unit
    if max_loss > balance * MAX_RISK_PER_TRADE:
        size = (balance * MAX_RISK_PER_TRADE) / risk_per_unit

    exchange.create_market_order(symbol, side.lower(), size)

    if side=="buy":
        sl = price - stop_distance
        tp = price + 2*stop_distance
        close_side="sell"
    else:
        sl = price + stop_distance
        tp = price - 2*stop_distance
        close_side="buy"

    exchange.create_order(symbol,'stop_market',close_side,size,None,
        {'stopPrice':sl,'reduceOnly':True})

    exchange.create_order(symbol,'take_profit_market',close_side,size,None,
        {'stopPrice':tp,'reduceOnly':True})

# ======================
# 🔥 回测
# ======================
def backtest(df, p):

    df = add_indicators(df.copy(), p)
    sig = np.sign(df['sma_s'] - df['sma_l'])

    df['strategy'] = df['ret'] * sig
    sharpe = df['strategy'].mean() / df['strategy'].std()

    return sharpe

# ======================
# 🔥 参数优化
# ======================
def optimize(df):

    best=None
    best_score=-999

    for vals in product(*PARAM_GRID.values()):
        p=dict(zip(PARAM_GRID.keys(),vals))
        sharpe = backtest(df, p)

        if sharpe>best_score:
            best_score=sharpe
            best=p

    return best

# ======================
# 🔄 自动调仓
# ======================
def rebalance(scores):
    total = sum(abs(v) for v in scores.values())
    return {k: v/total if total!=0 else 0 for k,v in scores.items()}

# ======================
# 🧠 信号融合（核心）
# ======================
def combined_signal(df_15m, df_1h, p):

    df_15m = add_indicators(df_15m, p)

    trend = np.sign(df_15m['sma_s'].iloc[-1]-df_15m['sma_l'].iloc[-1])
    mean = 1 if df_15m['close'].iloc[-1]<df_15m['lower'].iloc[-1] else -1 if df_15m['close'].iloc[-1]>df_15m['upper'].iloc[-1] else 0
    brk = 1 if df_15m['close'].iloc[-1]>df_15m['high_break'].iloc[-2] else -1 if df_15m['close'].iloc[-1]<df_15m['low_break'].iloc[-2] else 0

    base = trend + mean + brk

    ht = higher_tf_trend(df_1h)
    ai = ai_local(df_15m)

    w = ai_weight_adjust()

    score = base*w[0] + ht*w[1] + ai*w[2]

    return score

# ======================
# 🧠 主交易
# ======================
def trade():

    balance = get_balance()
    dd = drawdown(balance)

    print(f"资金:{balance} 回撤:{dd:.2%}")

    if dd > MAX_DRAWDOWN:
        print("❌ 停止交易")
        return

    scores = {}

    for sym in SYMBOLS:

        df_15m, df_1h = get_multi_tf_data(sym)

        if df_15m['ret'].std() > 0.05:
            continue

        p = optimize(df_15m)

        score = combined_signal(df_15m, df_1h, p)

        scores[sym] = score

    weights = rebalance(scores)

    for sym in scores:

        score = scores[sym]

        if abs(score) < 0.5:
            continue

        df_15m, _ = get_multi_tf_data(sym)
        p = optimize(df_15m)

        atr = df_15m['atr'].iloc[-1]
        price = df_15m['close'].iloc[-1]

        side = "buy" if score > 0 else "sell"

        capital = balance * abs(weights[sym])
        size = (capital * LEVERAGE) / price

        order(sym, side, size, price, atr, p)

# ======================
# ⏱️ 定时
# ======================
def wait():
    now = datetime.now(timezone.utc)
    sleep = (15-now.minute%15)*60
    time.sleep(sleep)

# ======================
# ▶️ 启动
# ======================
while True:
    try:
        trade()
        wait()
    except Exception as e:
        print(e)
        time.sleep(60)
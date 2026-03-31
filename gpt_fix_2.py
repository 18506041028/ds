import ccxt
import pandas as pd
import numpy as np
import time
import requests
import logging
from itertools import product
from datetime import datetime, timezone
from sklearn.ensemble import RandomForestClassifier
from openai import OpenAI
import os

# ======================
# 🧾 日志系统
# ======================
logging.basicConfig(
    filename='trading.log',
    level=logging.INFO,
    format='%(asctime)s | %(levelname)s | %(message)s'
)

def log(msg):
    print(msg)
    logging.info(msg)

# ======================
# 🔐 API配置（保留你的KEY）
# ======================
API_KEY = "72428777-7fe7-4c3c-a51a-abc7d1b56ed0"
SECRET = "C153B5C7BBFDD64EF717DCE293DDF77E"
PASSPHRASE = "3364586@Fj"

DEEPSEEK_API_KEY = "sk-87b06557c7354999966871a85cfb86b0"

deepseek_client = OpenAI(
    api_key=DEEPSEEK_API_KEY,
    base_url="https://api.deepseek.com"
)

exchange = ccxt.okx({
    'apiKey': API_KEY,
    'secret': SECRET,
    'password': PASSPHRASE,
    'enableRateLimit': True,
    'options': {'defaultType': 'swap'}
})

SYMBOLS = ['BTC/USDT:USDT','ETH/USDT:USDT','XAU/USDT:USDT']

# ======================
# ⚙️ 杠杆设置（已修复）
# ======================
LEVERAGE = 5

def set_leverage():
    for sym in SYMBOLS:
        try:
            instId = sym.replace("/", "-").replace(":USDT","-SWAP")
            params = {"mgnMode":"isolated"}
            exchange.set_leverage(LEVERAGE, instId, params)
            log(f"⚙️ 杠杆成功 {instId} {LEVERAGE}x")
        except Exception as e:
            log(f"❌ 杠杆失败 {sym} {e}")

# ======================
# 💰 资金管理
# ======================
INITIAL_CAPITAL = 100
MAX_DRAWDOWN = 0.2
MAX_TOTAL_POSITION = 0.1
MAX_POSITION_RATIO = 0.3
LEVERAGE = 5

peak_equity = INITIAL_CAPITAL

# ======================
# 📊 参数
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
def get_data(symbol, tf, limit=200):
    try:
        ohlcv = exchange.fetch_ohlcv(symbol, tf, limit=limit)
        df = pd.DataFrame(ohlcv, columns=['ts','open','high','low','close','volume'])
        df['ret'] = df['close'].pct_change()
        return df
    except Exception as e:
        log(f"❌ 获取数据失败 {symbol} {e}")
        return None

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
# 🤖 本地AI
# ======================
def ai_local(df):
    try:
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
        return 1 if pred else -1

    except Exception as e:
        log(f"❌ 本地AI失败 {e}")
        return 0

# ======================
# 🤖 AI缓存（已优化）
# ======================
AI_CACHE = {"time": None, "weights": (0.4,0.3,0.3)}

def ai_weight_adjust():
    global AI_CACHE
    now = time.time()

    if AI_CACHE["time"] and now - AI_CACHE["time"] < 900:
        return AI_CACHE["weights"]

    try:
        response = deepseek_client.chat.completions.create(
            model="deepseek-chat",
            messages=[{"role": "user", "content": "市场状态 TREND / RANGE / VOL"}],
            temperature=0.1
        )

        text = response.choices[0].message.content.upper()

        if "TREND" in text:
            w = (0.6,0.2,0.2)
        elif "RANGE" in text:
            w = (0.2,0.6,0.2)
        else:
            w = (0.3,0.2,0.5)

        AI_CACHE = {"time": now, "weights": w}

        log(f"🧠 AI权重 {w}")

        return w

    except Exception as e:
        log(f"⚠️ AI失败 {e}")
        return AI_CACHE["weights"]

# ======================
# 🧠 高周期趋势
# ======================
def higher_tf_trend(df):
    sma_fast = df['close'].rolling(20).mean()
    sma_slow = df['close'].rolling(50).mean()
    return 1 if sma_fast.iloc[-1] > sma_slow.iloc[-1] else -1

# ======================
# 💰 资金
# ======================
def get_balance():
    try:
        return exchange.fetch_balance()['total']['USDT']
    except Exception as e:
        log(f"❌ 获取余额失败 {e}")
        return 0

def drawdown(eq):
    global peak_equity
    if eq > peak_equity:
        peak_equity = eq
    return (peak_equity - eq) / peak_equity

# ======================
# 📊 总仓位
# ======================
def get_total_position():
    try:
        pos = exchange.fetch_positions()
        total = 0
        for p in pos:
            if p['contracts'] > 0:
                total += abs(p['notional'])
        return total
    except:
        return 0

# ======================
# 🚀 下单
# ======================
def order(symbol, side, size):
    try:
        exchange.create_market_order(symbol, side, size)
        log(f"🚀 下单 {symbol} {side} 数量:{size:.4f}")
    except Exception as e:
        log(f"❌ 下单失败 {symbol} {e}")

# ======================
# 🧠 信号
# ======================
def combined_signal(df15, df1h, p, w):

    df15 = add_indicators(df15, p)

    trend = np.sign(df15['sma_s'].iloc[-1]-df15['sma_l'].iloc[-1])
    mean = 1 if df15['close'].iloc[-1]<df15['lower'].iloc[-1] else -1 if df15['close'].iloc[-1]>df15['upper'].iloc[-1] else 0
    brk = 1 if df15['close'].iloc[-1]>df15['high_break'].iloc[-2] else -1 if df15['close'].iloc[-1]<df15['low_break'].iloc[-2] else 0

    base = trend + mean + brk
    ht = higher_tf_trend(df1h)
    ai = ai_local(df15)

    score = base*w[0] + ht*w[1] + ai*w[2]

    log(f"📊 base:{base} HT:{ht} AI:{ai} -> score:{score:.2f}")

    return score

# ======================
# 🧠 主交易
# ======================
def trade():

    balance = get_balance()
    dd = drawdown(balance)

    log(f"💰 资金:{balance:.2f} 回撤:{dd:.2%}")

    if dd > MAX_DRAWDOWN:
        log("❌ 触发最大回撤，停止交易")
        return

    total_pos = get_total_position()
    if total_pos > balance * MAX_TOTAL_POSITION:
        log("⚠️ 已达最大总仓位")
        return

    w = ai_weight_adjust()

    scores = {}

    for sym in SYMBOLS:

        df15 = get_data(sym,'15m')
        df1h = get_data(sym,'1h')

        if df15 is None or df1h is None:
            continue

        p = {"sma_s":10,"sma_l":50,"bb_std":2,"atr_mult":1,"breakout":20}

        score = combined_signal(df15, df1h, p, w)

        scores[sym] = score

    total = sum(abs(v) for v in scores.values())

    for sym in scores:

        if abs(scores[sym]) < 0.5:
            continue

        alloc = balance * MAX_TOTAL_POSITION * (abs(scores[sym]) / total)

        df = get_data(sym,'15m')
        if df is None:
            continue

        price = df['close'].iloc[-1]

        size = (alloc * LEVERAGE) / price

        side = "buy" if scores[sym] > 0 else "sell"

        order(sym, side, size)

# ======================
# ⏱️ 定时
# ======================
def wait():
    now = datetime.now(timezone.utc)
    sleep = (15 - now.minute % 15) * 60
    time.sleep(sleep)

# ======================
# ▶️ 启动
# ======================
set_leverage()

while True:
    try:
        trade()
        wait()
    except Exception as e:
        log(f"❌ 主循环错误 {e}")
        time.sleep(60)
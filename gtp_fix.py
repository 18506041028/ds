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
# 🧾 日志系统（核心）
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
# 🔐 API配置
# ======================
API_KEY = "72428777-7fe7-4c3c-a51a-abc7d1b56ed0"
SECRET = "C153B5C7BBFDD64EF717DCE293DDF77E"
PASSPHRASE = "3364586@Fj"

# DeepSeek API - 使用OpenAI兼容方式
DEEPSEEK_API_KEY = "sk-87b06557c7354999966871a85cfb86b0"

# 初始化DeepSeek客户端
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

# 加载市场信息
try:
    markets = exchange.load_markets()
except Exception as e:
    log(f"⚠️ 加载市场信息失败: {e}")
    markets = {}

# 定义最小订单量映射
MIN_ORDER_SIZE = {
    'BTC/USDT:USDT': 0.1,  # BTC最小订单量
    'ETH/USDT:USDT': 1,   # ETH最小订单量
    'XAU/USDT:USDT': 10,     # XAU最小订单量
}

# ======================
# 💰 资金管理
# ======================
INITIAL_CAPITAL = 100
MAX_DRAWDOWN = 0.2
TARGET_VOL = 0.02
MAX_RISK_PER_TRADE = 0.02
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
# 📥 获取数据（带容错）
# ======================
def get_data(symbol, tf, limit=500):
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
# 🤖 本地AI预测
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
        return 1 if pred==1 else -1

    except Exception as e:
        log(f"❌ AI预测失败 {e}")
        return 0

# ======================
# 🤖 DeepSeek权重 - 使用新的方法
# ======================
def ai_weight_adjust():
    try:
        # 获取最近的市场数据用于分析
        df = get_data('BTC/USDT:USDT', '1h', 50)
        if df is None:
            log("❌ 获取BTC数据失败，使用默认权重")
            return (0.4, 0.3, 0.3)
            
        current_price = df['close'].iloc[-1]
        sma_20 = df['close'].rolling(20).mean().iloc[-1]
        sma_50 = df['close'].rolling(50).mean().iloc[-1]
        
        # 构造分析提示
        prompt = f"""
        当前BTC价格: {current_price:.2f}
        20周期均线: {sma_20:.2f}
        50周期均线: {sma_50:.2f}
        
        请根据以上技术指标分析当前市场状态，回答只能是：TREND / RANGE / VOL
        - TREND: 当价格明显偏离均线，趋势性强
        - RANGE: 当价格在均线上下震荡，无明显趋势
        - VOL: 当价格波动剧烈，波动率高
        """

        response = deepseek_client.chat.completions.create(
            model="deepseek-chat",
            messages=[
                {"role": "system", "content": "你是一个专业的加密货币市场分析师，只输出市场状态：TREND / RANGE / VOL"},
                {"role": "user", "content": prompt}
            ],
            stream=False,
            temperature=0.1
        )

        text = response.choices[0].message.content.strip().upper()

        log(f"🧠 AI市场判断: {text}")

        if "TREND" in text:
            return (0.6, 0.2, 0.2)
        elif "RANGE" in text:
            return (0.2, 0.6, 0.2)
        elif "VOL" in text:
            return (0.3, 0.2, 0.5)
        else:
            # 如果响应不符合预期，返回默认值
            log(f"⚠️ 未识别的AI响应: {text}，使用默认权重")
            return (0.4, 0.3, 0.3)

    except Exception as e:
        log(f"❌ DeepSeek失败 {e}")
        return (0.4, 0.3, 0.3)

# ======================
# 🧠 1H趋势
# ======================
def higher_tf_trend(df):
    sma_fast = df['close'].rolling(20).mean()
    sma_slow = df['close'].rolling(50).mean()
    return 1 if sma_fast.iloc[-1] > sma_slow.iloc[-1] else -1

# ======================
# 💰 风控
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
# 🚀 下单（带日志）- 修复最小订单量问题
# ======================
def order(symbol, side, size, price, atr, p):
    try:
        stop_distance = p['atr_mult'] * atr
        balance = get_balance()

        # 获取该交易对的最小订单量
        min_size = MIN_ORDER_SIZE.get(symbol, 0.01)
        
        # 调整订单大小以满足最小要求
        adjusted_size = max(size, min_size)
        
        # 确保订单不超过最大允许值
        max_size = balance * MAX_POSITION_RATIO / price
        final_size = min(adjusted_size, max_size)

        # 检查是否有足够资金执行订单
        cost = final_size * price
        if cost > balance * 0.95:  # 保留5%的资金作为缓冲
            log(f"⚠️ 资金不足，无法下单 {symbol} 需要 {cost:.2f} USDT，可用 {balance:.2f} USDT")
            return

        log(f"📈 尝试下单 {symbol} {side} 数量: {size:.4f} -> 调整为: {final_size:.4f}")

        # 执行订单
        exchange.create_market_order(symbol, side.lower(), final_size)

        log(f"🚀 下单成功 {symbol} {side} 数量: {final_size:.4f}")

    except Exception as e:
        log(f"❌ 下单失败 {symbol} {e}")

# ======================
# 🔥 参数优化
# ======================
def optimize(df):
    best=None
    best_score=-999

    for vals in product(*PARAM_GRID.values()):
        p=dict(zip(PARAM_GRID.keys(),vals))
        df2 = add_indicators(df.copy(), p)  # 确保在复制的数据帧上添加指标
        sig = np.sign(df2['sma_s'] - df2['sma_l'])
        r = df2['ret'] * sig

        if r.std()==0:
            continue

        sharpe = r.mean()/r.std()

        if sharpe > best_score:
            best_score = sharpe
            best = p

    return best

# ======================
# 🧠 信号融合
# ======================
def combined_signal(df15, df1h, p):

    df15 = add_indicators(df15, p)

    trend = np.sign(df15['sma_s'].iloc[-1]-df15['sma_l'].iloc[-1])
    mean = 1 if df15['close'].iloc[-1]<df15['lower'].iloc[-1] else -1 if df15['close'].iloc[-1]>df15['upper'].iloc[-1] else 0
    brk = 1 if df15['close'].iloc[-1]>df15['high_break'].iloc[-2] else -1 if df15['close'].iloc[-1]<df15['low_break'].iloc[-2] else 0

    base = trend + mean + brk
    ht = higher_tf_trend(df1h)
    ai = ai_local(df15)
    w = ai_weight_adjust()

    score = base*w[0] + ht*w[1] + ai*w[2]

    log(f"📊 信号 base:{base} HT:{ht} AI:{ai} -> score:{score:.2f}")

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

    scores = {}

    for sym in SYMBOLS:

        df15 = get_data(sym,'15m')
        df1h = get_data(sym,'1h',200)

        if df15 is None or df1h is None:
            continue

        if df15['ret'].std() > 0.05:
            log(f"⚠️ 波动过大跳过 {sym}")
            continue

        p = optimize(df15)

        score = combined_signal(df15, df1h, p)

        scores[sym] = score

    total = sum(abs(v) for v in scores.values())
    weights = {k: v/total if total!=0 else 0 for k,v in scores.items()}

    for sym in scores:

        if abs(scores[sym]) < 0.5:
            continue

        df = get_data(sym,'15m')
        if df is None:
            log(f"❌ 获取交易数据失败 {sym}")
            continue
            
        p = optimize(df)

        # 在这里确保添加指标后再访问 atr
        df = add_indicators(df, p)
        
        # 检查atr列是否存在并有有效值
        if 'atr' not in df.columns or pd.isna(df['atr'].iloc[-1]):
            log(f"❌ ATR指标无效，跳过 {sym}")
            continue
            
        atr = df['atr'].iloc[-1]
        price = df['close'].iloc[-1]

        side = "buy" if scores[sym] > 0 else "sell"

        capital = balance * abs(weights[sym])
        size = (capital * LEVERAGE) / price
        
        # 调整大小以满足最小订单量要求
        min_size = MIN_ORDER_SIZE.get(sym, 0.01)
        size = max(size, min_size)

        order(sym, side, size, price, atr, p)

# ======================
# ⏱️ 定时 - 修复异常处理
# ======================
def wait():
    try:
        now = datetime.now(timezone.utc)
        sleep = (15-now.minute%15)*60
        time.sleep(sleep)
    except KeyboardInterrupt:
        log("⚠️ 用户中断程序")
        raise  # 重新抛出异常以正确终止程序

# ======================
# ▶️ 主循环（永不停机）
# ======================
while True:
    try:
        trade()
        wait()
    except KeyboardInterrupt:
        log("🛑 程序被用户中断")
        break
    except Exception as e:
        log(f"❌ 主循环错误 {e}")
        import traceback
        traceback.print_exc()
        time.sleep(60)
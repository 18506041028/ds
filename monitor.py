import os
import threading
import time
import queue
import json
from datetime import datetime
from flask import Flask, render_template_string, jsonify
import sys
from io import StringIO
from contextlib import redirect_stdout, redirect_stderr

# 创建一个Flask应用来提供网页界面
app = Flask(__name__)

# 全局变量存储数据
logs_queue = queue.Queue()
current_data = {
    'price': 0,
    'price_change': 0,
    'balance': 0,
    'position': '无持仓',
    'pnl': 0,
    'signal': '-',
    'confidence': '-',
    'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
}

class LogCapture:
    def __init__(self):
        self.logs = []
        self.max_logs = 100
        
    def write(self, msg):
        if msg.strip():  # 忽略空行
            timestamp = datetime.now().strftime('%H:%M:%S')
            log_entry = f"[{timestamp}] {msg.strip()}"
            
            # 分析日志内容并更新当前数据
            self.analyze_log(log_entry)
            
            # 添加到队列
            logs_queue.put(log_entry)
            
            # 保留最新的日志
            self.logs.append(log_entry)
            if len(self.logs) > self.max_logs:
                self.logs.pop(0)
    
    def analyze_log(self, log):
        """分析日志内容提取关键数据"""
        global current_data
        
        # 提取价格信息
        if "BTC当前价格:" in log:
            try:
                price_str = log.split("BTC当前价格:")[1].split(',')[0].strip().replace('$', '')
                current_data['price'] = float(price_str)
            except:
                pass
                
        # 提取价格变化
        if "价格变化:" in log:
            try:
                change_str = log.split("价格变化:")[1].split('%')[0].strip()
                current_data['price_change'] = float(change_str)
            except:
                pass
                
        # 提取余额
        if "当前USDT余额:" in log:
            try:
                balance_str = log.split("当前USDT余额:")[1].split()[0]
                current_data['balance'] = float(balance_str)
            except:
                pass
                
        # 提取持仓
        if "更新后持仓:" in log:
            try:
                if "None" in log or "无持仓" in log:
                    current_data['position'] = "无持仓"
                    current_data['pnl'] = 0
                else:
                    # 解析持仓信息
                    if "'side': 'long'" in log:
                        current_data['position'] = "多头"
                    elif "'side': 'short'" in log:
                        current_data['position'] = "空头"
                    # 盈亏信息
                    if "unrealizedPnl" in log:
                        try:
                            pnl_start = log.find("unrealizedPnl") + 14
                            pnl_end = log.find(",", pnl_start)
                            if pnl_end == -1: pnl_end = len(log)
                            current_data['pnl'] = float(log[pnl_start:pnl_end].strip())
                        except:
                            pass
            except:
                pass
                
        # 提取交易信号
        if "交易信号:" in log:
            try:
                signal = log.split("交易信号:")[1].split()[0]
                current_data['signal'] = signal
            except:
                pass
                
        # 提取信心等级
        if "信心程度:" in log:
            try:
                confidence = log.split("信心程度:")[1].split()[0]
                current_data['confidence'] = confidence
            except:
                pass
        
        # 更新时间戳
        current_data['timestamp'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

# 重定向输出
log_capture = LogCapture()
sys.stdout = log_capture
sys.stderr = log_capture

# HTML模板
html_template = """
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>DeepSeek BTC/USDT 交易机器人监控面板</title>
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <style>
        :root {
            --primary-color: #2c3e50;
            --secondary-color: #3498db;
            --success-color: #2ecc71;
            --warning-color: #f39c12;
            --danger-color: #e74c3c;
            --dark-bg: #2c3e50;
            --light-bg: #ecf0f1;
            --card-bg: #ffffff;
            --text-light: #ffffff;
            --text-dark: #2c3e50;
        }
        
        body {
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            margin: 0;
            padding: 0;
            background-color: #f5f7fa;
            color: var(--text-dark);
        }
        
        .container {
            max-width: 1400px;
            margin: 0 auto;
            padding: 20px;
        }
        
        header {
            background: linear-gradient(135deg, var(--primary-color), #1a2533);
            color: white;
            padding: 20px;
            border-radius: 10px;
            margin-bottom: 20px;
            box-shadow: 0 4px 12px rgba(0,0,0,0.1);
        }
        
        h1 {
            margin: 0;
            font-size: 28px;
        }
        
        .subtitle {
            font-size: 16px;
            opacity: 0.8;
            margin-top: 5px;
        }
        
        .dashboard-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
            gap: 20px;
            margin-bottom: 20px;
        }
        
        .card {
            background: var(--card-bg);
            border-radius: 10px;
            padding: 20px;
            box-shadow: 0 4px 12px rgba(0,0,0,0.05);
            transition: transform 0.3s ease;
        }
        
        .card:hover {
            transform: translateY(-5px);
        }
        
        .card-title {
            font-size: 18px;
            margin-top: 0;
            margin-bottom: 15px;
            color: var(--primary-color);
            border-bottom: 2px solid var(--secondary-color);
            padding-bottom: 10px;
        }
        
        .status-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 15px;
            margin-bottom: 20px;
        }
        
        .status-item {
            background: white;
            padding: 15px;
            border-radius: 8px;
            text-align: center;
            box-shadow: 0 2px 8px rgba(0,0,0,0.05);
        }
        
        .status-value {
            font-size: 24px;
            font-weight: bold;
            margin: 10px 0;
        }
        
        .status-label {
            font-size: 14px;
            color: #7f8c8d;
        }
        
        .value-positive {
            color: var(--success-color);
        }
        
        .value-negative {
            color: var(--danger-color);
        }
        
        .chart-container {
            height: 300px;
            margin-top: 20px;
        }
        
        .log-container {
            background: #1e1e1e;
            color: #dcdcdc;
            padding: 15px;
            border-radius: 8px;
            height: 400px;
            overflow-y: auto;
            font-family: 'Courier New', monospace;
            font-size: 14px;
            white-space: pre-wrap;
        }
        
        .log-line {
            margin: 3px 0;
            line-height: 1.4;
        }
        
        .log-info { color: #7ed3ef; }
        .log-success { color: #5cb85c; }
        .log-warning { color: #f0ad4e; }
        .log-error { color: #d9534f; }
        .log-debug { color: #9b59b6; }
        
        .controls {
            display: flex;
            gap: 10px;
            margin-bottom: 15px;
        }
        
        button {
            background: var(--secondary-color);
            color: white;
            border: none;
            padding: 10px 15px;
            border-radius: 5px;
            cursor: pointer;
            font-weight: bold;
            transition: background 0.3s;
        }
        
        button:hover {
            background: #2980b9;
        }
        
        button:disabled {
            background: #bdc3c7;
            cursor: not-allowed;
        }
        
        .position-card {
            background: linear-gradient(135deg, #3498db, #2c3e50);
            color: white;
        }
        
        .signal-card {
            background: linear-gradient(135deg, #2ecc71, #27ae60);
            color: white;
        }
        
        .signal-buy {
            background: linear-gradient(135deg, #2ecc71, #27ae60);
        }
        
        .signal-sell {
            background: linear-gradient(135deg, #e74c3c, #c0392b);
        }
        
        .signal-hold {
            background: linear-gradient(135deg, #f39c12, #d35400);
        }
        
        .indicators-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
            gap: 15px;
            margin-top: 20px;
        }
        
        .indicator-item {
            background: white;
            padding: 15px;
            border-radius: 8px;
            box-shadow: 0 2px 8px rgba(0,0,0,0.05);
        }
        
        .indicator-name {
            font-weight: bold;
            margin-bottom: 5px;
            color: var(--primary-color);
        }
        
        .indicator-value {
            font-size: 18px;
            font-weight: bold;
        }
        
        .trend-up {
            color: var(--success-color);
        }
        
        .trend-down {
            color: var(--danger-color);
        }
        
        footer {
            text-align: center;
            margin-top: 30px;
            padding: 20px;
            color: #7f8c8d;
            font-size: 14px;
        }
        
        @media (max-width: 768px) {
            .dashboard-grid {
                grid-template-columns: 1fr;
            }
            
            .status-grid {
                grid-template-columns: repeat(2, 1fr);
            }
            
            .indicators-grid {
                grid-template-columns: 1fr;
            }
        }
    </style>
</head>
<body>
    <div class="container">
        <header>
            <h1>🤖 DeepSeek BTC/USDT 交易机器人</h1>
            <div class="subtitle">实时监控面板 | 日志捕获 | 交易状态</div>
        </header>
        
        <div class="status-grid">
            <div class="status-item">
                <div class="status-label">当前价格</div>
                <div class="status-value" id="current-price">$<span id="price-value">0.00</span></div>
                <div class="status-label" id="price-change">0.00%</div>
            </div>
            <div class="status-item">
                <div class="status-label">账户余额</div>
                <div class="status-value" id="account-balance"><span id="balance-value">0</span> USDT</div>
                <div class="status-label">可用保证金</div>
            </div>
            <div class="status-item">
                <div class="status-label">当前持仓</div>
                <div class="status-value" id="position-status">无持仓</div>
                <div class="status-label" id="position-pnl">盈亏: $<span id="pnl-value">0.00</span></div>
            </div>
            <div class="status-item">
                <div class="status-label">最新信号</div>
                <div class="status-value" id="latest-signal">-</div>
                <div class="status-label" id="signal-confidence">信心: -</div>
            </div>
        </div>
        
        <div class="dashboard-grid">
            <div class="card">
                <h3 class="card-title">📈 价格走势</h3>
                <div class="chart-container">
                    <canvas id="priceChart"></canvas>
                </div>
            </div>
            
            <div class="card">
                <h3 class="card-title">📊 实时状态</h3>
                <div class="indicators-grid">
                    <div class="indicator-item">
                        <div class="indicator-name">最后更新时间</div>
                        <div class="indicator-value" id="update-time">-</div>
                    </div>
                    <div class="indicator-item">
                        <div class="indicator-name">交易周期</div>
                        <div class="indicator-value">5分钟</div>
                    </div>
                    <div class="indicator-item">
                        <div class="indicator-name">杠杆倍数</div>
                        <div class="indicator-value">10x</div>
                    </div>
                    <div class="indicator-item">
                        <div class="indicator-name">交易对</div>
                        <div class="indicator-value">BTC/USDT</div>
                    </div>
                </div>
            </div>
        </div>
        
        <div class="dashboard-grid">
            <div class="card">
                <h3 class="card-title">📋 最新交易信号</h3>
                <div class="card signal-card" id="signal-card">
                    <h3 id="signal-type">等待信号...</h3>
                    <p><strong>最新信号:</strong> <span id="signal-value">-</span></p>
                    <p><strong>信心等级:</strong> <span id="confidence-value">-</span></p>
                    <p><strong>执行时间:</strong> <span id="signal-time">-</span></p>
                </div>
                
                <div class="controls">
                    <button id="start-btn">启动机器人</button>
                    <button id="pause-btn">暂停机器人</button>
                    <button id="clear-log">清空日志</button>
                </div>
            </div>
            
            <div class="card">
                <h3 class="card-title">📝 实时日志</h3>
                <div class="log-container" id="log-container">
                    [系统] 监控面板已启动...
                    [INFO] 开始捕获交易机器人日志
                </div>
            </div>
        </div>
        
        <footer>
            <p>DeepSeek BTC/USDT 交易机器人监控面板 | 实时日志捕获系统</p>
            <p>注意：此页面实时显示Python脚本的输出日志</p>
        </footer>
    </div>

    <script>
        // 图表初始化
        const ctx = document.getElementById('priceChart').getContext('2d');
        const priceChart = new Chart(ctx, {
            type: 'line',
            data: {
                labels: Array.from({length: 20}, (_, i) => `T-${19-i}`),
                datasets: [{
                    label: 'BTC/USDT 价格',
                    data: Array(20).fill(45000),
                    borderColor: '#3498db',
                    backgroundColor: 'rgba(52, 152, 219, 0.1)',
                    borderWidth: 2,
                    tension: 0.4,
                    fill: true
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: {
                        display: false
                    }
                },
                scales: {
                    y: {
                        beginAtZero: false
                    }
                }
            }
        });

        // 价格数据缓存
        let priceHistory = [];
        const MAX_HISTORY = 20;

        // 添加价格到图表
        function addToChart(price) {
            priceHistory.push(price);
            if (priceHistory.length > MAX_HISTORY) {
                priceHistory.shift();
            }
            
            priceChart.data.labels = Array.from({length: priceHistory.length}, (_, i) => `T-${priceHistory.length-1-i}`);
            priceChart.data.datasets[0].data = [...priceHistory];
            priceChart.update();
        }

        // 更新UI数据
        function updateUI(data) {
            document.getElementById('price-value').textContent = data.price.toFixed(2);
            
            const changeEl = document.getElementById('price-change');
            changeEl.textContent = `${data.price_change >= 0 ? '+' : ''}${data.price_change.toFixed(2)}%`;
            changeEl.className = data.price_change >= 0 ? 'status-label value-positive' : 'status-label value-negative';
            
            document.getElementById('balance-value').textContent = data.balance.toFixed(2);
            
            document.getElementById('position-status').textContent = data.position;
            
            const pnlValue = document.getElementById('pnl-value');
            pnlValue.textContent = data.pnl.toFixed(2);
            pnlValue.className = data.pnl >= 0 ? 'value-positive' : 'value-negative';
            
            document.getElementById('latest-signal').textContent = data.signal;
            document.getElementById('signal-confidence').textContent = `信心: ${data.confidence}`;
            
            document.getElementById('update-time').textContent = data.timestamp;
            
            // 更新信号卡片
            document.getElementById('signal-type').textContent = data.signal;
            document.getElementById('signal-value').textContent = data.signal;
            document.getElementById('confidence-value').textContent = data.confidence;
            document.getElementById('signal-time').textContent = data.timestamp;
            
            // 根据信号类型更新样式
            const signalCard = document.getElementById('signal-card');
            signalCard.className = 'card signal-card';
            if (data.signal === 'BUY') {
                signalCard.classList.add('signal-buy');
            } else if (data.signal === 'SELL') {
                signalCard.classList.add('signal-sell');
            } else if (data.signal === 'HOLD') {
                signalCard.classList.add('signal-hold');
            }
            
            // 添加价格到图表
            if (data.price > 0) {
                addToChart(data.price);
            }
        }

        // 添加日志消息
        function addLogMessage(message) {
            const logContainer = document.getElementById('log-container');
            const logLine = document.createElement('div');
            logLine.className = 'log-line log-info';
            logLine.textContent = message;
            logContainer.appendChild(logLine);
            
            // 自动滚动到底部
            logContainer.scrollTop = logContainer.scrollHeight;
            
            // 限制日志行数
            if (logContainer.children.length > 200) {
                logContainer.removeChild(logContainer.firstChild);
            }
        }

        // 清空日志
        document.getElementById('clear-log').addEventListener('click', () => {
            document.getElementById('log-container').innerHTML = '';
            addLogMessage('[系统] 日志已清空');
        });

        // 定期从服务器获取数据
        function fetchData() {
            fetch('/data')
                .then(response => response.json())
                .then(data => {
                    updateUI(data);
                })
                .catch(error => console.error('获取数据失败:', error));
        }

        // 定期获取日志
        function fetchLogs() {
            fetch('/logs')
                .then(response => response.json())
                .then(data => {
                    data.logs.forEach(log => {
                        addLogMessage(log);
                    });
                })
                .catch(error => console.error('获取日志失败:', error));
        }

        // 初始加载数据
        fetchData();
        fetchLogs();

        // 设置定时更新
        setInterval(fetchData, 1000);  // 每秒更新一次数据
        setInterval(fetchLogs, 2000);  // 每2秒更新一次日志

        // 按钮事件
        document.getElementById('start-btn').addEventListener('click', () => {
            alert('启动机器人功能需要在原脚本中实现');
        });
        
        document.getElementById('pause-btn').addEventListener('click', () => {
            alert('暂停机器人功能需要在原脚本中实现');
        });
    </script>
</body>
</html>
"""

@app.route('/')
def index():
    return render_template_string(html_template)

@app.route('/data')
def get_data():
    return jsonify(current_data)

@app.route('/logs')
def get_logs():
    # 获取队列中的所有日志
    logs = []
    while not logs_queue.empty():
        try:
            log = logs_queue.get_nowait()
            logs.append(log)
        except queue.Empty:
            break
    return jsonify({'logs': logs})

def run_web_server():
    app.run(host='0.0.0.0', port=5000, debug=False, use_reloader=False)

if __name__ == "__main__":
    # 启动Web服务器
    web_thread = threading.Thread(target=run_web_server)
    web_thread.daemon = True
    web_thread.start()
    
    print("Web监控面板已启动: http://localhost:5000")
    
    # 在这里导入并运行您的交易脚本
    # 注意：由于脚本会无限循环，这将阻塞主线程
    # 您可能需要修改原脚本使其支持停止
    try:
        from deepseek_ok_fix_带指标plus版本 import main
        main()
    except ImportError:
        # 如果无法导入原脚本，则保持监控面板运行
        print("请在浏览器中访问 http://localhost:5000 查看监控面板")
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            print("\n监控面板已关闭")
#!/bin/bash
# ==============================================================================
# 雷速指数分析系统 - 强力杀死旧进程并平滑重载服务脚本 (update.sh)
# ==============================================================================

echo "=========================================="
echo "🚀 开始强力重载服务..."
echo "=========================================="

# 1. 强拉最新 Git 提交
echo "📦 正在拉取 GitHub 远端最新代码..."
git fetch --all
git reset --hard origin/main

# 2. 强行杀死后台一切 app.py 的残留进程
echo "💀 正在清理内存中所有的老旧 Flask 进程..."
PID=$(pgrep -f "python.*app.py") || true
if [ ! -z "$PID" ]; then
    echo "发现老旧 Flask 进程 PIDs: $PID，正在强行杀死..."
    pkill -9 -f "python.*app.py" || true
    sleep 1
else
    echo "未发现内存中常驻的 python app.py 进程。"
fi

# 3. 释放端口 5000，防止端口冲突
echo "🔌 检查 5000 端口占用情况..."
PORT_PID=$(lsof -t -i:5000) || true
if [ ! -z "$PORT_PID" ]; then
    echo "发现 5000 端口被进程 $PORT_PID 占用，正在释放..."
    kill -9 $PORT_PID || true
    sleep 1
fi

# 4. 后台重新拉起服务
echo "🔥 正在后台干净启动新版 Flask 服务..."
if [ -d "venv" ]; then
    echo "检测到虚拟环境，使用 venv 启动..."
    nohup venv/bin/python app.py > flask.log 2>&1 &
else
    echo "未检测到虚拟环境，使用系统 python3 启动..."
    nohup python3 app.py > flask.log 2>&1 &
fi

sleep 2
NEW_PID=$(pgrep -f "python.*app.py") || true
if [ ! -z "$NEW_PID" ]; then
    echo "=========================================="
    echo "✅ 重载成功！新进程 PID: $NEW_PID 已在后台运行。"
    echo "📊 您可以运行 tail -f flask.log 查看实时启动日志。"
    echo "=========================================="
else
    echo "❌ 错误: 服务未能成功拉起，请查看当前目录下的 flask.log 日志文件！"
    exit 1
fi

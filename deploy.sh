#!/bin/bash

# ==============================================================================
# 雷速指数分析系统 - 一键日常更新部署脚本 (deploy.sh)
# ==============================================================================
# 作用：从 GitHub 拉取最新代码，自动增量安装 pip 依赖，并平滑重启 Systemd 守护进程。
# 使用方法：在服务器上运行 sh deploy.sh 即可。
# ==============================================================================

# 设置严格错误检查，任何一步出错立即停止
set -e

# 定义部署的绝对路径
DEPLOY_DIR="/opt/leisu-bypass"
SERVICE_NAME="leisu"

echo "=========================================="
echo "🚀 开始执行一键更新部署..."
echo "=========================================="

# 1. 确保在正确的部署目录下
if [ -d "$DEPLOY_DIR" ]; then
    cd "$DEPLOY_DIR"
else
    echo "❌ 错误: 部署目录 $DEPLOY_DIR 不存在，请先运行 setup.sh 进行首次初始化！"
    exit 1
fi

# 2. 从 GitHub 拉取最新代码
echo "📦 正在从 GitHub 仓库拉取最新代码..."
# 放弃本地未提交的修改，强行与 GitHub 远程分支对齐，避免冲突导致中断
git fetch --all
git reset --hard origin/main

# 3. 更新 Python 虚拟环境依赖包
echo "🐍 正在检查并更新 Python 虚拟环境中的依赖包..."
if [ -f "requirements.txt" ]; then
    venv/bin/pip install -r requirements.txt
else
    echo "⚠️ 警告: requirements.txt 未找到，跳过 pip 更新。"
fi

# 4. 重启 Systemd 守护服务以加载最新代码
echo "🔄 正在重启 Systemd 守护服务 ($SERVICE_NAME)..."
sudo systemctl restart $SERVICE_NAME

# 5. 检查服务运行状态
echo "📊 正在检查服务运行状态..."
sleep 1.5
if systemctl is-active --quiet $SERVICE_NAME; then
    echo "=========================================="
    echo "✅ 一键更新部署成功！服务正在后台平稳运行。"
    echo "=========================================="
else
    echo "❌ 错误: 服务重启后未能正常运行，请执行以下命令查看错误日志："
    echo "   sudo journalctl -u $SERVICE_NAME -n 50 -f"
    exit 1
fi

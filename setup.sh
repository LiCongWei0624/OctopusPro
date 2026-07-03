#!/bin/bash

# ==============================================================================
# 雷速指数分析系统 - 首次一键初始化部署脚本 (setup.sh)
# ==============================================================================
# 作用：自动在 Linux 服务器上配置 Python、Node.js，克隆/准备代码目录，
#       安装依赖，自动补全 Playwright 缺失的系统动态链接库，并自动配置 Systemd 服务守护。
# 适用系统：Ubuntu / Debian (推荐)，CentOS 用户请参考文档说明。
# 使用方法：sudo bash setup.sh <Your-GitHub-Repo-URL>
# ==============================================================================

set -e

REPO_URL=$1
DEPLOY_DIR=$(cd "$(dirname "$0")"; pwd)
SERVICE_NAME="leisu"

echo "=========================================="
echo "🎯 开始雷速指数系统首次一键部署初始化..."
echo "=========================================="

# 确保以 root 权限运行
if [ "$EUID" -ne 0 ]; then
  echo "❌ 请使用 sudo 运行此脚本，以保证能够安装系统依赖包！"
  exit 1
fi

# 1. 检查并安装 Git, Python, Node.js 等基础环境
echo "🛠️ 1. 检查并安装基础软件包..."
if [ -f /etc/debian_version ]; then
    # Ubuntu / Debian
    apt-get update
    apt-get install -y git python3 python3-pip python3-venv python3-dev build-essential curl
    
    # 检查 node 是否存在，不存在则安装
    if ! command -v node &> /dev/null; then
        echo "📦 正在安装 Node.js..."
        curl -fsSL https://deb.nodesource.com/setup_18.x | bash -
        apt-get install -y nodejs
    fi
elif [ -f /etc/redhat-release ]; then
    # CentOS / RHEL
    yum update -y
    yum install -y git python3 python3-devel python3-pip gcc gcc-c++ make curl
    if ! command -v node &> /dev/null; then
        echo "📦 正在安装 Node.js..."
        curl -fsSL https://rpm.nodesource.com/setup_18.x | bash -
        yum install -y nodejs
    fi
else
    echo "⚠️ 无法确定操作系统类型，请确保已手动安装 git, python3, pip, nodejs。"
fi

# 2. 准备代码目录
echo "📂 2. 配置部署代码目录..."
echo "📍 部署目录将设为当前脚本所在绝对路径: $DEPLOY_DIR"
cd "$DEPLOY_DIR"

# 3. 初始化虚拟环境并安装依赖
echo "🐍 3. 初始化 Python 虚拟环境与依赖包..."
python3 -m venv venv
venv/bin/pip install --upgrade pip
if [ -f "requirements.txt" ]; then
    venv/bin/pip install -r requirements.txt
else
    # 兜底依赖安装
    venv/bin/pip install flask beautifulsoup4 playwright cryptography requests
fi

# 4. 安装 Playwright Chromium 及系统链接库依赖 (极关键)
echo "🌐 4. 安装 Playwright Chromium 浏览器及其底层系统依赖包..."
venv/bin/playwright install chromium
venv/bin/playwright install-deps chromium

# 5. 自动创建 Systemd 守护进程文件
echo "⚙️ 5. 配置 Systemd 后台服务守护..."
SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"

cat <<EOF > "$SERVICE_FILE"
[Unit]
Description=LeiSu Bypass Flask Service
After=network.target

[Service]
User=root
WorkingDirectory=${DEPLOY_DIR}
ExecStart=${DEPLOY_DIR}/venv/bin/python app.py
Restart=always
RestartSec=5
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
EOF

# 6. 启动并启用服务自启动
echo "🔄 6. 启动服务并设置开机自启动..."
systemctl daemon-reload
systemctl start $SERVICE_NAME
systemctl enable $SERVICE_NAME

# 7. 最终检测
echo "📊 7. 运行状态检测..."
sleep 2
if systemctl is-active --quiet $SERVICE_NAME; then
    echo "========================================================="
    echo "🎉 雷速指数系统一键部署初始化成功！"
    echo "========================================================="
    echo "   📍 服务运行目录: $DEPLOY_DIR"
    echo "   📍 服务状态: 正在后台正常运行"
    echo "   📍 局域网访问地址: http://服务器公网IP:5000"
    echo "   📍 查看日志命令: sudo journalctl -u $SERVICE_NAME -f"
    echo "   📍 日常一键更新命令: sh deploy.sh"
    echo "========================================================="
else
    echo "❌ 警告: 初始化已完成，但服务未能正常运行。"
    echo "   请执行以下命令查看出错日志："
    echo "   sudo journalctl -u $SERVICE_NAME -n 50 --no-pager"
fi

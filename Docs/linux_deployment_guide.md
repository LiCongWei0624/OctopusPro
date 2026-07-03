# 雷速指数分析系统 - Linux 服务器部署指南

本系统包含 Python (Flask) 服务端、Playwright 无头浏览器、及 Node.js WAF 挑战求解器。在部署至 Linux 服务器（如 Ubuntu / Debian / CentOS）时，请按照以下保姆级步骤进行配置，以确保无头浏览器与解密引擎能够平稳运行。

---

## 1. 基础环境准备

在 Linux 服务器上，首先需要安装 Python 3、Node.js 及相关系统工具。

### 对于 Ubuntu / Debian 系统：
```bash
sudo apt update
# 安装 Python3 及其开发工具、虚拟环境、pip
sudo apt install -y python3 python3-pip python3-venv python3-dev build-essential
# 安装 Node.js 运行时
curl -fsSL https://deb.nodesource.com/setup_18.x | sudo -E bash -
sudo apt install -y nodejs
```

### 对于 CentOS / RHEL 系统：
```bash
sudo yum update -y
# 安装 Python3、pip 及开发包
sudo yum install -y python3 python3-devel python3-pip gcc gcc-c++ make
# 安装 Node.js 运行时
curl -fsSL https://rpm.nodesource.com/setup_18.x | sudo bash -
sudo yum install -y nodejs
```

验证 Node.js 是否成功安装在系统 `PATH` 中（系统后台需要直接调用 `node` 执行解密脚本）：
```bash
node -v
```

---

## 2. 拷贝代码并初始化虚拟环境

将项目代码上传至服务器的部署目录（如 `/opt/leisu-bypass`），然后执行以下操作：

```bash
# 进入部署目录
cd /opt/leisu-bypass

# 创建 Python 虚拟环境 (推荐，隔离全局包冲突)
python3 -m venv venv

# 激活虚拟环境
source venv/bin/activate

# 升级 pip
pip install --upgrade pip

# 安装 Python 依赖包
pip install -r requirements.txt
```

*(注：如果在项目根目录下没有 `requirements.txt`，可以通过 `pip freeze > requirements.txt` 生成，或确保安装了 `flask`, `beautifulsoup4`, `playwright`, `cryptography`, `requests` 等核心库。)*

---

## 3. 安装与配置 Playwright (核心关键步骤)

在 Linux (无桌面环境) 上运行 Playwright，必须拉取对应的浏览器内核并安装其依赖的系统动态链接库（.so 库），否则 Chromium 会因缺少库文件报错无法启动。

```bash
# 激活虚拟环境状态下执行：
# 1. 安装 Chromium 浏览器内核
playwright install chromium

# 2. 安装 Chromium 运行所需的 Linux 系统底层依赖包 (需要 sudo 权限)
playwright install-deps chromium
```

> [!TIP]
> **CentOS/RHEL 的额外说明：**
> 如果您是在旧版 CentOS 下运行，`playwright install-deps` 可能会提示包管理器不兼容。这时可以通过以下命令手动补充可能缺失的依赖：
> `sudo yum install -y alsa-lib at-spi2-atk atk cups-libs dbus-glib libdrm libXcomposite libXdamage libXext libXg3 libXrandr libxshmfence libXtst mesa-libgbm pango shadow-utils`

---

## 4. 测试服务运行

在启动生产服务前，建议在虚拟环境下先手动运行测试，确保 WAF 破盾与解密逻辑在 Linux 下完全正常。

```bash
# 开启服务
python app.py
```
在本地或通过 curl 访问：`curl http://127.0.0.1:5000/api/matches` 观察是否能够成功抓取数据。

---

## 5. 配置 Systemd 进行服务进程守护

为了让系统在 Linux 后台持久运行，并且在服务器崩溃重启后能够自启动，推荐配置 Systemd 守护进程。

创建服务配置文件：
```bash
sudo nano /etc/systemd/system/leisu.service
```

写入以下配置内容：
```ini
[Unit]
Description=LeiSu Bypass Flask Service
After=network.target

[Service]
User=root
WorkingDirectory=/opt/leisu-bypass
# 指向虚拟环境中的 python 路径，以便自动加载依赖
ExecStart=/opt/leisu-bypass/venv/bin/python app.py
Restart=always
RestartSec=5
# 环境变量配置
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
```

保存并退出（在 nano 中按 `Ctrl + O`，回车保存，`Ctrl + X` 退出）。

启动服务并设置自启动：
```bash
# 重新加载 systemd 配置
sudo systemctl daemon-reload

# 启动雷速服务
sudo systemctl start leisu

# 设置开机自启动
sudo systemctl enable leisu

# 检查服务运行状态
sudo systemctl status leisu
```

---

## 6. 配置 Nginx 反向代理与 Gzip 压缩 (可选，推荐)

若需要支持外网域名访问并增强加载速度，可在服务器上安装 Nginx 并进行反向代理配置：

```nginx
server {
    listen 80;
    server_name your_domain_or_ip;

    # 配置前端静态文件及接口反向代理
    location / {
        proxy_pass http://127.0.0.1:5000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    # 开启 Gzip 压缩，显著减少历史变盘等大 JSON 传输时间
    gzip on;
    gzip_types text/plain application/javascript application/json text/css;
    gzip_min_length 1024;
}
```
配置完成后重启 Nginx：`sudo systemctl restart nginx`。

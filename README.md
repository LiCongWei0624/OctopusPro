# 🐙 OctopusPro (雷速数据决策与大模型智能量化研判系统)

`OctopusPro` 是一款面向足球赛事的数据决策与大模型量化研判系统。系统基于前后端分离架构，融合了网络防爬风控对抗、无头浏览器运行时解密、独家情报对冲分析以及大模型流式研判推演等前沿技术，致力于为量化投注与赛事决策提供坚实的数据概率支撑。

---

## ✨ 核心特性

1. **🔒 独立静态 Trend 走势页破盾与运行时解密 (100% 成功率)**
   - 彻底解决了雷速指数接口 404 及 Aliyun WAF 拦截超时的痛点。
   - 通过 Playwright 子进程加载独立的 `trend-{match_id}-{cid}` 页面，并在浏览器运行时环境下直接调用雷速原生 `window.$.rot(key, STATIC_CONFIG.KST)` 解密函数，**秒级、100% 成功提取**被 Canvas 图像混淆的水位与盘口明细。

2. **📈 核心指数庄家 (36*、皇*) 历史变盘走势明细追踪**
   - 自动截取最具有资金流向代表性的核心庄家最近 10 次变盘历史（让球、大小球、欧赔）。
   - 将盘口升降与水位微调以最直观的时间轴与折线图形式进行 Canvas 平滑绘制渲染。

3. **🧠 AI 量化研判与同初盘/同走势历史赛果对比**
   - 将独家 SWOT 情报、近期战绩、伤停名单与即时指数水位结合，生成深度赛事 Context。
   - **大数据库智能对标**：在历史同初盘统计为空时，AI 能够基于自身大数据库，主动匹配 2-3 场历史中初盘盘口与临场变盘走势完全相同的真实已完场比赛，列出具体球队及赛果，计算胜平负真实比例，给出明确的博弈买入倾向。
   - 采用流式（Stream）打字机效果输出包含：**胜平负方向预测**、**让球推荐**、**大小球及具体盘口建议**、**精准比分预测**与**同盘口概率对比**在内的深度研判报告。

4. **🚀 生产级一键自动化运维部署 (CI/CD)**
   - 编写了保姆级 [Linux 部署配置指南](Docs/linux_deployment_guide.md)。
   - 提供了一键初始化安装脚本 `setup.sh`（自动装机、补全 Playwright 系统底层 `.so` 依赖库、配置 Systemd 服务自启动）。
   - 日常一键更新脚本 `deploy.sh`，实现 GitHub 最新提交的秒级无感热拉取重启。

---

## 🛠️ 技术栈

- **后端**：Python (Flask) + BeautifulSoup 4 + Playwright (Python)
- **解密引擎**：Node.js (Cryptography) + Caesar Decrypt
- **前端**：Vanilla HTML5 + CSS3 + ChartJS (Canvas)
- **大模型**：DeepSeek-V4 (OpenCode Zen API)

---

## 🧭 快速开始

### 本地开发 (Windows / macOS)

1. **克隆项目并安装依赖**
   ```bash
   git clone https://github.com/LiCongWei0624/OctopusPro.git
   cd OctopusPro
   pip install -r requirements.txt
   ```
2. **初始化无头浏览器**
   ```bash
   playwright install chromium
   ```
3. **启动 Flask 开发服务器**
   ```bash
   python app.py
   ```
   访问本地前端界面：`http://localhost:5000`

---

## 🌐 Linux 服务器一键部署与更新

### 首次环境部署
在您的干净 Linux (如 Ubuntu/Debian) 服务器终端，直接执行 `setup.sh` 初始化脚本：
```bash
sudo bash -c "$(curl -fsSL https://raw.githubusercontent.com/LiCongWei0624/OctopusPro/main/setup.sh)" -- https://github.com/LiCongWei0624/OctopusPro.git
```
> 脚本将自动安装 Node.js、配置虚拟环境、补全缺失的系统依赖链接库，并以 `Systemd` 守护进程将项目注册为开机自启动服务（可通过 `sudo systemctl status leisu` 检查）。

### 日常一键更新
在本地修改完代码并 `git push` 到 GitHub 后，只需 SSH 登录服务器，进入项目目录执行更新脚本即可：
```bash
cd /opt/leisu-bypass
sh deploy.sh
```
> 脚本将自动从 GitHub 拉取最新分支，升级依赖，并重启守护服务使新代码在一秒内生效。

---

## 📂 项目结构

```text
OctopusPro/
├── Docs/                     # 系统开发、更新与部署文档
│   ├── linux_deployment_guide.md   # Linux 部署保姆级说明
│   └── walkthrough.md        # 系统迭代重构记录
├── templates/                # 前端 HTML 模板目录
├── static/                   # 样式表与前端 Canvas 图表渲染逻辑
├── cache/                    # 本地赛事变盘详情与 AI 研判结果 JSON 缓存
├── app.py                    # Flask 核心路由与大模型 Context 装配控制中心
├── auth_generator.py         # Playwright 静态走势页 Canvas 运行时解密器
├── detail_scraper.py         # 交锋历史、伤停及 SWOT 情报 BeautifulSoup 提取器
├── setup.sh                  # Linux 首次部署一键初始化脚本
└── deploy.sh                 # Linux 日常一键更新脚本
```

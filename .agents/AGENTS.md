# Antigravity Workspace Instruction & Rules

## ⚠️ 每次修改代码前的强制首要步骤 (Mandatory Pre-read)

你在处理本项目（LiCongWei0624/OctopusPro）的任何修改、重构或调试请求之前，**必须首先**读取并理解以下两个设计与开发规范文档，防止修好一个 Bug 的同时搞坏了系统的其他反爬或解密流程：

1. **架构与原理设计**：[01-架构与设计.md](file:///d:/Code/Tools/LeiSu-Bypass/docs/01-架构与设计.md)
2. **核心防坏开发规约**：[02-开发指南.md](file:///d:/Code/Tools/LeiSu-Bypass/docs/02-开发指南.md)

## 📌 关键模块防御重点提示

1. **WAF Cookie 隔离**：对赔率走势（odds）的抓取必须只装载 `GLOBAL_ODDS_CJ`；对主页及数据详情的抓取必须只装载 `GLOBAL_CJ`。严禁混合，否则会导致大面积 403 封锁。
2. **Caesar 26偏置暴力解密**：JS 数据解密模块如果发生任何异常，切记捕获它，并自动 Fallback 到 BeautifulSoup HTML 解析。绝不允许向上传播异常导致服务崩溃。
3. **比分全零审计与 HTML Fallback**：若 JS 解密得到的 H2H 历史交锋比分全为 `"0:0"`，或近期战绩有一队全为 `"0:0"`，必须重置并触发 HTML BeautifulSoup 备用解析器，以确保次级赛事及冷门赛事比分的正确性。
4. **大模型 System Prompt 修改**：System Prompt 在 `app.py` 中有硬编码定义，在 `ai_config.json` 中有持久化配置。修改其中之一时，必须双份保持对齐。

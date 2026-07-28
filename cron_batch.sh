#!/bin/bash
# ============================================================
# OctopusPro 每日批采定时任务
# ============================================================
cd /home/hermesprojects/OctopusPro || exit 1

LOG_DIR="batch_results"
mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/cron_$(date +%Y%m%d_%H%M%S).log"

echo "[$(date)] 开始 OctopusPro 批量采集" >> "$LOG_FILE"
echo "[$(date)] 工作目录: $(pwd)" >> "$LOG_FILE"

# 从 .env 加载 API Key
if [ -f ".env" ]; then
    set -a
    source .env
    set +a
fi

if [ -z "$LINSHU_AI_API_KEY" ]; then
    echo "[$(date)] 错误: LINSHU_AI_API_KEY 未设置（检查 .env 或环境变量）" >> "$LOG_FILE"
    exit 1
fi

# 运行批量采集
echo "[$(date)] 启动 batch_collect.py ..." >> "$LOG_FILE"
python3 -u batch_collect.py >> "$LOG_FILE" 2>&1
EXIT_CODE=$?

echo "[$(date)] batch_collect.py 完成, 退出码=$EXIT_CODE" >> "$LOG_FILE"
exit $EXIT_CODE
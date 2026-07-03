import re
import os

app_js_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'static', 'app.js')

with open(app_js_path, 'r', encoding='utf-8', errors='ignore') as f:
    content = f.read()

# 1. 替换配置逻辑 (采用切片替换)
replacement_config = """// Global AI Config Modal Controls
function openAiConfigModal() {
    const modal = document.getElementById('ai-config-modal');
    if (!modal) return;
    
    loadAiConfigFromServer((cfg) => {
        document.getElementById('global-ai-base').value = cfg.api_base || 'https://opencode.ai/zen/v1';
        document.getElementById('global-ai-key').value = cfg.api_key || '';
        document.getElementById('global-ai-model').value = cfg.model_name || 'minimax-m2.5-free';
        document.getElementById('global-ai-prompt').value = cfg.system_prompt || '';
        modal.style.display = 'flex';
    });
}
window.openAiConfigModal = openAiConfigModal;

function closeAiConfigModal() {
    const modal = document.getElementById('ai-config-modal');
    if (modal) {
        modal.style.display = 'none';
    }
}
window.closeAiConfigModal = closeAiConfigModal;

function closeAiConfigModalOnBackdrop(event) {
    if (event.target.id === 'ai-config-modal') {
        closeAiConfigModal();
    }
}
window.closeAiConfigModalOnBackdrop = closeAiConfigModalOnBackdrop;

function saveGlobalAiConfigToServer() {
    const keyInput = document.getElementById('global-ai-key');
    const baseInput = document.getElementById('global-ai-base');
    const modelSelect = document.getElementById('global-ai-model');
    const promptTextarea = document.getElementById('global-ai-prompt');
    
    if (!keyInput || !baseInput || !modelSelect || !promptTextarea) return;
    
    const key = keyInput.value.trim();
    const base = baseInput.value.trim();
    const model = modelSelect.value;
    const prompt = promptTextarea.value;
    
    const payload = {
        api_key: key,
        api_base: base,
        model_name: model,
        system_prompt: prompt
    };
    
    fetch('/api/ai_config', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
    })
    .then(res => res.json())
    .then(res => {
        const statusSpan = document.getElementById('global-ai-save-status');
        if (res.success) {
            currentAiConfig = payload;
            if (statusSpan) {
                statusSpan.style.color = 'var(--color-success)';
                statusSpan.textContent = '✓ 配置已成功存入本地数据库';
                statusSpan.style.display = 'inline';
                setTimeout(() => {
                    statusSpan.style.display = 'none';
                    closeAiConfigModal();
                }, 1200);
            } else {
                closeAiConfigModal();
            }
        } else {
            if (statusSpan) {
                statusSpan.style.color = 'var(--color-danger)';
                statusSpan.textContent = '✗ 保存失败: ' + res.error;
                statusSpan.style.display = 'inline';
                setTimeout(() => { statusSpan.style.display = 'none'; }, 3000);
            } else {
                console.error("保存配置失败: " + res.error);
            }
        }
    })
    .catch(err => {
        const statusSpan = document.getElementById('global-ai-save-status');
        if (statusSpan) {
            statusSpan.style.color = 'var(--color-danger)';
            statusSpan.textContent = '✗ 连接保存接口失败';
            statusSpan.style.display = 'inline';
            setTimeout(() => { statusSpan.style.display = 'none'; }, 3000);
        } else {
            console.error("连接保存配置接口失败:", err);
        }
    });
}
window.saveGlobalAiConfigToServer = saveGlobalAiConfigToServer;"""

pattern_config = re.compile(r"// Global AI Config Modal Controls.*?window\.saveGlobalAiConfigToServer = saveGlobalAiConfigToServer;", re.DOTALL)
match_config = pattern_config.search(content)
if match_config:
    start_idx, end_idx = match_config.span()
    content = content[:start_idx] + replacement_config + content[end_idx:]
    print("替换配置逻辑成功")
else:
    print("没有找到配置逻辑")

# 2. 替换渲染逻辑，解析最新的 # 标题、## 标题、以及 * / - 无序列表
replacement_render = """function renderFullMarkdownReport(text) {
    const report = document.getElementById('ai-report-content');
    if (report) {
        accumulatedMarkdown = text;
        report.innerHTML = parseSimpleMarkdown(text);
    }
}

function parseSimpleMarkdown(md) {
    let html = md;
    
    // Replace # header with h3
    html = html.replace(/^#\\s+(.+)$/gm, '<h3>$1</h3>');
    // Replace ## header with h4
    html = html.replace(/^##\\s+(.+)$/gm, '<h4>$1</h4>');
    // Replace ### or #### headers with h5
    html = html.replace(/^(?:####|###)\\s+(.+)$/gm, '<h5>$1</h5>');
    
    // Replace **bold** with <b>bold</b>
    html = html.replace(/\\*\\*(.*?)\\*\\*/g, '<b>$1</b>');
    
    // Replace list * or - with <li>
    html = html.replace(/^\\s*[\\*\\-]\\s+(.+)$/gm, '<li>$1</li>');
    
    // Process paragraphs
    let lines = html.split('\\n\\n');
    html = lines.map(line => {
        let trimmed = line.trim();
        if (!trimmed) return '';
        if (trimmed.startsWith('<h') || trimmed.startsWith('<li')) {
            return trimmed;
        }
        return `<p>${trimmed}</p>`;
    }).join('');
    
    // Single newlines to linebreaks
    html = html.replace(/\\n/g, '<br>');
    
    return html;
}

function renderAiTab(match, details) {
    // If config hasn't been loaded from database, fetch it asynchronously
    if (!currentAiConfig) {
        loadAiConfigFromServer(() => {
            if (activeDetailTab === 'ai') {
                const tabContainer = document.getElementById('tab-content-ai');
                if (tabContainer) {
                    tabContainer.innerHTML = renderAiTab(match, details);
                    checkAndLoadCachedReport(match.id);
                }
            }
        });
    }
    
    return `
        <div class="ai-prediction-container">
            <!-- 运行分析按钮 -->
            <button id="btn-run-ai-analysis" class="btn-ai-run" onclick="generateAiReport('${match.id}', '${encodeURIComponent(match.home_team)}', '${encodeURIComponent(match.away_team)}')">
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polygon points="5 3 19 12 5 21 5 3"></polygon></svg>
                <span>一键生成 AI 深度研判报告</span>
            </button>

            <!-- 下方 AI 分析生成骨架屏与报告区域 -->
            <div class="details-card">
                <div class="details-card-title">AI 实时推理报告</div>
                
                <!-- 加载状态骨架屏 -->
                <div id="ai-generating-status" class="ai-skeleton-screen" style="display:none;">
                    <div style="display: flex; align-items: center; gap: 0.5rem; margin-bottom: 0.5rem;">
                        <div class="pulse-beacon" style="width: 8px; height: 8px; background-color: var(--color-primary); box-shadow: 0 0 6px var(--color-primary);"></div>
                        <span style="font-size: 0.85rem; font-weight: 700; color: var(--color-primary);">大模型正在深度研判战意、阵型与变盘逻辑中...</span>
                    </div>
                    <div class="ai-skeleton-title"></div>
                    <div class="ai-skeleton-text"></div>
                    <div class="ai-skeleton-text"></div>
                    <div class="ai-skeleton-text short"></div>
                    <div class="ai-skeleton-block" style="margin-top: 0.5rem;"></div>
                </div>

                <!-- 结果展示区域 -->
                <div id="ai-report-content" class="ai-markdown-report">
                    <p style="color:var(--text-muted); font-style:italic;">请点击上方“一键生成 AI 深度研判报告”按钮启动分析。您也可以点击导航栏右上角的“AI配置”配置 API 密钥。</p>
                </div>
            </div>
        </div>
    `;
}

function renderIntelTab(match, details)"""

pattern_render = re.compile(r"function renderFullMarkdownReport\(text\).*?function renderIntelTab\(match, details\)", re.DOTALL)
match_render = pattern_render.search(content)
if match_render:
    start_idx, end_idx = match_render.span()
    content = content[:start_idx] + replacement_render + content[end_idx:]
    print("替换渲染逻辑成功")
else:
    print("未找到渲染逻辑")

with open(app_js_path, 'w', encoding='utf-8') as f:
    f.write(content)

print("修补完成，static/app.js 完美保存！")

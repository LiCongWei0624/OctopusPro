let allMatches = [];
let groupedMatches = {}; // Key: Date, Value: Array of Matches
let selectedDate = null;
let selectedMatch = null;
let activeDetailTab = 'intel'; // intel, history, squad, odds
let matchDetailsCache = {}; // Cache for match details in memory
let selectedLeague = '全部';

// Initial Load
document.addEventListener('DOMContentLoaded', () => {
    loadMatches();
    
    // Auto-refresh today's matches every 5 minutes
    setInterval(() => {
        const todayStr = getTodayDateString();
        const todayYYYYMMDD = convertToYYYYMMDD(todayStr);
        console.log("Auto-refreshing today's matches...");
        
        fetch(`/api/refresh?date=${todayYYYYMMDD}`)
            .then(res => res.json())
            .then(res => {
                if (res.success) {
                    allMatches = res.data;
                    groupMatchesByDate(allMatches);
                    if (selectedDate === todayStr) {
                        const matches = groupedMatches[todayStr] || [];
                        const filtered = selectedLeague === '全部' ? matches : matches.filter(m => m.competition === selectedLeague);
                        document.getElementById('match-count-badge').innerText = `${filtered.length} 场`;
                        renderMatchCards(filtered);
                    }
                    updateSyncTime();
                }
            })
            .catch(err => console.error("Auto-refresh error:", err));
    }, 5 * 60 * 1000);
});

// Fetch Matches list
function loadMatches() {
    showMatchesLoading();
    const todayStr = getTodayDateString();
    const todayYYYYMMDD = convertToYYYYMMDD(todayStr);
    
    fetch(`/api/matches?today=${todayYYYYMMDD}`)
        .then(res => res.json())
        .then(res => {
            if (res.success) {
                allMatches = res.data;
                groupMatchesByDate(allMatches);
                renderDateSidebar();
                
                // Select today's date by default, fallback to first date
                const dates = getDatesRange();
                if (dates.includes(todayStr)) {
                    selectDate(todayStr);
                } else if (dates.length > 0) {
                    selectDate(dates[0]);
                } else {
                    renderEmptyState();
                }
                updateSyncTime();
            } else {
                showErrorState(res.error || "获取赛事列表失败。");
            }
        })
        .catch(err => {
            showErrorState("网络连接失败，请确认后端服务器正常运行。");
            console.error(err);
        });
}

// Refresh matches triggering
function refreshData() {
    const btn = document.getElementById('refresh-btn');
    btn.classList.add('btn-loading');
    btn.disabled = true;
    
    showMatchesLoading();
    // Clear details cache on refresh
    matchDetailsCache = {};
    
    const targetDateStr = convertToYYYYMMDD(selectedDate);
    
    fetch(`/api/refresh?date=${targetDateStr}`)
        .then(res => res.json())
        .then(res => {
            btn.classList.remove('btn-loading');
            btn.disabled = false;
            
            if (res.success) {
                allMatches = res.data;
                groupMatchesByDate(allMatches);
                renderDateSidebar();
                
                // Keep the same date selected
                if (selectedDate) {
                    renderDateMatches(selectedDate);
                }
                updateSyncTime();
            } else {
                showErrorState(res.error || "获取雷速数据失败，请重试。");
            }
        })
        .catch(err => {
            btn.classList.remove('btn-loading');
            btn.disabled = false;
            showErrorState("同步请求失败，请检查连接。");
            console.error(err);
        });
}

// Group Matches by Date
function groupMatchesByDate(matches) {
    groupedMatches = {};
    matches.forEach(m => {
        if (!groupedMatches[m.date]) {
            groupedMatches[m.date] = [];
        }
        groupedMatches[m.date].push(m);
    });
}

// Render Date Sidebar
function renderDateSidebar() {
    const container = document.getElementById('date-list');
    container.innerHTML = '';
    
    const dates = getDatesRange();
    dates.forEach(date => {
        const li = document.createElement('li');
        li.className = `date-tab ${selectedDate === date ? 'active' : ''}`;
        li.id = `date-tab-${date}`;
        li.innerText = date;
        li.onclick = () => selectDate(date);
        container.appendChild(li);
    });
}

// Select Date Tab
function selectDate(date) {
    selectedDate = date;
    selectedLeague = '全部';
    
    // Toggle active state in UI
    document.querySelectorAll('.date-tab').forEach(t => t.classList.remove('active'));
    const activeTab = document.getElementById(`date-tab-${date}`);
    if (activeTab) activeTab.classList.add('active');
    
    const todayStr = getTodayDateString();
    if (date !== todayStr) {
        refreshDateData(date);
    } else {
        renderDateMatches(date);
    }
}

// Fetch matches for a specific date from backend on-demand
function refreshDateData(date) {
    const dateStr = convertToYYYYMMDD(date);
    showMatchesLoading();
    
    fetch(`/api/refresh?date=${dateStr}`)
        .then(res => res.json())
        .then(res => {
            if (res.success && res.data) {
                allMatches = res.data;
                groupMatchesByDate(allMatches);
            } else {
                console.warn("同步返回的数据为空或失败，将尝试使用本地已加载的缓存赛事。");
            }
            renderDateMatches(date);
        })
        .catch(err => {
            console.error("同步请求失败:", err);
            // 发生网络错误时，同样尝试降级渲染本地已有的缓存
            renderDateMatches(date);
        });
}

// Render matches after selection or refresh
function renderDateMatches(date) {
    const matches = groupedMatches[date] || [];
    const leagues = ['全部'];
    matches.forEach(m => {
        if (m.competition && !leagues.includes(m.competition)) {
            leagues.push(m.competition);
        }
    });
    
    const majorLeaguesOrder = ["世界杯", "欧洲杯", "英超", "西甲", "德甲", "意甲", "法甲", "欧冠", "荷甲", "葡超", "英冠", "巴甲"];
    const otherLeagues = leagues.slice(1).sort((a, b) => {
        const idxA = majorLeaguesOrder.indexOf(a);
        const idxB = majorLeaguesOrder.indexOf(b);
        if (idxA !== -1 && idxB !== -1) return idxA - idxB;
        if (idxA !== -1) return -1;
        if (idxB !== -1) return 1;
        return a.localeCompare(b, 'zh-CN');
    });
    const sortedLeagues = ['全部', ...otherLeagues];
    
    renderLeagueFilters(sortedLeagues);
    
    document.getElementById('match-count-badge').innerText = `${matches.length} 场`;
    renderMatchCards(matches);
    
    if (matches.length > 0) {
        selectMatch(matches[0]);
    } else {
        renderNoMatchSelected();
    }
}

// Convert "MM-DD 星期X" to YYYYMMDD format
function convertToYYYYMMDD(dateTabStr) {
    const parts = dateTabStr.split(' ')[0].split('-');
    const mm = parts[0];
    const dd = parts[1];
    const today = new Date();
    let year = today.getFullYear();
    
    const month = parseInt(mm) - 1;
    const currentMonth = today.getMonth();
    if (currentMonth === 11 && month === 0) {
        year += 1;
    } else if (currentMonth === 0 && month === 11) {
        year -= 1;
    }
    
    return `${year}${mm}${dd}`;
}

// Render League Filters Pills
function renderLeagueFilters(leagues) {
    const filterBar = document.getElementById('league-filter-bar');
    filterBar.innerHTML = '';
    leagues.forEach(league => {
        const pill = document.createElement('div');
        pill.className = `league-pill ${selectedLeague === league ? 'active' : ''}`;
        pill.innerText = league;
        pill.onclick = () => selectLeague(league);
        filterBar.appendChild(pill);
    });
}

// Filter matches by League
function selectLeague(league) {
    selectedLeague = league;
    document.querySelectorAll('.league-pill').forEach(p => {
        if (p.innerText === league) p.classList.add('active');
        else p.classList.remove('active');
    });
    
    const matches = groupedMatches[selectedDate] || [];
    const filtered = league === '全部' ? matches : matches.filter(m => m.competition === league);
    document.getElementById('match-count-badge').innerText = `${filtered.length} 场`;
    renderMatchCards(filtered);
    
    if (filtered.length > 0) {
        const currentMatchInFiltered = filtered.find(m => m.id === selectedMatch?.id);
        if (!currentMatchInFiltered) {
            selectMatch(filtered[0]);
        }
    } else {
        renderNoMatchSelected();
    }
}

// Render Match Cards in Middle Column (Premium Horizontal Style)
function renderMatchCards(matches) {
    const container = document.getElementById('matches-container');
    container.innerHTML = '';
    
    if (matches.length === 0) {
        container.innerHTML = `
            <div class="empty-state" style="padding: 40px 20px; text-align: center; color: #8a99ad; font-size: 14px;">
                <span class="iconfont" style="font-size: 24px; display: block; margin-bottom: 8px;">&#xe682;</span>
                所选日期暂无一级/主流赛事
            </div>
        `;
        return;
    }
    
    matches.forEach(m => {
        const card = document.createElement('div');
        card.className = `match-card ${selectedMatch && selectedMatch.id === m.id ? 'active' : ''}`;
        card.id = `match-card-${m.id}`;
        card.onclick = () => selectMatch(m);
        
        let scoreDisplay = 'vs';
        let penaltyDisplay = '';
        let halfDisplay = '';
        let statusText = '已排期';
        let statusClass = 'scheduled';
        
        const status = Number(m.status || 1);
        if (status === 1) {
            statusText = '已排期';
            statusClass = 'scheduled';
        } else if (status === 2) {
            statusText = '上半场';
            statusClass = 'live';
        } else if (status === 3) {
            statusText = '中场';
            statusClass = 'live';
        } else if (status === 4) {
            statusText = '下半场';
            statusClass = 'live';
        } else if (status === 5) {
            statusText = '加时赛';
            statusClass = 'live';
        } else if (status === 7) {
            statusText = '点球大战';
            statusClass = 'live';
        } else if (status === 8) {
            statusText = '已结束';
            statusClass = 'finished';
        }
        
        if (status >= 2 && status <= 8) {
            if (m.score && m.score.trim() !== '') {
                scoreDisplay = m.score.replace('-', ' : ').replace(':', ' : ');
            }
            if (m.half_score && m.half_score.trim() !== '') {
                halfDisplay = `<span class="half-score-label" style="font-size: 0.75rem; color: #8a99ad; display: block; margin-top: 2px;">半: ${m.half_score}</span>`;
            }
            if (m.penalty_score && m.penalty_score.trim() !== '') {
                penaltyDisplay = `<span class="penalty-label" style="font-size: 0.75rem; color: #e74c5b; display: block; font-weight: bold; margin-top: 2px;">点: ${m.penalty_score}</span>`;
            }
        }
        
        card.innerHTML = `
            <div class="match-time-col">
                <span class="m-time">${m.time}</span>
                <span class="m-league" title="${m.competition}">${m.competition}</span>
            </div>
            <div class="match-teams-col">
                <div class="m-team home">
                    <span class="team-name">${m.home_team}</span>
                    ${m.home_rank ? `<span class="team-rank">${m.home_rank}</span>` : ''}
                </div>
                <div class="m-score-wrap" style="display: flex; flex-direction: column; align-items: center; justify-content: center; min-width: 60px;">
                    <span class="m-score" style="font-size: 1.1rem; font-weight: 700;">${scoreDisplay}</span>
                    ${halfDisplay}
                    ${penaltyDisplay}
                </div>
                <div class="m-team away">
                    <span class="team-name">${m.away_team}</span>
                    ${m.away_rank ? `<span class="team-rank">${m.away_rank}</span>` : ''}
                </div>
            </div>
            <div class="match-status-col">
                <span class="status-chip ${statusClass}">${statusText}</span>
            </div>
        `;
        container.appendChild(card);
    });
}

// Select a Match
function selectMatch(match) {
    selectedMatch = match;
    
    // Toggle active state in Match Cards UI
    document.querySelectorAll('.match-card').forEach(c => c.classList.remove('active'));
    const activeCard = document.getElementById(`match-card-${match.id}`);
    if (activeCard) activeCard.classList.add('active');
    
    // Update mobile details title
    const mobTitle = document.getElementById('mobile-match-title');
    if (mobTitle) {
        mobTitle.innerText = `${match.home_team} VS ${match.away_team}`;
    }
    
    // Slide in the details view on mobile
    const detailsPanel = document.querySelector('.panel-details');
    if (detailsPanel) {
        detailsPanel.classList.add('slide-in');
    }
    
    // Load Match Details
    loadMatchDetails(match);
}

// Close mobile details view
function closeMobileDetails() {
    const detailsPanel = document.querySelector('.panel-details');
    if (detailsPanel) {
        detailsPanel.classList.remove('slide-in');
    }
}

// Fetch and load Match Details
function loadMatchDetails(match) {
    if (!match.id) {
        renderNoIntelligenceView(match);
        return;
    }
    
    // Check local memory cache first
    if (matchDetailsCache[match.id]) {
        renderMatchDetails(match, matchDetailsCache[match.id]);
        return;
    }
    
    showDetailsLoading();
    
    fetch(`/api/match_details?id=${match.id}&home=${encodeURIComponent(match.home_team)}&away=${encodeURIComponent(match.away_team)}`)
        .then(res => res.json())
        .then(res => {
            if (res.success) {
                matchDetailsCache[match.id] = res.data;
                renderMatchDetails(match, res.data);
            } else {
                renderDetailsError(res.error || "获取比赛详情失败。");
            }
        })
        .catch(err => {
            renderDetailsError("网络连接失败，请检查网络或后端服务器状态。");
            console.error(err);
        });
}

// Switch Right Panel Tabs (intel, history, squad, odds)
function switchDetailTab(tabName) {
    activeDetailTab = tabName;
    
    // Toggle tab active class
    document.querySelectorAll('.detail-tab').forEach(t => t.classList.remove('active'));
    const clickedTab = Array.from(document.querySelectorAll('.detail-tab')).find(t => {
        const attr = t.getAttribute('onclick');
        return attr && attr.includes("'" + tabName + "'");
    });
    if (clickedTab) clickedTab.classList.add('active');
    
    // Toggle content divs active class
    document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
    const activeContent = document.getElementById(`tab-content-${tabName}`);
    if (activeContent) activeContent.classList.add('active');
    
    // 切换到 AI 研判 tab 时，自动检查并秒级载入已缓存的 AI 预测报告
    if (tabName === 'ai' && selectedMatch) {
        checkAndLoadCachedReport(selectedMatch.id);
    }
}

// Render Complete Match Details
function renderMatchDetails(match, details) {
    const container = document.getElementById('details-content');
    container.innerHTML = '';
    
    // Show refresh button since details exist
    const refreshBtn = document.getElementById('btn-refresh-match');
    if (refreshBtn) refreshBtn.style.display = 'inline-flex';
    
    // 1. VS Header
    let html = `
        <div class="details-vs-header">
            <div class="match-league" style="font-size: 0.8rem; font-weight:700;">${match.competition}</div>
            <div class="vs-row">
                <div class="vs-logo-team">
                    <h2>${match.home_team}</h2>
                    ${match.home_rank ? `<span>${match.home_rank}</span>` : ''}
                </div>
                <div class="vs-circle">VS</div>
                <div class="vs-logo-team">
                    <h2>${match.away_team}</h2>
                    ${match.away_rank ? `<span>${match.away_rank}</span>` : ''}
                </div>
            </div>
            <div style="font-size:0.8rem; color:var(--text-muted); font-weight:600;">
                开赛时间: ${match.date} ${match.time}
            </div>
        </div>
    `;
    
    // Add sub-content divs for the 5 tabs
    html += `
        <!-- TAB 1: Intelligence / SWOT -->
        <div id="tab-content-intel" class="tab-content ${activeDetailTab === 'intel' ? 'active' : ''}">
            ${renderIntelTab(match, details)}
        </div>
        
        <!-- TAB 2: H2H & Recent History -->
        <div id="tab-content-history" class="tab-content ${activeDetailTab === 'history' ? 'active' : ''}">
            ${renderHistoryTab(match, details)}
        </div>
        
        <!-- TAB 3: Squad & Injuries -->
        <div id="tab-content-squad" class="tab-content ${activeDetailTab === 'squad' ? 'active' : ''}">
            ${renderSquadTab(match, details)}
        </div>
        
        <!-- TAB 4: Odds & Trends -->
        <div id="tab-content-odds" class="tab-content ${activeDetailTab === 'odds' ? 'active' : ''}">
            ${renderOddsTab(match, details)}
        </div>
        
        <!-- TAB 5: AI Prediction Analysis -->
        <div id="tab-content-ai" class="tab-content ${activeDetailTab === 'ai' ? 'active' : ''}">
            ${renderAiTab(match, details)}
        </div>
    `;
    
    container.innerHTML = html;
    
    // 如果当前选中的是 AI 选项卡，在切换场次后自动尝试秒级拉取并渲染已有的 AI 分析缓存
    if (activeDetailTab === 'ai') {
        checkAndLoadCachedReport(match.id);
    }
}

// Force refresh current match details
function forceRefreshCurrentMatch() {
    if (!selectedMatch || !selectedMatch.id) return;
    
    const refreshBtn = document.getElementById('btn-refresh-match');
    if (!refreshBtn || refreshBtn.classList.contains('refreshing')) return;
    
    refreshBtn.classList.add('refreshing');
    const btnText = refreshBtn.querySelector('span');
    if (btnText) btnText.textContent = '刷新中...';
    
    fetch(`/api/match_details?id=${selectedMatch.id}&home=${encodeURIComponent(selectedMatch.home_team)}&away=${encodeURIComponent(selectedMatch.away_team)}&force=true`)
        .then(res => res.json())
        .then(res => {
            if (res.success) {
                // Update memory cache
                matchDetailsCache[selectedMatch.id] = res.data;
                // Re-render
                renderMatchDetails(selectedMatch, res.data);
            } else {
                alert("刷新失败: " + (res.error || "未知错误"));
            }
        })
        .catch(err => {
            alert("刷新本场网络连接失败。");
            console.error(err);
        })
        .finally(() => {
            refreshBtn.classList.remove('refreshing');
            if (btnText) btnText.textContent = '刷新本场';
        });
}
window.forceRefreshCurrentMatch = forceRefreshCurrentMatch;

// Global variable to keep track of current AI Configuration loaded from DB
let currentAiConfig = null;
let accumulatedMarkdown = '';

function loadAiConfigFromServer(callback) {
    fetch('/api/ai_config')
        .then(res => res.json())
        .then(res => {
            if (res.success) {
                currentAiConfig = res.data;
                if (callback) callback(res.data);
            } else {
                console.error("加载AI配置失败:", res.error);
            }
        })
        .catch(err => console.error("连接配置接口失败:", err));
}

// Global AI Config Modal Controls
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
window.saveGlobalAiConfigToServer = saveGlobalAiConfigToServer;

function checkAndLoadCachedReport(matchId) {
    if (!selectedMatch) return;
    
    fetch('/api/match_ai_analysis', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            match_id: matchId,
            home_team: selectedMatch.home_team,
            away_team: selectedMatch.away_team,
            force: false
        })
    })
    .then(res => res.json())
    .then(res => {
        const report = document.getElementById('ai-report-content');
        if (res.success && res.cached && report) {
            renderFullMarkdownReport(res.text);
        }
    })
    .catch(err => console.log("本场赛事尚未生成 AI 预测缓存报告"));
}

function generateAiReport(matchId, homeTeam, awayTeam) {
    const runBtn = document.getElementById('btn-run-ai-analysis');
    const skeleton = document.getElementById('ai-generating-status');
    const report = document.getElementById('ai-report-content');
    
    if (skeleton && report) {
        skeleton.style.display = 'flex';
        report.style.display = 'none';
        report.innerHTML = '';
    }
    if (runBtn) {
        runBtn.disabled = true;
        const runText = runBtn.querySelector('span');
        if (runText) runText.textContent = 'AI 研判生成中...';
    }
    
    accumulatedMarkdown = '';
    
    fetch('/api/match_ai_analysis', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            match_id: matchId,
            home_team: decodeURIComponent(homeTeam),
            away_team: decodeURIComponent(awayTeam),
            force: true
        })
    })
    .then(response => {
        if (!response.ok) {
            throw new Error(`HTTP 异常 ${response.status}`);
        }
        
        const contentType = response.headers.get('content-type');
        if (contentType && contentType.includes('application/json')) {
            return response.json().then(res => {
                if (!res.success) {
                    throw new Error(res.error || "生成失败");
                }
                if (res.cached) {
                    if (skeleton && report) {
                        skeleton.style.display = 'none';
                        report.style.display = 'block';
                    }
                    renderFullMarkdownReport(res.text);
                }
            });
        }
        
        const reader = response.body.getReader();
        const decoder = new TextDecoder('utf-8');
        let buffer = '';
        
        if (skeleton && report) {
            skeleton.style.display = 'none';
            report.style.display = 'block';
        }
        
        function readChunk() {
            return reader.read().then(({ done, value }) => {
                if (done) {
                    if (runBtn) {
                        runBtn.disabled = false;
                        const runText = runBtn.querySelector('span');
                        if (runText) runText.textContent = '一键生成 AI 深度研判报告';
                    }
                    return;
                }
                
                buffer += decoder.decode(value, { stream: true });
                const lines = buffer.split('\n');
                buffer = lines.pop();
                
                for (const line of lines) {
                    const trimmed = line.trim();
                    if (trimmed.startsWith('data:')) {
                        try {
                            const jsonStr = trimmed.slice(5).trim();
                            const parsed = JSON.parse(jsonStr);
                            if (parsed.error) {
                                report.innerHTML = `<p style="color:var(--color-danger); font-weight:700;">生成出错: ${parsed.error}</p>`;
                                if (runBtn) {
                                    runBtn.disabled = false;
                                    const runText = runBtn.querySelector('span');
                                    if (runText) runText.textContent = '一键生成 AI 深度研判报告';
                                }
                                return;
                            }
                            if (parsed.text) {
                                appendTokenToReport(parsed.text);
                            }
                        } catch (e) {
                            // ignore syntax errors during partial json chunk
                        }
                    }
                }
                return readChunk();
            });
        }
        return readChunk();
    })
    .catch(err => {
        if (skeleton && report) {
            skeleton.style.display = 'none';
            report.style.display = 'block';
            report.innerHTML = `<p style="color:var(--color-danger); font-weight:700;">生成出错: ${err.message || err}</p>`;
        }
        if (runBtn) {
            runBtn.disabled = false;
            const runText = runBtn.querySelector('span');
            if (runText) runText.textContent = '一键生成 AI 深度研判报告';
        }
    });
}
window.generateAiReport = generateAiReport;

function appendTokenToReport(token) {
    const report = document.getElementById('ai-report-content');
    if (!report) return;
    accumulatedMarkdown += token;
    report.innerHTML = parseSimpleMarkdown(accumulatedMarkdown);
}

function renderFullMarkdownReport(text) {
    const report = document.getElementById('ai-report-content');
    if (report) {
        accumulatedMarkdown = text;
        report.innerHTML = parseSimpleMarkdown(text);
    }
}

function parseSimpleMarkdown(md) {
    let html = md;
    
    // Replace # header with h3
    html = html.replace(/^#\s+(.+)$/gm, '<h3>$1</h3>');
    // Replace ## header with h4
    html = html.replace(/^##\s+(.+)$/gm, '<h4>$1</h4>');
    // Replace ### or #### headers with h5
    html = html.replace(/^(?:####|###)\s+(.+)$/gm, '<h5>$1</h5>');
    
    // Replace **bold** with <b>bold</b>
    html = html.replace(/\*\*(.*?)\*\*/g, '<b>$1</b>');
    
    // Replace list * or - with <li>
    html = html.replace(/^\s*[\*\-]\s+(.+)$/gm, '<li>$1</li>');
    
    // Process paragraphs
    let lines = html.split('\n\n');
    html = lines.map(line => {
        let trimmed = line.trim();
        if (!trimmed) return '';
        if (trimmed.startsWith('<h') || trimmed.startsWith('<li')) {
            return trimmed;
        }
        return `<p>${trimmed}</p>`;
    }).join('');
    
    // Single newlines to linebreaks
    html = html.replace(/\n/g, '<br>');
    
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

function renderIntelTab(match, details) {
    let tabHtml = '';
    
    // 1. Win Probability
    const hasProb = match.win_probability && match.win_probability.home && match.win_probability.away;
    if (hasProb) {
        tabHtml += `
            <div class="details-card">
                <div class="details-card-title">AI 获胜概率预测</div>
                <div class="prob-group">
                    <div class="prob-labels">
                        <span class="home">${match.home_team} ${match.win_probability.home}</span>
                        <span class="away">${match.win_probability.away} ${match.away_team}</span>
                    </div>
                    <div class="prob-track">
                        <div class="prob-fill-home" style="width: ${match.win_probability.home}"></div>
                        <div class="prob-fill-away" style="width: ${match.win_probability.away}"></div>
                    </div>
                </div>
            </div>
        `;
    }
    
    // 2. Similar Trend
    const hasTrend = match.similar_trend && match.similar_trend.stats && match.similar_trend.stats.length > 0;
    if (hasTrend) {
        tabHtml += `
            <div class="details-card">
                <div class="details-card-title">相似历史盘口走势</div>
                <p class="trend-desc" style="font-size:0.85rem; color:var(--text-secondary); margin-bottom:0.75rem;">
                    ${match.similar_trend.description}
                </p>
                <div class="similar-grid">
                    ${match.similar_trend.stats.map(s => {
                        const isPrimary = s.percentage.replace('%', '') > 50;
                        return `
                            <div class="similar-item ${isPrimary ? 'highlight' : ''}">
                                <span class="similar-label">${s.outcome.split(' ')[0]}</span>
                                <span class="similar-val">${s.percentage}</span>
                                <span class="similar-count">${s.outcome.split(' ')[1] || ''}</span>
                            </div>
                        `;
                    }).join('')}
                </div>
            </div>
        `;
    }
    
    // 3. SWOT Intelligence List
    const hasSwot = details.pros_cons && (details.pros_cons.home.pros.length > 0 || details.pros_cons.away.pros.length > 0);
    if (hasSwot) {
        tabHtml += `
            <div class="details-card">
                <div class="details-card-title">独家情报 SWOT 分析</div>
                <div class="swot-split">
                    <!-- Home SWOT -->
                    <div class="swot-card-side">
                        <h4>${match.home_team}</h4>
                        <div class="swot-group">
                            <div class="swot-sub-header pros">
                                <span style="font-size:0.9rem;">🟢</span> 有利情报
                            </div>
                            <ul class="swot-item-list pros-list">
                                ${details.pros_cons.home.pros.length > 0
                                    ? details.pros_cons.home.pros.map(p => `<li>${p}</li>`).join('')
                                    : `<li style="color:var(--text-muted); border:none; background:none;">暂无有利情报</li>`
                                }
                            </ul>
                        </div>
                        <div class="swot-group">
                            <div class="swot-sub-header cons">
                                <span style="font-size:0.9rem;">🔴</span> 不利情报
                            </div>
                            <ul class="swot-item-list cons-list">
                                ${details.pros_cons.home.cons.length > 0
                                    ? details.pros_cons.home.cons.map(c => `<li>${c}</li>`).join('')
                                    : `<li style="color:var(--text-muted); border:none; background:none;">暂无不利情报</li>`
                                }
                            </ul>
                        </div>
                    </div>
                    
                    <!-- Away SWOT -->
                    <div class="swot-card-side">
                        <h4>${match.away_team}</h4>
                        <div class="swot-group">
                            <div class="swot-sub-header pros">
                                <span style="font-size:0.9rem;">🟢</span> 有利情报
                            </div>
                            <ul class="swot-item-list pros-list">
                                ${details.pros_cons.away.pros.length > 0
                                    ? details.pros_cons.away.pros.map(p => `<li>${p}</li>`).join('')
                                    : `<li style="color:var(--text-muted); border:none; background:none;">暂无有利情报</li>`
                                }
                            </ul>
                        </div>
                        <div class="swot-group">
                            <div class="swot-sub-header cons">
                                <span style="font-size:0.9rem;">🔴</span> 不利情报
                            </div>
                            <ul class="swot-item-list cons-list">
                                ${details.pros_cons.away.cons.length > 0
                                    ? details.pros_cons.away.cons.map(c => `<li>${c}</li>`).join('')
                                    : `<li style="color:var(--text-muted); border:none; background:none;">暂无不利情报</li>`
                                }
                            </ul>
                        </div>
                    </div>
                </div>
            </div>
        `;
    }
    
    if (tabHtml === '') {
        tabHtml = `<div class="welcome-view"><h3>暂无情报预测数据</h3></div>`;
    }
    return tabHtml;
}

function renderHistoryTab(match, details) {
    let tabHtml = '';
    
    // 1. H2H Section
    tabHtml += `<div class="details-card">`;
    tabHtml += `<div class="details-card-title">历史对决交锋 (近 10 场)</div>`;
    if (details.h2h && details.h2h.has_history && details.h2h.matches.length > 0) {
        tabHtml += `
            <table class="table-panel">
                <thead>
                    <tr>
                        <th>赛事</th>
                        <th>比赛日期</th>
                        <th style="text-align:right;">主队</th>
                        <th style="text-align:center;">比分</th>
                        <th>客队</th>
                        <th style="text-align:center;">主胜负</th>
                    </tr>
                </thead>
                <tbody>
                    ${details.h2h.matches.map(m => `
                        <tr>
                            <td>${m.competition}</td>
                            <td class="date">${m.date}</td>
                            <td style="text-align:right;" class="${m.home === match.home_team ? 'bold-td' : ''}">${m.home}</td>
                            <td style="text-align:center; font-weight:700;">${m.score}</td>
                            <td class="${m.away === match.home_team ? 'bold-td' : ''}">${m.away}</td>
                            <td style="text-align:center;">
                                <span class="badge-outcome ${getOutcomeClass(m.result)}">${m.result}</span>
                            </td>
                        </tr>
                    `).join('')}
                </tbody>
            </table>
        `;
    } else {
        tabHtml += `<p class="trend-desc" style="color:var(--text-muted); font-style:italic;">双方近三年内暂无交战历史。</p>`;
    }
    tabHtml += `</div>`;
    
    // 2. Recent Results Section
    tabHtml += `<div class="details-card">`;
    tabHtml += `<div class="details-card-title">${match.home_team} 近期战绩</div>`;
    if (details.recent_results && details.recent_results.home.length > 0) {
        tabHtml += `
            <table class="table-panel">
                <thead>
                    <tr>
                        <th>赛事</th>
                        <th>比赛日期</th>
                        <th style="text-align:right;">主队</th>
                        <th style="text-align:center;">比分</th>
                        <th>客队</th>
                        <th style="text-align:center;">结果</th>
                    </tr>
                </thead>
                <tbody>
                    ${details.recent_results.home.map(m => `
                        <tr>
                            <td>${m.competition}</td>
                            <td class="date">${m.date}</td>
                            <td style="text-align:right;" class="${m.home === match.home_team ? 'bold-td' : ''}">${m.home}</td>
                            <td style="text-align:center; font-weight:700;">${m.score}</td>
                            <td class="${m.away === match.home_team ? 'bold-td' : ''}">${m.away}</td>
                            <td style="text-align:center;">
                                <span class="badge-outcome ${getOutcomeClass(m.result)}">${m.result}</span>
                            </td>
                        </tr>
                    `).join('')}
                </tbody>
            </table>
        `;
    } else {
        tabHtml += `<p style="color:var(--text-muted); font-style:italic;">暂无近期战绩数据。</p>`;
    }
    tabHtml += `</div>`;
    
    // Away Recent Results
    tabHtml += `<div class="details-card">`;
    tabHtml += `<div class="details-card-title">${match.away_team} 近期战绩</div>`;
    if (details.recent_results && details.recent_results.away.length > 0) {
        tabHtml += `
            <table class="table-panel">
                <thead>
                    <tr>
                        <th>赛事</th>
                        <th>比赛日期</th>
                        <th style="text-align:right;">主队</th>
                        <th style="text-align:center;">比分</th>
                        <th>客队</th>
                        <th style="text-align:center;">结果</th>
                    </tr>
                </thead>
                <tbody>
                    ${details.recent_results.away.map(m => `
                        <tr>
                            <td>${m.competition}</td>
                            <td class="date">${m.date}</td>
                            <td style="text-align:right;" class="${m.home === match.away_team ? 'bold-td' : ''}">${m.home}</td>
                            <td style="text-align:center; font-weight:700;">${m.score}</td>
                            <td class="${m.away === match.away_team ? 'bold-td' : ''}">${m.away}</td>
                            <td style="text-align:center;">
                                <span class="badge-outcome ${getOutcomeClass(m.result)}">${m.result}</span>
                            </td>
                        </tr>
                    `).join('')}
                </tbody>
            </table>
        `;
    } else {
        tabHtml += `<p style="color:var(--text-muted); font-style:italic;">暂无近期战绩数据。</p>`;
    }
    tabHtml += `</div>`;
    
    return tabHtml;
}

function renderSquadTab(match, details) {
    let tabHtml = '';
    
    const hasHomeInjuries = details.injuries && (details.injuries.home.injuries.length > 0 || details.injuries.home.suspensions.length > 0);
    const hasAwayInjuries = details.injuries && (details.injuries.away.injuries.length > 0 || details.injuries.away.suspensions.length > 0);
    
    // Home injuries
    tabHtml += `<div class="details-card">`;
    tabHtml += `<div class="details-card-title">${match.home_team} 伤停与阵容信息</div>`;
    if (hasHomeInjuries) {
        tabHtml += `
            <table class="table-panel">
                <thead>
                    <tr>
                        <th>球员</th>
                        <th>位置</th>
                        <th>原因</th>
                        <th>状态</th>
                        <th>开始时间</th>
                        <th>回归时间</th>
                    </tr>
                </thead>
                <tbody>
                    ${details.injuries.home.injuries.map(p => `
                        <tr>
                            <td class="bold-td">${p.player}</td>
                            <td><span class="badge-pos">${p.position}</span></td>
                            <td>${p.reason}</td>
                            <td style="color:var(--color-danger); font-weight:600;">伤病</td>
                            <td>${p.start_time}</td>
                            <td>${p.return_time}</td>
                        </tr>
                    `).join('')}
                    ${details.injuries.home.suspensions.map(p => `
                        <tr>
                            <td class="bold-td">${p.player}</td>
                            <td><span class="badge-pos">${p.position}</span></td>
                            <td>${p.reason}</td>
                            <td style="color:var(--color-warning); font-weight:600;">停赛</td>
                            <td>${p.start_time}</td>
                            <td>${p.return_time}</td>
                        </tr>
                    `).join('')}
                </tbody>
            </table>
        `;
    } else {
        tabHtml += `
            <p style="color:var(--text-muted); font-style:italic;">
                此场赛事该队暂无伤停球员，主力阵容齐整。
            </p>
        `;
    }
    tabHtml += `</div>`;
    
    // Away injuries
    tabHtml += `<div class="details-card">`;
    tabHtml += `<div class="details-card-title">${match.away_team} 伤停与阵容信息</div>`;
    if (hasAwayInjuries) {
        tabHtml += `
            <table class="table-panel">
                <thead>
                    <tr>
                        <th>球员</th>
                        <th>位置</th>
                        <th>原因</th>
                        <th>状态</th>
                        <th>开始时间</th>
                        <th>回归时间</th>
                    </tr>
                </thead>
                <tbody>
                    ${details.injuries.away.injuries.map(p => `
                        <tr>
                            <td class="bold-td">${p.player}</td>
                            <td><span class="badge-pos">${p.position}</span></td>
                            <td>${p.reason}</td>
                            <td style="color:var(--color-danger); font-weight:600;">伤病</td>
                            <td>${p.start_time}</td>
                            <td>${p.return_time}</td>
                        </tr>
                    `).join('')}
                    ${details.injuries.away.suspensions.map(p => `
                        <tr>
                            <td class="bold-td">${p.player}</td>
                            <td><span class="badge-pos">${p.position}</span></td>
                            <td>${p.reason}</td>
                            <td style="color:var(--color-warning); font-weight:600;">停赛</td>
                            <td>${p.start_time}</td>
                            <td>${p.return_time}</td>
                        </tr>
                    `).join('')}
                </tbody>
            </table>
        `;
    } else {
        tabHtml += `
            <p style="color:var(--text-muted); font-style:italic;">
                此场赛事该队暂无伤停球员，主力阵容齐整。
            </p>
        `;
    }
    tabHtml += `</div>`;
    
    tabHtml += `
        <div style="font-size:0.8rem; color:var(--text-muted); padding:0 0.5rem; text-align:center;">
            💡 注：首发及替补名单通常在开赛前一小时内由赛事官方公布，本版块展示实时伤病/停赛阵容削弱情报。
        </div>
    `;
    
    return tabHtml;
}

function renderOddsTab(match, details) {
    const indexData = details.odds_index || [];
    if (indexData.length === 0) {
        return `<div class="welcome-view"><h3>暂无详细指数数据</h3></div>`;
    }
    
    const companyToCid = {
        "36*": 2,
        "皇*": 3,
        "威***": 9,
        "易**": 10,
        "澳*": 7,
        "立*": 5,
        "韦*": 11,
        "Inter*": 13,
        "12*": 14,
        "利*": 15,
        "盈*": 16,
        "18**": 17
    };
    
    let handicapRows = indexData.map(row => {
        if (!row.cid) {
            row.cid = companyToCid[row.company];
        }
        const h = row.handicap;
        const homeInit = h.initial[0].toFixed(2);
        const awayInit = h.initial[1].toFixed(2);
        const homeInst = h.instant[0].toFixed(2);
        const awayInst = h.instant[1].toFixed(2);
        
        const classHome = h.trends[0] > 0 ? 'up' : (h.trends[0] < 0 ? 'down' : '');
        const classAway = h.trends[1] > 0 ? 'up' : (h.trends[1] < 0 ? 'down' : '');
        
        return `
            <tr class="odds-row-clickable" onclick="toggleOddsTrend(${match.id}, ${row.cid}, 1, this)">
                <td class="company-cell">
                    <span class="company-name-trend">${row.company}</span>
                    <span class="trend-icon-mini">📈</span>
                </td>
                <td>
                    <div class="odds-cell-group">
                        <span class="odds-num">${homeInit}</span>
                        <span class="odds-line">${h.initial_line || h.line || '0'}</span>
                        <span class="odds-num">${awayInit}</span>
                    </div>
                </td>
                <td>
                    <div class="odds-cell-group">
                        <span class="odds-num ${classHome}">${homeInst}</span>
                        <span class="odds-line">${h.instant_line || h.line || '0'}</span>
                        <span class="odds-num ${classAway}">${awayInst}</span>
                    </div>
                </td>
            </tr>
            <tr id="trend-row-${row.cid}-1" class="trend-chart-row" style="display:none;">
                <td colspan="3" class="trend-chart-td">
                    <div class="trend-chart-box">
                        <div class="trend-loading-spinner">正在拉取实时变盘走势...</div>
                        <div class="trend-chart-wrapper" style="position: relative; height: 160px; width: 100%; display: none;">
                            <canvas id="trend-canvas-${row.cid}-1" style="height: 160px; width: 100%;"></canvas>
                        </div>
                        <div id="trend-details-${row.cid}-1" class="trend-details-box" style="display: none;"></div>
                    </div>
                </td>
            </tr>
        `;
    }).join('');
    
    let europeRows = indexData.map(row => {
        if (!row.cid) {
            row.cid = companyToCid[row.company];
        }
        const e = row.europe;
        const initH = e.initial[0].toFixed(2);
        const initD = e.initial[1].toFixed(2);
        const initA = e.initial[2].toFixed(2);
        const instH = e.instant[0].toFixed(2);
        const instD = e.instant[1].toFixed(2);
        const instA = e.instant[2].toFixed(2);
        
        const classH = e.trends[0] > 0 ? 'up' : (e.trends[0] < 0 ? 'down' : '');
        const classD = e.trends[1] > 0 ? 'up' : (e.trends[1] < 0 ? 'down' : '');
        const classA = e.trends[2] > 0 ? 'up' : (e.trends[2] < 0 ? 'down' : '');
        
        return `
            <tr class="odds-row-clickable" onclick="toggleOddsTrend(${match.id}, ${row.cid}, 2, this)">
                <td class="company-cell">
                    <span class="company-name-trend">${row.company}</span>
                    <span class="trend-icon-mini">📈</span>
                </td>
                <td>
                    <div class="odds-cell-group">
                        <span class="odds-num">${initH}</span>
                        <span class="odds-divider">|</span>
                        <span class="odds-num">${initD}</span>
                        <span class="odds-divider">|</span>
                        <span class="odds-num">${initA}</span>
                    </div>
                </td>
                <td>
                    <div class="odds-cell-group">
                        <span class="odds-num ${classH}">${instH}</span>
                        <span class="odds-divider">|</span>
                        <span class="odds-num ${classD}">${instD}</span>
                        <span class="odds-divider">|</span>
                        <span class="odds-num ${classA}">${instA}</span>
                    </div>
                </td>
            </tr>
            <tr id="trend-row-${row.cid}-2" class="trend-chart-row" style="display:none;">
                <td colspan="3" class="trend-chart-td">
                    <div class="trend-chart-box">
                        <div class="trend-loading-spinner">正在拉取实时变盘走势...</div>
                        <div class="trend-chart-wrapper" style="position: relative; height: 160px; width: 100%; display: none;">
                            <canvas id="trend-canvas-${row.cid}-2" style="height: 160px; width: 100%;"></canvas>
                        </div>
                        <div id="trend-details-${row.cid}-2" class="trend-details-box" style="display: none;"></div>
                    </div>
                </td>
            </tr>
        `;
    }).join('');
    
    let overUnderRows = indexData.map(row => {
        if (!row.cid) {
            row.cid = companyToCid[row.company];
        }
        const ou = row.over_under || { line: '0', initial: [1.0, 1.0], instant: [1.0, 1.0], trends: [0, 0] };
        const overInit = ou.initial[0].toFixed(2);
        const underInit = ou.initial[1].toFixed(2);
        const overInst = ou.instant[0].toFixed(2);
        const underInst = ou.instant[1].toFixed(2);
        
        const classOver = ou.trends[0] > 0 ? 'up' : (ou.trends[0] < 0 ? 'down' : '');
        const classUnder = ou.trends[1] > 0 ? 'up' : (ou.trends[1] < 0 ? 'down' : '');
        
        return `
            <tr class="odds-row-clickable" onclick="toggleOddsTrend(${match.id}, ${row.cid}, 3, this)">
                <td class="company-cell">
                    <span class="company-name-trend">${row.company}</span>
                    <span class="trend-icon-mini">📈</span>
                </td>
                <td>
                    <div class="odds-cell-group">
                        <span class="odds-num">${overInit}</span>
                        <span class="odds-line">${ou.initial_line || ou.line || '0'}</span>
                        <span class="odds-num">${underInit}</span>
                    </div>
                </td>
                <td>
                    <div class="odds-cell-group">
                        <span class="odds-num ${classOver}">${overInst}</span>
                        <span class="odds-line">${ou.instant_line || ou.line || '0'}</span>
                        <span class="odds-num ${classUnder}">${underInst}</span>
                    </div>
                </td>
            </tr>
            <tr id="trend-row-${row.cid}-3" class="trend-chart-row" style="display:none;">
                <td colspan="3" class="trend-chart-td">
                    <div class="trend-chart-box">
                        <div class="trend-loading-spinner">正在拉取实时变盘走势...</div>
                        <div class="trend-chart-wrapper" style="position: relative; height: 160px; width: 100%; display: none;">
                            <canvas id="trend-canvas-${row.cid}-3" style="height: 160px; width: 100%;"></canvas>
                        </div>
                        <div id="trend-details-${row.cid}-3" class="trend-details-box" style="display: none;"></div>
                    </div>
                </td>
            </tr>
        `;
    }).join('');
    
    return `
        <div class="odds-tab-subheaders">
            <button id="subtab-handicap-btn" class="odds-subtab-btn active" onclick="switchOddsSubtab('handicap')">让球 (Handicap)</button>
            <button id="subtab-europe-btn" class="odds-subtab-btn" onclick="switchOddsSubtab('europe')">胜平负 (1X2)</button>
            <button id="subtab-overunder-btn" class="odds-subtab-btn" onclick="switchOddsSubtab('over_under')">总进球 (Over/Under)</button>
        </div>
        
        <div id="odds-subtab-handicap" class="odds-subtab-content">
            <div class="odds-table-container">
                <table class="odds-table">
                    <thead>
                        <tr>
                            <th style="text-align:left; padding-left: 1rem;">公司</th>
                            <th>初始让球 (主/盘口/客)</th>
                            <th>即时让球 (主/盘口/客)</th>
                        </tr>
                    </thead>
                    <tbody>
                        ${handicapRows}
                    </tbody>
                </table>
            </div>
        </div>
        
        <div id="odds-subtab-europe" class="odds-subtab-content" style="display:none;">
            <div class="odds-table-container">
                <table class="odds-table">
                    <thead>
                        <tr>
                            <th style="text-align:left; padding-left: 1rem;">公司</th>
                            <th>初始赔率 (主/平/客)</th>
                            <th>即时赔率 (主/平/客)</th>
                        </tr>
                    </thead>
                    <tbody>
                        ${europeRows}
                    </tbody>
                </table>
            </div>
        </div>
        
        <div id="odds-subtab-over_under" class="odds-subtab-content" style="display:none;">
            <div class="odds-table-container">
                <table class="odds-table">
                    <thead>
                        <tr>
                            <th style="text-align:left; padding-left: 1rem;">公司</th>
                            <th>初始总进球 (大/盘口/小)</th>
                            <th>即时总进球 (大/盘口/小)</th>
                        </tr>
                    </thead>
                    <tbody>
                        ${overUnderRows}
                    </tbody>
                </table>
            </div>
        </div>
    `;
}

// Helpers
function getOutcomeClass(result) {
    if (result === '胜') return 'win';
    if (result === '平') return 'draw';
    if (result === '负') return 'loss';
    return '';
}

function showMatchesLoading() {
    document.getElementById('matches-container').innerHTML = `
        <div class="loading-shimmer">
            <div class="card-shimmer"></div>
            <div class="card-shimmer"></div>
            <div class="card-shimmer"></div>
        </div>
    `;
}

function showDetailsLoading() {
    document.getElementById('details-content').innerHTML = `
        <div class="shimmer-box" style="height: 100px;"></div>
        <div class="shimmer-box" style="height: 250px;"></div>
        <div class="shimmer-box" style="height: 180px;"></div>
    `;
}

function renderNoMatchSelected() {
    document.getElementById('details-content').innerHTML = `
        <div class="welcome-view">
            <div class="animated-icon">📅</div>
            <h3>当前日期暂无赛事</h3>
            <p>请在左侧侧边栏中选择其他日期以查看比赛日程。</p>
        </div>
    `;
}

function renderNoIntelligenceView(match) {
    document.getElementById('details-content').innerHTML = `
        <div class="welcome-view">
            <div class="animated-icon">🔒</div>
            <h3>无高级分析数据</h3>
            <p>${match.home_team} VS ${match.away_team} 此场赛事雷速没有提供深度情报接口支持，您可以查阅其他核心赛事。</p>
        </div>
    `;
}

function renderDetailsError(msg) {
    document.getElementById('details-content').innerHTML = `
        <div class="welcome-view" style="color: var(--color-danger);">
            <div class="animated-icon">⚠️</div>
            <h3>获取详情出错</h3>
            <p>${msg}</p>
        </div>
    `;
}

function showErrorState(msg) {
    document.getElementById('matches-container').innerHTML = `
        <div class="welcome-view" style="color: var(--color-danger); padding: 2rem 0;">
            <div class="animated-icon">⚠️</div>
            <h3>连接异常</h3>
            <p>${msg}</p>
            <button class="btn-refresh" style="margin-top: 1rem;" onclick="loadMatches()">重新尝试</button>
        </div>
    `;
}

function updateSyncTime() {
    const now = new Date();
    const pad = (n) => String(n).padStart(2, '0');
    const timeStr = `${pad(now.getHours())}:${pad(now.getMinutes())}:${pad(now.getSeconds())}`;
    document.getElementById('sync-time').innerText = `最近同步: ${timeStr}`;
}

function switchOddsSubtab(type) {
    document.getElementById('subtab-handicap-btn').classList.toggle('active', type === 'handicap');
    document.getElementById('subtab-europe-btn').classList.toggle('active', type === 'europe');
    document.getElementById('subtab-overunder-btn').classList.toggle('active', type === 'over_under');
    
    document.getElementById('odds-subtab-handicap').style.display = type === 'handicap' ? 'block' : 'none';
    document.getElementById('odds-subtab-europe').style.display = type === 'europe' ? 'block' : 'none';
    document.getElementById('odds-subtab-over_under').style.display = type === 'over_under' ? 'block' : 'none';
}
window.switchOddsSubtab = switchOddsSubtab;

function getTodayDateString() {
    const now = new Date();
    const mm = String(now.getMonth() + 1).padStart(2, '0');
    const dd = String(now.getDate()).padStart(2, '0');
    const weekdays = ["星期日", "星期一", "星期二", "星期三", "星期四", "星期五", "星期六"];
    const w = weekdays[now.getDay()];
    return `${mm}-${dd} ${w}`;
}

function getDatesRange() {
    const dates = [];
    const weekdays = ["星期日", "星期一", "星期二", "星期三", "星期四", "星期五", "星期六"];
    const today = new Date();
    
    for (let i = -10; i <= 10; i++) {
        const d = new Date(today);
        d.setDate(today.getDate() + i);
        
        const mm = String(d.getMonth() + 1).padStart(2, '0');
        const dd = String(d.getDate()).padStart(2, '0');
        const w = weekdays[d.getDay()];
        dates.push(`${mm}-${dd} ${w}`);
    }
    return dates;
}

// 全局图表缓存实例
const chartInstances = {};

function toggleOddsTrend(matchId, cid, type, trEl) {
    // 容错兜底：若 cid 缺失（如由于读取了不含 cid 属性的历史缓存），则利用公司名称匹配映射出正确的 ID
    if (!cid || cid === 'undefined' || cid === undefined) {
        const companyEl = trEl.querySelector('.company-name-trend');
        const companyName = companyEl ? companyEl.textContent.trim() : null;
        const companyToCid = {
            "36*": 2,
            "皇*": 3,
            "威***": 9,
            "易**": 10,
            "澳*": 7,
            "立*": 5,
            "韦*": 11,
            "Inter*": 13,
            "12*": 14,
            "利*": 15,
            "盈*": 16,
            "18**": 17
        };
        if (companyName && companyToCid[companyName]) {
            cid = companyToCid[companyName];
            console.log(`[Odds Trend Tool] Auto-mapped missing company '${companyName}' to cid: ${cid}`);
        }
    }

    // 找到走势面板所在的 <tr>
    const trendRow = trEl.nextElementSibling;
    if (!trendRow || !trendRow.classList.contains('trend-chart-row')) {
        return;
    }
    
    // 如果目前已经是展开的，直接折叠
    if (trendRow.style.display !== 'none') {
        trendRow.style.display = 'none';
        trEl.classList.remove('odds-row-active');
        return;
    }
    
    // 折叠该表格内的其它所有展开的走势行，保证视觉简洁
    const allTrendRows = trEl.parentElement.querySelectorAll('.trend-chart-row');
    allTrendRows.forEach(r => r.style.display = 'none');
    const allClickableRows = trEl.parentElement.querySelectorAll('.odds-row-clickable');
    allClickableRows.forEach(r => r.classList.remove('odds-row-active'));
    
    // 展开当前行
    trendRow.style.display = 'table-row';
    trEl.classList.add('odds-row-active');
    
    const box = trendRow.querySelector('.trend-chart-box');
    const spinner = box.querySelector('.trend-loading-spinner');
    const wrapper = box.querySelector('.trend-chart-wrapper');
    const detailsBox = box.querySelector('#trend-details-' + cid + '-' + type);
    const canvasId = 'trend-canvas-' + cid + '-' + type;
    
    // 如果已经加载过数据了，就不重复请求，只做渲染
    if (wrapper.getAttribute('data-loaded') === 'true') {
        return;
    }
    
    // 显示 loading
    spinner.style.display = 'block';
    wrapper.style.display = 'none';
    detailsBox.style.display = 'none';
    
    // 发起 API 请求拉取数据
    fetch(`/api/match_odds_detail?match_id=${matchId}&cid=${cid}&type=${type}`)
        .then(response => response.json())
        .then(res => {
            if (res.success && res.data && res.data.length > 0) {
                spinner.style.display = 'none';
                wrapper.style.display = 'block';
                detailsBox.style.display = 'block';
                
                // 绘制图表
                drawChart(canvasId, res.data, type);
                
                // 渲染变盘明文列表
                renderTrendDetails(detailsBox, res.data, type);
                
                wrapper.setAttribute('data-loaded', 'true');
            } else {
                spinner.innerText = res.error || '该盘口暂无详细历史变盘走势点';
            }
        })
        .catch(err => {
            spinner.innerText = '拉取数据出错，可能受网关安全保护限制。';
            console.error('Error fetching trend detail:', err);
        });
}
window.toggleOddsTrend = toggleOddsTrend;

function drawChart(canvasId, trendData, type) {
    const ctx = document.getElementById(canvasId).getContext('2d');
    
    // 反转数组，让变盘历史时间从早到晚排序展示（通常接口返回的是最新到最旧）
    const sortedData = [...trendData].reverse();
    
    // 准备数据
    const labels = sortedData.map(item => {
        if (item.match_status > 1) {
            return `滚盘 ${item.match_time || ''}'`;
        }
        return item.change_time || '即时';
    });
    
    let datasets = [];
    
    if (type === 1 || type === 3) {
        // 让球 (1) 或 大小球 (3)
        const homeOdds = sortedData.map(item => parseFloat(item.home));
        const awayOdds = sortedData.map(item => parseFloat(item.away));
        
        // 粉蓝渐变
        const gradientHome = ctx.createLinearGradient(0, 0, 0, 160);
        gradientHome.addColorStop(0, 'rgba(54, 162, 235, 0.3)');
        gradientHome.addColorStop(1, 'rgba(54, 162, 235, 0.0)');
        
        // 橘黄渐变
        const gradientAway = ctx.createLinearGradient(0, 0, 0, 160);
        gradientAway.addColorStop(0, 'rgba(255, 159, 64, 0.3)');
        gradientAway.addColorStop(1, 'rgba(255, 159, 64, 0.0)');
        
        datasets = [
            {
                label: type === 1 ? '主队/大球水位' : '大球水位',
                data: homeOdds,
                borderColor: '#36a2eb',
                backgroundColor: gradientHome,
                fill: true,
                tension: 0.4,
                borderWidth: 2,
                pointRadius: 2,
                pointHoverRadius: 5
            },
            {
                label: type === 1 ? '客队/小球水位' : '小球水位',
                data: awayOdds,
                borderColor: '#ff9f40',
                backgroundColor: gradientAway,
                fill: true,
                tension: 0.4,
                borderWidth: 2,
                pointRadius: 2,
                pointHoverRadius: 5
            }
        ];
    } else if (type === 2) {
        // 胜平负 (1X2) 欧指三条线
        const winOdds = sortedData.map(item => parseFloat(item.home));
        const drawOdds = sortedData.map(item => parseFloat(item.draw));
        const loseOdds = sortedData.map(item => parseFloat(item.away));
        
        datasets = [
            {
                label: '主胜',
                data: winOdds,
                borderColor: '#4bc0c0',
                fill: false,
                tension: 0.4,
                borderWidth: 2,
                pointRadius: 2
            },
            {
                label: '平局',
                data: drawOdds,
                borderColor: '#9966ff',
                fill: false,
                tension: 0.4,
                borderWidth: 2,
                pointRadius: 2
            },
            {
                label: '客胜',
                data: loseOdds,
                borderColor: '#ff6384',
                fill: false,
                tension: 0.4,
                borderWidth: 2,
                pointRadius: 2
            }
        ];
    }
    
    // 如果已有实例则销毁，防止报错
    if (chartInstances[canvasId]) {
        chartInstances[canvasId].destroy();
    }
    
    chartInstances[canvasId] = new Chart(ctx, {
        type: 'line',
        data: {
            labels: labels,
            datasets: datasets
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: {
                    display: true,
                    position: 'top',
                    labels: {
                        color: 'var(--text-muted)',
                        boxWidth: 12,
                        font: { size: 10 }
                    }
                },
                tooltip: {
                    mode: 'index',
                    intersect: false
                }
            },
            scales: {
                x: {
                    grid: { display: false },
                    ticks: {
                        color: 'var(--text-muted)',
                        font: { size: 9 },
                        maxRotation: 45,
                        autoSkip: true,
                        maxTicksLimit: 8
                    }
                },
                y: {
                    grid: { color: 'rgba(200, 200, 200, 0.1)' },
                    ticks: {
                        color: 'var(--text-muted)',
                        font: { size: 9 }
                    }
                }
            }
        }
    });
}

function renderTrendDetails(container, trendData, type) {
    let listHtml = `
        <div class="trend-detail-header">
            <span>变盘时刻</span>
            <span>变动方向</span>
            <span>赔率明细 (主/平/客)</span>
        </div>
    `;
    
    // 最新的变盘放在最上面展示
    trendData.forEach(item => {
        let lineVal = item.line_zh || item.line || '';
        let oddsVal = '';
        if (type === 1 || type === 3) {
            oddsVal = `${parseFloat(item.home).toFixed(2)} | ${parseFloat(item.away).toFixed(2)}`;
        } else {
            oddsVal = `${parseFloat(item.home).toFixed(2)} | ${parseFloat(item.draw).toFixed(2)} | ${parseFloat(item.away).toFixed(2)}`;
        }
        
        let timeStr = item.change_time || '即时';
        if (item.match_status > 1) {
            timeStr = `<span class="in-play-badge">滚 ${item.match_time || ''}'</span>`;
        }
        
        listHtml += `
            <div class="trend-detail-row">
                <span class="trend-detail-time">${timeStr}</span>
                <span class="trend-detail-line">${lineVal || '欧指'}</span>
                <span class="trend-detail-val">${oddsVal}</span>
            </div>
        `;
    });
    
    container.innerHTML = listHtml;
}

window.toggleOddsTrend = toggleOddsTrend;

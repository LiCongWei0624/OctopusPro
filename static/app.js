let allMatches = [];
let groupedMatches = {}; // Key: Date, Value: Array of Matches
let selectedDate = null;
let selectedMatch = null;
let activeDetailTab = 'intel'; // intel, history, squad, odds
let matchDetailsCache = {}; // Cache for match details in memory
let selectedLeague = '全部';
let selectedStatus = '全部';
let searchQuery = '';
let activeReportVersion = 0;
let latestReports = ['', '', ''];
let latestStatusList = ['processing', 'processing', 'processing'];
let latestFinalTicket = '';
let searchRenderTimer = null;
const MAX_MATCH_DETAILS_CACHE = 24;

let aiPollingTimer = null;

function cacheMatchDetails(matchId, details) {
    delete matchDetailsCache[matchId];
    matchDetailsCache[matchId] = details;
    const cachedIds = Object.keys(matchDetailsCache);
    while (cachedIds.length > MAX_MATCH_DETAILS_CACHE) {
        delete matchDetailsCache[cachedIds.shift()];
    }
}

function isAnalyzableFixture(match) {
    return match && [1, 2, 3, 4, 5, 7, 10, 13].includes(Number(match.status));
}

function isLiveFixture(match) {
    return match && [2, 3, 4, 5, 7, 10].includes(Number(match.status));
}

// Sliding date range options & Custom Datepicker states
let startOffsetDays = -2;
let endOffsetDays = 2;
let calendarYear = new Date().getFullYear();
let calendarMonth = new Date().getMonth();
let isDateLoading = false;

function checkAndLoadCachedReport(matchId) {
    if (!selectedMatch) return;
    if (!isAnalyzableFixture(selectedMatch)) return;
    
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
        if (res.success && (res.reports || res.text) && report) {
            latestFinalTicket = res.final_ticket || '';
            renderFullMarkdownReport(res.reports || res.text);
        } else if (report) {
            report.innerHTML = `<p style="color:var(--text-muted); font-style:italic;">请点击上方“一键生成 AI 深度研判报告”按钮启动分析。您也可以点击导航栏右上角的“AI配置”配置 API 密钥。</p>`;
        }
    })
    .catch(err => {
        const report = document.getElementById('ai-report-content');
        if (report) {
            report.innerHTML = `<p style="color:var(--text-muted); font-style:italic;">请点击上方“一键生成 AI 深度研判报告”按钮启动分析。您也可以点击导航栏右上角的“AI配置”配置 API 密钥。</p>`;
        }
        console.log("本场赛事尚未生成 AI 预测缓存报告");
    });
}
window.checkAndLoadCachedReport = checkAndLoadCachedReport;

// Initial Load
document.addEventListener('DOMContentLoaded', () => {
    autoFixHtmlCacheBug();
    loadMatches();
    
    // Bind slider container scroll event
    const wrapper = document.getElementById('date-tabs-wrapper');
    if (wrapper) {
        wrapper.addEventListener('scroll', () => handleTabsScroll(wrapper));
    }
    
    // Global click listener to close custom calendar popover
    document.addEventListener('click', (e) => {
        const popover = document.getElementById('custom-datepicker-popover');
        const trigger = document.getElementById('calendar-trigger-btn');
        if (popover && popover.style.display !== 'none') {
            if (!popover.contains(e.target) && !trigger.contains(e.target)) {
                popover.style.display = 'none';
            }
        }
    });

    // Keep the visible day aligned with the server-side 10-minute refresh.
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
                        filterAndRenderMatches();
                    }
                    updateSyncTime();
                }
            })
            .catch(err => console.error("Auto-refresh error:", err));
    }, 10 * 60 * 1000);
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
    if (!container) return;
    container.innerHTML = '';
    
    const todayStr = getTodayDateString();
    
    const dateObj = new Date();
    dateObj.setDate(dateObj.getDate() - 1);
    const mm = String(dateObj.getMonth() + 1).padStart(2, '0');
    const dd = String(dateObj.getDate()).padStart(2, '0');
    const weekdays = ["星期日", "星期一", "星期二", "星期三", "星期四", "星期五", "星期六"];
    const yesterdayStr = `${mm}-${dd} ${weekdays[dateObj.getDay()]}`;
    
    const tObj = new Date();
    tObj.setDate(tObj.getDate() + 1);
    const tMm = String(tObj.getMonth() + 1).padStart(2, '0');
    const tDd = String(tObj.getDate()).padStart(2, '0');
    const tomorrowStr = `${tMm}-${tDd} ${weekdays[tObj.getDay()]}`;
    
    const dates = getDatesRange();
    dates.forEach(date => {
        const li = document.createElement('li');
        li.className = `date-tab ${selectedDate === date ? 'active' : ''}`;
        li.id = `date-tab-${date}`;
        
        let label = date;
        if (date === todayStr) label = `${date.split(' ')[0]} 今天`;
        else if (date === yesterdayStr) label = `${date.split(' ')[0]} 昨天`;
        else if (date === tomorrowStr) label = `${date.split(' ')[0]} 明天`;
        
        li.innerText = label;
        li.onclick = () => selectDate(date);
        container.appendChild(li);
    });

    // Update arrows status after render
    updateSliderArrowsState();
}

// Select Date Tab
function selectDate(date) {
    selectedDate = date;
    selectedLeague = '全部';
    selectedStatus = '全部';
    
    // 检查对应日期的页签是否存在于 DOM 中
    const tabExists = !!document.getElementById(`date-tab-${date}`);
    if (!tabExists) {
        // 如果不存在，强制重新渲染滑动条以生成并高亮该页签
        renderDateSidebar();
    }
    
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

    // 仅进行滑动居中定位，不再向两侧无限拉取加载日期
    scrollToSelectedTab(date);
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
    filterAndRenderMatches();
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

// Render League & Status Filters and Search Bar
function renderLeagueFilters(leagues) {
    const filterBar = document.getElementById('league-filter-bar');
    if (!filterBar) return;
    
    const statuses = ['全部', '进行中', '未开始', '已结束', '异常/推迟'];
    
    filterBar.innerHTML = `
        <div class="filter-controls-column">
            <div class="search-input-wrapper">
                <svg class="search-icon" viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="3">
                    <circle cx="11" cy="11" r="8"></circle>
                    <line x1="21" y1="21" x2="16.65" y2="16.65"></line>
                </svg>
                <input type="text" id="match-search-input" class="search-input-field" placeholder="搜索球队、联赛..." value="${searchQuery}" oninput="filterMatchesBySearch()">
            </div>
            <div class="filter-dropdowns-row">
                <div class="dropdown-wrapper">
                    <select id="league-select" class="league-select-dropdown" onchange="filterMatchesByLeague(this.value)">
                        ${leagues.map(l => `<option value="${l}" ${selectedLeague === l ? 'selected' : ''}>${l === '全部' ? '全部联赛' : l}</option>`).join('')}
                    </select>
                </div>
                <div class="dropdown-wrapper">
                    <select id="status-select" class="league-select-dropdown" onchange="filterMatchesByStatus(this.value)">
                        ${statuses.map(s => `<option value="${s}" ${selectedStatus === s ? 'selected' : ''}>${s === '全部' ? '全部状态' : s}</option>`).join('')}
                    </select>
                </div>
            </div>
        </div>
    `;
}

// Handle status selector dropdown events
function filterMatchesByStatus(statusName) {
    selectedStatus = statusName;
    filterAndRenderMatches();
}

// Filter matches by selected league and search query, then render cards
function filterAndRenderMatches() {
    const matches = groupedMatches[selectedDate] || [];
    const filtered = matches.filter(m => {
        const leagueMatch = (selectedLeague === '全部' || m.competition === selectedLeague);
        
        const q = searchQuery.trim().toLowerCase();
        const textMatch = !q || 
            (m.competition && m.competition.toLowerCase().includes(q)) ||
            (m.home_team && m.home_team.toLowerCase().includes(q)) ||
            (m.away_team && m.away_team.toLowerCase().includes(q));
            
        const status = Number(m.status || 1);
        let statusMatch = false;
        if (selectedStatus === '全部') {
            statusMatch = true;
        } else if (selectedStatus === '进行中') {
            statusMatch = (status === 2 || status === 3 || status === 4 || status === 5 || status === 7 || status === 10);
        } else if (selectedStatus === '未开始') {
            statusMatch = (status === 1 || status === 13);
        } else if (selectedStatus === '已结束') {
            statusMatch = (status === 8 || status === 11);
        } else if (selectedStatus === '异常/推迟') {
            statusMatch = (status === 9 || status === 12);
        }
            
        return leagueMatch && textMatch && statusMatch;
    });
    
    document.getElementById('match-count-badge').innerText = `${filtered.length} 场`;
    renderMatchCards(filtered);
    
    if (filtered.length > 0) {
        const currentMatchInFiltered = filtered.find(m => m.id === selectedMatch?.id);
        if (!currentMatchInFiltered) {
            const isMobile = window.innerWidth <= 768;
            const isSearching = searchQuery.trim() !== '';
            if (!isMobile && !isSearching) {
                selectMatch(filtered[0]);
            }
        }
    } else {
        renderNoMatchSelected();
    }
}

// Handle search input events
function filterMatchesBySearch() {
    const searchInput = document.getElementById('match-search-input');
    if (searchInput) {
        searchQuery = searchInput.value;
        clearTimeout(searchRenderTimer);
        searchRenderTimer = setTimeout(filterAndRenderMatches, 120);
    }
}

// Handle league selector dropdown events
function filterMatchesByLeague(leagueName) {
    selectedLeague = leagueName;
    filterAndRenderMatches();
}

// Filter matches by League (compatibility and direct call support)
function selectLeague(league) {
    selectedLeague = league;
    const selectEl = document.getElementById('league-select');
    if (selectEl) {
        selectEl.value = league;
    }
    filterAndRenderMatches();
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
    
    const fragment = document.createDocumentFragment();
    matches.forEach(m => {
        const status = Number(m.status || 1);
        const isLive = (status >= 2 && status <= 7);
        const card = document.createElement('div');
        card.className = `match-card ${selectedMatch && selectedMatch.id === m.id ? 'active' : ''} ${isLive ? 'live-match' : ''}`;
        card.id = `match-card-${m.id}`;
        card.onclick = () => selectMatch(m);
        
        let scoreDisplay = 'vs';
        let penaltyDisplay = '';
        let halfDisplay = '';
        let statusText = '已排期';
        let statusClass = 'scheduled';
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
        } else if (status === 9) {
            statusText = '已推迟';
            statusClass = 'finished';
        } else if (status === 10) {
            statusText = '已中断';
            statusClass = 'live';
        } else if (status === 11) {
            statusText = '已腰斩';
            statusClass = 'finished';
        } else if (status === 12) {
            statusText = '已取消';
            statusClass = 'finished';
        } else if (status === 13) {
            statusText = '待定';
            statusClass = 'scheduled';
        }
        
        let homeScore = '';
        let awayScore = '';
        
        if (status >= 2 && status <= 8) {
            if (m.score && m.score.includes('-')) {
                const parts = m.score.split('-');
                homeScore = parts[0].trim();
                awayScore = parts[1].trim();
            } else if (m.score && m.score.includes(':')) {
                const parts = m.score.split(':');
                homeScore = parts[0].trim();
                awayScore = parts[1].trim();
            } else {
                homeScore = m.score || '';
                awayScore = '';
            }
            
            if (m.half_score && m.half_score.trim() !== '') {
                halfDisplay = `<span class="half-score-label" style="font-size: 0.72rem; color: #8a99ad;">半:${m.half_score}</span>`;
            }
            if (m.penalty_score && m.penalty_score.trim() !== '') {
                penaltyDisplay = `<span class="penalty-label" style="font-size: 0.72rem; color: #e74c5b; font-weight: bold;">点:${m.penalty_score}</span>`;
            }
        }
        
        card.innerHTML = `
            <div class="match-time-col">
                <span class="m-time">${m.time}</span>
                <span class="m-league" title="${m.competition}">${m.competition}</span>
            </div>
            <div class="match-teams-col-vertical">
                <div class="m-team-row home">
                    <span class="team-name-wrap">
                        <span class="team-name" title="${m.home_team}">${m.home_team}</span>
                        ${m.home_rank ? `<span class="team-rank">${m.home_rank}</span>` : ''}
                    </span>
                    <span class="team-score home-score">${homeScore}</span>
                </div>
                <div class="m-team-row away">
                    <span class="team-name-wrap">
                        <span class="team-name" title="${m.away_team}">${m.away_team}</span>
                        ${m.away_rank ? `<span class="team-rank">${m.away_rank}</span>` : ''}
                    </span>
                    <span class="team-score away-score">${awayScore}</span>
                </div>
            </div>
            <div class="match-status-col-vertical">
                <span class="status-chip ${statusClass}">${statusText}</span>
                ${halfDisplay || penaltyDisplay ? `
                    <div class="extra-scores" style="display: flex; gap: 0.35rem; justify-content: flex-end; align-items: center; margin-top: 3px;">
                        ${halfDisplay}
                        ${penaltyDisplay}
                    </div>
                ` : ''}
            </div>
        `;
        fragment.appendChild(card);
    });
    container.appendChild(fragment);
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
    
    // 让刷新本场按钮在加载期置灰占位，规避数据渲染时才蹦出来导致页签向左被挤压的抖动
    const refreshBtn = document.getElementById('btn-refresh-match');
    if (refreshBtn) {
        refreshBtn.style.display = 'inline-flex';
        refreshBtn.classList.add('btn-disabled');
        refreshBtn.disabled = true;
        const btnText = refreshBtn.querySelector('span');
        if (btnText) btnText.textContent = '刷新本场';
    }

    // Check local memory cache first
    if (matchDetailsCache[match.id]) {
        if (refreshBtn) {
            refreshBtn.classList.remove('btn-disabled');
            refreshBtn.disabled = false;
        }
        renderMatchDetails(match, matchDetailsCache[match.id]);
        return;
    }
    
    showDetailsLoading(match);
    
    fetch(`/api/match_details?id=${match.id}&home=${encodeURIComponent(match.home_team)}&away=${encodeURIComponent(match.away_team)}`)
        .then(res => res.json())
        .then(res => {
            if (res.success) {
                cacheMatchDetails(match.id, res.data);
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
    if (refreshBtn) {
        refreshBtn.style.display = 'inline-flex';
        refreshBtn.classList.remove('btn-disabled');
        refreshBtn.classList.remove('refreshing');
        refreshBtn.disabled = false;
        const btnText = refreshBtn.querySelector('span');
        if (btnText) btnText.textContent = '刷新本场';
    }
    
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
    
    // 渲染完详情后，自动静默触发 12 家博彩公司走势图的排队异步拉取写缓存，供 AI 全量分析使用
    triggerOddsBackgroundFetch(match.id, details);
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
                cacheMatchDetails(selectedMatch.id, res.data);
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
        }
    });
}
window.saveGlobalAiConfigToServer = saveGlobalAiConfigToServer;

function formatBacktestRate(value) {
    return typeof value === 'number' ? `${(value * 100).toFixed(1)}%` : '--';
}

function formatBacktestDateTime(isoString) {
    if (!isoString) return '--';
    try {
        const date = new Date(isoString);
        if (isNaN(date.getTime())) return isoString;
        
        const pad = (num) => String(num).padStart(2, '0');
        const yyyy = date.getFullYear();
        const mm = pad(date.getMonth() + 1);
        const dd = pad(date.getDate());
        const hh = pad(date.getHours());
        const min = pad(date.getMinutes());
        const ss = pad(date.getSeconds());
        
        return `${yyyy}-${mm}-${dd} ${hh}:${min}:${ss}`;
    } catch (_) {
        return isoString;
    }
}

let backtestSamples = [];
let backtestFilters = { date: 'all', competition: 'all', status: 'all', query: '' };
let expandedBacktestSampleId = null;

function escapeBacktestHtml(value) {
    return String(value ?? '').replace(/[&<>'"]/g, char => ({
        '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;'
    })[char]);
}

function formatPredictionSide(side, homeTeam, awayTeam) {
    if (side === 'home') return homeTeam || '主队';
    if (side === 'away') return awayTeam || '客队';
    return side === 'draw' ? '平局' : '--';
}

function formatAsianHandicapPrediction(handicap, homeTeam, awayTeam) {
    if (!handicap || !handicap.team) return '--';
    const team = formatPredictionSide(handicap.team, homeTeam, awayTeam);
    const line = Number(handicap.line);
    if (!Number.isFinite(line)) return `${team} 让球 --`;
    if (line > 0) return `${team} 受让 ${line}`;
    if (line < 0) return `${team} 让 ${Math.abs(line)}`;
    return `${team} 平手`;
}

function formatOverUnderPrediction(overUnder) {
    if (!overUnder || !overUnder.side) return '--';
    return `${overUnder.side === 'over' ? '大' : '小'} ${overUnder.line ?? '--'}`;
}

function backtestOutcomeLabel(market, outcome) {
    if (!outcome) return '待结算';
    if (market === 'one_x_two') return outcome === 'win' ? '命中' : '未中';
    return formatSettlementOutcome(outcome);
}

function backtestOutcomeClass(outcome) {
    if (['win', 'half_win'].includes(outcome)) return 'won';
    if (outcome === 'push') return 'push';
    if (['loss', 'half_loss'].includes(outcome)) return 'lost';
    return 'pending';
}

function backtestPredictionMarkup(sample) {
    const prediction = sample.prediction;
    if (!prediction) return '<span class="backtest-market-pick muted">未保存结构化预测</span>';
    const picks = [
        ['胜平负', formatPredictionSide(prediction.one_x_two, sample.home_team, sample.away_team)],
        ['让球', formatAsianHandicapPrediction(prediction.asian_handicap, sample.home_team, sample.away_team)],
        ['大小球', formatOverUnderPrediction(prediction.over_under)],
    ].filter(([, value]) => value && value !== '--');
    return `<div class="backtest-market-picks">${picks.map(([label, value]) => `<span class="backtest-market-pick"><b>${escapeBacktestHtml(label)}</b>${escapeBacktestHtml(value)}</span>`).join('')}</div>`;
}

function backtestSettlementMarkup(sample) {
    if (!sample.result) return '<span class="backtest-market-result pending">待比赛完赛结算</span>';
    const result = sample.result;
    const outcomes = [
        ['胜平负', result.one_x_two?.outcome],
        ['让球', result.asian_handicap?.outcome],
        ['大小球', result.over_under?.outcome],
    ].filter(([, outcome]) => outcome);
    return `<div class="backtest-settlement"><strong class="backtest-score">${escapeBacktestHtml(result.score || '--')}</strong>${outcomes.map(([label, outcome]) => `<span class="backtest-market-result ${backtestOutcomeClass(outcome)}"><b>${escapeBacktestHtml(label)}</b>${backtestOutcomeLabel(label === '胜平负' ? 'one_x_two' : 'market', outcome)}</span>`).join('')}</div>`;
}

function predictionRecordFromReport(report) {
    const blocks = String(report || '').matchAll(/```(?:json)?\s*([\s\S]*?)```/gi);
    let record = null;
    for (const block of blocks) {
        try {
            const parsed = JSON.parse(block[1].trim());
            if (parsed && typeof parsed.prediction_record === 'object') record = parsed.prediction_record;
        } catch (_) {
            // The report can still be streaming while the JSON block is incomplete.
        }
    }
    return record;
}

function finalTicketPredictionMarkup(report) {
    const prediction = predictionRecordFromReport(report);
    if (!prediction) return '';
    const home = selectedMatch?.home_team || '主队';
    const away = selectedMatch?.away_team || '客队';
    const picks = [
        ['胜平负', formatPredictionSide(prediction.one_x_two, home, away)],
        ['让球', formatAsianHandicapPrediction(prediction.asian_handicap, home, away)],
        ['大小球', formatOverUnderPrediction(prediction.over_under)],
    ].filter(([, value]) => value && value !== '--');
    if (!picks.length) return '';
    return `<section class="cro-structured-picks"><h5>最终执行预测</h5><div>${picks.map(([label, value]) => `<span><b>${escapeBacktestHtml(label)}</b><strong>${escapeBacktestHtml(value)}</strong></span>`).join('')}</div></section>`;
}

function formatSettlementOutcome(outcome) {
    return ({ win: '赢', half_win: '赢半', push: '走盘', half_loss: '输半', loss: '输' })[outcome] || '--';
}

function predictionSampleStatus(sample) {
    if (!sample.prediction) return { label: '未追踪', className: 'untracked' };
    if (!sample.result) return { label: '待结算', className: 'pending' };
    return { label: '已结算', className: 'settled' };
}

function backtestFixtureStatusLabel(status) {
    const numericStatus = Number(status);
    if ([2, 3, 4, 5, 7, 10].includes(numericStatus)) return '进行中';
    if ([1, 13].includes(numericStatus)) return '未开始';
    if ([8, 11].includes(numericStatus)) return '已结束';
    if ([9, 12].includes(numericStatus)) return '异常/推迟';
    return '状态未知';
}

function backtestSampleDate(sample) {
    return sample.fixture_date || String(sample.kickoff || '').split(' ')[0] || '未标注日期';
}

function backtestDateOrder(date) {
    const matched = /^(\d{2})-(\d{2})/.exec(date || '');
    return matched ? Number(matched[1]) * 100 + Number(matched[2]) : 0;
}

function getFilteredBacktestSamples() {
    return backtestSamples.filter(sample => {
        const sampleDate = backtestSampleDate(sample);
        const competition = sample.competition || '未分类';
        const queryText = `${sample.home_team || ''} ${sample.away_team || ''} ${competition}`.toLowerCase();
        const dateMatch = backtestFilters.date === 'all' || sampleDate === backtestFilters.date;
        const competitionMatch = backtestFilters.competition === 'all' || competition === backtestFilters.competition;
        const queryMatch = !backtestFilters.query || queryText.includes(backtestFilters.query.toLowerCase());
        const status = predictionSampleStatus(sample).className;
        let statusMatch = backtestFilters.status === 'all';
        if (backtestFilters.status.startsWith('settlement:')) {
            statusMatch = status === backtestFilters.status.slice('settlement:'.length);
        } else if (backtestFilters.status.startsWith('fixture:')) {
            statusMatch = backtestFixtureStatusLabel(sample.fixture_status) === backtestFilters.status.slice('fixture:'.length);
        }
        return dateMatch && competitionMatch && queryMatch && statusMatch;
    });
}

function renderBacktestSampleFilters() {
    const container = document.getElementById('backtest-sample-filters');
    if (!container) return;
    const dates = [...new Set(backtestSamples.map(backtestSampleDate))].sort((a, b) => backtestDateOrder(b) - backtestDateOrder(a));
    const competitions = [...new Set(backtestSamples.map(sample => sample.competition || '未分类'))].sort((a, b) => a.localeCompare(b, 'zh-CN'));
    const statusOptions = [
        ['fixture:进行中', '赛事：进行中'],
        ['fixture:未开始', '赛事：未开始'],
        ['fixture:已结束', '赛事：已结束'],
        ['fixture:异常/推迟', '赛事：异常/推迟'],
        ['settlement:settled', '回测：已结算'],
        ['settlement:pending', '回测：待结算'],
        ['settlement:untracked', '回测：未追踪'],
    ];
    const optionMarkup = (items, selected, allLabel) => [
        `<option value="all">${allLabel}</option>`,
        ...items.map(item => {
            const value = Array.isArray(item) ? item[0] : item;
            const label = Array.isArray(item) ? item[1] : item;
            return `<option value="${escapeBacktestHtml(value)}" ${selected === value ? 'selected' : ''}>${escapeBacktestHtml(label)}</option>`;
        })
    ].join('');
    container.innerHTML = `
        <label class="backtest-filter-control"><span>日期</span><select onchange="setBacktestFilter('date', this.value)">${optionMarkup(dates, backtestFilters.date, '全部日期')}</select></label>
        <label class="backtest-filter-control"><span>联赛</span><select onchange="setBacktestFilter('competition', this.value)">${optionMarkup(competitions, backtestFilters.competition, '全部联赛')}</select></label>
        <label class="backtest-filter-control"><span>状态</span><select onchange="setBacktestFilter('status', this.value)">${optionMarkup(statusOptions, backtestFilters.status, '全部状态')}</select></label>
        <label class="backtest-filter-control backtest-filter-search"><span>查找</span><input type="search" value="${escapeBacktestHtml(backtestFilters.query)}" placeholder="球队或联赛" oninput="setBacktestFilter('query', this.value)"></label>
        <button type="button" class="backtest-filter-reset" onclick="resetBacktestFilters()" title="重置筛选" aria-label="重置筛选">↺</button>
    `;
}

function renderBacktestSampleTable() {
    const container = document.getElementById('backtest-sample-list');
    const count = document.getElementById('backtest-sample-count');
    if (!container || !count) return;
    const samples = getFilteredBacktestSamples();
    count.textContent = `显示 ${samples.length} / ${backtestSamples.length} 条`;
    container.innerHTML = samples.length ? `
        <div class="backtest-sample-table-wrap">
            <table class="backtest-sample-table">
                <thead><tr><th>赛事</th><th>赛前预测</th><th>赛果与结算</th><th>状态</th><th></th></tr></thead>
                <tbody>
                    ${samples.map(sample => {
                        const status = predictionSampleStatus(sample);
                        const expanded = Number(sample.id) === expandedBacktestSampleId;
                        return `<tr class="${expanded ? 'is-expanded' : ''}">
                            <td><strong>${escapeBacktestHtml(sample.home_team)} <small>vs</small> ${escapeBacktestHtml(sample.away_team)}</strong><span>${escapeBacktestHtml(sample.competition || '未分类')} · ${escapeBacktestHtml(sample.kickoff || backtestSampleDate(sample))}</span></td>
                            <td>${backtestPredictionMarkup(sample)}</td>
                            <td>${backtestSettlementMarkup(sample)}</td>
                            <td><span class="backtest-status ${status.className}">${status.label}</span><small class="backtest-fixture-state">赛事：${backtestFixtureStatusLabel(sample.fixture_status)}</small></td>
                            <td><button type="button" class="backtest-detail-button ${expanded ? 'active' : ''}" onclick="loadPredictionSampleDetail(${Number(sample.id)})">${expanded ? '收起' : '明细'}</button></td>
                        </tr>${expanded ? `<tr class="backtest-expanded-row"><td colspan="5"><div id="backtest-sample-detail-${Number(sample.id)}" class="backtest-sample-detail"><p class="backtest-loading">正在读取该样本的完整记录...</p></div></td></tr>` : ''}`;
                    }).join('')}
                </tbody>
            </table>
        </div>` : '<p class="backtest-empty">没有符合筛选条件的样本。</p>';
}

function setBacktestFilter(name, value) {
    backtestFilters[name] = value;
    clearPredictionSampleDetail();
    renderBacktestSampleTable();
}
window.setBacktestFilter = setBacktestFilter;

function resetBacktestFilters() {
    backtestFilters = { date: 'all', competition: 'all', status: 'all', query: '' };
    clearPredictionSampleDetail();
    renderBacktestSampleFilters();
    renderBacktestSampleTable();
}
window.resetBacktestFilters = resetBacktestFilters;

function predictionSampleDetailMarkup(sample) {
    const prediction = sample.prediction;
    const result = sample.result;
    const home = sample.home_team || '主队';
    const away = sample.away_team || '客队';
    const predictionRows = prediction ? [
        ['胜平负', formatPredictionSide(prediction.one_x_two, home, away)],
        ['亚洲让球', formatAsianHandicapPrediction(prediction.asian_handicap, home, away)],
        ['大小球', formatOverUnderPrediction(prediction.over_under)],
        ['置信度', ({ high: '高', medium: '中', low: '低' })[prediction.confidence] || '低']
    ] : [['结构化预测', '该报告未返回有效 prediction_record']];
    const settlementRows = result ? [
        ['最终比分', result.score || '--'],
        ['胜平负结算', formatSettlementOutcome(result.one_x_two?.outcome)],
        ['亚洲让球结算', `${formatSettlementOutcome(result.asian_handicap?.outcome)}${result.asian_handicap?.unit_return !== undefined ? ` (${result.asian_handicap.unit_return > 0 ? '+' : ''}${result.asian_handicap.unit_return} 单位)` : ''}`],
        ['大小球结算', `${formatSettlementOutcome(result.over_under?.outcome)}${result.over_under?.unit_return !== undefined ? ` (${result.over_under.unit_return > 0 ? '+' : ''}${result.over_under.unit_return} 单位)` : ''}`],
        ['结算时间', formatBacktestDateTime(sample.settled_at)]
    ] : [['结算状态', prediction ? '等待比赛完赛或赛果同步' : '无可结算结构化预测']];
    const rowMarkup = rows => rows.map(([label, value]) => `<div class="backtest-detail-row"><span>${escapeBacktestHtml(label)}</span><strong>${escapeBacktestHtml(value)}</strong></div>`).join('');

    return `
        <div class="backtest-detail-header">
            <div><span class="backtest-detail-eyebrow">样本 #${sample.id} · ${escapeBacktestHtml(sample.analysis_mode || 'prematch')}</span><h4>${escapeBacktestHtml(home)} <small>vs</small> ${escapeBacktestHtml(away)}</h4></div>
            <button type="button" class="backtest-detail-close" onclick="clearPredictionSampleDetail()" aria-label="关闭明细">×</button>
        </div>
        <div class="backtest-detail-meta">${escapeBacktestHtml(sample.competition || '未分类')} · 赛事 ID ${escapeBacktestHtml(sample.match_id)} · 开赛 ${escapeBacktestHtml(sample.kickoff || '--')} · 分析于 ${escapeBacktestHtml(formatBacktestDateTime(sample.created_at))} · ${escapeBacktestHtml(sample.model_name || '--')}</div>
        <div class="backtest-detail-grid">
            <section><h5>预测记录</h5>${rowMarkup(predictionRows)}</section>
            <section><h5>完赛结果</h5>${rowMarkup(settlementRows)}</section>
        </div>
        <details class="backtest-raw-detail"><summary>赛前输入样本</summary><pre>${sample.context ? escapeBacktestHtml(sample.context) : '此历史样本生成时尚未保存赛前输入。新生成的预测会保留该数据。'}</pre></details>
        <details class="backtest-raw-detail"><summary>最终预测报告</summary><pre>${escapeBacktestHtml(sample.final_report || '无报告内容')}</pre></details>
    `;
}

function clearPredictionSampleDetail() {
    if (expandedBacktestSampleId === null) return;
    expandedBacktestSampleId = null;
    renderBacktestSampleTable();
}
window.clearPredictionSampleDetail = clearPredictionSampleDetail;

function loadPredictionSampleDetail(predictionId) {
    if (expandedBacktestSampleId === predictionId) {
        clearPredictionSampleDetail();
        return;
    }
    expandedBacktestSampleId = predictionId;
    renderBacktestSampleTable();
    fetch(`/api/prediction_backtest/${encodeURIComponent(predictionId)}`)
        .then(res => res.json())
        .then(res => {
            if (expandedBacktestSampleId !== predictionId) return;
            const container = document.getElementById(`backtest-sample-detail-${predictionId}`);
            if (!container) return;
            container.innerHTML = res.success
                ? predictionSampleDetailMarkup(res.data)
                : `<p class="backtest-empty">无法读取样本明细：${escapeBacktestHtml(res.error || '未知错误')}</p>`;
        })
        .catch(() => {
            if (expandedBacktestSampleId !== predictionId) return;
            const container = document.getElementById(`backtest-sample-detail-${predictionId}`);
            if (container) container.innerHTML = '<p class="backtest-empty">无法读取样本明细，请稍后重试。</p>';
        });
}
window.loadPredictionSampleDetail = loadPredictionSampleDetail;

function closePredictionBacktestModal() {
    const modal = document.getElementById('prediction-backtest-modal');
    if (modal) modal.style.display = 'none';
    clearPredictionSampleDetail();
}
window.closePredictionBacktestModal = closePredictionBacktestModal;

function closePredictionBacktestOnBackdrop(event) {
    if (event.target.id === 'prediction-backtest-modal') closePredictionBacktestModal();
}
window.closePredictionBacktestOnBackdrop = closePredictionBacktestOnBackdrop;

function renderPredictionBacktest(data) {
    const container = document.getElementById('prediction-backtest-content');
    if (!container) return;

    const overview = data.overview || {};
    const metrics = data.metrics || {};
    backtestSamples = data.recent || [];
    backtestFilters = { date: 'all', competition: 'all', status: 'all', query: '' };
    expandedBacktestSampleId = null;
    const cards = [
        ['独立样本', `${overview.tracked || 0} / ${overview.window_size || 0}`, '已写入可结算结构化预测'],
        ['已结算', `${overview.settled || 0}`, '具备最终比分的样本'],
        ['待结算', `${overview.pending || 0}`, '比赛尚未结束或未同步结果'],
        ['未追踪', `${overview.untracked || 0}`, '报告未返回有效 prediction_record'],
    ];

    const marketCards = [
        ['胜平负', metrics.one_x_two, '命中率'],
        ['让球', metrics.asian_handicap, '赢盘率'],
        ['大小球', metrics.over_under, '赢盘率'],
    ];
    const marketDetail = (label, metric) => {
        if (!metric || !metric.settled) return '暂无已结算样本';
        if (label === '胜平负') return `命中 ${metric.wins || 0} / ${metric.settled} 场 · 未中 ${metric.losses || 0} 场`;
        return `全赢 ${metric.wins || 0} · 赢半 ${metric.half_wins || 0} · 走水 ${metric.pushes || 0} · 输半 ${metric.half_losses || 0} · 全输 ${metric.losses || 0}`;
    };

    container.innerHTML = `
        <section class="backtest-summary-grid">
            ${cards.map(([label, value, hint]) => `<article class="backtest-stat"><span>${label}</span><strong>${value}</strong><small>${hint}</small></article>`).join('')}
        </section>
        <section class="backtest-section">
            <div class="backtest-section-heading"><h4>市场表现</h4><span>仅统计已结算样本</span></div>
            <div class="backtest-market-grid">
                ${marketCards.map(([label, metric, rateLabel]) => `<article class="backtest-market"><span>${label}</span><strong>${formatBacktestRate(metric && metric.hit_rate)}</strong><small>${rateLabel} · ${marketDetail(label, metric)}</small>${label !== '胜平负' && metric && metric.settled ? '<i>赢半按 0.5 场计入赢盘率；走水不计入</i>' : ''}${metric && metric.settlement_units !== undefined ? `<em>净结算单位 ${metric.settlement_units > 0 ? '+' : ''}${metric.settlement_units}</em>` : ''}</article>`).join('')}
            </div>
        </section>
        <section class="backtest-section">
            <div class="backtest-section-heading"><h4>样本明细</h4><span>点击查看赛前输入、预测及赛果结算</span></div>
            <div id="backtest-sample-filters" class="backtest-sample-filters"></div>
            <div class="backtest-sample-list-heading"><span id="backtest-sample-count"></span></div>
            <div id="backtest-sample-list"></div>
        </section>
        ${overview.tracked ? '' : '<p class="backtest-empty">当前还没有可结算预测。生成首份赛前分析后，系统会自动记录；每场仅保留一份赛前预测，避免重复生成影响样本正确率。</p>'}
    `;
    renderBacktestSampleFilters();
    renderBacktestSampleTable();
}

function openPredictionBacktestModal() {
    const modal = document.getElementById('prediction-backtest-modal');
    const container = document.getElementById('prediction-backtest-content');
    if (!modal || !container) return;

    modal.style.display = 'flex';
    clearPredictionSampleDetail();
    container.innerHTML = '<p class="backtest-loading">正在同步已完场比赛并计算回测...</p>';
    fetch('/api/prediction_backtest')
        .then(res => res.json())
        .then(res => {
            if (res.success) renderPredictionBacktest(res.data);
            else container.innerHTML = `<p class="backtest-empty">回测暂不可用：${res.error || '未知错误'}</p>`;
        })
        .catch(() => {
            container.innerHTML = '<p class="backtest-empty">无法读取回测数据，请稍后重试。</p>';
        });
}
window.openPredictionBacktestModal = openPredictionBacktestModal;

function generateAiReport(matchId, homeTeam, awayTeam) {
    if (!isAnalyzableFixture(selectedMatch)) {
        alert("仅支持未开赛、待定或进行中的赛事分析；已结束、取消或推迟赛事不能生成新报告。");
        return;
    }
    if (!matchDetailsCache[matchId]) {
        alert("本场比赛的独家情报等基础数据尚未加载完成，请稍候数据加载成功后，再手动点击一键生成分析！");
        return;
    }
    
    const runBtn = document.getElementById('btn-run-ai-analysis');
    const skeleton = document.getElementById('ai-generating-status');
    const report = document.getElementById('ai-report-content');
    
    // 初始化三版本状态与展示
    latestReports = ['', '', ''];
    latestStatusList = ['processing', 'processing', 'processing'];
    latestFinalTicket = '';
    activeReportVersion = 0; 
    
    if (skeleton && report) {
        skeleton.style.display = 'none';
        report.style.display = 'block';
    }
    renderReportContent(true);
    
    if (runBtn) {
        runBtn.disabled = true;
        const runText = runBtn.querySelector('span');
        if (runText) runText.textContent = 'AI 研判并发生成中...';
    }
    
    if (aiPollingTimer) {
        clearInterval(aiPollingTimer);
        aiPollingTimer = null;
    }
    
    // 1. 发起后台异步托管生成
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
    .then(res => res.json())
    .then(res => {
        if (!res.success) {
            throw new Error(res.error || "异步托管生成请求失败");
        }
        
        console.log("[AI Background Worker] Managed successfully! Message:", res.message);
        
        // 2. 开启心跳短轮询
        aiPollingTimer = setInterval(() => {
            fetch(`/api/ai_analysis_status?match_id=${matchId}`)
                .then(stRes => stRes.json())
                .then(stRes => {
                    if (stRes.success) {
                        if (stRes.status === 'completed') {
                            clearInterval(aiPollingTimer);
                            aiPollingTimer = null;
                            
                            if (runBtn) {
                                runBtn.disabled = false;
                                const runText = runBtn.querySelector('span');
                                if (runText) runText.textContent = '一键生成 AI 深度研判报告';
                            }
                            latestFinalTicket = stRes.final_ticket || '';
                            renderFullMarkdownReport(stRes.reports);
                        } else if (stRes.status === 'failed') {
                            clearInterval(aiPollingTimer);
                            aiPollingTimer = null;
                            
                            if (report) {
                                report.innerHTML = `<p style="color:var(--color-danger); font-weight:700;">生成出错: ${stRes.error || "大模型连接超时，请重试。"}</p>`;
                            }
                            if (runBtn) {
                                runBtn.disabled = false;
                                const runText = runBtn.querySelector('span');
                                if (runText) runText.textContent = '一键生成 AI 深度研判报告';
                            }
                        } else if (stRes.status === 'processing') {
                            // 正在并发处理中，流式刷新三版本结果
                            latestFinalTicket = stRes.final_ticket || '';
                            renderStreamingMarkdown(stRes.reports, stRes.status_list);
                        }
                    }
                })
                .catch(err => {
                    console.error("[AI Status Polling] Ping failed:", err);
                });
        }, 1500);
    })
    .catch(err => {
        if (report) {
            report.innerHTML = `<p style="color:var(--color-danger); font-weight:700;">发送请求失败: ${err.message || err}</p>`;
        }
        if (runBtn) {
            runBtn.disabled = false;
            const runText = runBtn.querySelector('span');
            if (runText) runText.textContent = '一键生成 AI 深度研判报告';
        }
    });
}
window.generateAiReport = generateAiReport;

function renderReportContent(isStreaming = false) {
    const reportContainer = document.getElementById('ai-report-content');
    if (!reportContainer) return;
    
    const text = latestReports[activeReportVersion] || '';
    const status = latestStatusList[activeReportVersion] || 'idle';
    
    let ticketHtml = '';
    const allEsCompleted = latestStatusList.every(s => s === 'completed');
    
    if (status === 'processing' && allEsCompleted && (!latestFinalTicket || latestFinalTicket.trim() === '')) {
        // 精算师报告生成完成，但CRO风控聚合处于长考中：显示流光骨架屏
        ticketHtml = `
            <div class="cro-ticket-card cro-loading-card">
                <div class="cro-ticket-header">
                    <span class="cro-ticket-title">⚖️ 基金风控中心·终极决策单收敛中</span>
                    <span class="cro-ticket-badge">CRO 联审审计中...</span>
                </div>
                <div class="cro-ticket-body" style="padding: 1.25rem 1rem;">
                    <div class="cro-skeleton-pulse"></div>
                    <div class="cro-skeleton-pulse" style="width: 80%;"></div>
                    <p style="color:var(--text-muted); font-size: 0.85rem; font-style:italic; margin-top: 1rem; display: flex; align-items: center; gap: 6px; margin-bottom: 0;">
                        <span class="pulse-beacon" style="display:inline-block; width:8px; height:8px; background-color: var(--color-primary); box-shadow: 0 0 6px var(--color-primary);"></span>
                        🧠 首席风险官正在提取 3 份研判的共识、评估趋势动能溢价并触发三道反诱盘过滤器审计，请耐心等候最后裁决...
                    </p>
                </div>
            </div>
        `;
    } else if (latestFinalTicket && latestFinalTicket.trim() !== '') {
        // CRO 已开始输出：流式打字机渲染
        let parsedTicket = parseSimpleMarkdown(latestFinalTicket, isStreaming && status === 'processing');
        const structuredPicks = finalTicketPredictionMarkup(latestFinalTicket);
        
        parsedTicket = parsedTicket.replace(/🤝\s*【达成绝对共识的玩法】[^\s\:\：\n\r]*/g, '<span class="cro-tag cro-tag-consensus">🤝 核心共识</span>');
        parsedTicket = parsedTicket.replace(/⚡\s*【冲突重塑与(?:降档收敛|诱盘拦截)报告】[^\s\:\：\n\r]*/g, '<span class="cro-tag cro-tag-melt">⚡ 冲突重塑</span>');
        
        // 判断是否全面熔断：检查执行主单里有没有有效的投资项目（比如是否有“无”或者是否包含全面熔断的字样）
        const hasNoConsensus = latestFinalTicket.includes("投资项目：无") || 
                              latestFinalTicket.includes("核心共识项】\n- 无") ||
                              latestFinalTicket.includes("核心共识项】\n- **投资项目**：无") ||
                              latestFinalTicket.includes("全部玩法触发熔断") ||
                              latestFinalTicket.includes("触发全面熔断");
        
        let warnBanner = '';
        if (hasNoConsensus) {
            warnBanner = `
                <div class="cro-warn-banner">
                    <div class="cro-warn-icon">🚨</div>
                    <div class="cro-warn-text">
                        <strong>风控警告：本场两头受压，模型触发全面熔断，精算师建议放弃本场，请锁定下一场共识赛事。</strong>
                    </div>
                </div>
            `;
        }
        
        ticketHtml = `
            <div class="cro-ticket-card">
                <div class="cro-ticket-header">
                    <span class="cro-ticket-title">⚖️ 基金风控中心·终极决策执行单</span>
                    <span class="cro-ticket-badge">${status === 'processing' ? 'CRO 终审签署中...' : 'CRO 终审签发'}</span>
                </div>
                ${warnBanner}
                <div class="cro-ticket-body">
                    ${structuredPicks}
                    ${parsedTicket}
                </div>
            </div>
        `;
    }
    
    let tabsHtml = '';
    // 只要有任意一个版本有文字，或者正在处理中，就显示版本页签
    if (latestReports.some(r => r && r.trim() !== '') || latestStatusList.some(s => s === 'processing')) {
        tabsHtml = `
            <div class="ai-version-tabs">
                <button class="ai-version-tab ${activeReportVersion === 0 ? 'active' : ''} ${latestStatusList[0] === 'processing' ? 'processing' : ''}" onclick="switchReportVersion(0)">
                    🤖 研判版本 A
                </button>
                <button class="ai-version-tab ${activeReportVersion === 1 ? 'active' : ''} ${latestStatusList[1] === 'processing' ? 'processing' : ''}" onclick="switchReportVersion(1)">
                    🤖 研判版本 B
                </button>
                <button class="ai-version-tab ${activeReportVersion === 2 ? 'active' : ''} ${latestStatusList[2] === 'processing' ? 'processing' : ''}" onclick="switchReportVersion(2)">
                    🤖 研判版本 C
                </button>
            </div>
        `;
    }
    
    let textHtml = '';
    if (text && text.trim() !== '') {
        textHtml = parseSimpleMarkdown(text, isStreaming && status === 'processing');
    } else {
        if (status === 'processing') {
            textHtml = `<p style="color:var(--text-muted); font-style:italic;"><span class="pulse-beacon" style="display:inline-block; width:8px; height:8px; margin-right:6px; background-color: var(--color-primary); box-shadow: 0 0 6px var(--color-primary);"></span>大模型正在全力组织该版本研判逻辑，请稍候...<span class="ai-cursor"></span></p>`;
        } else {
            textHtml = `<p style="color:var(--text-muted); font-style:italic;">该版本的研判报告为空，或生成中发生错误。</p>`;
        }
    }
    
    reportContainer.innerHTML = ticketHtml + tabsHtml + textHtml;
}

function switchReportVersion(verIdx) {
    activeReportVersion = verIdx;
    renderReportContent(true);
}
window.switchReportVersion = switchReportVersion;

function renderFullMarkdownReport(text) {
    if (Array.isArray(text)) {
        latestReports = text;
        latestStatusList = ['completed', 'completed', 'completed'];
    } else {
        latestReports = [text || '', '', ''];
        latestStatusList = ['completed', 'completed', 'completed'];
    }
    renderReportContent(false);
}

function renderStreamingMarkdown(reports, statusList) {
    latestReports = Array.isArray(reports) ? reports : [reports || '', '', ''];
    latestStatusList = Array.isArray(statusList) ? statusList : ['processing', 'processing', 'processing'];
    renderReportContent(true);
}



function parseSimpleMarkdown(md, isStreaming = false) {
    let html = md;
    
    // 替换 > 引用块
    html = html.replace(/^\s*>\s+(.+)$/gm, '<blockquote>$1</blockquote>');
    
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
    
    // 替换数字有序列表
    html = html.replace(/^\s*(\d+)\.\s+(.+)$/gm, '<li>$1. $2</li>');
    
    // Process paragraphs
    let lines = html.split('\n\n');
    html = lines.map(line => {
        let trimmed = line.trim();
        if (!trimmed) return '';
        if (trimmed.startsWith('<h') || trimmed.startsWith('<li') || trimmed.startsWith('<blockquote')) {
            return trimmed;
        }
        if (trimmed === '<think>' || trimmed === '</think>') {
            return trimmed;
        }
        return `<p>${trimmed}</p>`;
    }).join('');
    
    // Single newlines to linebreaks
    html = html.replace(/\n/g, '<br>');
    
    // 2. 处理 <think> 标签的推理过程折叠框替换
    if (html.includes('<think>')) {
        if (html.includes('</think>')) {
            // Model reasoning can quote nested <think> tags from an input report.
            // The stream wrapper closes last, so only that final boundary is valid.
            const startIndex = html.indexOf('<think>');
            const closeIndex = html.lastIndexOf('</think>');
            const before = html.substring(0, startIndex);
            const reasoning = html.substring(startIndex + 7, closeIndex);
            const answer = html.substring(closeIndex + 8);
            html = `${before}<details class="ai-think-details"><summary>🧠 AI 思考推理过程（已完成，点击展开/折叠）</summary>${reasoning}</details>${answer}`;
            if (isStreaming) {
                html += '<span class="ai-cursor"></span>';
            }
        } else {
            // 未闭合（正在流式思考中），折叠框设为 open，且将光标塞在折叠框内末尾
            const index = html.indexOf('<think>');
            const before = html.substring(0, index);
            const inside = html.substring(index + 7); // 跳过 '<think>'
            let summary = "🧠 AI 正在思考推理中...";
            
            if (isStreaming) {
                html = `${before}<details class="ai-think-details" open><summary>${summary}</summary>${inside}<span class="ai-cursor"></span></details>`;
            } else {
                html = `${before}<details class="ai-think-details" open><summary>${summary}</summary>${inside}</details>`;
            }
        }
    } else {
        if (isStreaming) {
            html += '<span class="ai-cursor"></span>';
        }
    }
    
    return html;
}

function renderAiTab(match, details) {
    const isAnalyzable = isAnalyzableFixture(match);
    const isLive = isLiveFixture(match);
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
            <!-- 一键生成研判报告按钮 -->
            <button id="btn-run-ai-analysis" class="btn-ai-run" style="width: 100%; margin-bottom: 0.85rem;" ${isAnalyzable ? '' : 'disabled title="仅支持未开赛或进行中的赛事"'} onclick="generateAiReport('${match.id}', '${encodeURIComponent(match.home_team)}', '${encodeURIComponent(match.away_team)}')">
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polygon points="5 3 19 12 5 21 5 3"></polygon></svg>
                <span>${isLive ? '一键生成 AI 滚球分析（实时盘口）' : (isAnalyzable ? '一键生成 AI 赛前研判报告' : '仅支持未开赛或进行中赛事')}</span>
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

function renderPlayerEvents(player, incidents) {
    if (!incidents || incidents.length === 0) return '';
    let icons = '';
    incidents.forEach(inc => {
        const type = inc.type;
        const time = inc.time;
        if (type === 1) {
            icons += ` <span class="event-icon" title="${time}分钟进球">⚽ ${time}'</span>`;
        } else if (type === 3) {
            icons += ` <span class="event-icon" title="${time}分钟黄牌">🟨 ${time}'</span>`;
        } else if (type === 9) {
            if (inc.in_player_id === player.player_id) {
                icons += ` <span class="event-icon" title="${time}分钟换上" style="color:var(--color-success)">⬆️ ${time}'</span>`;
            } else if (inc.out_player_id === player.player_id) {
                icons += ` <span class="event-icon" title="${time}分钟换下" style="color:var(--text-muted)">⬇️ ${time}'</span>`;
            }
        }
    });
    return icons;
}

function renderSquadTab(match, details) {
    let tabHtml = '';
    
    const hasHomeInjuries = details.injuries && details.injuries.home && (details.injuries.home.injuries.length > 0 || details.injuries.home.suspensions.length > 0);
    const hasAwayInjuries = details.injuries && details.injuries.away && (details.injuries.away.injuries.length > 0 || details.injuries.away.suspensions.length > 0);
    
    // 1. Home injuries
    tabHtml += `<div class="details-card">`;
    tabHtml += `<div class="details-card-title">${match.home_team} 伤停信息</div>`;
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
            <p style="color:var(--text-muted); font-style:italic; margin: 0.5rem 0;">
                此场赛事该队暂无伤停球员，主力阵容齐整。
            </p>
        `;
    }
    tabHtml += `</div>`;
    
    // 2. Away injuries
    tabHtml += `<div class="details-card">`;
    tabHtml += `<div class="details-card-title">${match.away_team} 伤停信息</div>`;
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
            <p style="color:var(--text-muted); font-style:italic; margin: 0.5rem 0;">
                此场赛事该队暂无伤停球员，主力阵容齐整。
            </p>
        `;
    }
    tabHtml += `</div>`;
    
    // 3. Render starting lineup and substitutes if available
    const hasLineup = details.injuries && details.injuries.home && details.injuries.home.startings && details.injuries.home.startings.length > 0;
    if (hasLineup) {
        tabHtml += `
            <div class="details-card">
                <div class="details-card-title" style="display:flex; justify-content:space-between; align-items:center;">
                    <span>⚔️ 首发对决阵容</span>
                    <span style="font-size:0.82rem; font-weight:500; color:var(--text-muted); background:var(--bg-hover); padding:2px 8px; border-radius:12px;">
                        ${details.injuries.home_formation || '未定'} 阵型  VS  ${details.injuries.away_formation || '未定'} 阵型
                    </span>
                </div>
                <div class="lineup-vs-container">
                    <div class="lineup-column home-lineup">
                        <div class="column-team-header" style="text-align:left; font-weight:700; font-size:0.88rem; margin-bottom:0.4rem; color:var(--color-primary);">${match.home_team}</div>
                        ${details.injuries.home.startings.map(p => `
                            <div class="player-row">
                                <span class="player-number">${p.shirt_number}</span>
                                <img src="${p.logo}" class="player-avatar" onerror="this.src='https://cdn.leisu.com/image/player_default.png'">
                                <span class="player-name">${p.name}</span>
                                <span class="player-position">${p.position}</span>
                                <span class="player-events">${renderPlayerEvents(p, p.incidents)}</span>
                            </div>
                        `).join('')}
                    </div>
                    <div class="lineup-column away-lineup">
                        <div class="column-team-header" style="text-align:right; font-weight:700; font-size:0.88rem; margin-bottom:0.4rem; color:var(--color-primary);">${match.away_team}</div>
                        ${details.injuries.away.startings.map(p => `
                            <div class="player-row row-reverse">
                                <span class="player-number">${p.shirt_number}</span>
                                <img src="${p.logo}" class="player-avatar" onerror="this.src='https://cdn.leisu.com/image/player_default.png'">
                                <span class="player-name">${p.name}</span>
                                <span class="player-position">${p.position}</span>
                                <span class="player-events">${renderPlayerEvents(p, p.incidents)}</span>
                            </div>
                        `).join('')}
                    </div>
                </div>
                
                <!-- 主教练对决 -->
                <div class="managers-versus">
                    <div class="manager-item">主教练: <strong>${details.injuries.home_manager || '未知'}</strong></div>
                    <div class="vs-label">VS</div>
                    <div class="manager-item" style="text-align:right;">主教练: <strong>${details.injuries.away_manager || '未知'}</strong></div>
                </div>
            </div>
            
            <div class="details-card">
                <div class="details-card-title">🔁 替补席名单</div>
                <div class="lineup-vs-container">
                    <div class="lineup-column home-lineup">
                        ${details.injuries.home.substitutes.map(p => `
                            <div class="player-row">
                                <span class="player-number">${p.shirt_number}</span>
                                <img src="${p.logo}" class="player-avatar" onerror="this.src='https://cdn.leisu.com/image/player_default.png'">
                                <span class="player-name">${p.name}</span>
                                <span class="player-position">${p.position}</span>
                                <span class="player-events">${renderPlayerEvents(p, p.incidents)}</span>
                            </div>
                        `).join('')}
                    </div>
                    <div class="lineup-column away-lineup">
                        ${details.injuries.away.substitutes.map(p => `
                            <div class="player-row row-reverse">
                                <span class="player-number">${p.shirt_number}</span>
                                <img src="${p.logo}" class="player-avatar" onerror="this.src='https://cdn.leisu.com/image/player_default.png'">
                                <span class="player-name">${p.name}</span>
                                <span class="player-position">${p.position}</span>
                                <span class="player-events">${renderPlayerEvents(p, p.incidents)}</span>
                            </div>
                        `).join('')}
                    </div>
                </div>
            </div>
        `;
    } else {
        tabHtml += `
            <div class="details-card" style="text-align:center; padding: 1.5rem 0;">
                <p style="color:var(--text-muted); font-style:italic;">
                    💡 注：此场赛事官方暂未公布双方首发及替补名单。首发及替补名单通常在开赛前一小时内由赛事官方公布。
                </p>
            </div>
        `;
    }
    
    return tabHtml;
}

function cleanHandicap(line) {
    if (!line) return '';
    let lineStr = String(line).trim();
    if (lineStr.startsWith('+')) {
        return lineStr.substring(1);
    }
    return lineStr;
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
                        <span class="odds-line">${cleanHandicap(h.initial_line || h.line || '0')}</span>
                        <span class="odds-num">${awayInit}</span>
                    </div>
                </td>
                <td>
                    <div class="odds-cell-group">
                        <span class="odds-num ${classHome}">${homeInst}</span>
                        <span class="odds-line">${cleanHandicap(h.instant_line || h.line || '0')}</span>
                        <span class="odds-num ${classAway}">${awayInst}</span>
                    </div>
                </td>
            </tr>
            <tr id="trend-row-${row.cid}-1" class="trend-chart-row" style="display:none;">
                <td colspan="3" class="trend-chart-td">
                    <div class="trend-chart-box">
                        <div class="trend-loading-spinner shimmer-loading">
                            <div class="shimmer-line"></div>
                            <div class="shimmer-line medium"></div>
                            <div class="shimmer-line short"></div>
                            <span style="font-size:0.8rem; color:var(--color-text-secondary); margin-top:5px; display:inline-block;">正在拉取实时变盘走势...</span>
                        </div>
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
                        <div class="trend-loading-spinner shimmer-loading">
                            <div class="shimmer-line"></div>
                            <div class="shimmer-line medium"></div>
                            <div class="shimmer-line short"></div>
                            <span style="font-size:0.8rem; color:var(--color-text-secondary); margin-top:5px; display:inline-block;">正在拉取实时变盘走势...</span>
                        </div>
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
                        <span class="odds-line">${cleanHandicap(ou.initial_line || ou.line || '0')}</span>
                        <span class="odds-num">${underInit}</span>
                    </div>
                </td>
                <td>
                    <div class="odds-cell-group">
                        <span class="odds-num ${classOver}">${overInst}</span>
                        <span class="odds-line">${cleanHandicap(ou.instant_line || ou.line || '0')}</span>
                        <span class="odds-num ${classUnder}">${underInst}</span>
                    </div>
                </td>
            </tr>
            <tr id="trend-row-${row.cid}-3" class="trend-chart-row" style="display:none;">
                <td colspan="3" class="trend-chart-td">
                    <div class="trend-chart-box">
                        <div class="trend-loading-spinner shimmer-loading">
                            <div class="shimmer-line"></div>
                            <div class="shimmer-line medium"></div>
                            <div class="shimmer-line short"></div>
                            <span style="font-size:0.8rem; color:var(--color-text-secondary); margin-top:5px; display:inline-block;">正在拉取实时变盘走势...</span>
                        </div>
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

function showDetailsLoading(match) {
    const container = document.getElementById('details-content');
    if (!container || !match) return;
    
    let scoreDisplay = 'vs';
    if (match.score && (match.score.includes('-') || match.score.includes(':'))) {
        scoreDisplay = match.score.replace('-', ':');
    }
    
    container.innerHTML = `
        <div class="details-vs-header">
            <div class="match-league" style="font-size: 0.8rem; font-weight:700;">${match.competition}</div>
            <div class="vs-row">
                <div class="vs-logo-team">
                    <h2>${match.home_team}</h2>
                    ${match.home_rank ? `<span>${match.home_rank}</span>` : ''}
                </div>
                <div class="vs-circle">${scoreDisplay}</div>
                <div class="vs-logo-team">
                    <h2>${match.away_team}</h2>
                    ${match.away_rank ? `<span>${match.away_rank}</span>` : ''}
                </div>
            </div>
            <div style="font-size:0.8rem; color:var(--text-muted); font-weight:600;">
                开赛时间: ${match.date} ${match.time}
            </div>
        </div>
        <div class="skeleton-content-wrapper" style="padding: 1.25rem; display: flex; flex-direction: column; gap: 1rem;">
            <div class="shimmer-box" style="height: 100px;"></div>
            <div class="shimmer-box" style="height: 250px;"></div>
            <div class="shimmer-box" style="height: 180px;"></div>
        </div>
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
    
    for (let i = startOffsetDays; i <= endOffsetDays; i++) {
        const d = new Date(today);
        d.setDate(today.getDate() + i);
        
        const mm = String(d.getMonth() + 1).padStart(2, '0');
        const dd = String(d.getDate()).padStart(2, '0');
        const w = weekdays[d.getDay()];
        dates.push(`${mm}-${dd} ${w}`);
    }
    
    // 如果用户选择了一个超出当前默认范围的日期，则动态扩充边界以包容它
    if (selectedDate && !dates.includes(selectedDate)) {
        try {
            const parts = selectedDate.split(' ')[0].split('-');
            const mm = parseInt(parts[0]);
            const dd = parseInt(parts[1]);
            
            const today = new Date();
            const currentYear = today.getFullYear();
            let selYear = currentYear;
            const currentMonth = today.getMonth();
            if (currentMonth === 11 && mm === 1) {
                selYear += 1;
            } else if (currentMonth === 0 && mm === 12) {
                selYear -= 1;
            }
            
            const selD = new Date(selYear, mm - 1, dd);
            const diffTime = selD - today;
            const diffDays = Math.ceil(diffTime / (1000 * 60 * 60 * 24));
            
            if (diffDays < startOffsetDays) {
                startOffsetDays = diffDays - 5;
            } else if (diffDays > endOffsetDays) {
                endOffsetDays = diffDays + 5;
            }
            return getDatesRange();
        } catch (e) {
            console.error("解析选择日期出错:", e);
        }
    }
    return dates;
}

// 边缘滑动自动扩充
function loadMoreDates(direction, callback) {
    if (isDateLoading) return;
    isDateLoading = true;
    
    const wrapper = document.getElementById('date-tabs-wrapper');
    const oldScrollWidth = wrapper ? wrapper.scrollWidth : 0;
    
    if (direction === 'left') {
        startOffsetDays -= 10;
    } else if (direction === 'right') {
        endOffsetDays += 10;
    }
    
    renderDateSidebar();
    
    if (direction === 'left' && wrapper) {
        setTimeout(() => {
            const newScrollWidth = wrapper.scrollWidth;
            const diff = newScrollWidth - oldScrollWidth;
            wrapper.scrollLeft = wrapper.scrollLeft + diff;
            isDateLoading = false;
            if (callback) callback();
        }, 0);
    } else {
        setTimeout(() => {
            isDateLoading = false;
            if (callback) callback();
        }, 0);
    }
}

// 物理箭头滚动
function scrollDateTabs(direction) {
    const wrapper = document.getElementById('date-tabs-wrapper');
    if (!wrapper) return;
    
    const scrollAmount = wrapper.clientWidth * 0.7;
    if (direction === 'prev') {
        wrapper.scrollLeft -= scrollAmount;
    } else {
        wrapper.scrollLeft += scrollAmount;
    }
}
window.scrollDateTabs = scrollDateTabs;

// 滑动监听
function handleTabsScroll(el) {
    updateSliderArrowsState();
}
window.handleTabsScroll = handleTabsScroll;

// 更新箭头状态
function updateSliderArrowsState() {
    const wrapper = document.getElementById('date-tabs-wrapper');
    const prevBtn = document.querySelector('.slider-arrow.prev-arrow');
    const nextBtn = document.querySelector('.slider-arrow.next-arrow');
    if (!wrapper || !prevBtn || !nextBtn) return;
    
    prevBtn.disabled = wrapper.scrollLeft <= 2;
    nextBtn.disabled = (wrapper.scrollLeft + wrapper.clientWidth >= wrapper.scrollWidth - 2);
}
window.updateSliderArrowsState = updateSliderArrowsState;

// 定位并居中选中日期
function scrollToSelectedTab(date) {
    setTimeout(() => {
        const tab = document.getElementById(`date-tab-${date}`);
        const wrapper = document.getElementById('date-tabs-wrapper');
        if (tab && wrapper) {
            const wrapperWidth = wrapper.clientWidth;
            const tabLeft = tab.offsetLeft;
            const tabWidth = tab.clientWidth;
            
            const targetScroll = tabLeft - (wrapperWidth / 2) + (tabWidth / 2);
            wrapper.scrollTo({
                left: targetScroll,
                behavior: 'smooth'
            });
        }
    }, 50);
}
window.scrollToSelectedTab = scrollToSelectedTab;

// 格式化日期为 Tab 键标识 MM-DD 星期X
function formatToTabStr(y, m, d) {
    const dObj = new Date(y, m, d);
    const mm = String(dObj.getMonth() + 1).padStart(2, '0');
    const dd = String(dObj.getDate()).padStart(2, '0');
    const weekdays = ["星期日", "星期一", "星期二", "星期三", "星期四", "星期五", "星期六"];
    return `${mm}-${dd} ${weekdays[dObj.getDay()]}`;
}

// 切换日历面板显示/隐藏
function toggleCustomDatePicker(event) {
    if (event) event.stopPropagation();
    const popover = document.getElementById('custom-datepicker-popover');
    if (!popover) return;
    
    const isHidden = popover.style.display === 'none';
    if (isHidden) {
        const aiModal = document.getElementById('ai-config-modal');
        if (aiModal) aiModal.style.display = 'none';
        
        if (selectedDate) {
            try {
                const parts = selectedDate.split(' ')[0].split('-');
                const mm = parseInt(parts[0]);
                const dd = parseInt(parts[1]);
                const today = new Date();
                let year = today.getFullYear();
                const currentMonth = today.getMonth();
                if (currentMonth === 11 && mm === 1) {
                    year += 1;
                } else if (currentMonth === 0 && mm === 12) {
                    year -= 1;
                }
                calendarYear = year;
                calendarMonth = mm - 1;
            } catch (e) {
                const today = new Date();
                calendarYear = today.getFullYear();
                calendarMonth = today.getMonth();
            }
        } else {
            const today = new Date();
            calendarYear = today.getFullYear();
            calendarMonth = today.getMonth();
        }
        renderPopoverCalendar();
        popover.style.display = 'flex';
    } else {
        popover.style.display = 'none';
    }
}
window.toggleCustomDatePicker = toggleCustomDatePicker;

// 切换月份
function changePopoverMonth(delta) {
    calendarMonth += delta;
    if (calendarMonth < 0) {
        calendarMonth = 11;
        calendarYear -= 1;
    } else if (calendarMonth > 11) {
        calendarMonth = 0;
        calendarYear += 1;
    }
    renderPopoverCalendar();
}
window.changePopoverMonth = changePopoverMonth;

// 渲染月份网格
function renderPopoverCalendar() {
    const grid = document.getElementById('popover-calendar-grid');
    const lbl = document.getElementById('cal-current-month-lbl');
    if (!grid || !lbl) return;
    
    lbl.innerText = `${calendarYear}年${String(calendarMonth + 1).padStart(2, '0')}月`;
    grid.innerHTML = '';
    
    const firstDayIndex = new Date(calendarYear, calendarMonth, 1).getDay();
    const totalDays = new Date(calendarYear, calendarMonth + 1, 0).getDate();
    const prevTotalDays = new Date(calendarYear, calendarMonth, 0).getDate();
    
    const weekdays = ["星期日", "星期一", "星期二", "星期三", "星期四", "星期五", "星期六"];
    const today = new Date();
    const todayStr = `${String(today.getMonth() + 1).padStart(2, '0')}-${String(today.getDate()).padStart(2, '0')} ${weekdays[today.getDay()]}`;
    
    // 1. 上月填充
    for (let i = firstDayIndex - 1; i >= 0; i--) {
        const dayNum = prevTotalDays - i;
        const div = document.createElement('div');
        div.className = 'popover-cal-day other-month';
        div.innerText = dayNum;
        
        let pm = calendarMonth - 1;
        let py = calendarYear;
        if (pm < 0) { pm = 11; py -= 1; }
        const dateStr = formatToTabStr(py, pm, dayNum);
        div.onclick = () => selectCalendarTabDate(dateStr);
        grid.appendChild(div);
    }
    
    // 2. 本月天数
    for (let d = 1; d <= totalDays; d++) {
        const div = document.createElement('div');
        div.innerText = d;
        
        const dateStr = formatToTabStr(calendarYear, calendarMonth, d);
        
        let classes = 'popover-cal-day';
        if (dateStr === todayStr) {
            classes += ' today';
        }
        if (dateStr === selectedDate) {
            classes += ' active';
        }
        div.className = classes;
        div.onclick = () => selectCalendarTabDate(dateStr);
        grid.appendChild(div);
    }
    
    // 3. 下月填充
    const renderedCount = firstDayIndex + totalDays;
    const remaining = 42 - renderedCount;
    for (let d = 1; d <= remaining; d++) {
        const div = document.createElement('div');
        div.className = 'popover-cal-day other-month';
        div.innerText = d;
        
        let nm = calendarMonth + 1;
        let ny = calendarYear;
        if (nm > 11) { nm = 0; ny += 1; }
        const dateStr = formatToTabStr(ny, nm, d);
        div.onclick = () => selectCalendarTabDate(dateStr);
        grid.appendChild(div);
    }
}

// 选中日历中某天
function selectCalendarTabDate(dateStr) {
    selectedDate = dateStr;
    const popover = document.getElementById('custom-datepicker-popover');
    if (popover) popover.style.display = 'none';
    
    selectDate(dateStr);
}
window.selectCalendarTabDate = selectCalendarTabDate;

// 快捷选项点击
function selectPopoverQuickDate(type) {
    const today = new Date();
    if (type === 'yesterday') {
        today.setDate(today.getDate() - 1);
    } else if (type === 'tomorrow') {
        today.setDate(today.getDate() + 1);
    }
    
    const weekdays = ["星期日", "星期一", "星期二", "星期三", "星期四", "星期五", "星期六"];
    const mm = String(today.getMonth() + 1).padStart(2, '0');
    const dd = String(today.getDate()).padStart(2, '0');
    const dateStr = `${mm}-${dd} ${weekdays[today.getDay()]}`;
    
    selectCalendarTabDate(dateStr);
}
window.selectPopoverQuickDate = selectPopoverQuickDate;

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
        let lineVal = cleanHandicap(item.line_zh || item.line || '');
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

// Auto-fix HTML layout cache bug dynamically
function autoFixHtmlCacheBug() {
    const oldSidebar = document.querySelector('.sidebar-dates');
    const navbar = document.querySelector('.navbar');
    
    if (oldSidebar) {
        console.warn("[HTML Cache Fix] Detected legacy sidebar-dates aside element due to browser cache. Removing it to prevent grid displacement.");
        oldSidebar.remove();
        
        // 既然 index.html 是旧的，那么 body 里下必然缺少了顶级全宽贯穿日期选择控制栏 .top-date-bar。我们必须动态把它注入并组装起来！
        if (navbar && !document.querySelector('.top-date-bar')) {
            const topDateBar = document.createElement('div');
            topDateBar.className = 'top-date-bar';
            topDateBar.innerHTML = `
                <div class="date-slider-container">
                    <div class="date-tabs-wrapper" id="date-tabs-wrapper">
                        <ul id="date-list" class="date-tabs">
                            <div class="tab-skeleton"></div>
                            <div class="tab-skeleton"></div>
                        </ul>
                    </div>
                </div>
                
                <div class="datepicker-container" id="datepicker-container">
                    <button class="calendar-picker-btn" id="calendar-trigger-btn" onclick="toggleCustomDatePicker(event)" title="点击日历选择任意日期">
                        <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2.5">
                            <rect x="3" y="4" width="18" height="18" rx="2" ry="2"></rect>
                            <line x1="16" y1="2" x2="16" y2="6"></line>
                            <line x1="8" y1="2" x2="8" y2="6"></line>
                            <line x1="3" y1="10" x2="21" y2="10"></line>
                        </svg>
                    </button>
                    
                    <div class="custom-datepicker-popover" id="custom-datepicker-popover" style="display: none;" onclick="event.stopPropagation()">
                        <div class="popover-quick-dates">
                            <button class="btn-popover-quick" onclick="selectPopoverQuickDate('yesterday')">昨天</button>
                            <button class="btn-popover-quick" onclick="selectPopoverQuickDate('today')">今天</button>
                            <button class="btn-popover-quick" onclick="selectPopoverQuickDate('tomorrow')">明天</button>
                        </div>
                        
                        <div class="popover-calendar-header" style="justify-content: center;">
                            <span class="cal-current-month" id="cal-current-month-lbl">2026年07月</span>
                        </div>
                        
                        <div class="popover-calendar-weekdays">
                            <span>日</span><span>一</span><span>二</span><span>三</span><span>四</span><span>五</span><span>六</span>
                        </div>
                        
                        <div class="popover-calendar-grid" id="popover-calendar-grid"></div>
                    </div>
                </div>
            `;
            navbar.insertAdjacentElement('afterend', topDateBar);
            
            // 绑定事件
            const wrapper = topDateBar.querySelector('#date-tabs-wrapper');
            if (wrapper) {
                wrapper.addEventListener('scroll', () => handleTabsScroll(wrapper));
            }
            
            renderDateSidebar();
        }
    }
}

// 全局静默指数队列管理状态
let oddsFetchQueue = [];
let currentOddsFetchMatchId = null;
let oddsFetchIntervalId = null;

function triggerOddsBackgroundFetch(matchId, details) {
    if (!matchId || !details) return;
    
    // 自动获取前端 AI 选项卡按钮并初始化状态，解禁之前残留的按钮以防锁死
    const aiTab = document.querySelector('.detail-tab[onclick*="\'ai\'"]');
    const resetAiTabUI = () => {
        if (aiTab) {
            aiTab.classList.remove('tab-disabled');
            aiTab.removeAttribute('title');
            const fText = aiTab.querySelector('.tab-text-full');
            const sText = aiTab.querySelector('.tab-text-short');
            if (fText) fText.textContent = 'AI 预测分析';
            if (sText) sText.textContent = 'AI';
        }
    };
    resetAiTabUI();
    
    currentOddsFetchMatchId = matchId;
    oddsFetchQueue = [];
    
    // Stop scheduling the previous match. An in-flight request may finish, but
    // it cannot schedule another request once the selected match has changed.
    if (oddsFetchIntervalId) {
        clearTimeout(oddsFetchIntervalId);
        oddsFetchIntervalId = null;
    }
    
    const companyToCid = {
        "36*": 2, "皇*": 3, "立*": 5, "澳*": 7, 
        "威***": 9, "易**": 10, "韦*": 11, "Inter*": 13,
        "12*": 14, "利*": 15, "盈*": 16, "18**": 17
    };
    
    const indexData = details.odds_index || [];
    
    indexData.forEach(row => {
        const cid = row.cid || companyToCid[row.company];
        if (cid) {
            oddsFetchQueue.push({ matchId, cid, type: 1 });
        }
    });
    
    if (oddsFetchQueue.length === 0) return;
    
    // The full instant odds snapshot is already available in match details.
    // This queue warms the heavier handicap-trend history before AI analysis.
    if (aiTab) {
        aiTab.classList.add('tab-disabled');
        aiTab.setAttribute('title', '正在同步重点公司的让球走势，请稍候...');
        const fText = aiTab.querySelector('.tab-text-full');
        const sText = aiTab.querySelector('.tab-text-short');
        if (fText) fText.textContent = 'AI 预测分析 (同步走势中...)';
        if (sText) sText.textContent = 'AI (同步中)';
    }
    
    console.log(`[Background Fetcher] Queue initialized with ${oddsFetchQueue.length} companies to cache.`);

    const fetchNextTrend = () => {
        if (matchId !== currentOddsFetchMatchId) return;
        if (oddsFetchQueue.length === 0) {
            oddsFetchIntervalId = null;
            resetAiTabUI();
            console.log(`[Background Fetcher] All odds trends successfully cached for match ${matchId}!`);
            return;
        }

        const task = oddsFetchQueue.shift();
        console.log(`[Background Fetcher] Fetching trend for match ${task.matchId}, company ${task.cid}...`);
        fetch(`/api/match_odds_detail?match_id=${task.matchId}&cid=${task.cid}&type=${task.type}`)
            .then(res => res.json())
            .then(res => {
                if (res.success) console.log(`[Background Fetcher] Cached trend for company ${task.cid}.`);
                else console.warn(`[Background Fetcher] Skip/Fail for company ${task.cid}:`, res.error);
            })
            .catch(err => console.error(`[Background Fetcher] Error:`, err))
            .finally(() => {
                if (matchId === currentOddsFetchMatchId) {
                    oddsFetchIntervalId = setTimeout(fetchNextTrend, 350);
                }
            });
    };

    fetchNextTrend();
}

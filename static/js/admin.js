/**
 * Gas Station Game - Admin Logic (admin.js)
 * Features: Metacognition Toggle, Rank Ties, Reaction Time, Modal Fixes, Delete Match, Chat Scope Badges, Global Controls.
 * NEW Features: Student Status Tracking, Issue Reports Rendering, HKT Localization.
 */

const socket = io();
let currentInspectId = null;
let isCoachActive = false; // Track Coach State

// ==========================================
// 1. MODAL FUNCTIONS
// ==========================================

function openBotModal() {
    const modal = document.getElementById('bot-modal');
    if (modal) {
        modal.style.display = 'block';
    } else {
        console.error("❌ Error: 'bot-modal' ID not found in HTML");
    }
}

function closeBotModal() {
    const modal = document.getElementById('bot-modal');
    if (modal) modal.style.display = 'none';
}

function closeModal() {
    document.getElementById('details-modal').style.display = 'none';
    currentInspectId = null;
    isCoachActive = false; // Reset Coach state on close
}

// ==========================================
// 2. INITIALIZATION & NAVIGATION
// ==========================================

window.onload = () => {
    generateScheduleUI();
    console.log("✅ Admin Logic Loaded. Session:", SESSION_CODE);
};

socket.on('connect', () => {
    socket.emit('join_session', { session_code: SESSION_CODE, role: 'admin' });
});

function switchView(viewName) {
    // Hide all
    document.querySelectorAll('.view-section').forEach(el => el.classList.remove('active'));
    document.querySelectorAll('.tab-btn').forEach(el => el.classList.remove('active'));

    // Show target
    const target = document.getElementById(`view-${viewName}`);
    if(target) target.classList.add('active');

    // Activate Tab [MODIFIED: Added 'status' to the index map]
    const map = { 'settings':0, 'lobby':1, 'status':2, 'home':3, 'results':4 };
    const btns = document.querySelectorAll('.tab-btn');
    if(map[viewName] !== undefined && btns[map[viewName]]) {
        btns[map[viewName]].classList.add('active');
        btns[map[viewName]].disabled = false;
        btns[map[viewName]].style.opacity = '1';
    }
}

function openLobby() {
    document.getElementById('invite-link-box').style.display = 'block';

    // Enable Lobby, Status, and Home Tabs
    document.getElementById('tab-lobby').disabled = false;
    document.getElementById('tab-lobby').style.opacity = '1';

    document.getElementById('tab-status').disabled = false;
    document.getElementById('tab-status').style.opacity = '1';

    document.getElementById('tab-home').disabled = false;
    document.getElementById('tab-home').style.opacity = '1';

    document.getElementById('btn-open-lobby').style.display = 'none';
    document.getElementById('btn-start-game').style.display = 'block';

    switchView('lobby');
    alert("✅ Lobby is open! Students can join now.");
}

// ==========================================
// 3. SETTINGS & START GAME
// ==========================================

function generateScheduleUI() {
    const count = parseInt(document.getElementById('total-rounds').value) || 5;
    const tbody = document.getElementById('schedule-body');
    if(!tbody) return;
    tbody.innerHTML = "";

    for (let i = 1; i <= count; i++) {
        const tr = document.createElement('tr');
        tr.className = "round-row";
        tr.dataset.round = i;

        tr.innerHTML = `
            <td style="text-align:center; font-weight:700; color:#64748b;">${i}</td>
            <td><input type="number" class="form-input cfg-dur" value="45" style="width:100%; text-align:center;"></td>
            <td style="text-align:center;"><input type="checkbox" class="cfg-blind" style="width:16px; height:16px;"></td>
            <td style="text-align:center;"><input type="checkbox" class="cfg-silent" style="width:16px; height:16px;"></td>
            <td>
                <select class="form-input cfg-spy" style="font-size:0.8rem; width:100%; text-align:center;">
                    <option value="none">-</option>
                    <option value="1line">1 Line</option>
                    <option value="2lines">2 Lines</option>
                    <option value="all">All Chat</option>
                    <option value="decision">Decision</option>
                </select>
            </td>
            <td style="text-align:center;"><input type="checkbox" class="cfg-modify" style="width:16px; height:16px;"></td>
            <td>
                <select class="form-input cfg-modify-penalty" style="font-size:0.75rem; width:100%;">
                    <option value="50">$50</option>
                    <option value="100">$100</option>
                    <option value="200">$200</option>
                </select>
            </td>
            <td style="text-align:center;"><input type="number" class="form-input cfg-skew" value="1.0" step="0.1" style="width:100%; text-align:center;"></td>
            <td><input type="text" class="form-input cfg-msg" placeholder="Optional msg..." style="width:100%;"></td>
            <td style="text-align:center;"><input type="checkbox" class="cfg-shuffle" style="width:16px; height:16px;"></td>
        `;
        tbody.appendChild(tr);
    }
}

function getDetailedSchedule() {
    const rows = document.querySelectorAll('.round-row');
    let schedule = [];
    rows.forEach(row => {
        schedule.push({
            round_num: parseInt(row.dataset.round),
            duration: parseInt(row.querySelector('.cfg-dur').value) || 45,
            blind: row.querySelector('.cfg-blind').checked,
            silent: row.querySelector('.cfg-silent').checked,
            spy: row.querySelector('.cfg-spy').value,
            modify_allowed: row.querySelector('.cfg-modify').checked,
            modify_penalty: parseInt(row.querySelector('.cfg-modify-penalty').value) || 0,
            skew: parseFloat(row.querySelector('.cfg-skew').value) || 1.0,
            message: row.querySelector('.cfg-msg').value.trim(),
            shuffle: row.querySelector('.cfg-shuffle').checked
        });
    });
    return schedule;
}

function startGame() {
    const schedule = getDetailedSchedule();
    if(schedule.length === 0) return alert("⚠️ Please Reset Table first!");

    // 获取时间模式 (Async / Sync / Mixed)
    const syncModeValue = document.getElementById('sync-mode').value;

    if(confirm(`🚀 Start Game?\nRounds: ${schedule.length}\nMode: ${syncModeValue.toUpperCase()}`)) {
        socket.emit('admin_start_game', {
            session_code: SESSION_CODE,
            schedule: schedule,
            sync_mode: syncModeValue,
            timeout_mode: document.getElementById('timeout-mode').value,
            sudden_death: document.getElementById('sudden-death-mode').value === 'true',
            total_rounds: schedule.length
        });

        // 跳转到直播看板
        switchView('home');
    }
}

// Metacognition Toggle Logic
function toggleCoach() {
    if(!currentInspectId) return;

    // Toggle State
    isCoachActive = !isCoachActive;

    // Update Button UI
    const modal = document.getElementById('details-modal');
    const buttons = modal.querySelectorAll('button');
    let targetBtn = null;
    buttons.forEach(b => { if(b.innerText.includes('Start') || b.innerText.includes('Stop')) targetBtn = b; });

    if(targetBtn) {
        if (isCoachActive) {
            targetBtn.innerHTML = "⏹ Stop Reflection";
            targetBtn.classList.remove('btn-success');
            targetBtn.classList.add('btn-danger'); // Red for stop
        } else {
            targetBtn.innerHTML = "✨ Start Reflection";
            targetBtn.classList.remove('btn-danger');
            targetBtn.classList.add('btn-success'); // Green for start
        }
    }

    // Send to Backend
    socket.emit('admin_toggle_metacognition', {
        session_code: SESSION_CODE,
        match_id: currentInspectId,
        enable: isCoachActive
    });
}

function triggerSuddenDeath() {
    if(confirm("⚠️ Trigger +2 Rounds immediately?")) {
        socket.emit('admin_sudden_death', { session_code: SESSION_CODE });
    }
}

// ==========================================
// 4. LOBBY & TEAM PAIRING
// ==========================================

socket.on('admin_lobby_update', (data) => {
    document.getElementById('lobby-count').innerText = data.lobby.length;
    const list = document.getElementById('lobby-list');

    // Added the kick button (✖) next to player names
    if (data.lobby.length) {
        list.innerHTML = data.lobby.map(p => `
            <div class="player-chip">
                ${p.name}
                <button onclick="kickLobbyPlayer('${p.sid}')" style="background:none; border:none; color:#ef4444; font-weight:bold; cursor:pointer; margin-left:5px;" title="Kick Player">✖</button>
            </div>
        `).join('');
    } else {
        list.innerHTML = '<div style="padding:20px; color:#999; width:100%; text-align:center;">Waiting...</div>';
    }
});

// Global Control Functions
function kickLobbyPlayer(sid) {
    if(confirm("Kick this player from the lobby?")) {
        socket.emit('admin_kick_lobby', { session_code: SESSION_CODE, target_sid: sid });
    }
}

let isGlobalPaused = false;
function toggleGlobalPause() {
    isGlobalPaused = !isGlobalPaused;
    const btn = document.getElementById('btn-global-pause');
    if (isGlobalPaused) {
        btn.innerHTML = "▶ Resume";
        btn.className = "btn btn-success";
    } else {
        btn.innerHTML = "⏸ Pause";
        btn.className = "btn btn-warning";
    }
    socket.emit('admin_toggle_global_pause', { session_code: SESSION_CODE, paused: isGlobalPaused });
}

function deleteEntireSession() {
    if(confirm("🚨 WARNING: This will permanently DELETE the entire session, kick out all players, and erase all unsaved data!\n\nAre you absolutely sure?")) {
        socket.emit('admin_delete_session', { session_code: SESSION_CODE });
        window.location.href = '/admin'; // Return to Admin Dashboard
    }
}


function createTeams() {
    const size = document.getElementById('team-size').value;
    const count = parseInt(document.getElementById('lobby-count').innerText) || 0;

    if (count < 2) {
        if(!confirm("⚠️ Not enough players (need at least 2). Pair anyway?")) return;
    }

    socket.emit('admin_create_teams', { session_code: SESSION_CODE, team_size: size });

    setTimeout(() => {
        switchView('home');
    }, 300);
}

function submitBots() {
    socket.emit('admin_add_bots', {
        session_code: SESSION_CODE,
        strategies: {
            tft: document.getElementById('bot-tft').value,
            grim: document.getElementById('bot-grim').value,
            random: document.getElementById('bot-rnd').value,
            custom: { count: document.getElementById('bot-custom-qty').value, prompt: document.getElementById('bot-custom-prompt').value }
        }
    });
    closeBotModal();
}

// ==========================================
// 5. LIVE BOARD & NEW STATUS UPDATES
// ==========================================

socket.on('admin_match_list_update', (data) => {

    // 1. Matches rendering
    const container = document.getElementById('matches-container');
    if (container) {
        const activeCount = data.matches.filter(m => !m.is_finished).length;
        const counter = document.getElementById('active-match-count');
        if (counter) counter.innerText = activeCount + " Active";

        container.innerHTML = "";

        if (data.matches.length === 0) {
            container.innerHTML = '<div style="padding:40px; text-align:center; color:#999; width:100%;">No matches created yet. Go to Lobby > Create Teams.</div>';
        } else {
            let htmlBuffer = "";
            data.matches.sort((a,b) => a.id.localeCompare(b.id)).forEach(m => {
                htmlBuffer += createMatchCard(m);
            });
            container.innerHTML = htmlBuffer;
        }
    }

    if(data.avg_reaction) {
        const timeStat = document.getElementById('stat-time');
        if(timeStat) timeStat.innerText = data.avg_reaction;
    }

    if(data.scatter_data) {
        updateResultsBoard(data.scatter_data);
    }

    // [NEW] 2. Student Status Update
    if(data.student_status) {
        updateStudentStatusTable(data.student_status);
    }

    // [NEW] 3. Issues Update
    if(data.issues) {
        updateIssuesTable(data.issues);
    }
});

// [NEW] Function to render the Student Status table
function updateStudentStatusTable(students) {
    const tbody = document.getElementById('student-status-body');
    if(!tbody) return;

    if (!students || students.length === 0) {
        tbody.innerHTML = '<tr><td colspan="5" style="text-align:center; padding:30px;">No students connected yet.</td></tr>';
        return;
    }

    let html = "";
    students.forEach(s => {
        const connBadge = s.is_online
            ? `<span class="status-badge status-online">🟢 Online</span>`
            : `<span class="status-badge status-offline">🔴 Offline</span>`;

        html += `
        <tr>
            <td style="color:#64748b; font-family:monospace;">${s.student_id}</td>
            <td style="font-weight:bold;">${s.name}</td>
            <td><span style="background:#f1f5f9; padding:2px 6px; border-radius:4px; font-size:0.85rem;">${s.team}</span></td>
            <td>${connBadge}</td>
            <td>${s.state}</td>
        </tr>`;
    });
    tbody.innerHTML = html;
}

// [NEW] Function to render the Issue Reports
function updateIssuesTable(issues) {
    const tbody = document.getElementById('issue-reports-body');
    if(!tbody) return;

    if (!issues || issues.length === 0) {
        tbody.innerHTML = '<tr><td colspan="3" style="text-align:center; padding:20px; color:#64748b;">No issues reported.</td></tr>';
        return;
    }

    // Reverse to show newest first
    const sortedIssues = [...issues].reverse();

    let html = "";
    sortedIssues.forEach(iss => {
        html += `
        <tr style="background:#fff5f5; border-bottom:1px solid #fee2e2;">
            <td style="color:#ef4444; font-weight:600; font-family:monospace;">${iss.time}</td>
            <td style="font-weight:bold;">${iss.player}</td>
            <td style="color:#991b1b; font-weight:500;">${iss.text}</td>
        </tr>`;
    });
    tbody.innerHTML = html;
}

function createMatchCard(m) {
    let rows = '';
    const maxRounds = m.total_rounds || 5;

    for(let i=1; i<=maxRounds; i++) {
        const h = m.history ? m.history.find(x => x.round === i) : null;
        if(h) {
            rows += `<tr>
                <td style="color:#94a3b8;">${i}</td>
                <td style="color:${h.move_a==='keep'?'#10b981':'#ef4444'}; font-weight:bold;">${h.move_a.toUpperCase()}</td>
                <td>HK$${h.score_a}</td>
                <td style="color:${h.move_b==='keep'?'#10b981':'#ef4444'}; font-weight:bold;">${h.move_b.toUpperCase()}</td>
                <td>HK$${h.score_b}</td>
            </tr>`;
        } else {
            rows += `<tr><td style="color:#e2e8f0;">${i}</td><td>-</td><td></td><td>-</td><td></td></tr>`;
        }
    }

    let statusBadge = `<span style="color:#f59e0b">Ready</span>`;
    if(m.is_finished) statusBadge = `<span style="color:#333; font-weight:bold;">🏁 Done</span>`;
    else if(m.status === 'playing') statusBadge = `<span style="color:#10b981; font-weight:bold;">▶ Round ${m.round}</span>`;
    else if(m.status === 'break') statusBadge = `<span style="color:#3b82f6;">⏸ Break</span>`;
    else if(m.status === 'waiting_sync') statusBadge = `<span style="color:#f97316;">⏳ Waiting...</span>`;

    return `
    <div class="match-card">
        <div style="display:flex; justify-content:space-between; align-items:center; padding:10px 15px; background:#f8fafc; border-bottom:1px solid #e2e8f0;">
            <div style="font-size:0.85rem;">
                <span style="background:#3b82f6; color:white; padding:2px 6px; border-radius:4px;">${m.team_a_name}</span> vs 
                <span style="background:#ef4444; color:white; padding:2px 6px; border-radius:4px;">${m.team_b_name}</span>
            </div>
            <div style="display:flex; gap:10px; align-items:center;">
                <span style="font-size:0.75rem;">${statusBadge}</span>
                <button onclick="inspectMatch('${m.id}')" style="border:none; background:none; cursor:pointer; font-size:1.1rem; opacity:0.7;" title="Inspect">👁️</button>
                <button onclick="deleteMatch('${m.id}')" style="border:none; background:none; cursor:pointer; font-size:1.1rem; opacity:0.7; color:#ef4444;" title="Delete Match">🗑️</button>
            </div>
        </div>
        <div style="padding:0;">
            <table class="data-table" style="text-align:center; font-size:0.8rem;">
                <thead style="background:#fff;">
                    <tr><th style="padding:5px;">#</th><th style="padding:5px;">Blue</th><th style="padding:5px;">$</th><th style="padding:5px;">Red</th><th style="padding:5px;">$</th></tr>
                </thead>
                <tbody>${rows}</tbody>
            </table>
        </div>
    </div>`;
}

function updateResultsBoard(players) {
    let totalCoop = 0;
    players.forEach(p => totalCoop += p.keep_rate || 0);
    const avgCoop = players.length > 0 ? Math.round(totalCoop / players.length) : 0;

    const totalProfit = players.reduce((acc, p) => acc + (p.total_profit || 0), 0);
    const avgProfit = players.length > 0 ? Math.round(totalProfit / players.length) : 0;

    document.getElementById('stat-profit').innerText = "HK$" + avgProfit;
    document.getElementById('stat-coop').innerText = avgCoop + "%";

    const tbody = document.getElementById('leaderboard-body');
    if(!tbody) return;

    if (!players || players.length === 0) {
        tbody.innerHTML = '<tr><td colspan="6" style="text-align:center; padding:30px;">No data yet.</td></tr>';
        return;
    }

    players.sort((a, b) => b.total_profit - a.total_profit);

    let html = "";
    let currentRank = 1;

    for (let i = 0; i < players.length; i++) {
        const p = players[i];

        if (i > 0 && p.total_profit === players[i-1].total_profit) {
            // Rank remains the same
        } else {
            currentRank = i + 1;
        }

        let rowStyle = "";
        if(currentRank === 1) rowStyle = "background:#fffbe6; font-weight:bold;";
        else if(currentRank === 2) rowStyle = "background:#f8fafc;";

        html += `
        <tr style="${rowStyle}">
            <td>${currentRank}</td>
            <td>${p.name} ${p.is_bot ? '🤖' : ''}</td>
            <td><span style="color:${p.team_color === 'blue' ? '#3b82f6' : '#ef4444'}">●</span> ${p.team_color ? p.team_color.toUpperCase() : 'N/A'}</td>
            <td style="text-align:right; font-family:monospace;">HK$${p.total_profit || 0}</td>
            <td style="text-align:right;">${p.keep_rate || 0}%</td>
            <td style="text-align:right;">${Math.round((p.char_count || 0) / 10)}</td> 
        </tr>`;
    }

    tbody.innerHTML = html;
}

// ==========================================
// 6. INSPECTOR & AI
// ==========================================

function inspectMatch(id) {
    currentInspectId = id;
    document.getElementById('details-modal').style.display = 'block';

    // Reset toggle UI to default when opening inspector
    isCoachActive = false;
    const modal = document.getElementById('details-modal');
    const buttons = modal.querySelectorAll('button');
    buttons.forEach(btn => {
        if(btn.innerText.includes('Stop') || btn.innerText.includes('Start')) {
            btn.innerHTML = "✨ Start Reflection";
            btn.classList.remove('btn-danger');
            btn.classList.add('btn-success');
        }
    });

    socket.emit('admin_request_details', { session_code: SESSION_CODE, match_id: id });
}

function sendAdminChat() {
    const txt = document.getElementById('admin-chat-input').value;
    if(currentInspectId && txt) {
        socket.emit('admin_send_chat', { session_code: SESSION_CODE, match_id: currentInspectId, message: txt });
        document.getElementById('admin-chat-input').value = "";
    }
}

function analyzeMatchAI() {
    if(!currentInspectId) return;
    document.getElementById('ai-loading').style.display = 'block';
    document.getElementById('ai-result').innerHTML = "";
    socket.emit('admin_analyze_match', { session_code: SESSION_CODE, match_id: currentInspectId });
}

socket.on('admin_analysis_result', (data) => {
    if(data.match_id !== currentInspectId) return;
    document.getElementById('ai-loading').style.display = 'none';
    document.getElementById('ai-result').innerHTML = data.analysis;
});

socket.on('admin_receive_details', (data) => {
    if(!data || data.id !== currentInspectId) return;

    // Stats
    const statsDiv = document.getElementById('inspector-stats');
    if(statsDiv) {
        const reactA = data.team_a_avg_time ? (data.team_a_avg_time + "s") : "N/A";
        const reactB = data.team_b_avg_time ? (data.team_b_avg_time + "s") : "N/A";
        statsDiv.innerHTML = `
            <strong>${data.team_a_name}:</strong> HK$${data.score_a} (Avg: ${reactA})<br>
            <strong>${data.team_b_name}:</strong> HK$${data.score_b} (Avg: ${reactB})
        `;
    }

    // History
    const histBody = document.getElementById('modal-history');
    if(histBody) {
        histBody.innerHTML = data.history.map(h => `
            <tr>
                <td>${h.round}</td>
                <td style="color:${h.move_a==='keep'?'#10b981':'#ef4444'}; font-weight:bold;">${h.move_a.toUpperCase()}</td>
                <td style="color:${h.move_b==='keep'?'#10b981':'#ef4444'}; font-weight:bold;">${h.move_b.toUpperCase()}</td>
            </tr>
        `).join('');
    }

    // Chat
    const chatBox = document.getElementById('modal-chat');
    if(chatBox) {
        chatBox.innerHTML = "";
        data.chat_logs.forEach(m => appendChatMsg(chatBox, m));
        chatBox.scrollTop = chatBox.scrollHeight;
    }

    // Extract Latest Coach Message
    const lastCoachMsg = data.chat_logs.slice().reverse().find(m => m.sender === 'AI Coach' || m.is_coach);
    const aiResultBox = document.getElementById('ai-result');
    if (aiResultBox) {
        if (lastCoachMsg) {
            aiResultBox.innerHTML = `
                <div style="border-left: 3px solid #f59e0b; padding-left: 10px; margin-bottom: 5px;">
                    <strong style="color: #b45309;">🎓 Latest Coach Insight:</strong>
                </div>
                <div style="font-size: 0.9rem; line-height: 1.5; color: #334155;">
                    ${lastCoachMsg.text}
                </div>
            `;
        } else {
            aiResultBox.innerHTML = `<span style="color:#94a3b8;">No analysis yet. Click 'Analyze' or 'Start Reflection' below.</span>`;
        }
    }
});

socket.on('receive_message', (data) => {
    if(currentInspectId) {
        const chatBox = document.getElementById('modal-chat');
        if(chatBox) {
            appendChatMsg(chatBox, data);
            chatBox.scrollTop = chatBox.scrollHeight;
        }
    }
});

function appendChatMsg(box, m) {
    let bg = '#fff'; let align = 'flex-start'; let border = '#e2e8f0';
    if(m.sender.includes('Blue') || m.sender.includes('Team A')) { bg='#eff6ff'; align='flex-end'; border='#dbeafe'; }
    if(m.sender.includes('Red') || m.sender.includes('Team B')) { bg='#fef2f2'; align='flex-start'; border='#fecaca'; }
    if(m.sender === 'ADMIN') { bg='#fef3c7'; align='center'; border='#fcd34d'; }
    if(m.sender === 'SYSTEM') { bg='#f8fafc'; align='center'; border='#eee'; }
    if(m.sender.includes('Spy')) { bg='#faf5ff'; align='center'; border='#d8b4fe'; }
    if(m.sender === 'AI Coach' || m.is_coach) { bg='#f0fdf4'; align='center'; border='#bbf7d0'; }

    const div = document.createElement('div');
    div.style.cssText = `max-width:90%; padding:6px 10px; border-radius:8px; margin-bottom:5px; font-size:0.85rem; background:${bg}; align-self:${align}; border:1px solid ${border};`;

    // Extract Scope Badges
    let scopeBadge = '';
    if (m.scope === 'team') {
        scopeBadge = '<span style="background:#e2e8f0; color:#475569; padding:2px 4px; border-radius:4px; font-size:0.65rem; margin-right:5px; vertical-align:top;">🔒 TEAM</span>';
    } else if (m.scope === 'all' && m.sender !== 'ADMIN' && m.sender !== 'SYSTEM' && m.sender !== 'AI Coach' && !m.is_coach) {
        scopeBadge = '<span style="background:#dbeafe; color:#1e40af; padding:2px 4px; border-radius:4px; font-size:0.65rem; margin-right:5px; vertical-align:top;">📢 PUBLIC</span>';
    }

    if (m.sender === 'AI Coach' || m.is_coach) {
        div.innerHTML = `<div style="font-weight:bold; color:#166534; margin-bottom:4px;">🎓 AI Coach:</div><div style="line-height:1.5; text-align:left;">${m.text}</div>`;
    } else if (m.sender === 'SYSTEM' || m.sender === 'ADMIN') {
        div.innerHTML = `<strong>${m.sender}:</strong> ${m.text}`;
    } else {
        // Normal player message with scope badge
        div.innerHTML = `<div style="margin-bottom:2px;">${scopeBadge}<strong>${m.sender}</strong></div> <div style="line-height:1.4;">${m.text}</div>`;
    }

    box.appendChild(div);
}

window.onclick = function(event) {
    const dModal = document.getElementById('details-modal');
    const bModal = document.getElementById('bot-modal');
    if (event.target == dModal) closeModal();
    if (event.target == bModal) closeBotModal();
}

// ==========================================
// 7. DELETE MATCH LOGIC
// ==========================================
function deleteMatch(matchId) {
    if (confirm("⚠️ Are you sure you want to DELETE this negotiation?\nPlayers in this group will be forcefully disconnected. (Yes / No)")) {
        socket.emit('admin_delete_match', { session_code: SESSION_CODE, match_id: matchId });
    }
}
/**
 * Milk Tea Shop Game - Player Logic (game.js)
 * Features: Gameplay, Chat, AI Coach, Results UI, Dynamic Skew, Channel Isolation, Auto-Reconnect.
 */

const socket = io();
let currentChannel = 'team'; // Default chat scope
let resultChart = null; // Chart instance

// --- 1. INITIALIZATION & CONNECTION DEBUGGING ---
window.onload = () => {
    console.log("✅ Player Logic Loaded. Session:", SESSION_CODE);

    // 1. Prioritize reading parameters from the URL or localStorage for auto-login
    let savedId = URL_AUTO_ID || localStorage.getItem('milk_tea_id_' + SESSION_CODE);
    let savedName = URL_AUTO_NAME || localStorage.getItem('milk_tea_name_' + SESSION_CODE);

    if (savedId && savedName) {
        document.getElementById('student_id').value = savedId;
        document.getElementById('username').value = savedName;
        // Delay auto-login slightly to ensure Socket connection is established
        setTimeout(() => {
            console.log("🔄 Auto-reconnecting...");
            login();
        }, 500);
    }
};

socket.on('connect', () => {
    console.log("✅ Socket Connected! ID:", socket.id);
});

socket.on('connect_error', (err) => {
    console.error("❌ Connection Failed:", err);
    alert("Unable to connect to the server. Please check your network or refresh the page.");
    resetLoginButton();
});

// --- 2. LOGIN & LOBBY ---
function login() {
    const idInput = document.getElementById('student_id');
    const nameInput = document.getElementById('username');
    if (!idInput || !nameInput) return;

    const studentId = idInput.value.trim();
    const name = nameInput.value.trim();

    if (!studentId) { alert("Please enter your Student ID!"); return; }
    if (!name) { alert("Please enter your Name!"); return; }

    // Save to local storage for quick reconnection if the page is closed
    localStorage.setItem('milk_tea_id_' + SESSION_CODE, studentId);
    localStorage.setItem('milk_tea_name_' + SESSION_CODE, name);

    const btn = document.querySelector('#login-screen button');
    if (btn) {
        btn.disabled = true;
        btn.innerText = "Connecting...";
    }

    if (!SESSION_CODE || SESSION_CODE === '{{ session_code }}') {
        alert("Session Code Error. Please reload.");
        resetLoginButton();
        return;
    }

    // Send student_id to the server
    socket.emit('login', { session_code: SESSION_CODE, name: name, student_id: studentId });
}

function resetLoginButton() {
    const btn = document.querySelector('#login-screen button');
    if(btn) {
        btn.disabled = false;
        btn.innerText = "Join Game / 进入对局";
    }
}

socket.on('login_success', (data) => {
    document.getElementById('login-screen').style.display = 'none';

    // [NEW] Dynamically update the URL in the browser address bar
    const studentId = document.getElementById('student_id').value.trim();
    const playerName = document.getElementById('username').value.trim();

    if (studentId) {
        // Pushes the new state to the browser history, changing the URL to /game/CODE/ID/NAME
        const newUrl = `/game/${SESSION_CODE}/${studentId}/${encodeURIComponent(playerName)}`;
        window.history.pushState({ path: newUrl }, '', newUrl);
    }

    if (data.reconnected) {
        document.getElementById('game-ui').style.display = 'block';
    } else {
        document.getElementById('lobby-screen').style.display = 'block';
    }
});

socket.on('error_msg', (data) => {
    alert("⚠️ " + data.msg);
    resetLoginButton();
});

// --- [NEW] ADMIN FORCE DELETE LISTENER ---
// Listens for the admin deleting the match/session or kicking the player
socket.on('match_deleted', (data) => {
    alert("🛑 " + data.msg);
    // Clear local storage so they don't auto-reconnect if kicked
    localStorage.removeItem('milk_tea_id_' + SESSION_CODE);
    localStorage.removeItem('milk_tea_name_' + SESSION_CODE);
    window.location.href = '/';
});

// --- 3. GAME START ---
socket.on('game_start_setup', (data) => {
    document.getElementById('lobby-screen').style.display = 'none';
    document.getElementById('game-ui').style.display = 'block';

    const teamTitle = document.getElementById('team-name');
    if(teamTitle) {
        teamTitle.innerText = data.team_name;
        teamTitle.className = data.is_blue ? 'text-blue' : 'text-red';
    }

    const memberList = document.getElementById('teammates-list');
    if(memberList) memberList.innerText = "Members: " + data.teammates.join(', ');

    const chatWin = document.getElementById('chat-window');
    if(chatWin) chatWin.innerHTML = '<div class="message msg-system" data-scope="system"><div class="msg-text">Channel Established.</div></div>';

    const chatTabs = document.querySelector('.chat-tabs');
    const msgIn = document.getElementById('msgInput');

    if (data.teammates.length === 1) {
        currentChannel = 'all';
        if(chatTabs) chatTabs.style.display = 'none';
        if(msgIn) msgIn.placeholder = "Message your opponent...";
    } else {
        currentChannel = 'team';
        if(chatTabs) chatTabs.style.display = 'flex';
        setChatChannel('team');
    }
});

// --- 4. GAMEPLAY ACTIONS ---
function submitTeamMove(choice) {
    socket.emit('submit_team_move', { session_code: SESSION_CODE, choice: choice });
}

socket.on('team_decision_locked', (data) => {
    const statusMsg = document.getElementById('status-msg');
    if(statusMsg) {
        statusMsg.style.display = 'block';
        statusMsg.innerText = `🔒 Decision Locked: ${data.move.toUpperCase()} (by ${data.by})`;
    }

    const btns = document.getElementById('action-buttons');
    if(btns) {
        const k = btns.querySelector('.btn-keep');
        const c = btns.querySelector('.btn-cut');
        if(k) k.style.display = 'none';
        if(c) c.style.display = 'none';
    }
});

function modifyMove(newChoice) {
    socket.emit('modify_move', { session_code: SESSION_CODE, choice: newChoice });
}

socket.on('move_modified', (data) => {
    const statusMsg = document.getElementById('status-msg');
    if(statusMsg) statusMsg.innerText = `✏️ Modified to: ${data.new_choice.toUpperCase()} (Penalty: HK$${data.penalty})`;
    showBroadcast(`Choice modified to ${data.new_choice} by ${data.player}`);
});

// --- 5. SPY ALERT ---
socket.on('spy_move_alert', (data) => {
    showBroadcast(data.msg);
    const win = document.getElementById('chat-window');
    if(win) {
        const msgDiv = document.createElement('div');
        msgDiv.className = 'message msg-spy';
        msgDiv.setAttribute('data-scope', 'spy');
        msgDiv.innerHTML = `<div class="msg-text" style="font-weight:bold; color:#b91c1c;">${data.msg}</div>`;
        win.appendChild(msgDiv);
        win.scrollTop = win.scrollHeight;
    }
});

// --- 6. ROUND & TIMER ---
socket.on('start_round_timer', (data) => {
    const rDisp = document.getElementById('round-display');
    if(rDisp) rDisp.innerText = `Round ${data.round} / ${data.total}`;

    // Lock Rename Input on Round 1
    if (data.round === 1) {
        const renameInput = document.getElementById('rename-input');
        const renameBtn = document.querySelector('.btn-rename');

        if (renameInput && renameBtn) {
            renameInput.disabled = true;
            renameInput.placeholder = "Locked";
            renameBtn.disabled = true;
            renameBtn.style.opacity = "0.5";
            renameBtn.innerText = "Locked";
        }
    }

    const resOver = document.getElementById('result-overlay');
    const statMsg = document.getElementById('status-msg');
    if(resOver) resOver.style.display = 'none';
    if(statMsg) statMsg.style.display = 'none';

    const btns = document.getElementById('action-buttons');
    if(btns) {
        btns.style.display = 'block';
        const k = btns.querySelector('.btn-keep');
        const c = btns.querySelector('.btn-cut');
        if(k) k.style.display = 'flex';
        if(c) c.style.display = 'flex';
    }

    const modSec = document.getElementById('modify-section');
    if(modSec) modSec.style.display = data.config.modify_allowed ? 'block' : 'none';

    const chatHeader = document.getElementById('chat-header-status');
    if(chatHeader) chatHeader.style.display = data.config.spy ? 'block' : 'none';

    const msgInput = document.getElementById('msgInput');
    const sendBtn = document.querySelector('#chat-container button');

    if(msgInput && sendBtn) {
        if (data.config.silent) {
            msgInput.disabled = true;
            msgInput.placeholder = "🔇 Silent Mode Active (Chat Disabled)";
            msgInput.style.backgroundColor = "#f1f5f9";
            sendBtn.disabled = true;
            sendBtn.style.opacity = "0.5";
        } else {
            msgInput.disabled = false;
            msgInput.placeholder = "Type a message...";
            msgInput.style.backgroundColor = "white";
            sendBtn.disabled = false;
            sendBtn.style.opacity = "1";
        }
    }

    // --- PAYOFF MATRIX DYNAMIC SKEW UPDATE ---
    const skew = data.config.skew || 1.0;

    const p_kk = document.getElementById('p-kk-you');
    const p_kc = document.getElementById('p-kc-you');
    const p_ck = document.getElementById('p-ck-you');
    const p_cc = document.getElementById('p-cc-you');

    // Updated base payoffs for HK Milk Tea Context
    if(p_kk) p_kk.innerText = `HK$${Math.round(10000 * skew)}`;
    if(p_kc) p_kc.innerText = `HK$${Math.round(3000 * skew)}`;
    if(p_ck) p_ck.innerText = `HK$${Math.round(15000 * skew)}`;
    if(p_cc) p_cc.innerText = `HK$${Math.round(6000 * skew)}`;

    const btnKeepDesc = document.querySelector('.btn-keep .act-desc');
    const btnCutDesc = document.querySelector('.btn-cut .act-desc');

    if(btnKeepDesc) {
        btnKeepDesc.innerText = `Cooperate (HK$${Math.round(10000 * skew)} / HK$${Math.round(3000 * skew)})`;
    }
    if(btnCutDesc) {
        btnCutDesc.innerText = `Compete (HK$${Math.round(15000 * skew)} / HK$${Math.round(6000 * skew)})`;
    }

    startCountdown(data.end_time);
});

let timerInterval;
function startCountdown(endTime) {
    clearInterval(timerInterval);
    const timerEl = document.getElementById('timer');
    if(!timerEl) return;

    timerEl.classList.remove('timer-danger');

    timerInterval = setInterval(() => {
        const now = Date.now() / 1000;
        const remaining = Math.max(0, Math.floor(endTime - now));
        const mins = Math.floor(remaining / 60);
        const secs = remaining % 60;

        timerEl.innerText = `${mins.toString().padStart(2, '0')}:${secs.toString().padStart(2, '0')}`;

        if (remaining <= 5) timerEl.classList.add('timer-danger');
        if (remaining <= 0) clearInterval(timerInterval);
    }, 1000);
}

socket.on('update_timer', (data) => {
    const timerEl = document.getElementById('timer');
    if (!timerEl) return;
    clearInterval(timerInterval);

    if (data.mode === 'countdown') {
        timerEl.innerText = `Next: ${data.value}s`;
        if (data.value <= 5) timerEl.classList.add('timer-danger');
        else timerEl.classList.remove('timer-danger');
    } else if (data.mode === 'text') {
        timerEl.innerText = data.value;
        timerEl.classList.remove('timer-danger');
    }
});

// --- 7. RESULTS & END GAME ---
socket.on('round_result', (data) => {
    const overlay = document.getElementById('result-overlay');
    if(!overlay) return;

    overlay.style.display = 'block';

    if (data.blind) {
        overlay.innerHTML = `<div style="color:#64748b; padding:20px;">🙈 Round Complete. Results are hidden.</div>`;
    } else {
        overlay.innerHTML = `
            <div style="font-size:1.1rem; margin-bottom:10px; font-weight:bold;">Round Results</div>
            <div style="margin-bottom:5px;">You: <span style="font-weight:800; color:${data.my_move === 'keep' ? '#166534' : '#991b1b'}">${data.my_move.toUpperCase()}</span> (+HK$${data.my_profit})</div>
            <div>Opponent: <span style="font-weight:800; color:${data.enemy_move === 'keep' ? '#166534' : '#991b1b'}">${data.enemy_move.toUpperCase()}</span> (+HK$${data.enemy_profit})</div>
        `;
    }
});

socket.on('game_over', (data) => {
    const modal = document.getElementById('game-over-modal');
    if(modal) modal.style.display = 'flex';

    const tbody = document.getElementById('game-over-history-body');
    if(tbody) {
        tbody.innerHTML = data.history.map(h => {
            const myClass = h.score_a >= h.score_b ? 'text-green-600 font-bold' : 'text-red-600';
            const oppClass = h.score_b >= h.score_a ? 'text-green-600 font-bold' : 'text-red-600';
            return `
            <tr style="border-bottom:1px solid #f1f5f9;">
                <td style="padding:12px;">${h.round}</td>
                <td style="padding:12px;" class="${myClass}">HK$${h.score_a} <span style="font-size:0.8em; color:#94a3b8;">(${h.move_a.toUpperCase()})</span></td>
                <td style="padding:12px;" class="${oppClass}">HK$${h.score_b} <span style="font-size:0.8em; color:#94a3b8;">(${h.move_b.toUpperCase()})</span></td>
            </tr>
            `;
        }).join('');
    }

    const canvas = document.getElementById('scoreChart');
    if(!canvas) return;

    const ctx = canvas.getContext('2d');
    const labels = data.history.map(h => `R${h.round}`);

    let cumulativeA = 0;
    let cumulativeB = 0;
    const dataA = data.history.map(h => { cumulativeA += h.score_a; return cumulativeA; });
    const dataB = data.history.map(h => { cumulativeB += h.score_b; return cumulativeB; });

    if (resultChart) resultChart.destroy();

    resultChart = new Chart(ctx, {
        type: 'line',
        data: {
            labels: labels,
            datasets: [
                {
                    label: 'Blue Team (HK$)',
                    data: dataA,
                    borderColor: '#2563eb',
                    backgroundColor: 'rgba(37, 99, 235, 0.1)',
                    tension: 0.3,
                    fill: true
                },
                {
                    label: 'Red Team (HK$)',
                    data: dataB,
                    borderColor: '#dc2626',
                    backgroundColor: 'rgba(220, 38, 38, 0.1)',
                    tension: 0.3,
                    fill: true
                }
            ]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                title: { display: true, text: 'Cumulative Profit' }
            },
            scales: {
                y: { beginAtZero: true }
            }
        }
    });
});

// --- 8. CHAT UTILITIES ---

// Strict logic to show/hide messages based on active tab
function setChatChannel(channel) {
    currentChannel = channel;
    const btnTeam = document.getElementById('btn-channel-team');
    const btnAll = document.getElementById('btn-channel-all');

    if(btnTeam) btnTeam.classList.toggle('active', channel === 'team');
    if(btnAll) btnAll.classList.toggle('active', channel === 'all');

    // Filter existing messages in the chat window
    const msgs = document.querySelectorAll('#chat-window .message');
    msgs.forEach(msg => {
        const scope = msg.getAttribute('data-scope');

        // System, Coach, and Admin messages show in BOTH tabs
        if (!scope || scope === 'system' || scope === 'coach' || msg.classList.contains('msg-admin')) {
            msg.style.display = 'block';
        }
        // Team Tab: Show 'team' and 'spy' messages
        else if (channel === 'team' && (scope === 'team' || scope === 'spy')) {
            msg.style.display = 'block';
        }
        // Public Tab: Show 'all' messages only
        else if (channel === 'all' && scope === 'all') {
            msg.style.display = 'block';
        }
        // Otherwise, hide the message
        else {
            msg.style.display = 'none';
        }
    });

    const win = document.getElementById('chat-window');
    if(win) win.scrollTop = win.scrollHeight;
}

function handleEnter(e) { if (e.key === 'Enter') sendMessage(); }

function sendMessage() {
    const input = document.getElementById('msgInput');
    if (!input || input.disabled) return;

    const text = input.value.trim();
    if (!text) return;

    socket.emit('send_message', { session_code: SESSION_CODE, message: text, scope: currentChannel });
    input.value = "";
}

socket.on('receive_message', (data) => {
    const win = document.getElementById('chat-window');
    if(!win) return;

    const nameInput = document.getElementById('username');
    const myName = nameInput ? nameInput.value : "";
    let msgClass = 'msg-them';

    if (data.sender === myName) msgClass = 'msg-me';
    if (data.sender === 'ADMIN') msgClass = 'msg-admin';
    if (data.sender === 'SYSTEM') msgClass = 'msg-system';
    if (data.is_spy) msgClass = 'msg-spy';
    if (data.is_coach || data.sender === 'AI Coach') msgClass = 'msg-coach';

    const msgDiv = document.createElement('div');
    msgDiv.className = `message ${msgClass}`;

    // Attach scope for filtering logic
    msgDiv.setAttribute('data-scope', data.scope || 'all');

    if (data.sender === 'SYSTEM') {
        msgDiv.setAttribute('data-scope', 'system');
        msgDiv.innerHTML = `<div class="msg-text" style="white-space: pre-wrap;">${data.text}</div>`;
    } else if (data.is_coach || data.sender === 'AI Coach') {
        msgDiv.setAttribute('data-scope', 'coach');
        msgDiv.innerHTML = `
            <div class="msg-meta">🎓 AI Coach</div>
            <div class="msg-text" style="font-size:0.95rem; line-height:1.6;">${data.text}</div>
        `;
    } else {
        // We no longer need the "(Public)" text badge because tabs isolate the views
        msgDiv.innerHTML = `
            <div class="msg-meta">${data.sender}</div>
            <div class="msg-text">${data.text}</div>
        `;
    }

    win.appendChild(msgDiv);

    // Immediately hide the new message if it doesn't belong in the currently viewed tab
    const scope = msgDiv.getAttribute('data-scope');
    if (scope !== 'system' && scope !== 'coach' && data.sender !== 'ADMIN') {
        if (currentChannel === 'team' && scope === 'all') msgDiv.style.display = 'none';
        if (currentChannel === 'all' && (scope === 'team' || scope === 'spy')) msgDiv.style.display = 'none';
    }

    win.scrollTop = win.scrollHeight;
});

socket.on('system_broadcast', (data) => {
    showBroadcast(data.text);
});

function showBroadcast(text) {
    const broadcast = document.getElementById('broadcast-overlay');
    if(!broadcast) return;
    broadcast.innerText = text;
    broadcast.classList.add('show');
    setTimeout(() => broadcast.classList.remove('show'), 5000);
}

// Game Over UI Logic: Close Modal -> Show Left Panel
function closeAndShowChat() {
    // 1. Hide Modal
    const modal = document.getElementById('game-over-modal');
    if(modal) modal.style.display = 'none';

    // 2. Hide Active Game Controls
    const activePanel = document.getElementById('active-game-panel');
    if(activePanel) activePanel.style.display = 'none';

    // 3. Show Summary Panel
    const summaryPanel = document.getElementById('final-summary-panel');
    if(summaryPanel) summaryPanel.style.display = 'block';

    // 4. Copy History to Mini Table
    const modalHistory = document.getElementById('game-over-history-body');
    const miniHistory = document.getElementById('mini-history-body');

    if (modalHistory && miniHistory) {
        miniHistory.innerHTML = modalHistory.innerHTML;
    }
}
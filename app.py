# app.py - Very top of the file

# 1. IMMEDIATE EVENTLET PATCHING (MUST BE FIRST)
import eventlet

eventlet.monkey_patch()

# 2. STANDARD IMPORTS
import os
from flask import Flask, render_template, request, Response, redirect, url_for, flash
from flask_socketio import SocketIO, emit, join_room, leave_room
from flask_login import LoginManager, login_user, login_required, logout_user, current_user
import time
import csv
import io
import random
import string
from datetime import datetime, timezone, timedelta
import json

# 3. YOUR APP IMPORTS
from extensions import db
from models import SessionLog, ChatRecord, GameResult, AdminUser

# --- SERVICES IMPORT ---
try:
    from bot_service import BotService

    bot_manager = BotService()
    print("✅ BotService loaded successfully.")
except Exception as e:
    print(f"⚠️ BotService failed to load: {e}. Bots will not chat.")
    bot_manager = None

try:
    from analysis_service import AnalysisService

    analysis_service = AnalysisService()
    print("✅ AnalysisService loaded successfully.")
except Exception as e:
    print(f"⚠️ AnalysisService failed to load: {e}. AI Analysis will not work.")
    analysis_service = None

# --- CONFIGURATION ---
app = Flask(__name__)
app.config['SECRET_KEY'] = 'ACTR2026_SECRET_KEY'
basedir = os.path.abspath(os.path.dirname(__file__))
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(basedir, 'gas_station.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db.init_app(app)

socketio = SocketIO(app, cors_allowed_origins="*", ping_timeout=60, ping_interval=25, async_mode='eventlet')


@socketio.on('connect')
def start_background_threads():
    global thread_started
    if 'thread_started' not in globals():
        socketio.start_background_task(monitor_timeouts)
        globals()['thread_started'] = True
        print("🚀 Background monitor thread started!")


login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

# --- IN-MEMORY GAME STATE ---
active_sessions = {}
HKT = timezone(timedelta(hours=8))


@login_manager.user_loader
def load_user(user_id):
    if user_id == "ACTR2026":
        return AdminUser(user_id)
    return None


# ==========================================
# 1. HELPER FUNCTIONS
# ==========================================

def log_action(s_code, user, action):
    """Log an action with Hong Kong Time for audit/review."""
    if s_code in active_sessions:
        timestamp = datetime.now(HKT).strftime('%Y-%m-%d %H:%M:%S')
        active_sessions[s_code]['action_logs'].append({
            'time': timestamp,
            'user': user,
            'action': action
        })


def generate_session_code():
    while True:
        code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))
        if code not in active_sessions:
            return code


def save_chat_to_db(s_code, m_id, sender, text, scope):
    try:
        with app.app_context():
            log = ChatRecord(session_code=s_code, match_id=m_id, sender=sender, message=text, scope=scope)
            db.session.add(log)
            db.session.commit()
    except Exception as e:
        print(f"DB Error (Chat): {e}")


def send_admin_update(s_code):
    sd = active_sessions.get(s_code)
    if not sd: return

    player_data = []
    student_status = []
    all_reaction_times = []

    for sid, p in sd['players'].items():
        match_id = p.get('match_id')
        prof = 0
        k_rate = 0
        p_state = "Lobby"

        if match_id in sd['matches']:
            m = sd['matches'][match_id]
            if m.get('is_finished'):
                p_state = "Finished"
            elif m.get('status') == 'playing':
                p_state = "In Game"
            else:
                p_state = "Waiting"

            for h in m['history']:
                if p['team_id'] == m['team_a']:
                    prof += h['score_a']
                    if h['move_a'] == 'keep': k_rate += 1
                else:
                    prof += h['score_b']
                    if h['move_b'] == 'keep': k_rate += 1
            if len(m['history']) > 0:
                k_rate = int((k_rate / len(m['history'])) * 100)

        # Basic scatter data
        player_data.append({
            'name': p['name'],
            'team_color': 'blue' if str(p.get('team_id', '')).endswith('_A') else 'red',
            'total_profit': prof,
            'keep_rate': k_rate,
            'msg_count': p['stats']['msg_count'],
            'char_count': p['stats']['char_count'],
            'is_bot': p.get('is_bot', False)
        })

        # Detailed Status Data for the new Tab
        if not p.get('is_bot'):
            student_status.append({
                'sid': sid,
                'student_id': p.get('student_id', 'N/A'),
                'name': p['name'],
                'is_online': p.get('is_online', False),
                'state': p_state,
                'team': sd['teams'][p['team_id']]['custom_name'] if 'team_id' in p and p['team_id'] in sd[
                    'teams'] else "Unassigned"
            })

    m_list = []
    total_profit = 0

    for tid, t_data in sd['teams'].items():
        all_reaction_times.extend(t_data.get('reaction_times', []))

    for mid, m in sd['matches'].items():
        total_profit += sum(h['score_a'] + h['score_b'] for h in m['history'])
        m_list.append({
            'id': mid,
            'round': m.get('round', 0),
            'status': m['status'],
            'is_finished': m.get('is_finished', False),
            'team_a_name': sd['teams'][m['team_a']].get('custom_name', 'Blue'),
            'team_b_name': sd['teams'][m['team_b']].get('custom_name', 'Red'),
            'history': m['history'],
            'total_rounds': sd['config'].get('total_rounds', 5),
            'modified_moves': m.get('modify_count', 0)
        })

    p_count = len(sd['players'])
    avg_prof = int(total_profit / p_count) if p_count > 0 else 0

    avg_reaction_str = f"{round(sum(all_reaction_times) / len(all_reaction_times), 2)}s" if all_reaction_times else "0s"

    socketio.emit('admin_lobby_update', {'lobby': sd['lobby']}, room=s_code)
    socketio.emit('admin_match_list_update', {
        'matches': m_list,
        'avg_profit_pp': avg_prof,
        'scatter_data': player_data,
        'student_status': student_status,
        'issues': sd.get('issues', []),
        'avg_reaction': avg_reaction_str
    }, room=s_code)


def add_bot(s_code, name_prefix, strategy, custom_prompt=""):
    sid = f"bot_{strategy}_{int(time.time() * 1000)}_{random.randint(100, 999)}"
    active_sessions[s_code]['players'][sid] = {
        'name': f"{name_prefix}_{random.randint(1, 99)}",
        'session_code': s_code,
        'stats': {'msg_count': 0, 'char_count': 0, 'coop_count': 0, 'total_votes': 0},
        'is_bot': True,
        'is_online': True,
        'strategy': strategy,
        'custom_prompt': custom_prompt
    }
    active_sessions[s_code]['lobby'].append({'sid': sid, 'name': active_sessions[s_code]['players'][sid]['name']})


def assign_teams(sd, team_id, match_id, member_sids, default_name, is_blue):
    for sid in member_sids:
        if sid in sd['players']:
            sd['players'][sid].update({'team_id': team_id, 'match_id': match_id})
            if not sd['players'][sid].get('is_bot'):
                join_room(team_id, sid)
                join_room(match_id, sid)
                socketio.emit('game_start_setup', {
                    'team_name': default_name,
                    'is_blue': is_blue,
                    'teammates': [sd['players'][s]['name'] for s in member_sids if s in sd['players']]
                }, room=sid)


def update_player_team(sd, sid, new_tid, old_tid):
    with app.app_context():
        if sid in sd['players']:
            sd['players'][sid]['team_id'] = new_tid
            if not sd['players'][sid].get('is_bot'):
                leave_room(old_tid, sid=sid, namespace='/')
                join_room(new_tid, sid=sid, namespace='/')


def finish_match(s_code, m_id):
    sd = active_sessions[s_code]
    m = sd['matches'][m_id]
    m['status'] = 'finished'
    m['is_finished'] = True
    log_action(s_code, "SYSTEM", f"Match {m_id} finished.")
    socketio.emit('game_over', {'history': m['history']}, room=m['id'])


# ==========================================
# 2. ROUTES
# ==========================================
@app.route('/')
def index():
    return render_template('landing.html')


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        if username == 'ACTR2026' and password == 'ACTR2026':
            user = AdminUser(username)
            login_user(user)
            return redirect(url_for('admin_dashboard'))
        else:
            flash('Invalid credentials')
    return render_template('login.html')


@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))


@app.route('/admin')
@login_required
def admin_dashboard():
    active_list = []
    for code, data in active_sessions.items():
        p_count = len(data['lobby']) + len([p for p in data['players'].values() if not p.get('is_bot')])
        is_paused = data['config'].get('global_pause', False)
        active_list.append({'code': code, 'players': p_count, 'is_paused': is_paused})
    return render_template('admin_dashboard.html', sessions=active_list)


@app.route('/admin/create_session', methods=['POST'])
@login_required
def create_session():
    code = generate_session_code()
    active_sessions[code] = {
        'matches': {}, 'players': {}, 'teams': {}, 'lobby': [],
        'action_logs': [], 'issues': [],
        'config': {
            'total_rounds': 5,
            'sync_mode': False,
            'timeout_mode': 'keep',
            'schedule': [],
            'sudden_death_surprise': False,
            'global_pause': False
        }
    }
    db_sess = SessionLog(session_code=code, admin_id=current_user.id)
    db.session.add(db_sess)
    db.session.commit()
    log_action(code, "ADMIN", "Session Created")
    return redirect(url_for('admin_panel_view', session_code=code))


@app.route('/admin/delete_session/<session_code>', methods=['POST'])
@login_required
def route_delete_session(session_code):
    """Allows Admin to delete from Dashboard."""
    if session_code in active_sessions:
        socketio.emit('match_deleted', {'msg': 'This session has been permanently deleted by the Admin.'},
                      room=session_code)
        del active_sessions[session_code]
        flash(f'Session {session_code} deleted successfully.')
    return redirect(url_for('admin_dashboard'))


@app.route('/admin/pause_session/<session_code>', methods=['POST'])
@login_required
def route_pause_session(session_code):
    """Allows Admin to pause/resume from Dashboard."""
    if session_code in active_sessions:
        sd = active_sessions[session_code]
        config = sd['config']
        is_paused = not config.get('global_pause', False)
        config['global_pause'] = is_paused

        if is_paused:
            config['pause_start_time'] = time.time()
            log_action(session_code, "ADMIN", "Triggered Global Pause from Dashboard")
            socketio.emit('system_broadcast', {'text': "⏸ Admin has PAUSED the entire session."}, room=session_code)
        else:
            if 'pause_start_time' in config:
                pause_duration = time.time() - config['pause_start_time']
                for m in sd['matches'].values():
                    if 'end_time' in m: m['end_time'] += pause_duration
                    if 'break_end_time' in m: m['break_end_time'] += pause_duration
                    if 'sync_wait_start' in m: m['sync_wait_start'] += pause_duration
                del config['pause_start_time']
            log_action(session_code, "ADMIN", "Resumed Session from Dashboard")
            socketio.emit('system_broadcast', {'text': "▶ Session RESUMED."}, room=session_code)
        send_admin_update(session_code)
    return redirect(url_for('admin_dashboard'))


@app.route('/admin/session/<session_code>')
@login_required
def admin_panel_view(session_code):
    if session_code not in active_sessions:
        flash("Session expired or does not exist.")
        return redirect(url_for('admin_dashboard'))
    share_link = url_for('participant_join', session_code=session_code, _external=True)
    return render_template('admin.html', session_code=session_code, share_link=share_link)


@app.route('/game/<session_code>')
@app.route('/game/<session_code>/<student_id>')
@app.route('/game/<session_code>/<student_id>/<player_name>')
def participant_join(session_code, student_id='', player_name=''):
    if session_code not in active_sessions:
        return "<h1>Session Not Found</h1>", 404
    return render_template('participant.html', session_code=session_code, auto_id=student_id, auto_name=player_name)


@app.route('/admin/export_csv/<session_code>')
@login_required
def export_csv(session_code):
    if session_code not in active_sessions: return "Session not found", 404
    sd = active_sessions[session_code]
    output = io.StringIO()
    writer = csv.writer(output)

    writer.writerow([
        'Match ID', 'Round',
        'Blue Team', 'Blue Players (ID-Name)', 'Blue Move', 'Blue Profit (HKD)',
        'Red Team', 'Red Players (ID-Name)', 'Red Move', 'Red Profit (HKD)'
    ])

    for m in sd['matches'].values():
        ta = sd['teams'].get(m['team_a'])
        tb = sd['teams'].get(m['team_b'])
        if not ta or not tb: continue

        b_name = ta.get('custom_name', 'Blue')
        r_name = tb.get('custom_name', 'Red')

        b_players = " | ".join(
            [f"{sd['players'][s].get('student_id', 'BOT')}-{sd['players'][s]['name']}" for s in ta['members'] if
             s in sd['players']])
        r_players = " | ".join(
            [f"{sd['players'][s].get('student_id', 'BOT')}-{sd['players'][s]['name']}" for s in tb['members'] if
             s in sd['players']])

        for h in m['history']:
            writer.writerow([
                m['id'], h['round'],
                b_name, b_players, h['move_a'], h['score_a'],
                r_name, r_players, h['move_b'], h['score_b']
            ])

    return Response(output.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition": f"attachment;filename=MilkTea_Results_{session_code}.csv"})


@app.route('/admin/export_logs/<session_code>')
@login_required
def export_logs(session_code):
    if session_code not in active_sessions: return "Session not found", 404
    sd = active_sessions[session_code]
    output = io.StringIO()
    writer = csv.writer(output)

    writer.writerow(['Time (HKT)', 'User', 'Action'])
    for log in sd.get('action_logs', []):
        writer.writerow([log['time'], log['user'], log['action']])

    return Response(output.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition": f"attachment;filename=MilkTea_AuditLogs_{session_code}.csv"})


# ==========================================
# 3. SOCKET.IO EVENTS
# ==========================================

@socketio.on('join_session')
def handle_join_session(data):
    sid = request.sid
    s_code = data.get('session_code')
    role = data.get('role', 'player')
    if not s_code or s_code not in active_sessions:
        emit('error', {'msg': 'Invalid Session'})
        return
    join_room(s_code)
    if role == 'admin':
        send_admin_update(s_code)


@socketio.on('login')
def handle_player_login(data):
    sid = request.sid
    s_code = data.get('session_code')
    name = data.get('name')
    student_id = data.get('student_id', 'N/A')

    if not s_code or s_code not in active_sessions:
        emit('error_msg', {'msg': 'Session expired or invalid.'})
        return

    sd = active_sessions[s_code]
    existing_sid = None

    for old_sid, p_info in sd['players'].items():
        if p_info.get('student_id') == student_id and not p_info.get('is_bot'):
            existing_sid = old_sid
            break

    if existing_sid:
        player_data = sd['players'].pop(existing_sid)
        player_data['name'] = name
        player_data['is_online'] = True  # Set Online
        sd['players'][sid] = player_data

        if 'team_id' in player_data: join_room(player_data['team_id'], sid)
        if 'match_id' in player_data:
            join_room(player_data['match_id'], sid)
            match = sd['matches'].get(player_data['match_id'])
            if match and match['status'] == 'paused':
                match['status'] = 'playing'
                socketio.emit('system_broadcast', {'text': f"✅ {name} returned. Resuming..."}, room=match['id'])

        log_action(s_code, f"{name} ({student_id})", "Reconnected/Logged In")
        emit('login_success', {'reconnected': True}, room=sid)
    else:
        sd['players'][sid] = {
            'name': name,
            'student_id': student_id,
            'session_code': s_code,
            'stats': {'msg_count': 0, 'char_count': 0, 'coop_count': 0, 'total_votes': 0},
            'is_bot': False,
            'is_online': True  # Set Online
        }
        sd['lobby'].append({'sid': sid, 'name': name})
        log_action(s_code, f"{name} ({student_id})", "First Login")
        emit('login_success', {'reconnected': False}, room=sid)

    send_admin_update(s_code)


@socketio.on('disconnect')
def on_disconnect():
    sid = request.sid
    for s_code, sd in active_sessions.items():
        if sid in sd['players']:
            p = sd['players'][sid]
            p['is_online'] = False  # Set Offline

            if p.get('is_bot'): continue
            log_action(s_code, p['name'], "Disconnected")

            m_id = p.get('match_id')
            if m_id and m_id in sd['matches']:
                match = sd['matches'][m_id]
                if not match['is_finished']:
                    match['status'] = 'paused'
                    socketio.emit('system_broadcast', {'text': f"⚠️ {p['name']} disconnected. Game paused."}, room=m_id)
            send_admin_update(s_code)
            break


@socketio.on('report_issue')
def handle_report_issue(data):
    """Allows student to send an alert/issue straight to admin dashboard"""
    s_code = data.get('session_code')
    issue_text = data.get('text')
    sid = request.sid
    sd = active_sessions.get(s_code)

    if sd and sid in sd['players']:
        p_name = sd['players'][sid]['name']
        timestamp = datetime.now(HKT).strftime('%H:%M:%S')

        issue_obj = {
            'time': timestamp,
            'player': p_name,
            'text': issue_text,
            'resolved': False
        }
        sd['issues'].append(issue_obj)
        log_action(s_code, p_name, f"Reported Issue: {issue_text}")
        send_admin_update(s_code)


@socketio.on('admin_create_teams')
def admin_create_teams(data):
    s_code = data.get('session_code')
    if not s_code or s_code not in active_sessions: return
    sd = active_sessions[s_code]
    lobby = sd['lobby']
    size = int(data['team_size'])
    needed = size * 2

    while len(lobby) >= needed:
        m_id = f"{s_code}_m_{int(time.time())}_{len(sd['matches'])}"
        ta_id, tb_id = f"{m_id}_A", f"{m_id}_B"
        ta_sids = [lobby.pop(0)['sid'] for _ in range(size)]
        tb_sids = [lobby.pop(0)['sid'] for _ in range(size)]

        sd['teams'][ta_id] = {'members': ta_sids, 'custom_name': 'Blue', 'reaction_times': []}
        sd['teams'][tb_id] = {'members': tb_sids, 'custom_name': 'Red', 'reaction_times': []}
        sd['matches'][m_id] = {
            'id': m_id, 'team_a': ta_id, 'team_b': tb_id,
            'moves': {}, 'round': 0, 'history': [], 'chat_logs': [], 'status': 'setup', 'is_finished': False,
            'modify_count': 0
        }

        assign_teams(sd, ta_id, m_id, ta_sids, 'Blue', True)
        assign_teams(sd, tb_id, m_id, tb_sids, 'Red', False)

    log_action(s_code, "ADMIN", "Created Teams")
    send_admin_update(s_code)


@socketio.on('update_team_name')
def handle_team_name_update(data):
    sid = request.sid
    s_code = next((k for k, v in active_sessions.items() if sid in v['players']), None)
    if not s_code: return
    player = active_sessions[s_code]['players'][sid]
    new_name = data.get('name', '').strip()[:15]
    if not new_name: return
    tid = player.get('team_id')
    if tid:
        old_name = active_sessions[s_code]['teams'][tid]['custom_name']
        active_sessions[s_code]['teams'][tid]['custom_name'] = new_name
        log_action(s_code, player['name'], f"Changed team name {old_name} -> {new_name}")
        emit('team_name_updated', {'name': new_name}, room=tid)
        send_admin_update(s_code)


# --- GAME LOGIC ---
@socketio.on('admin_start_game')
def admin_start_game(data):
    s_code = data.get('session_code')
    if not s_code or s_code not in active_sessions: return
    sd = active_sessions[s_code]
    config = sd['config']

    config['schedule'] = data['schedule']
    config['total_rounds'] = data['total_rounds']
    config['sync_mode'] = data.get('sync_mode', 'async')
    config['timeout_mode'] = data.get('timeout_mode', 'keep')
    config['sudden_death_surprise'] = data.get('sudden_death', False)
    config['sudden_death_triggered'] = False

    sd['sync_waiting'] = []

    log_action(s_code, "ADMIN", "Started Game Scenario")

    for m in sd['matches'].values():
        if m.get('is_finished', False): continue
        m['round'] = 0
        m['status'] = 'ready'
        m['history'] = []
        m['moves'] = {}
        m['is_finished'] = False
        m['modify_count'] = 0
        start_next_round(s_code, m['id'])
    send_admin_update(s_code)


@socketio.on('admin_trigger_metacognition')
def handle_metacognition(data):
    s_code = data.get('session_code')
    m_id = data.get('match_id')
    admin_sid = request.sid

    if not s_code or s_code not in active_sessions: return
    sd = active_sessions[s_code]

    if m_id not in sd['matches']: return
    match = sd['matches'][m_id]

    log_action(s_code, "ADMIN", f"Triggered Metacognition for Match {m_id}")
    socketio.emit('system_broadcast', {'text': "🎓 The AI Coach is analyzing your gameplay logic..."}, room=m_id)
    socketio.start_background_task(run_coaching_task, s_code, m_id, admin_sid)


def run_coaching_task(s_code, m_id, admin_sid):
    with app.app_context():
        sd = active_sessions.get(s_code)
        if not sd: return
        match = sd['matches'].get(m_id)

        ta_name = sd['teams'][match['team_a']].get('custom_name', 'Blue')
        tb_name = sd['teams'][match['team_b']].get('custom_name', 'Red')

        if analysis_service:
            feedback = analysis_service.generate_coaching_feedback(match, ta_name, tb_name)
            coach_msg = {'sender': 'AI Coach', 'text': feedback, 'scope': 'all', 'is_spy': False, 'is_coach': True}
            match['chat_logs'].append({'sender': 'AI Coach', 'text': feedback, 'scope': 'all', 'is_coach': True})
            save_chat_to_db(s_code, m_id, 'AI Coach', feedback, 'all')
            socketio.emit('receive_message', coach_msg, room=m_id, namespace='/')
            if admin_sid:
                socketio.emit('receive_message', coach_msg, room=admin_sid, namespace='/')


def start_next_round(s_code, m_id):
    sd = active_sessions[s_code]
    m = sd['matches'][m_id]
    config = sd['config']
    m['round'] += 1
    current_round_idx = m['round'] - 1

    if current_round_idx >= len(config['schedule']):
        finish_match(s_code, m_id)
        return

    round_cfg = config['schedule'][current_round_idx]
    m['status'] = 'playing'
    m['moves'] = {}
    m['modify_count'] = 0
    m['round_start_time'] = time.time()
    m['spy_msg_counts'] = {m['team_a']: 0, m['team_b']: 0}

    duration = int(round_cfg.get('duration', 45))
    m['end_time'] = time.time() + duration

    if 'break_end_time' in m: del m['break_end_time']
    if 'modified_move_a' in m: del m['modified_move_a']
    if 'modified_move_b' in m: del m['modified_move_b']

    features = []
    team_size = len(sd['teams'][m['team_a']]['members'])
    is_1vs1 = (team_size == 1)

    if round_cfg.get('blind'): features.append("🙈 Blind Mode: Results will be HIDDEN this round.")
    if round_cfg.get('silent'): features.append("🔇 Silent Mode: Chat is DISABLED.")

    spy_mode = round_cfg.get('spy', 'none')
    if spy_mode != 'none' and not is_1vs1:
        if spy_mode == '1line':
            features.append("🕵️ Spy Mode (Lv1): You will see the FIRST message from opponents.")
        elif spy_mode == '2lines':
            features.append("🕵️ Spy Mode (Lv2): You will see the FIRST 2 messages from opponents.")
        elif spy_mode == 'all':
            features.append("🕵️ Spy Mode (Max): You will see ALL opponent chat.")
        elif spy_mode == 'decision':
            features.append("🕵️ Spy Mode (Tacit): You will be alerted of the opponent's CHOICE (Keep/Cut).")

    if round_cfg.get('modify_allowed'): features.append(
        "✏️ Modify Allowed: You can change your move after submitting (with penalty).")

    if round_cfg.get('shuffle'):
        if is_1vs1:
            features.append("⚠️ Shuffle: (Inactive in 1vs1 scenario).")
        else:
            features.append("🔀 Shuffle: Teams have been remixed!")

    skew_val = float(round_cfg.get('skew', 1.0))
    if skew_val != 1.0:
        features.append(f"📈 Payoff Skew: All monetary gains/losses are multiplied by {skew_val}x!")

    intro_text = f"🔔 Round {m['round']} Started!\n------------------\n"
    if features:
        intro_text += "\n".join(features)
    else:
        intro_text += "✅ Standard Round: Normal communication and scoring apply."

    if round_cfg.get('message'): intro_text += f"\n\n📢 Note: {round_cfg['message']}"

    socketio.emit('system_broadcast', {'text': f"Round {m['round']} Started! Check chat for rules."}, room=m['id'])
    save_chat_to_db(s_code, m_id, "SYSTEM", intro_text, "all")

    m['chat_logs'].append({'sender': 'SYSTEM', 'text': intro_text, 'scope': 'all'})
    socketio.emit('receive_message', {'sender': 'SYSTEM', 'text': intro_text, 'scope': 'all'}, room=m['id'],
                  namespace='/')

    socketio.emit('start_round_timer', {
        'round': m['round'],
        'total': config['total_rounds'],
        'end_time': m['end_time'],
        'config': {
            'silent': round_cfg.get('silent', False),
            'blind': round_cfg.get('blind', False),
            'modify_allowed': round_cfg.get('modify_allowed', False),
            'modify_penalty': round_cfg.get('modify_penalty', 0),
            'spy': (spy_mode != 'none'),
            'spy_lines': round_cfg.get('spy_lines', 'all'),
            'skew': skew_val
        }
    }, room=m['id'])

    for sid, p in sd['players'].items():
        if p.get('is_bot') and p.get('match_id') == m['id']:
            socketio.start_background_task(run_bot_turn, s_code, m['id'], sid, p['strategy'], m['history'])

    send_admin_update(s_code)


def run_bot_turn(s_code, m_id, bot_sid, strategy, history):
    time.sleep(random.randint(5, 15))
    with app.app_context():
        sd = active_sessions.get(s_code)
        if not sd: return
        match = sd['matches'].get(m_id)
        if not match or match['status'] != 'playing': return

        choice = 'keep'
        if strategy == 'random':
            choice = random.choice(['keep', 'cut'])
        elif strategy == 'grim':
            bot_p = sd['players'][bot_sid]
            my_team = bot_p['team_id']
            has_betrayed = False
            for h in history:
                opp_move = h['move_b'] if my_team == match['team_a'] else h['move_a']
                if opp_move == 'cut': has_betrayed = True; break
            choice = 'cut' if has_betrayed else 'keep'
        elif strategy == 'tft':
            if not history:
                choice = 'keep'
            else:
                bot_p = sd['players'][bot_sid]
                my_team = bot_p['team_id']
                last_round = history[-1]
                opp_move = last_round['move_b'] if my_team == match['team_a'] else last_round['move_a']
                choice = opp_move
        elif strategy == 'custom':
            choice = 'keep'

        _core_submit_move(s_code, bot_sid, choice)


def _core_submit_move(s_code, sid, choice):
    sd = active_sessions[s_code]
    p = sd['players'].get(sid)
    if not p: return
    match = sd['matches'].get(p.get('match_id'))
    if not match or match['status'] != 'playing': return

    p['stats']['total_votes'] += 1
    if choice == 'keep': p['stats']['coop_count'] += 1

    if p['team_id'] not in match['moves']:
        if 'round_start_time' in match:
            reaction_time = round(time.time() - match['round_start_time'], 2)
            if 'reaction_times' not in sd['teams'][p['team_id']]:
                sd['teams'][p['team_id']]['reaction_times'] = []
            sd['teams'][p['team_id']]['reaction_times'].append(reaction_time)

        match['moves'][p['team_id']] = choice
        log_action(s_code, p['name'], f"Submitted {choice.upper()} for Match {match['id']}")
        socketio.emit('team_decision_locked', {'move': choice, 'by': p['name']}, room=p['team_id'], namespace='/')

        schedule = sd['config'].get('schedule', [])
        if 0 < match['round'] <= len(schedule):
            round_cfg = schedule[match['round'] - 1]
            spy_mode = round_cfg.get('spy', 'none')
            if spy_mode == 'decision':
                opp_team = match['team_b'] if p['team_id'] == match['team_a'] else match['team_a']
                socketio.emit('spy_move_alert', {'player': p['name'], 'move': choice,
                                                 'msg': f"🕵️ SPY INTEL: Opponent selected {choice.upper()}"},
                              room=opp_team, namespace='/')

    if len(match['moves']) == 2:
        sync_mode = sd['config'].get('sync_mode', 'async')
        if sync_mode == 'async':
            if 'end_time' in match: del match['end_time']
            resolve_round(s_code, match['id'])
        elif sync_mode == 'mixed':
            new_end_time = time.time() + 10
            match['end_time'] = new_end_time
            socketio.emit('update_timer', {'mode': 'countdown', 'value': 10}, room=match['id'])
            socketio.emit('system_broadcast', {'text': "⚠️ Both submitted! 10s Grace Period started."},
                          room=match['id'])
    else:
        send_admin_update(s_code)


@socketio.on('submit_team_move')
def handle_move(data):
    sid = request.sid
    s_code = data.get('session_code')
    if not s_code or s_code not in active_sessions: return
    _core_submit_move(s_code, sid, data['choice'])


def resolve_round(s_code, m_id):
    sd = active_sessions[s_code]
    m = sd['matches'][m_id]
    if m['status'] != 'playing': return

    config = sd['config']
    round_cfg = config['schedule'][m['round'] - 1]
    skew = float(round_cfg.get('skew', 1.0))
    default = 'keep' if config.get('timeout_mode') == 'keep' else 'cut'

    has_a = m['team_a'] in m['moves']
    has_b = m['team_b'] in m['moves']
    if not has_a: m['moves'][m['team_a']] = default
    if not has_b: m['moves'][m['team_b']] = default

    ma, mb = m['moves'][m['team_a']], m['moves'][m['team_b']]
    modify_penalty = round_cfg.get('modify_penalty', 0)

    penalty_a = modify_penalty * m['modify_count'] if 'modified_move_a' in m else 0
    penalty_b = modify_penalty * m['modify_count'] if 'modified_move_b' in m else 0

    if 'modified_move_a' in m: ma = m['modified_move_a']
    if 'modified_move_b' in m: mb = m['modified_move_b']

    # HKD Adjusted Scale Payoffs (Base * approx 8)
    base_payoffs = {('keep', 'keep'): (10000, 10000), ('keep', 'cut'): (3000, 15000),
                    ('cut', 'keep'): (15000, 3000), ('cut', 'cut'): (6000, 6000)}
    base_sa, base_sb = base_payoffs.get((ma, mb), (0, 0))

    if config.get('timeout_mode') == 'zero':
        if not has_a: base_sa = 0
        if not has_b: base_sb = 0

    sa, sb = max(0, int(base_sa * skew) - penalty_a), max(0, int(base_sb * skew) - penalty_b)
    m['history'].append({'round': m['round'], 'score_a': sa, 'score_b': sb, 'move_a': ma, 'move_b': mb})

    if round_cfg.get('blind'):
        report_text = f"📊 Round {m['round']} Result:\n🙈 Results are HIDDEN this round."
    else:
        report_text = f"📊 Round {m['round']} Result:\nBlue ({ma.upper()}): +HK${sa}\nRed ({mb.upper()}): +HK${sb}"

    save_chat_to_db(s_code, m_id, "SYSTEM", report_text, "all")
    m['chat_logs'].append({'sender': 'SYSTEM', 'text': report_text, 'scope': 'all'})
    socketio.emit('receive_message', {'sender': 'SYSTEM', 'text': report_text, 'scope': 'all'}, room=m['id'],
                  namespace='/')

    if m['round'] == config['total_rounds'] and config.get('sudden_death_surprise') and not config.get(
            'sudden_death_triggered'):
        config['sudden_death_triggered'] = True
        last_cfg = config['schedule'][-1]
        for i in range(1, 3):
            extra_rnd = last_cfg.copy()
            extra_rnd['round_num'] = config['total_rounds'] + i
            extra_rnd['message'] = "Surprise! Surprise! There are two more rounds."
            config['schedule'].append(extra_rnd)
        config['total_rounds'] += 2
        log_action(s_code, "SYSTEM", "Triggered Sudden Death (+2 Rounds)")
        socketio.emit('system_broadcast', {'text': "🎁 Surprise! Surprise! There are TWO more rounds!"}, room=s_code)

    socketio.emit('round_result',
                  {'my_move': ma, 'enemy_move': mb, 'my_profit': sa, 'enemy_profit': sb, 'round': m['round'],
                   'blind': round_cfg.get('blind', False)}, room=m['team_a'])
    socketio.emit('round_result',
                  {'my_move': mb, 'enemy_move': ma, 'my_profit': sb, 'enemy_profit': sa, 'round': m['round'],
                   'blind': round_cfg.get('blind', False)}, room=m['team_b'])

    if round_cfg.get('shuffle', False): perform_shuffle(s_code, m_id)

    if config.get('sync_mode', False) and config['sync_mode'] == 'sync':
        m['status'] = 'waiting_sync'
        sd.setdefault('sync_waiting', []).append(m_id)
        m['sync_wait_start'] = time.time()
        active_matches = [mid for mid, match in sd['matches'].items() if not match.get('is_finished', False)]
        if len(sd['sync_waiting']) == len(active_matches):
            for mid in sd['sync_waiting']:
                sd['matches'][mid]['status'] = 'break'
                sd['matches'][mid]['break_end_time'] = time.time() + 5
                socketio.emit('update_timer', {'mode': 'countdown', 'value': 5}, room=mid)
            sd['sync_waiting'] = []
    else:
        m['status'] = 'break'
        m['break_end_time'] = time.time() + 5
        socketio.emit('update_timer', {'mode': 'countdown', 'value': 5}, room=m['id'])

    if 'end_time' in m: del m['end_time']
    send_admin_update(s_code)


def monitor_timeouts():
    with app.app_context():
        while True:
            socketio.sleep(1)
            try:
                now = time.time()
                for s_code in list(active_sessions.keys()):
                    sd = active_sessions[s_code]
                    if sd.get('config', {}).get('global_pause', False): continue

                    for m in list(sd['matches'].values()):
                        if m['status'] == 'playing' and 'end_time' in m:
                            remaining = int(m['end_time'] - now)
                            if remaining >= 0:
                                socketio.emit('update_timer', {'mode': 'countdown', 'value': remaining}, room=m['id'])
                            if now > m['end_time']:
                                resolve_round(s_code, m['id'])

                        elif m['status'] == 'break' and 'break_end_time' in m:
                            remaining = int(m['break_end_time'] - now)
                            if remaining <= 0:
                                start_next_round(s_code, m['id'])
                            else:
                                socketio.emit('update_timer', {'mode': 'countdown', 'value': remaining}, room=m['id'])

                        elif m['status'] == 'waiting_sync' and 'sync_wait_start' in m:
                            if now > m['sync_wait_start'] + 60:
                                if m['id'] in sd.get('sync_waiting', []): sd['sync_waiting'].remove(m['id'])
                                m['status'] = 'break'
                                m['break_end_time'] = time.time() + 5
                                socketio.emit('update_timer', {'mode': 'countdown', 'value': 5}, room=m['id'])
                            else:
                                socketio.emit('update_timer', {'mode': 'text', 'value': 'Waiting for others...'},
                                              room=m['id'])
            except Exception as e:
                print(f"❌ Monitor Error: {e}")


def _core_send_message(s_code, sid, message, scope):
    sd = active_sessions[s_code]
    p = sd['players'].get(sid)
    if not p: return
    match = sd['matches'].get(p.get('match_id'))
    if not match: return

    schedule = sd['config'].get('schedule', [])
    spy_mode = 'none'
    silent_active = False

    if 0 < match['round'] <= len(schedule):
        round_cfg = schedule[match['round'] - 1]
        spy_mode = round_cfg.get('spy', 'none')
        silent_active = round_cfg.get('silent', False)

    if silent_active and not p.get('is_bot'):
        socketio.emit('error_msg', {'msg': '🔇 Chat is disabled in Silent Mode!'}, room=sid, namespace='/')
        return

    save_chat_to_db(s_code, p.get('match_id'), p['name'], message, scope)
    match['chat_logs'].append({'sender': p['name'], 'text': message, 'scope': scope, 'team_id': p['team_id']})

    current_msg_count = match.get('spy_msg_counts', {}).get(p['team_id'], 0)
    if 'spy_msg_counts' in match: match['spy_msg_counts'][p['team_id']] += 1

    team_size = len(sd['teams'][p['team_id']]['members'])
    is_1vs1 = (team_size == 1)
    should_spy = False

    if scope == 'team' and not is_1vs1 and spy_mode != 'none':
        if spy_mode == 'all':
            should_spy = True
        elif spy_mode == '1line' and current_msg_count < 1:
            should_spy = True
        elif spy_mode == '2lines' and current_msg_count < 2:
            should_spy = True

    room_id = p['team_id'] if scope == 'team' else p['match_id']
    socketio.emit('receive_message', {'sender': p['name'], 'text': message, 'scope': scope, 'is_spy': False},
                  room=room_id, namespace='/')

    if should_spy:
        opp_team = match['team_b'] if p['team_id'] == match['team_a'] else match['team_a']
        socketio.emit('receive_message',
                      {'sender': f"🕵️ {p['name']} (Spy)", 'text': message, 'scope': 'spy', 'is_spy': True},
                      room=opp_team, namespace='/')

    p['stats']['msg_count'] += 1
    p['stats']['char_count'] += len(message)

    if not p.get('is_bot') and bot_manager:
        socketio.start_background_task(run_bot_chat, s_code, match['id'], scope, p['team_id'])


def perform_shuffle(s_code, m_id):
    sd = active_sessions.get(s_code)
    if not sd: return
    m = sd['matches'].get(m_id)
    if not m: return

    match_players = [sid for sid, p in sd['players'].items() if p.get('match_id') == m_id and not p.get('is_bot')]
    if len(match_players) < 2: return

    random.shuffle(match_players)
    half_index = len(match_players) // 2
    team_a_sids, team_b_sids = match_players[:half_index], match_players[half_index:]

    ta_id, tb_id = m['team_a'], m['team_b']
    sd['teams'][ta_id]['members'] = team_a_sids
    for sid in team_a_sids: update_player_team(sd, sid, ta_id, sd['players'][sid]['team_id'])

    sd['teams'][tb_id]['members'] = team_b_sids
    for sid in team_b_sids: update_player_team(sd, sid, tb_id, sd['players'][sid]['team_id'])

    log_action(s_code, "SYSTEM", f"Performed Shuffle on Match {m_id}")
    socketio.emit('system_broadcast', {'text': "🔀 Teams have been SHUFFLED!"}, room=m_id)


def run_bot_chat(s_code, m_id, trigger_scope='all', trigger_team_id=None):
    with app.app_context():
        sd = active_sessions.get(s_code)
        if not sd: return
        match = sd['matches'].get(m_id)
        if not match: return

        schedule = sd['config'].get('schedule', [])
        if 0 < match['round'] <= len(schedule):
            if schedule[match['round'] - 1].get('silent', False): return

        bots = [p for sid, p in sd['players'].items() if p.get('is_bot') and p.get('match_id') == m_id]

        for bot in bots:
            # If it's a private team message, ONLY bots on that team can hear/respond
            if trigger_scope == 'team' and bot['team_id'] != trigger_team_id:
                continue

            if bot_manager:
                config = bot_manager.get_config(bot['name'])
                if bot_manager.should_respond(m_id, config):

                    # Filter the chat history so the bot only sees Public msgs + its own Team's private msgs
                    visible_history = []
                    for msg in match['chat_logs']:
                        msg_scope = msg.get('scope', 'all')
                        if msg_scope == 'all' or msg_scope == 'system':
                            visible_history.append(msg)
                        elif msg_scope == 'team' and msg.get('team_id') == bot['team_id']:
                            visible_history.append(msg)

                    resp = bot_manager.generate_response(bot['name'], visible_history)
                    if resp:
                        time.sleep(2)

                        # Bot replies in the same channel the human used
                        reply_scope = trigger_scope
                        target_room = bot['team_id'] if reply_scope == 'team' else match['id']

                        match['chat_logs'].append(
                            {'sender': bot['name'], 'text': resp, 'scope': reply_scope, 'team_id': bot['team_id']})
                        bot['stats']['msg_count'] += 1
                        bot['stats']['char_count'] += len(resp)

                        socketio.emit('receive_message',
                                      {'sender': bot['name'], 'text': resp, 'scope': reply_scope, 'is_spy': False},
                                      room=target_room, namespace='/')
                        try:
                            save_chat_to_db(s_code, m_id, bot['name'], resp, reply_scope)
                        except:
                            pass


@socketio.on('send_message')
def chat(data):
    sid = request.sid
    s_code = data.get('session_code')
    if not s_code: return
    _core_send_message(s_code, sid, data['message'], data.get('scope'))


@socketio.on('admin_send_chat')
def admin_chat(data):
    s_code, m_id, msg = data.get('session_code'), data.get('match_id'), data.get('message')
    if not s_code or not m_id: return
    payload = {'sender': 'ADMIN', 'text': msg, 'scope': 'all'}
    socketio.emit('receive_message', payload, room=m_id)
    socketio.emit('receive_message', payload, room=request.sid)
    save_chat_to_db(s_code, m_id, 'ADMIN', msg, 'all')
    sd = active_sessions.get(s_code)
    if sd and m_id in sd['matches']:
        sd['matches'][m_id]['chat_logs'].append({'sender': 'ADMIN', 'text': msg, 'scope': 'all'})
        log_action(s_code, "ADMIN", f"Sent chat to Match {m_id}: {msg}")


@socketio.on('modify_move')
def handle_modify_move(data):
    sid, s_code, new_choice = request.sid, data.get('session_code'), data.get('choice')
    sd = active_sessions.get(s_code)
    p = sd['players'].get(sid) if sd else None
    match = sd['matches'].get(p.get('match_id')) if p else None
    if not match or match['status'] != 'playing': return

    round_cfg = sd['config']['schedule'][match['round'] - 1]
    if not round_cfg.get('modify_allowed'): return

    if p['team_id'] == match['team_a']:
        match['modified_move_a'] = new_choice
    else:
        match['modified_move_b'] = new_choice

    match['modify_count'] = match.get('modify_count', 0) + 1
    penalty = round_cfg.get('modify_penalty', 0) * match['modify_count']

    log_action(s_code, p['name'], f"Modified Move to {new_choice.upper()} (Penalty: {penalty})")
    socketio.emit('move_modified', {'player': p['name'], 'new_choice': new_choice, 'penalty': penalty},
                  room=p['team_id'])

    if round_cfg.get('spy', 'none') == 'decision':
        opp_team = match['team_b'] if p['team_id'] == match['team_a'] else match['team_a']
        socketio.emit('spy_move_alert', {'player': p['name'], 'move': new_choice,
                                         'msg': f"🕵️ SPY UPDATE: Opponent changed to {new_choice.upper()}"},
                      room=opp_team, namespace='/')

    send_admin_update(s_code)


@socketio.on('admin_request_details')
def admin_request_details(data):
    s_code = data.get('session_code')
    m_id = data.get('match_id')
    sd = active_sessions.get(s_code)
    if not sd or m_id not in sd['matches']: return

    m = sd['matches'][m_id]
    ta = sd['teams'][m['team_a']]
    tb = sd['teams'][m['team_b']]

    def get_avg_time(team_data):
        times = team_data.get('reaction_times', [])
        return round(sum(times) / len(times), 2) if times else 0

    score_a = sum(h['score_a'] for h in m['history'])
    score_b = sum(h['score_b'] for h in m['history'])

    response = {
        'id': m['id'],
        'team_a_name': ta.get('custom_name', 'Blue'),
        'team_b_name': tb.get('custom_name', 'Red'),
        'score_a': score_a,
        'score_b': score_b,
        'team_a_avg_time': get_avg_time(ta),
        'team_b_avg_time': get_avg_time(tb),
        'history': m['history'],
        'chat_logs': m['chat_logs']
    }
    emit('admin_receive_details', response)


@socketio.on('admin_analyze_match')
def admin_analyze_match(data):
    s_code = data.get('session_code')
    m_id = data.get('match_id')
    sd = active_sessions.get(s_code)
    if not sd or m_id not in sd['matches']: return

    if not analysis_service:
        emit('admin_analysis_result', {'match_id': m_id, 'analysis': "⚠️ Analysis Service not loaded (Check API Key)."},
             room=request.sid)
        return

    m = sd['matches'][m_id]
    ta_name = sd['teams'][m['team_a']].get('custom_name', 'Blue')
    tb_name = sd['teams'][m['team_b']].get('custom_name', 'Red')

    log_action(s_code, "ADMIN", f"Requested Analysis for Match {m_id}")
    analysis_text = analysis_service.analyze_match(m, ta_name, tb_name)
    emit('admin_analysis_result', {'match_id': m_id, 'analysis': analysis_text}, room=request.sid)


@socketio.on('admin_delete_match')
def handle_delete_match(data):
    s_code = data.get('session_code')
    m_id = data.get('match_id')
    sd = active_sessions.get(s_code)

    if not sd or m_id not in sd['matches']: return
    match = sd['matches'][m_id]

    socketio.emit('match_deleted', {'msg': 'Your negotiation has been terminated by the Admin.'}, room=m_id)

    sids_to_remove = []
    for sid, p in list(sd['players'].items()):
        if p.get('match_id') == m_id:
            sids_to_remove.append(sid)

    for sid in sids_to_remove:
        leave_room(m_id, sid=sid)
        if 'team_id' in sd['players'][sid]: leave_room(sd['players'][sid]['team_id'], sid=sid)
        del sd['players'][sid]

    if match['team_a'] in sd['teams']: del sd['teams'][match['team_a']]
    if match['team_b'] in sd['teams']: del sd['teams'][match['team_b']]
    del sd['matches'][m_id]

    if m_id in sd.get('sync_waiting', []): sd['sync_waiting'].remove(m_id)

    log_action(s_code, "ADMIN", f"Deleted Match {m_id}")
    send_admin_update(s_code)


@socketio.on('admin_kick_lobby')
def admin_kick_lobby(data):
    s_code = data.get('session_code')
    target_sid = data.get('target_sid')
    sd = active_sessions.get(s_code)
    if not sd: return

    sd['lobby'] = [p for p in sd['lobby'] if p['sid'] != target_sid]
    if target_sid in sd['players']:
        log_action(s_code, "ADMIN", f"Kicked Player {sd['players'][target_sid]['name']} from Lobby")
        del sd['players'][target_sid]

    socketio.emit('match_deleted', {'msg': 'You have been removed from the lobby by the Admin.'}, room=target_sid)
    send_admin_update(s_code)


@socketio.on('admin_delete_session')
def admin_delete_session(data):
    s_code = data.get('session_code')
    if s_code in active_sessions:
        socketio.emit('match_deleted', {'msg': 'This session has been permanently deleted by the Admin.'}, room=s_code)
        del active_sessions[s_code]


@socketio.on('admin_toggle_global_pause')
def admin_toggle_global_pause(data):
    s_code = data.get('session_code')
    is_paused = data.get('paused')
    sd = active_sessions.get(s_code)
    if not sd: return

    config = sd['config']
    config['global_pause'] = is_paused

    if is_paused:
        config['pause_start_time'] = time.time()
        log_action(s_code, "ADMIN", "Triggered Global Pause")
        socketio.emit('system_broadcast', {'text': "⏸ Admin has PAUSED the entire session."}, room=s_code)
    else:
        if 'pause_start_time' in config:
            pause_duration = time.time() - config['pause_start_time']
            for m in sd['matches'].values():
                if 'end_time' in m: m['end_time'] += pause_duration
                if 'break_end_time' in m: m['break_end_time'] += pause_duration
                if 'sync_wait_start' in m: m['sync_wait_start'] += pause_duration
            del config['pause_start_time']
        log_action(s_code, "ADMIN", "Resumed Global Pause")
        socketio.emit('system_broadcast', {'text': "▶ Session RESUMED."}, room=s_code)
    send_admin_update(s_code)


@socketio.on('admin_add_bots')
def admin_add_bots(data):
    s_code = data.get('session_code')
    if not s_code: return
    strat = data.get('strategies', {})
    for _ in range(int(strat.get('tft', 0))): add_bot(s_code, "Bot_TFT", "tft")
    for _ in range(int(strat.get('grim', 0))): add_bot(s_code, "Bot_Grim", "grim")
    for _ in range(int(strat.get('random', 0))): add_bot(s_code, "Bot_Rnd", "random")

    custom_cfg = strat.get('custom', {})
    custom_count = int(custom_cfg.get('count', 0))
    custom_prompt = custom_cfg.get('prompt', '')
    for _ in range(custom_count): add_bot(s_code, "Bot_AI", "custom", custom_prompt)

    log_action(s_code, "ADMIN", "Added Bots to Lobby")
    send_admin_update(s_code)


if __name__ == '__main__':
    with app.app_context(): db.create_all()
    socketio.run(app, host='0.0.0.0', port=5001, debug=True, use_reloader=False)
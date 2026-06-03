# Group AI Chat Bot (ACTR)

Research platform for group chat experiments with configurable AI personas, multi-session management, and **Qualtrics embedding**.

## Quick start

```bash
pip install -r requirements.txt
# Set DEEPSEEK_API_KEY in .env (OPENAI_API_KEY optional for GPT personas; see .env.example)
python main.py
```

```bash
python3 -m unittest discover -s tests -v
```

- **Home (profile):** http://localhost:8000/home — production: https://xjhuang.com/home
- **Admin:** http://localhost:8000/admin
- **Dashboard:** http://localhost:8000/dashboard
- **Qualtrics participant chat:** http://localhost:8000/embed.html

---

## Qualtrics (3 steps)

1. **Admin** — create session, enable **Qualtrics integration**, copy the HTML block from the setup guide.
2. **Survey Flow → Embedded Data** — add `transcript`, `chat_status`, and `condition` (if you use conditions).
3. **Chat question → HTML** — paste the block (includes `qualtrics-parent-snippet.js` + iframe). Use your live server (e.g. `https://group.xjhuang.com`).

Preview until the chat header shows **Connected**. After the session, see **Data & Analysis** for `transcript` and `chat_status` (`completed_full`, `left_early`, `no_messages`, `never_joined`). Or use **Dashboard → Export**.

---

## Admin experiment options

| Option | Values | Use |
|--------|--------|-----|
| **Assignment** | FIFO / Stratified | FIFO = first-come matching; Stratified = separate waiting list per `condition` value |
| **Speaking turns** | Off / Round-robin / Timed | Controls which human may send |
| **AI starts conversation** | On / Off | First bot sends opening message when room is empty |
| **Qualtrics integration** | On / Off | Transcript to Embedded Data + auto-advance via parent script |

---

## Session modes (AI orchestration)

| Mode | Behavior |
|------|----------|
| 1 | All bots may reply |
| 2 | Intent router picks one bot |
| 3 | Only bots @mentioned or named in text |

Bot **timing** modes (per bot card) control delay/skip — separate from session mode.

---

## Architecture

### Data

- **Sessions** (`SES-*`): `config/sessions.json`
- **Groups** (`GRP-*`): many per session, same config
- **Participant index**: `config/participant_index.json` (uid → group for export)
- **Messages**: `db/local_db.json` or MongoDB

### Code layout

| Layer | Location | Role |
|-------|----------|------|
| Entry | `main.py` | Uvicorn entry; exports `app` |
| Web app | `actr/factory.py` | FastAPI app, CORS, static files, startup/shutdown |
| Routes | `actr/routes/` | HTTP pages, auth, sessions, admin, matching, export, WebSocket |
| Chat runtime | `actr/group_chat.py` | Broadcast, group timeout, idle nudges |
| AI pipeline | `actr/ai_service.py` | Human/bot message handling, orchestration, chains |
| Shared | `actr/deps.py`, `actr/schemas.py`, `actr/chat_context.py` | Templates, locks, Pydantic models, DB hydrate |
| Domain | `match_manager.py`, `bot_manager.py`, `session_runtime.py`, … | Matching, personas, turns, Qualtrics export |
| UI | `templates/`, `static/` | Admin, dashboard, embed, wait/chat pages |

## Environment

| Variable | Description |
|----------|-------------|
| `ADMIN_USERNAME` | Admin login username (default `ACTR2026`) |
| `ADMIN_PASSWORD` | Admin login password (default `ACTR2026`; **change in production**) |
| `ADMIN_AUTH_SECRET` | Optional fixed cookie token instead of derived hash |
| `ADMIN_COOKIE_SECURE` | Set `true` when served over HTTPS (Secure cookie flag) |
| `LLM_PROVIDER` | Default for new personas without a model: `deepseek` (default) or `openai` |
| `DEEPSEEK_API_KEY` | DeepSeek API ([platform](https://platform.deepseek.com/api_keys)); required for default bots |
| `OPENAI_API_KEY` | OpenAI API; required only for personas using GPT models in Admin |
| `DEEPSEEK_CHAT_MODEL` | Default `deepseek-chat` (or `deepseek-reasoner`) when `LLM_PROVIDER=deepseek` |
| `OPENAI_CHAT_MODEL` | Default `gpt-5` / `gpt-5.5` / `gpt-4o` when `LLM_PROVIDER=openai` |
| `DEEPSEEK_AUX_MODEL` | Orchestrator / scoring on DeepSeek (default `deepseek-chat`) |
| `OPENAI_AUX_MODEL` | Orchestrator / scoring on OpenAI (default `gpt-5-mini` when `LLM_PROVIDER=openai`) |
| `GROUP_SPEND_CAP_USD` | Max estimated API spend per chat group (default `8.0`) |
| `SESSION_SPEND_CAP_USD` | Optional cap per session (all groups combined) |
| `ALERT_EMAIL_TO` | Ops mail group (comma-separated); all cap alerts + burst/hourly |
| `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_FROM` | Outbound mail for alerts |
| `ALERT_CAP_WARN_RATIO` | Level 1 cap warning threshold (default `0.8` = 80%) |
| `ALERT_HOURLY_SPEND_USD` | Burst alert if current hour spend exceeds this (default `40`) |
| `ALERT_GROUP_BURST_USD` | Burst alert if one group total exceeds this (default `15`) |
| `ALERT_COOLDOWN_MINUTES` | Min minutes between burst/hourly emails (default `30`) |

Per-persona **model** is set in Admin (DeepSeek Chat / Reasoner or GPT-5.5 / GPT-5 / GPT-4o). API routing follows the model id. Example preset uses **deepseek-chat** for both a and b; pick a GPT model there to use OpenAI for that bot.
| `MONGO_URL` | Optional MongoDB |

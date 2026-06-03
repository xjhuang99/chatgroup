"""Bot orchestration, replies, and message persistence pipeline."""

import asyncio
import random
from typing import Dict, List, Optional

from activity_logger import activity_logger
from bot_interaction import (
    all_peer_names,
    apply_mention_prefix,
    bots_for_message,
    build_mention_system_note,
    filter_bots_for_trigger,
    interaction_settings,
    maybe_self_correction,
    pick_mention_target,
    schedule_bot_chain,
)
from bot_manager import (
    analyze_intent,
    assess_reply_probability,
    build_style_mimic_hint,
    compute_typing_delay_seconds,
    get_or_create_bot_from_cfg,
    jitter_delay_extra,
    persona_mode4_reply_threshold,
    persona_mode4_should_reply,
    resolve_chat_model,
)
from chat_log import append_chat_log_event
from bot_queue import BotResponse, bot_response_queue
from usage_tracker import SpendCapExceeded, check_can_spend
from cache_manager import cache_manager
from context_manager import get_context, get_or_create_context, resolve_context_max_chars
from db.database import save_message
from error_handler import error_handler
from group_idle import is_group_chat_live
from match_manager import match_manager

from actr.deps import DEFAULT_IDLE_THRESHOLD, get_group_lock, touch_group_activity
from actr.group_chat import broadcast, reset_idle_timer
from actr.room_context import (
    commit_room_message,
    get_context_version,
    init_room_context_state,
    is_context_stale,
    is_parallel_session,
    mode4_settings,
    refresh_user_text_suffix,
    transcript_note_for_refresh,
)


async def _persona_mode4_gate(
    session_id: str,
    group_id: str,
    bot_cfg: Dict,
    bot_name: str,
    user_id: str,
    user_text: str,
    history_summary: str,
    peer_names: List[str],
) -> bool:
    """Persona mode 4: model score vs threshold (no random roll). Returns True to proceed."""
    reply_p = await assess_reply_probability(
        bot_name,
        bot_cfg.get("prompt", ""),
        user_id,
        user_text,
        history_summary,
        peer_names=peer_names,
        session_id=session_id,
        group_id=group_id,
    )
    threshold = persona_mode4_reply_threshold(bot_cfg)
    will_reply = persona_mode4_should_reply(bot_cfg, reply_p)
    append_chat_log_event(
        session_id,
        group_id,
        "persona_mode4_assess",
        {
            "p_reply": round(reply_p, 3),
            "threshold": threshold,
            "decision": "reply" if will_reply else "skip",
            "trigger_user": user_id,
            "trigger_text": (user_text or "")[:500],
        },
        actor=bot_name,
    )
    print(
        f"[BOT]    Persona mode 4 {bot_name}: P(reply)={reply_p:.2f} "
        f"threshold={threshold:.2f} → {'reply' if will_reply else 'skip'}"
    )
    if not will_reply:
        activity_logger.log_bot_skipped(
            session_id,
            group_id,
            bot_name,
            reason="persona_mode4_below_threshold",
            extra={"p_reply": reply_p, "threshold": threshold},
        )
        return False
    return True


def _log_llm_turn(
    session_id: str,
    group_id: str,
    bot_name: str,
    bot_cfg: Dict,
    *,
    attempt: int,
    user_text: str,
    gen_user_text: str,
    summary_chars: int,
    model: str,
    refresh_suffix: str = "",
) -> None:
    append_chat_log_event(
        session_id,
        group_id,
        "llm_request",
        {
            "attempt": attempt + 1,
            "model": model,
            "persona_prompt": (bot_cfg.get("prompt") or "")[:4000],
            "trigger_text": (user_text or "")[:800],
            "llm_user_text": (gen_user_text or "")[:2000],
            "context_summary_chars": summary_chars,
            "refresh_suffix": refresh_suffix or None,
        },
        actor=bot_name,
    )


async def _sleep_unless_stale(
    seconds: float,
    group_info: Dict,
    version_at_start: int,
    bot_name: str,
    group_id: str,
) -> bool:
    """Sleep up to seconds; return False if room cancelled or peer bumped context."""
    elapsed = 0.0
    step = 0.2
    while elapsed < seconds:
        if bot_response_queue.is_room_cancelled(group_id):
            return False
        if is_context_stale(group_info, version_at_start, bot_name):
            return False
        chunk = min(step, seconds - elapsed)
        await asyncio.sleep(chunk)
        elapsed += chunk
    return not is_context_stale(group_info, version_at_start, bot_name)


async def _staggered_enqueue(
    session_id: str,
    group_id: str,
    display_name: str,
    data: str,
    bot_cfg: Dict,
    session_cfg,
    ctx,
    group_info: Dict,
    chain_depth: int,
    settings: Dict,
    jitter_max: float,
) -> None:
    if jitter_max > 0:
        await asyncio.sleep(random.uniform(0, jitter_max))
    await _enqueue_single_bot(
        session_id,
        group_id,
        display_name,
        data,
        bot_cfg,
        session_cfg,
        ctx,
        group_info,
        chain_depth,
        settings,
    )


async def batch_save_messages(_msg_type: str, messages: list) -> None:
    """Persist callback for cache_manager: batch-saves cached messages to DB."""
    for msg in messages:
        await save_message(msg["room_id"], msg["sender"], msg["text"])


async def _enqueue_single_bot(
    session_id: str,
    group_id: str,
    display_name: str,
    data: str,
    bot_cfg: Dict,
    session_cfg,
    ctx,
    group_info: Dict,
    chain_depth: int,
    settings: Dict,
) -> None:
    bot_instance = get_or_create_bot_from_cfg(group_id, bot_cfg, group_info)
    max_ctx = resolve_context_max_chars(bot_cfg)
    full_summary = ctx.get_context_summary(max_chars=max_ctx)

    async def handler(resp):
        fresh_ctx = get_context(resp.room_id)
        latest_summary = (
            fresh_ctx.get_context_summary(max_chars=max_ctx) if fresh_ctx else full_summary
        )
        await handle_bot_reply(
            session_id,
            resp.room_id,
            resp.user_id,
            resp.user_text,
            bot_instance,
            latest_summary,
            bot_cfg,
            group_info,
            chain_depth=chain_depth,
            settings=settings,
        )

    await bot_response_queue.enqueue(
        BotResponse(
            room_id=group_id,
            bot_name=bot_cfg["name"],
            user_id=display_name,
            user_text=data,
            priority=1,
            handler=handler,
        )
    )
    activity_logger.log_bot_triggered(session_id, group_id, bot_cfg["name"])


async def _orchestrate_bot_replies(
    session_id: str,
    group_id: str,
    display_name: str,
    data: str,
    session_cfg,
    ctx,
    group_info: Dict,
    chain_depth: int,
    settings: Dict,
) -> None:
    if not (session_cfg.bot_enabled and session_cfg.bots):
        return
    if bot_response_queue.is_room_cancelled(group_id):
        return
    allowed, reason = check_can_spend(session_id, group_id, group_info)
    if not allowed:
        print(f"[AI] 🛑 Spend cap / ended: {reason}")
        return

    mode = session_cfg.session_mode
    print(f"[AI] 🤖 Orchestrate mode={mode} chain_depth={chain_depth}")

    bot_list: List[Dict] = []
    if mode == 2:
        intent_ctx = resolve_context_max_chars(session_cfg.bots[0] if session_cfg.bots else {})
        history_text = ctx.get_context_summary(max_chars=min(50_000, intent_ctx))
        chosen_name = await analyze_intent(
            data, session_cfg.bots, history_text, session_id=session_id, group_id=group_id
        )
        if not chosen_name:
            chosen_name = random.choice(session_cfg.bots)["name"]
        bot_cfg = next((b for b in session_cfg.bots if b["name"] == chosen_name), None)
        if bot_cfg:
            bot_list = [bot_cfg]
    else:
        bot_list = bots_for_message(session_cfg, data)

    bot_list = filter_bots_for_trigger(bot_list, display_name)

    if not bot_list:
        return

    if is_parallel_session(session_cfg):
        jitter_max, _, _ = mode4_settings(session_cfg)
        bot_response_queue.set_room_concurrency(group_id, len(bot_list))
        init_room_context_state(group_info)
        print(f"[AI]    → Mode 4 parallel queue ({len(bot_list)} bots, jitter≤{jitter_max}s)")
        tasks = [
            asyncio.create_task(
                _staggered_enqueue(
                    session_id,
                    group_id,
                    display_name,
                    data,
                    bot_cfg,
                    session_cfg,
                    ctx,
                    group_info,
                    chain_depth,
                    settings,
                    jitter_max,
                )
            )
            for bot_cfg in bot_list
        ]
        await asyncio.gather(*tasks)
    else:
        bot_response_queue.set_room_concurrency(group_id, 1)
        for bot_cfg in bot_list:
            print(f"[AI]    → Queueing bot: {bot_cfg['name']}")
            await _enqueue_single_bot(
                session_id,
                group_id,
                display_name,
                data,
                bot_cfg,
                session_cfg,
                ctx,
                group_info,
                chain_depth,
                settings,
            )
    await bot_response_queue.ensure_queue_processor(group_id)


async def process_ai_logic(
    session_id: str,
    group_id: str,
    display_name: str,
    data: str,
    chain_depth: int = 0,
    trigger_kind: str = "human",
) -> None:
    """Background processing: persist (human only), then bot orchestration with chain depth."""
    try:
        session_cfg = match_manager.get_session(session_id)
        if not session_cfg:
            print(f"[AI] ❌ No session config for {session_id}")
            return

        settings = interaction_settings(session_cfg)
        if chain_depth > 0 and not settings["bot_reply_on_any_message"]:
            return

        print(
            f"[AI] 📨 process_ai_logic: session={session_id} group={group_id} "
            f"from={display_name} chain={chain_depth} kind={trigger_kind} msg={data[:60]!r}"
        )

        group_info = match_manager.get_group_info(session_id, group_id)
        if not group_info or group_info.get("ended"):
            print(f"[AI] 🔚 Group {group_id} ended, skipping AI")
            return
        if group_info.get("paused", False):
            print(f"[AI] ⏸ Room {group_id} is paused, skipping AI")
            return
        if bot_response_queue.is_room_cancelled(group_id):
            return
        allowed, cap_reason = check_can_spend(session_id, group_id, group_info)
        if not allowed:
            print(f"[AI] 🛑 {cap_reason}")
            return

        limit = match_manager.resolve_history_limit(session_cfg)
        ctx = get_or_create_context(group_id, max_messages=limit)

        if chain_depth == 0 and trigger_kind == "human":
            should_flush = cache_manager.cache_message(group_id, display_name, data)
            init_room_context_state(group_info)
            if is_parallel_session(session_cfg):
                await commit_room_message(
                    group_id, display_name, data, group_info, bump_for_peers=True
                )
            else:
                await save_message(group_id, display_name, data)
                ctx.add_message(display_name, data)
            activity_logger.log_user_message(session_id, group_id, display_name, data)
            append_chat_log_event(
                session_id,
                group_id,
                "human_message",
                {"text": data[:2000]},
                actor=display_name,
            )
            if is_group_chat_live(match_manager, session_id, group_id):
                reset_idle_timer(session_id, group_id, DEFAULT_IDLE_THRESHOLD)
            if should_flush:
                await cache_manager.flush_messages(group_id)

        await _orchestrate_bot_replies(
            session_id,
            group_id,
            display_name,
            data,
            session_cfg,
            ctx,
            group_info,
            chain_depth,
            settings,
        )

    except SpendCapExceeded as e:
        print(f"[AI] 🛑 process_ai_logic capped: {e}")
    except Exception as e:
        error_id = error_handler.handle_exception(e, "process_ai_logic")
        activity_logger.log_error(session_id, error_id, "process_ai_logic")


async def _handle_bot_reply_mode4(
    session_id: str,
    group_id: str,
    user_id: str,
    user_text: str,
    bot,
    bot_cfg,
    group_info: Dict,
    chain_depth: int,
    settings: Dict,
) -> None:
    """Parallel personas: refresh on peer commits; transcript notes on refresh attempts."""
    session_cfg = match_manager.get_session(session_id)
    if not session_cfg:
        return
    init_room_context_state(group_info)
    jitter_max, rethink_seconds, max_refresh_attempts = mode4_settings(session_cfg)
    max_ctx = resolve_context_max_chars(bot_cfg)
    persona_mode = bot_cfg.get("mode", 1)
    delay = bot_cfg.get("delay_seconds", 2)
    typing_cps = max(1, min(6, float(bot_cfg.get("typing_cps", 4))))
    idle_threshold = bot_cfg.get("idle_threshold", DEFAULT_IDLE_THRESHOLD)

    peer_names = all_peer_names(session_cfg, group_info, exclude=bot.name)
    mention_target = pick_mention_target(user_id, user_text, peer_names, settings)
    mention_note = build_mention_system_note(settings)

    if persona_mode == 3:
        if random.random() < bot_cfg.get("skip_rate", 0.2):
            activity_logger.log_bot_skipped(
                session_id, group_id, bot.name, reason="persona_mode3_skip"
            )
            append_chat_log_event(
                session_id, group_id, "bot_skipped",
                {"reason": "persona_mode3_skip", "skip_rate": bot_cfg.get("skip_rate")},
                actor=bot.name,
            )
            return
    elif persona_mode == 4:
        ctx = get_context(group_id)
        summary = ctx.get_context_summary(max_chars=max_ctx) if ctx else ""
        if not await _persona_mode4_gate(
            session_id, group_id, bot_cfg, bot.name, user_id, user_text, summary, peer_names
        ):
            return

    clean_text = user_text.replace(f"@{bot.name}", "").strip()
    if not clean_text:
        clean_text = "Continue the conversation naturally based on prior context."

    for attempt in range(max_refresh_attempts):
        version_at_start = get_context_version(group_info)
        if bot_response_queue.is_room_cancelled(group_id):
            return
        if not is_group_chat_live(match_manager, session_id, group_id):
            return

        pre_delay = delay
        if persona_mode in (2, 3, 4):
            pre_delay = delay + jitter_delay_extra()
        if attempt > 0:
            if not await _sleep_unless_stale(
                rethink_seconds, group_info, version_at_start, bot.name, group_id
            ):
                print(f"[BOT]    Mode4 {bot.name}: rethink interrupted (peer message)")
                continue
        elif not await _sleep_unless_stale(
            pre_delay, group_info, version_at_start, bot.name, group_id
        ):
            print(f"[BOT]    Mode4 {bot.name}: pre_delay interrupted (peer message)")
            continue

        ctx = get_context(group_id)
        full_summary = ctx.get_context_summary(max_chars=max_ctx) if ctx else ""
        gen_user_text = clean_text
        refresh_suffix = ""
        if attempt > 0:
            refresh_suffix = refresh_user_text_suffix(group_info, attempt)
            gen_user_text = clean_text + "\n" + refresh_suffix

        max_words = int(bot_cfg.get("max_words", 35))
        min_words = int(bot_cfg.get("min_words", 1))
        if min_words > max_words:
            min_words = max_words

        style_hint = ""
        if getattr(session_cfg, "style_mimic_enabled", False):
            target = (getattr(session_cfg, "style_mimic_target", None) or "c").strip()
            style_hint = await build_style_mimic_hint(
                group_id, target, bot.name, session_id=session_id
            )

        model = resolve_chat_model(bot_cfg)
        _log_llm_turn(
            session_id,
            group_id,
            bot.name,
            bot_cfg,
            attempt=attempt,
            user_text=user_text,
            gen_user_text=gen_user_text,
            summary_chars=len(full_summary or ""),
            model=model,
            refresh_suffix=refresh_suffix,
        )
        reply = await bot.generate_response(
            user_id,
            gen_user_text,
            full_summary,
            temperature=bot_cfg.get("temperature", 0.7),
            peer_names=peer_names,
            max_words=max_words,
            min_words=min_words,
            length_variation=bool(bot_cfg.get("length_variation", True)),
            style_mimic_hint=style_hint or None,
            max_tokens=bot_cfg.get("max_tokens"),
            mention_note=mention_note or None,
            mention_target=mention_target,
            emoji_enabled=bool(bot_cfg.get("emoji_enabled", False)),
            model=model,
            session_id=session_id,
        )
        if not reply:
            return
        if is_context_stale(group_info, version_at_start, bot.name):
            print(f"[BOT]    Mode4 {bot.name}: discard draft (attempt {attempt + 1})")
            append_chat_log_event(
                session_id,
                group_id,
                "mode4_refresh_discard",
                {"attempt": attempt + 1, "reason": "peer_message_during_generate"},
                actor=bot.name,
            )
            continue

        reply = apply_mention_prefix(reply, mention_target, settings)
        typing_delay = compute_typing_delay_seconds(reply, typing_cps)
        if not await _sleep_unless_stale(
            typing_delay, group_info, version_at_start, bot.name, group_id
        ):
            print(f"[BOT]    Mode4 {bot.name}: typing interrupted (peer message)")
            append_chat_log_event(
                session_id,
                group_id,
                "mode4_refresh_discard",
                {"attempt": attempt + 1, "reason": "peer_message_during_typing"},
                actor=bot.name,
            )
            continue

        append_chat_log_event(
            session_id,
            group_id,
            "llm_response",
            {"attempt": attempt + 1, "reply": reply, "typing_delay_sec": round(typing_delay, 2)},
            actor=bot.name,
        )

        note = None
        if attempt > 0:
            note = transcript_note_for_refresh(
                attempt,
                group_info.get("last_context_bump_sender") or "?",
                group_info.get("last_context_bump_text") or "",
            )

        async with get_group_lock(group_id):
            if is_context_stale(group_info, version_at_start, bot.name):
                continue
            should_flush = cache_manager.cache_message(group_id, bot.name, reply)
            await commit_room_message(
                group_id, bot.name, reply, group_info, note=note, bump_for_peers=True
            )
            await broadcast(
                session_id, group_id, {"type": "message", "sender": bot.name, "text": reply}
            )
            touch_group_activity(session_id, group_id)
            if should_flush:
                await cache_manager.flush_messages(group_id)

        activity_logger.log_bot_response(session_id, group_id, bot.name, reply, persona_mode)
        if is_group_chat_live(match_manager, session_id, group_id):
            reset_idle_timer(session_id, group_id, idle_threshold)
            schedule_bot_chain(
                session_id,
                group_id,
                bot.name,
                reply,
                chain_depth,
                settings,
                process_ai_logic,
            )

        def _append_ctx(gid: str, sender: str, text: str):
            c = get_context(gid)
            if c:
                c.add_message(sender, text)

        asyncio.create_task(
            maybe_self_correction(
                session_id,
                group_id,
                bot.name,
                reply,
                settings,
                broadcast,
                save_message,
                cache_manager.cache_message,
                _append_ctx,
            )
        )
        return

    print(f"[BOT]    Mode4 {bot.name}: abandoned after {max_refresh_attempts} refresh attempts")
    activity_logger.log_bot_skipped(
        session_id, group_id, bot.name, reason="mode4_max_refresh_exhausted"
    )
    append_chat_log_event(
        session_id,
        group_id,
        "bot_skipped",
        {"reason": "mode4_max_refresh_exhausted", "max_refresh_attempts": max_refresh_attempts},
        actor=bot.name,
    )


async def handle_bot_reply(
    session_id: str,
    group_id: str,
    user_id: str,
    user_text: str,
    bot,
    full_summary,
    bot_cfg,
    group_info=None,
    chain_depth: int = 0,
    settings: Optional[Dict] = None,
) -> None:
    """Handles persona-specific AI generation and broadcasting."""
    try:
        print(
            f"[BOT] 🟡 handle_bot_reply started: bot={bot.name} group={group_id} chain={chain_depth}"
        )
        session_cfg = match_manager.get_session(session_id)
        group_info = group_info or match_manager.get_group_info(session_id, group_id) or {}
        if settings is None and session_cfg:
            settings = interaction_settings(session_cfg)
        if session_cfg and is_parallel_session(session_cfg):
            await _handle_bot_reply_mode4(
                session_id,
                group_id,
                user_id,
                user_text,
                bot,
                bot_cfg,
                group_info,
                chain_depth,
                settings or interaction_settings(session_cfg),
            )
            return

        async with get_group_lock(group_id):
            if bot_response_queue.is_room_cancelled(group_id):
                return
            if not is_group_chat_live(match_manager, session_id, group_id):
                print(f"[BOT] 🔚 Group {group_id} ended, skip reply for {bot.name}")
                return
            mode = bot_cfg.get("mode", 1)
            delay = bot_cfg.get("delay_seconds", 2)
            typing_cps = max(1, min(6, float(bot_cfg.get("typing_cps", 4))))
            idle_threshold = bot_cfg.get("idle_threshold", DEFAULT_IDLE_THRESHOLD)

            print(
                f"[BOT]    mode={mode} model={resolve_chat_model(bot_cfg)} delay={delay}s "
                f"max_tokens={bot_cfg.get('max_tokens',200)} temp={bot_cfg.get('temperature',0.7)}"
            )

            session_cfg = match_manager.get_session(session_id)
            group_info = group_info or match_manager.get_group_info(session_id, group_id) or {}
            if settings is None:
                settings = interaction_settings(session_cfg)

            peer_names = all_peer_names(session_cfg, group_info, exclude=bot.name)
            mention_target = pick_mention_target(user_id, user_text, peer_names, settings)
            mention_note = build_mention_system_note(settings)

            if mode == 3:
                if random.random() < bot_cfg.get("skip_rate", 0.2):
                    activity_logger.log_bot_skipped(
                        session_id, group_id, bot.name, reason="persona_mode3_skip"
                    )
                    append_chat_log_event(
                        session_id, group_id, "bot_skipped",
                        {"reason": "persona_mode3_skip"},
                        actor=bot.name,
                    )
                    return
            elif mode == 4:
                if not await _persona_mode4_gate(
                    session_id,
                    group_id,
                    bot_cfg,
                    bot.name,
                    user_id,
                    user_text,
                    full_summary,
                    peer_names,
                ):
                    return

            pre_delay = delay
            if mode in (2, 3, 4):
                pre_delay = delay + jitter_delay_extra()
            await asyncio.sleep(pre_delay)

            clean_text = user_text.replace(f"@{bot.name}", "").strip()
            if not clean_text:
                clean_text = "Continue the conversation naturally based on prior context."

            max_words = int(bot_cfg.get("max_words", 35))
            min_words = int(bot_cfg.get("min_words", 1))
            if min_words > max_words:
                min_words = max_words
            length_variation = bool(bot_cfg.get("length_variation", True))
            emoji_enabled = bool(bot_cfg.get("emoji_enabled", False))

            style_hint = ""
            if session_cfg and getattr(session_cfg, "style_mimic_enabled", False):
                target = (getattr(session_cfg, "style_mimic_target", None) or "c").strip()
                style_hint = await build_style_mimic_hint(
                    group_id, target, bot.name, session_id=session_id
                )
                if style_hint:
                    print(f"[BOT]    style mimic '{target}' → {bot.name}")

            model = resolve_chat_model(bot_cfg)
            _log_llm_turn(
                session_id,
                group_id,
                bot.name,
                bot_cfg,
                attempt=0,
                user_text=user_text,
                gen_user_text=clean_text,
                summary_chars=len(full_summary or ""),
                model=model,
            )
            print(f"[BOT] 🔄 Calling generate_response for {bot.name}...")
            reply = await bot.generate_response(
                user_id,
                clean_text,
                full_summary,
                temperature=bot_cfg.get("temperature", 0.7),
                peer_names=peer_names,
                max_words=max_words,
                min_words=min_words,
                length_variation=length_variation,
                style_mimic_hint=style_hint or None,
                max_tokens=bot_cfg.get("max_tokens"),
                mention_note=mention_note or None,
                mention_target=mention_target,
                emoji_enabled=emoji_enabled,
                model=model,
                session_id=session_id,
            )
            if not reply:
                print(f"[BOT] ⚠️ {bot.name} returned empty reply")
                return

            append_chat_log_event(
                session_id,
                group_id,
                "llm_response",
                {"attempt": 1, "reply": reply},
                actor=bot.name,
            )
            reply = apply_mention_prefix(reply, mention_target, settings)

            typing_delay = compute_typing_delay_seconds(reply, typing_cps)
            print(f"[BOT] ✅ {bot.name} reply: {reply[:80]!r} (typing +{typing_delay:.1f}s)")
            await asyncio.sleep(typing_delay)
            await broadcast(session_id, group_id, {"type": "message", "sender": bot.name, "text": reply})
            touch_group_activity(session_id, group_id)

            should_flush = cache_manager.cache_message(group_id, bot.name, reply)
            await save_message(group_id, bot.name, reply)

            ctx = get_context(group_id)
            if ctx:
                ctx.add_message(bot.name, reply)
                cache_manager.invalidate_summary(group_id)

            if should_flush:
                await cache_manager.flush_messages(group_id)

            activity_logger.log_bot_response(session_id, group_id, bot.name, reply, mode)
            if is_group_chat_live(match_manager, session_id, group_id):
                reset_idle_timer(session_id, group_id, idle_threshold)
                schedule_bot_chain(
                    session_id,
                    group_id,
                    bot.name,
                    reply,
                    chain_depth,
                    settings,
                    process_ai_logic,
                )

            def _append_ctx(gid: str, sender: str, text: str):
                c = get_context(gid)
                if c:
                    c.add_message(sender, text)

            asyncio.create_task(
                maybe_self_correction(
                    session_id,
                    group_id,
                    bot.name,
                    reply,
                    settings,
                    broadcast,
                    save_message,
                    cache_manager.cache_message,
                    _append_ctx,
                )
            )

    except Exception as e:
        error_id = error_handler.handle_exception(e, "handle_bot_reply")
        activity_logger.log_error(session_id, error_id, "handle_bot_reply")

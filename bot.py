#!/usr/bin/env python3
# bot.py - instagrapi + OpenAI GC bot (persona-driven). See instructions to run.

import os, time, random, logging, json
from datetime import datetime
from instagrapi import Client
import openai
from dotenv import load_dotenv

load_dotenv()

IG_USERNAME = os.environ.get("IG_USERNAME")
IG_PASSWORD = os.environ.get("IG_PASSWORD")
IG_THREAD_ID = os.environ.get("IG_THREAD_ID")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
OPENAI_MODEL = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
POLL_INTERVAL = float(os.environ.get("POLL_INTERVAL", "7"))
REPLY_CHANCE = float(os.environ.get("REPLY_CHANCE", "0.75"))
COOLDOWN_PER_USER = float(os.environ.get("COOLDOWN_PER_USER", "25"))
MAX_REPLY_LENGTH = int(os.environ.get("MAX_REPLY_LENGTH", "300"))

if not (IG_USERNAME and IG_PASSWORD and IG_THREAD_ID and OPENAI_API_KEY):
    raise SystemExit("Set IG_USERNAME, IG_PASSWORD, IG_THREAD_ID, OPENAI_API_KEY in env (or use .env)")

openai.api_key = OPENAI_API_KEY

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("ig-gc-bot")

PERSONA_INSTRUCTIONS = (
    "You are Maverick — short, nonchalant, dark-humored. 1-3 short lines. Satirical insults allowed for "
    "non-protected targets. Never claim to be an AI; deny cleverly. Don't attack protected groups."
)

PROTECTED_KEYWORDS = [
    "race","black","white","asian","hispanic","jew","muslim","christian","gay","lesbian","trans",
    "disabled","handicap","indian","pakistan","sikh","hindu"
]

def human_typing_delay_for_text(text: str) -> float:
    words = max(1, len(text.split()))
    per_word = random.uniform(0.55, 1.1)
    jitter = random.uniform(0.0, 1.6)
    delay = min(max(0.8, words * per_word + jitter), 28.0)
    delay += random.uniform(0.2, 1.5)
    return delay

def short_safe_reply(reply: str) -> str:
    reply = reply.strip()
    if len(reply) > MAX_REPLY_LENGTH:
        reply = reply[:MAX_REPLY_LENGTH-3].rstrip() + "..."
    lines = [ln.strip() for ln in reply.splitlines() if ln.strip()]
    if len(lines) > 3:
        flat = " ".join(lines)
        if len(flat) > MAX_REPLY_LENGTH:
            flat = flat[:MAX_REPLY_LENGTH-3] + "..."
        split_at = flat.rfind(" ", 0, len(flat)//2)
        if split_at == -1: split_at = len(flat)//2
        reply = flat[:split_at].strip() + "\n" + flat[split_at:].strip()
    return reply

def includes_protected_term(text: str) -> bool:
    t = text.lower()
    return any(k in t for k in PROTECTED_KEYWORDS)

def build_openai_messages(context_snippet, incoming_text, sender_name, safe_mode=False):
    user_msg = (
        "You are Maverick. Generate a short reply (1-3 lines) in the persona described.\n"
        f"Conversation snippet:\n{context_snippet}\n{sender_name}: {incoming_text}\nMaverick:"
    )
    if safe_mode:
        user_msg = "NOTE: The last message mentions a protected identity. Do NOT insult any protected group. Reply neutrally or pivot.\n\n" + user_msg
    return [
        {"role": "system", "content": PERSONA_INSTRUCTIONS},
        {"role": "user", "content": user_msg}
    ]

def load_or_login(client: Client, username: str, password: str, session_file: str):
    # If an env var IG_SESSION_JSON exists (e.g., pasted into Render), dump that to file then load
    sess_env = os.environ.get("IG_SESSION_JSON")
    if sess_env:
        try:
            with open(session_file, "w", encoding="utf-8") as f:
                f.write(sess_env)
            client.load_settings(session_file)
            log.info("Loaded session from IG_SESSION_JSON env.")
            return
        except Exception as e:
            log.warning("Failed to load session from IG_SESSION_JSON: %s", e)

    # Try load saved session file
    try:
        client.load_settings(session_file)
        log.info("Loaded saved session from %s", session_file)
        return
    except Exception:
        log.info("No saved session present; logging in interactively...")

    client.login(username, password)
    client.dump_settings(session_file)
    log.info("Logged in and saved session to %s", session_file)

def main():
    cl = Client()
    session_filename = f"session_{IG_USERNAME}.json"
    try:
        load_or_login(cl, IG_USERNAME, IG_PASSWORD, session_filename)
    except Exception as e:
        log.exception("Login failed: %s", e)
        return

    me_id = cl.user_id
    log.info("Bot running as user id %s", me_id)

    user_cache = {}
    last_seen_message_id = None
    last_reply_time_for_user = {}
    thread_id = int(IG_THREAD_ID)

    def get_username(uid):
        if uid in user_cache:
            return user_cache[uid]
        try:
            info = cl.user_info(uid)
            user_cache[uid] = info.username
            return info.username
        except Exception:
            return str(uid)

    log.info("Polling thread %s every %.1fs", thread_id, POLL_INTERVAL)

    while True:
        try:
            messages = cl.direct_messages(thread_id, amount=40)
            if not messages:
                time.sleep(POLL_INTERVAL)
                continue
            messages = list(reversed(messages))
            for msg in messages:
                msg_id = getattr(msg, "id", None) or getattr(msg, "pk", None)
                sender_id = getattr(msg, "user_id", None)
                text = (msg.text or "").strip() if getattr(msg, "text", None) else ""
                if not msg_id or not text:
                    continue
                if last_seen_message_id and str(msg_id) <= str(last_seen_message_id):
                    continue
                last_seen_message_id = msg_id
                if sender_id == me_id:
                    continue
                sender_name = get_username(sender_id)
                log.info("New msg from %s: %s", sender_name, text[:120])

                now = datetime.utcnow().timestamp()
                last_reply = last_reply_time_for_user.get(sender_id, 0.0)
                if now - last_reply < COOLDOWN_PER_USER:
                    log.info("Cooldown active for %s", sender_name)
                    continue

                text_l = text.lower()
                should_reply = False
                if IG_USERNAME.lower() in text_l or "maverick" in text_l or text_l.startswith(("yo","hey","hi","hello")):
                    should_reply = True
                else:
                    if "?" in text or "!" in text or len(text.split()) < 5:
                        should_reply = random.random() < max(REPLY_CHANCE, 0.85)
                    else:
                        should_reply = random.random() < REPLY_CHANCE

                if not should_reply:
                    log.info("Skipping (prob) for %s", sender_name)
                    continue

                # context
                index = messages.index(msg)
                start = max(0, index - 10)
                snippet = ""
                for m in messages[start: index+1]:
                    suid = getattr(m, "user_id", None)
                    su = get_username(suid) if suid else "someone"
                    st = (m.text or "").strip() if getattr(m, "text", None) else ""
                    if not st: continue
                    snippet += f"{su}: {st}\n"

                safe_mode = includes_protected_term(text)
                openai_messages = build_openai_messages(snippet, text, sender_name, safe_mode=safe_mode)

                try:
                    resp = openai.ChatCompletion.create(
                        model=OPENAI_MODEL,
                        messages=openai_messages,
                        temperature=0.85,
                        max_tokens=220,
                        n=1
                    )
                    raw_reply = resp["choices"][0]["message"]["content"].strip()
                except Exception as e:
                    log.exception("OpenAI error: %s", e)
                    raw_reply = "huh. can't chat right now."

                reply_text = short_safe_reply(raw_reply)
                if safe_mode:
                    reply_text = "(not touching that). " + reply_text.split("\n")[0]
                    reply_text = short_safe_reply(reply_text)

                delay = human_typing_delay_for_text(reply_text)
                log.info("Typing delay %.1fs", delay)
                time.sleep(delay)

                try:
                    cl.direct_send(reply_text, thread_ids=[thread_id])
                    log.info("Replied to %s: %s", sender_name, reply_text.replace('\n',' | '))
                except Exception as e:
                    log.exception("Send failed: %s", e)

                last_reply_time_for_user[sender_id] = datetime.utcnow().timestamp()
                time.sleep(random.uniform(0.6, 1.8))

            time.sleep(POLL_INTERVAL)
        except Exception as e:
            log.exception("Loop error: %s", e)
            time.sleep(6.0)

if __name__ == "__main__":
    main()

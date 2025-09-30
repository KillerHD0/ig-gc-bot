# find_thread.py
import os
from instagrapi import Client
from dotenv import load_dotenv
load_dotenv()

IG_USERNAME = os.environ.get("IG_USERNAME")
IG_PASSWORD = os.environ.get("IG_PASSWORD")
session_file = f"session_{IG_USERNAME}.json"

cl = Client()
try:
    cl.load_settings(session_file)
except Exception:
    cl.login(IG_USERNAME, IG_PASSWORD)
    cl.dump_settings(session_file)

threads = cl.direct_threads(amount=100)
for t in threads:
    t_id = getattr(t, "id", None) or getattr(t, "thread_id", None)
    title = getattr(t, "title", None)
    users = getattr(t, "users", None) or []
    usernames = [u.username for u in users if hasattr(u,'username')]
    print("THREAD_ID:", t_id, "| title:", title, "| users:", usernames)

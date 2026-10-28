# ==========================================
# N.O.V.A. - Broadcast & Intercom Protocol
# System-wide announcement engine with pre-announcement chime,
# multi-output TTS dispatch, Windows desktop toast, and persistent logging
# Fully compatible with Python 3.14.7 runtime
# ==========================================
import os
import json
import re
import datetime
from typing import Tuple, Callable, Optional
from sound_utils import play_chime
from notification_utils import show_toast

BROADCAST_LOG_FILE = "nova_broadcast_log.json"

def log_broadcast(message: str, channel: str = "All Stations"):
    """Appends broadcast transmission to JSON history log."""
    entry = {
        "timestamp": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "channel": channel,
        "message": message,
        "status": "transmitted"
    }
    history = []
    if os.path.exists(BROADCAST_LOG_FILE):
        try:
            with open(BROADCAST_LOG_FILE, "r", encoding="utf-8") as f:
                history = json.load(f)
        except Exception:
            history = []
            
    history.append(entry)
    try:
        with open(BROADCAST_LOG_FILE, "w", encoding="utf-8") as f:
            json.dump(history, f, indent=4)
    except Exception as e:
        print(f"[Broadcast] Error saving log: {e}")

def execute_broadcast(message: str, speak_fn: Optional[Callable[[str], None]] = None, channel: str = "All Stations") -> str:
    """
    Executes a complete acoustic and visual intercom transmission:
      1. Plays tactical pre-announcement alert chime.
      2. Dispatches Windows desktop toast notification.
      3. Speaks high-priority announcement over audio system.
      4. Saves message to persistent broadcast history log.
    """
    # 1. Acoustic Intercom Chime
    play_chime("broadcast", block=True)

    # 2. Windows Toast Notification to Desktop Notification Center
    toast_title = "📢 N.O.V.A. INTERCOM BROADCAST"
    toast_body = f"[{channel}] {message}"
    show_toast(toast_title, toast_body)

    # 3. Audio Voice Announcement
    announcement_text = f"Attention all personnel. Intercom broadcast from Boss: {message}."
    if speak_fn:
        try:
            speak_fn(announcement_text)
        except Exception as e:
            print(f"[Broadcast] Voice transmission error: {e}")

    # 4. Persistent History Logging
    log_broadcast(message, channel)

    return f"Broadcast transmitted across {channel.lower()} and logged to notification center, Boss."

def handle_broadcast_command(query: str, speak_fn: Optional[Callable[[str], None]] = None) -> Tuple[bool, str]:
    """
    Detects intercom and broadcast voice triggers such as:
      - 'broadcast dinner is ready'
      - 'announce meeting starts in five minutes'
      - 'intercom all stations code red'
    Returns: (handled: bool, response_speech: str)
    """
    q = query.lower().strip()

    # Match broadcast prefixes
    patterns = [
        r'\bbroadcast\s+that\s+(.*)',
        r'\bbroadcast\s+(?:to\s+(.*?)\s+that\s+)?(.*)',
        r'\bannounce\s+that\s+(.*)',
        r'\bannounce\s+(.*)',
        r'\bintercom\s+(.*)',
        r'\bsystem\s+announcement\s+(.*)'
    ]

    matched_message = None
    channel = "All Stations"

    # Specific channel targeting: "Broadcast to living room that dinner is ready"
    chan_match = re.search(r'\bbroadcast\s+to\s+([a-zA-Z\s]+?)\s+(?:that|saying)?\s+(.*)', q)
    if chan_match:
        channel = chan_match.group(1).title()
        matched_message = chan_match.group(2).strip()
    else:
        for pat in patterns:
            m = re.match(pat, q)
            if m:
                matched_message = m.group(1).strip()
                break

    if matched_message:
        # Strip extraneous punctuation or fill words
        clean_msg = matched_message.capitalize()
        if not clean_msg:
            return True, "Broadcast message content was empty, Boss."

        response = execute_broadcast(clean_msg, speak_fn=speak_fn, channel=channel)
        return True, response

    return False, ""

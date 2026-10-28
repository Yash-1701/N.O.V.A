# ==========================================
# N.O.V.A. - Persistent Reminders, Timers & Alarms Engine
# Multi-threaded background daemon scheduler with SQLite persistence
# Fully compatible with Python 3.14.7 runtime
# ==========================================
import os
import sqlite3
import datetime
import threading
import time
import re
from typing import Tuple, List, Dict, Any, Optional, Callable
from sound_utils import play_chime
from notification_utils import show_toast

DB_FILE = "nova_reminders.db"

class TimerReminderEngine:
    def __init__(self, db_path: str = DB_FILE):
        self.db_path = db_path
        self.speech_callback: Optional[Callable[[str], None]] = None
        self._is_running = False
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()
        self.init_db()

    def set_speech_callback(self, callback: Callable[[str], None]):
        """Registers N.O.V.A.'s speak() function to deliver spoken alerts."""
        self.speech_callback = callback

    def init_db(self):
        """Initializes SQLite schema for persistent storage of all timers and alerts."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS alerts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    type TEXT NOT NULL,           -- 'timer', 'reminder', 'alarm'
                    memo TEXT NOT NULL,
                    target_time TEXT NOT NULL,    -- ISO 8601 string or HH:MM
                    duration_seconds INTEGER DEFAULT 0,
                    recurring TEXT DEFAULT 'none',-- 'none', 'weekdays', 'daily'
                    status TEXT DEFAULT 'active', -- 'active', 'completed', 'cancelled'
                    last_triggered_date TEXT DEFAULT '',
                    created_at TEXT NOT NULL
                )
            ''')
            conn.commit()

    def start(self):
        """Starts the background scheduler daemon thread."""
        if not self._is_running:
            self._is_running = True
            self._thread = threading.Thread(target=self._daemon_loop, daemon=True, name="NOVA_SchedulerDaemon")
            self._thread.start()
            print("[Scheduler] N.O.V.A. Alert & Timer Engine daemon online.")

    def stop(self):
        """Stops the daemon scheduler cleanly."""
        self._is_running = False

    def _daemon_loop(self):
        """High-precision daemon loop running every 1 second without blocking."""
        while self._is_running:
            try:
                self._check_alerts()
            except Exception as e:
                print(f"[Scheduler] Error in daemon check: {e}")
            time.sleep(1)

    def _check_alerts(self):
        now = datetime.datetime.now()
        now_iso = now.strftime("%Y-%m-%d %H:%M:%S")
        today_date = now.strftime("%Y-%m-%d")
        current_hm = now.strftime("%H:%M")
        current_weekday = now.weekday() # 0 = Monday, 4 = Friday, 5 = Sat, 6 = Sun

        with self._lock:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()
                cursor.execute("SELECT * FROM alerts WHERE status = 'active'")
                active_alerts = cursor.fetchall()

                for alert in active_alerts:
                    alert_id = alert["id"]
                    a_type = alert["type"]
                    memo = alert["memo"]
                    target_time = alert["target_time"]
                    recurring = alert["recurring"]
                    last_trig = alert["last_triggered_date"]

                    should_fire = False

                    # 1. Countdown Timers & Specific Date-Time Reminders
                    if recurring == 'none':
                        if target_time <= now_iso:
                            should_fire = True
                            cursor.execute("UPDATE alerts SET status = 'completed' WHERE id = ?", (alert_id,))

                    # 2. Recurring Weekday Alarms (Mon-Fri at HH:MM)
                    elif recurring == 'weekdays':
                        if current_weekday in [0, 1, 2, 3, 4] and current_hm == target_time:
                            if last_trig != today_date:
                                should_fire = True
                                cursor.execute("UPDATE alerts SET last_triggered_date = ? WHERE id = ?", (today_date, alert_id))

                    # 3. Daily Recurring Alarms (Every day at HH:MM)
                    elif recurring == 'daily':
                        if current_hm == target_time:
                            if last_trig != today_date:
                                should_fire = True
                                cursor.execute("UPDATE alerts SET last_triggered_date = ? WHERE id = ?", (today_date, alert_id))

                    if should_fire:
                        conn.commit()
                        self._trigger_alert(a_type, memo, target_time)

    def _trigger_alert(self, a_type: str, memo: str, target_time: str):
        """Asynchronously dispatches chime, desktop toast, and spoken voice notification."""
        def _alert_worker():
            # 1. Acoustic Alert Chime
            chime_type = "timer" if a_type == "timer" else "alert"
            play_chime(chime_type, block=True)

            # 2. Native Windows Toast
            if a_type == "timer":
                title = "⏳ N.O.V.A. TIMER EXPIRED"
                body = f"Timer complete: {memo}"
                speech_text = f"Boss, alert: Your timer for {memo} has elapsed."
            elif a_type == "alarm":
                title = "⏰ N.O.V.A. SCHEDULED ALARM"
                body = f"Alarm ringing: {memo}"
                speech_text = f"Wake up, Boss. Scheduled alarm is ringing."
            else: # reminder
                title = "📌 N.O.V.A. REMINDER"
                body = f"Reminder: {memo}"
                speech_text = f"Boss, tactical reminder: {memo}."

            show_toast(title, body)

            # 3. Spoken Audio Notice
            if self.speech_callback:
                try:
                    self.speech_callback(speech_text)
                except Exception as e:
                    print(f"[Scheduler] Speech error: {e}")

        threading.Thread(target=_alert_worker, daemon=True).start()

    # -------------------------------------------------------------
    # SCHEDULING CRUD METHODS
    # -------------------------------------------------------------
    def add_timer(self, duration_seconds: int, memo: str = "Countdown") -> str:
        """Adds a relative countdown timer."""
        now = datetime.datetime.now()
        target = now + datetime.timedelta(seconds=duration_seconds)
        target_iso = target.strftime("%Y-%m-%d %H:%M:%S")

        with self._lock:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    INSERT INTO alerts (type, memo, target_time, duration_seconds, recurring, status, created_at)
                    VALUES ('timer', ?, ?, ?, 'none', 'active', ?)
                ''', (memo, target_iso, duration_seconds, now.strftime("%Y-%m-%d %H:%M:%S")))
                conn.commit()

        mins = duration_seconds // 60
        secs = duration_seconds % 60
        time_str = f"{mins} minute{'s' if mins != 1 else ''}" if mins else f"{secs} seconds"
        return f"Timer locked for {time_str} ({memo}), Boss. Daemon is monitoring countdown."

    def add_reminder(self, target_dt: datetime.datetime, memo: str) -> str:
        """Adds a scheduled task reminder at a specific timestamp."""
        target_iso = target_dt.strftime("%Y-%m-%d %H:%M:%S")
        now_iso = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        with self._lock:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    INSERT INTO alerts (type, memo, target_time, recurring, status, created_at)
                    VALUES ('reminder', ?, ?, 'none', 'active', ?)
                ''', (memo, target_iso, now_iso))
                conn.commit()

        time_display = target_dt.strftime("%I:%M %p")
        return f"Reminder established for {time_display}: '{memo}', Boss."

    def add_alarm(self, time_hm: str, recurring: str = 'none', memo: str = "Wake Up") -> str:
        """Adds an absolute alarm (one-off, daily, or weekdays)."""
        now = datetime.datetime.now()
        now_iso = now.strftime("%Y-%m-%d %H:%M:%S")

        if recurring == 'none':
            # Compute target date/time (today if after now, else tomorrow)
            target_h, target_m = map(int, time_hm.split(":"))
            target_dt = now.replace(hour=target_h, minute=target_m, second=0, microsecond=0)
            if target_dt <= now:
                target_dt += datetime.timedelta(days=1)
            target_time_val = target_dt.strftime("%Y-%m-%d %H:%M:%S")
        else:
            target_time_val = time_hm # Store as HH:MM for recurring comparison

        with self._lock:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    INSERT INTO alerts (type, memo, target_time, recurring, status, created_at)
                    VALUES ('alarm', ?, ?, ?, 'active', ?)
                ''', (memo, target_time_val, recurring, now_iso))
                conn.commit()

        recur_desc = " every weekday" if recurring == 'weekdays' else (" every day" if recurring == 'daily' else "")
        return f"Alarm configured for {time_hm}{recur_desc}, Boss."

    def list_active(self) -> str:
        """Returns a formatted spoken list of active alerts."""
        with self._lock:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()
                cursor.execute("SELECT * FROM alerts WHERE status = 'active' ORDER BY target_time ASC")
                rows = cursor.fetchall()

        if not rows:
            return "No active timers, reminders, or alarms on file, Boss."

        now = datetime.datetime.now()
        summaries = []
        for r in rows:
            a_type = r["type"]
            memo = r["memo"]
            t_time = r["target_time"]
            rec = r["recurring"]

            if a_type == "timer":
                try:
                    target_dt = datetime.datetime.strptime(t_time, "%Y-%m-%d %H:%M:%S")
                    diff = max(0, int((target_dt - now).total_seconds()))
                    mins = diff // 60
                    summaries.append(f"{mins} minute timer for {memo}")
                except Exception:
                    summaries.append(f"timer for {memo}")
            elif a_type == "alarm":
                rec_str = f" ({rec})" if rec != 'none' else ""
                summaries.append(f"alarm at {t_time}{rec_str}")
            else:
                try:
                    dt = datetime.datetime.strptime(t_time, "%Y-%m-%d %H:%M:%S")
                    summaries.append(f"reminder '{memo}' at {dt.strftime('%I:%M %p')}")
                except Exception:
                    summaries.append(f"reminder for {memo}")

        return f"Active alerts on docket: {', '.join(summaries)}, Boss."

    def cancel_active(self, a_type: Optional[str] = None) -> str:
        """Cancels active timers, reminders, or alarms."""
        with self._lock:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                if a_type:
                    cursor.execute("UPDATE alerts SET status = 'cancelled' WHERE status = 'active' AND type = ?", (a_type,))
                else:
                    cursor.execute("UPDATE alerts SET status = 'cancelled' WHERE status = 'active'")
                count = cursor.rowcount
                conn.commit()

        item_str = f"{a_type}s" if a_type else "alerts"
        return f"Cancelled {count} active {item_str}, Boss."

    # -------------------------------------------------------------
    # NATURAL LANGUAGE INTENT PARSING
    # -------------------------------------------------------------
    def handle_command(self, query: str) -> Tuple[bool, str]:
        """
        Parses natural language phrases for timers, reminders, and recurring alarms.
        Returns: (handled: bool, response_speech: str)
        """
        q = query.lower().strip()

        # 1. LIST COMMANDS
        if any(phrase in q for phrase in ["list timers", "list reminders", "list alarms", "what are my reminders", "active timers", "my alarms"]):
            return True, self.list_active()

        # 2. CANCEL COMMANDS
        if "cancel timer" in q or "stop timer" in q or "clear timers" in q:
            return True, self.cancel_active("timer")
        if "cancel reminder" in q or "clear reminders" in q or "delete reminder" in q:
            return True, self.cancel_active("reminder")
        if "cancel alarm" in q or "stop alarm" in q or "cancel my alarm" in q:
            return True, self.cancel_active("alarm")

        # 3. COUNTDOWN TIMERS
        # "Set a timer for 20 minutes", "Set a 5 minute timer", "Timer for 30 seconds"
        timer_match = re.search(r'\b(?:set\s+(?:a\s+)?)?timer\s+for\s+(\d+)\s*(minute|minutes|second|seconds|hour|hours|min|sec|hr)\b', q) or \
                      re.search(r'\b(?:set\s+a\s+)?(\d+)\s*(minute|minutes|second|seconds|hour|hours|min|sec|hr)\s+timer\b', q)
        if timer_match:
            val = int(timer_match.group(1))
            unit = timer_match.group(2).lower()
            memo = "General"
            
            # Extract memo if present: "timer for 10 minutes for pasta"
            memo_match = re.search(r'timer.*?(?:for|to)\s+(?:boiling|cooking|doing)?\s*([a-zA-Z0-9\s]+)$', q)
            if memo_match and val not in [int(s) for s in re.findall(r'\b\d+\b', memo_match.group(1))]:
                cand = memo_match.group(1).strip()
                if cand and not any(w in cand for w in ["minute", "second", "hour", "min", "sec"]):
                    memo = cand

            multiplier = 60 if "min" in unit else (3600 if "hour" in unit or "hr" in unit else 1)
            duration = val * multiplier
            return True, self.add_timer(duration, memo)

        # 4. REMINDERS: "Remind me to submit the assignment in 20 minutes"
        # Relative: "Remind me to [memo] in [X] [units]"
        rel_remind = re.search(r'\bremind\s+me\s+to\s+(.*?)\s+in\s+(\d+)\s*(minute|minutes|second|seconds|hour|hours|min|hr)\b', q) or \
                     re.search(r'\bremind\s+me\s+in\s+(\d+)\s*(minute|minutes|second|seconds|hour|hours|min|hr)\s+to\s+(.*)', q)
        if rel_remind:
            if rel_remind.group(1).isdigit():
                val = int(rel_remind.group(1))
                unit = rel_remind.group(2)
                memo = rel_remind.group(3).strip()
            else:
                memo = rel_remind.group(1).strip()
                val = int(rel_remind.group(2))
                unit = rel_remind.group(3)

            mult = 60 if "min" in unit else (3600 if "hour" in unit or "hr" in unit else 1)
            target_dt = datetime.datetime.now() + datetime.timedelta(seconds=val * mult)
            return True, self.add_reminder(target_dt, memo)

        # Absolute: "Remind me to [memo] at [time]" or "Remind me at [time] to [memo]"
        abs_remind = re.search(r'\bremind\s+me\s+to\s+(.*?)\s+at\s+(\d{1,2}(?::\d{2})?\s*(?:am|pm)?)\b', q) or \
                     re.search(r'\bremind\s+me\s+at\s+(\d{1,2}(?::\d{2})?\s*(?:am|pm)?)\s+to\s+(.*)', q)
        if abs_remind:
            if any(c in abs_remind.group(1) for c in ["am", "pm", ":"]) or abs_remind.group(1).strip().isdigit():
                time_str = abs_remind.group(1).strip()
                memo = abs_remind.group(2).strip()
            else:
                memo = abs_remind.group(1).strip()
                time_str = abs_remind.group(2).strip()

            target_dt = self._parse_time_string(time_str)
            if target_dt:
                return True, self.add_reminder(target_dt, memo)

        # 5. ALARMS & WAKE-UPS: "Wake me up at 7 AM every weekday" / "Set alarm for 6:30 AM"
        alarm_match = re.search(r'\b(?:wake\s+me\s+up|set\s+(?:an\s+)?alarm)\s+(?:for|at)\s+(\d{1,2}(?::\d{2})?\s*(?:am|pm)?)(.*?)$', q)
        if alarm_match:
            time_raw = alarm_match.group(1).strip()
            tail = alarm_match.group(2).lower()
            
            # Check recurrence
            recurring = 'none'
            if "weekday" in tail or "weekdays" in tail or "every weekday" in q:
                recurring = 'weekdays'
            elif "every day" in tail or "daily" in tail or "every morning" in tail or "every day" in q:
                recurring = 'daily'

            parsed_hm = self._parse_to_hm(time_raw)
            if parsed_hm:
                return True, self.add_alarm(parsed_hm, recurring=recurring)

        return False, ""

    def _parse_to_hm(self, time_str: str) -> Optional[str]:
        """Converts strings like '7 am', '7:30 pm', '14:00', '7' into 24-hr 'HH:MM' format."""
        ts = time_str.lower().strip()
        is_pm = "pm" in ts
        is_am = "am" in ts
        ts = re.sub(r'[^\d:]', '', ts)

        if not ts:
            return None

        if ":" in ts:
            parts = ts.split(":")
            h = int(parts[0])
            m = int(parts[1]) if len(parts) > 1 and parts[1] else 0
        else:
            h = int(ts)
            m = 0

        if is_pm and h < 12:
            h += 12
        elif is_am and h == 12:
            h = 0

        return f"{h:02d}:{m:02d}"

    def _parse_time_string(self, time_str: str) -> Optional[datetime.datetime]:
        """Parses user time string into a future datetime object."""
        hm = self._parse_to_hm(time_str)
        if not hm:
            return None
        h, m = map(int, hm.split(":"))
        now = datetime.datetime.now()
        target = now.replace(hour=h, minute=m, second=0, microsecond=0)
        if target <= now:
            target += datetime.timedelta(days=1)
        return target

# Global singleton engine
reminder_engine = TimerReminderEngine()

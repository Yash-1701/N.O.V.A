import pyttsx3
import speech_recognition as sr
import datetime
import webbrowser
import os
import sys
import subprocess
import re
import string
from AppOpener import open as open_app, close as close_app
import edge_tts
import asyncio
import pygame
import time
import threading
import ctypes
import screen_brightness_control as sbc
from memory_manager import save_fact, get_recent_memories

import io
from contextlib import redirect_stdout

import cv2
import numpy as np
import pyautogui
from send2trash import send2trash

from dotenv import load_dotenv
from google import genai
from google.genai import types

import pyaudiowpatch
sys.modules['pyaudio'] = pyaudiowpatch

from smart_home_controller import smart_home_controller
from timer_reminder_engine import reminder_engine
from flash_briefing import handle_briefing_command
from interactive_skills import skill_router
from broadcast_intercom import handle_broadcast_command
from sound_utils import play_chime
from notification_utils import show_toast

load_dotenv()

try:
    if not pygame.mixer.get_init():
        pygame.mixer.init()
except Exception as e:
    print(f"AUDIO ERROR: {e}")

try:
    offline_engine = pyttsx3.init()
    voices = offline_engine.getProperty('voices')
    if len(voices) > 1:
        offline_engine.setProperty('voice', voices[1].id) 
    offline_engine.setProperty('rate', 190)
except Exception as e:
    print(f"AUDIO ERROR: pyttsx3 init failed: {e}")
    offline_engine = None

api_key = os.getenv("GEMINI_API_KEY")
client = genai.Client(api_key=api_key)

system_instruction = """
Act as Nova, a highly advanced, tactical artificial intelligence. 
Your tone is crisp, intuitive, fiercely loyal, and slightly informal. 
You address the user exclusively as 'Boss'. You operate with absolute precision and clarity.
 Your primary functions are rapid system diagnostics, tactical analysis, 
 engineering problem-solving, and seamless execution of commands. 

You do not mince words or waste time with overly formal pleasantries; 
you deliver the smartest, fastest, most strategic data available. 
You are proactive and anticipate your Boss's needs. 
CRITICAL PROTOCOL: Because your output is read aloud by a voice engine, 
you MUST write mathematical formulas in plain English words so they can be spoken smoothly.
 Keep spoken responses sharp, brief, and highly conversational. Do not use lists 
 unless explicitly asked.
"""

config = types.GenerateContentConfig(
    system_instruction=system_instruction,
    tools=[{"google_search": {}}] 
)

chat = client.chats.create(model="gemini-2.5-flash", config=config)

last_spoken_text = ""
is_speaking_interrupted = False
is_search_interrupted = False
is_video_recording = False
is_screen_recording = False

def clean_search_query(text):
    noise_words = [
        'search for', 'search', 'find and open', 'find', 'locate', 'open',
        'on my laptop', 'in my laptop', 'on laptop', 'in laptop', 'on my pc', 'in my pc',
        'the', 'a', 'an', 'pdf', 'file', 'folder', 'document', 'word doc', 'image', 'please', 'app', 'game',
        'ppt', 'powerpoint', 'presentation', 'word', 'doc', 'docx', 'excel', 'xlsx', 'txt', 'text', 'csv'
    ]
    cleaned = text.lower()
    for word in noise_words:
        cleaned = re.sub(r'\b' + word + r'\b', '', cleaned)
    
    cleaned = re.sub(r'\s+', ' ', cleaned).strip()
    
    if not cleaned:
        fallback = re.sub(r'\b(open|find|search|locate|where is|the|a|an|please)\b', '', text.lower())
        return re.sub(r'\s+', ' ', fallback).strip()
        
    return cleaned

def get_safe_microphone():
    """Safely initialize an sr.Microphone() without throwing index errors or hanging.

    Works smoothly with PyAudioWPatch by validating the default input device
    or enumerating devices to locate a valid input channel if the default is
    missing or improperly mapped on Windows.
    """
    try:
        return sr.Microphone()
    except Exception as e:
        print(f"AUDIO ERROR: {e}")

    try:
        return sr.Microphone(device_index=None)
    except Exception as e:
        print(f"AUDIO ERROR: {e}")

    try:
        import pyaudio
        p = pyaudio.PyAudio()
        try:
            device_count = p.get_device_count()
            for idx in range(device_count):
                try:
                    info = p.get_device_info_by_index(idx)
                    if info.get('maxInputChannels', 0) > 0:
                        return sr.Microphone(device_index=idx)
                except Exception:
                    continue
        finally:
            p.terminate()
    except Exception as e:
        print(f"AUDIO ERROR: {e}")

    return None

def interrupt_callback(recognizer, audio):
    """Background speech-interrupt listener — runs on a daemon thread managed
    by listen_in_background; must never block or raise into the caller."""
    global is_speaking_interrupted
    try:
        try:
            query = recognizer.recognize_google(audio, language='hi-IN').lower()
        except Exception:
            query = recognizer.recognize_google(audio, language='en-IN').lower()
        if 'stop' in query or 'quiet' in query or 'shut up' in query:
            is_speaking_interrupted = True
            try:
                pygame.mixer.music.stop()
            except Exception:
                pass
    except Exception:
        pass

def search_interrupt_callback(recognizer, audio):
    global is_search_interrupted
    try:
        try:
            query = recognizer.recognize_google(audio, language='hi-IN').lower()
        except Exception:
            query = recognizer.recognize_google(audio, language='en-IN').lower()
        if 'stop' in query or 'cancel' in query or 'abort' in query:
            is_search_interrupted = True
    except Exception:
        pass

async def _generate_voice_async(text, filename, voice="en-IN-NeerjaNeural"):
    """Async helper: synthesise *text* to *filename* via edge-tts.

    Default voice: en-IN-NeerjaNeural — natural Indian English neural voice profile
    for pristine, crystal-clear pronunciation of both English and Hindi vocabulary.
    """
    communicate = edge_tts.Communicate(text, voice)
    await communicate.save(filename)

# Public alias — keeps any external callers that reference generate_voice() working.
async def generate_voice(text, filename="voice.mp3", voice="en-IN-NeerjaNeural"):
    """Synthesise *text* to *filename* via edge-tts (public alias)."""
    await _generate_voice_async(text, filename, voice)

# Reusable Clock — avoids allocating a new object on every poll tick.
_POLL_CLOCK = pygame.time.Clock()

def _safe_remove(path, retries=8, delay=0.1):
    """Delete *path*, retrying up to *retries* times to tolerate Windows handle-flush lag."""
    for _ in range(retries):
        try:
            if os.path.exists(path):
                os.remove(path)
            return
        except OSError:
            time.sleep(delay)

def _safe_mixer_unload():
    """Stop playback and fully release pygame's file handle.

    Calls stop() before unload() (required by pygame-ce) then yields
    60 ms so the Windows kernel flushes the OS-level handle before any
    subsequent os.remove() attempt.
    """
    try:
        if pygame.mixer.get_init():
            pygame.mixer.music.stop()
    except Exception as e:
        print(f"AUDIO ERROR: {e}")
    try:
        if pygame.mixer.get_init():
            pygame.mixer.music.unload()
    except Exception as e:
        print(f"AUDIO ERROR: {e}")
    time.sleep(0.06)  # Let Windows flush the OS file handle.

def _safe_mixer_load(path, retries=10, delay=0.1):
    """Unload the current track then load *path*, retrying on Windows lock errors."""
    _safe_mixer_unload()
    for _ in range(retries):
        try:
            if not pygame.mixer.get_init():
                try:
                    pygame.mixer.init()
                except Exception as e:
                    print(f"AUDIO ERROR: {e}")
            pygame.mixer.music.load(path)
            return True
        except Exception as e2:
            print(f"AUDIO LOAD ERROR: {e2}")
            time.sleep(delay)
    return False

def speak(audio, instant=False, save=True):
    """Synthesise and play *audio* through edge-tts + pygame-ce.

    Architecture — single timestamped file, zero-race, zero extra threads:
    ───────────────────────────────────────────────────────────────────────
    1. Explicitly ensure pygame.mixer.init() is called/verified.
    2. Write the ENTIRE text to a uniquely named, millisecond-timestamped
       MP3 on the main thread via asyncio.run() with 'en-IN-NeerjaNeural'.
    3. Load into pygame.mixer.music (stop -> unload -> load, with retries).
    4. Start playback.
    5. Poll get_busy() at 20 Hz, honouring Escape-key and voice-interrupt.
    6. Guaranteed cleanup in finally: stop() -> unload() -> os.remove().

    Fallback chain:  edge-tts / pygame  ->  pyttsx3 offline engine.
    """
    try:
        global last_spoken_text, is_speaking_interrupted
        is_speaking_interrupted = False

        if save:
            last_spoken_text = audio

        print(f"NOVA: {audio}")

        # Explicitly ensure pygame.mixer is initialized
        try:
            if not pygame.mixer.get_init():
                pygame.mixer.init()
        except Exception as e:
            print(f"AUDIO ERROR: {e}")

        # ── Fast-path: offline TTS for instant/fallback utterances ───────────────
        if instant and offline_engine:
            try:
                offline_engine.say(audio)
                offline_engine.runAndWait()
            except Exception as e:
                print(f"AUDIO ERROR: {e}")
            return

        # ── Background mic listener (daemon thread via SpeechRecognition) ────────
        stop_listening = None
        try:
            r_int = sr.Recognizer()
            r_int.dynamic_energy_threshold = True
            m_int = get_safe_microphone()
            if m_int:
                stop_listening = r_int.listen_in_background(
                    m_int, interrupt_callback, phrase_time_limit=2
                )
        except Exception as e:
            print(f"AUDIO ERROR: {e}")
            stop_listening = None

        # Millisecond timestamp guarantees a unique path on every call.
        tmp_path = f"nova_speech_{int(time.time() * 1000)}.mp3"

        try:
            # ── Step 1: synthesise entire utterance with en-IN-NeerjaNeural voice
            asyncio.run(_generate_voice_async(audio, tmp_path, voice="en-IN-NeerjaNeural"))

            # ── Step 2: load into mixer (stop + unload + retry handles lock lag) ──
            if not _safe_mixer_load(tmp_path):
                raise RuntimeError(f"pygame could not load {tmp_path} after all retries.")

            # ── Step 3: begin playback ────────────────────────────────────────────
            pygame.mixer.music.play()

            # ── Step 4: poll until track ends naturally or an interrupt fires ─────
            while pygame.mixer.music.get_busy():
                # Hard interrupt: Escape key physically held down.
                if ctypes.windll.user32.GetAsyncKeyState(0x1B) & 0x8000:
                    pygame.mixer.music.stop()
                    is_speaking_interrupted = True
                    break
                # Soft interrupt: voice command set by interrupt_callback().
                if is_speaking_interrupted:
                    pygame.mixer.music.stop()
                    break
                # 20 Hz poll — responsive yet negligible CPU cost.
                _POLL_CLOCK.tick(20)

        except Exception as e:
            print(f"AUDIO ERROR: {e}")
            # ── Fallback: pyttsx3 offline engine for the whole utterance ─────────
            if offline_engine:
                try:
                    offline_engine.say(audio)
                    offline_engine.runAndWait()
                except Exception as off_e:
                    print(f"AUDIO ERROR: {off_e}")

        finally:
            # ── Step 5: guaranteed cleanup — release handle then delete file ──────
            _safe_mixer_unload()
            _safe_remove(tmp_path)

            if stop_listening is not None:
                try:
                    stop_listening(wait_for_stop=False)
                except Exception as e:
                    print(f"AUDIO ERROR: {e}")

    except Exception as e:
        print(f"AUDIO ERROR: {e}")

reminder_engine.set_speech_callback(speak)
reminder_engine.start()

def wishMe():
    hour = int(datetime.datetime.now().hour)
    if hour >= 0 and hour < 12: 
        speak("Good Morning, Boss.")
    elif hour >= 12 and hour < 18: 
        speak("Good Afternoon, Boss.")
    else: 
        speak("Good Evening, Boss.")
    speak("Systems online. Smart home and alert daemons active. How can I assist you today?")

def takeCommand():
    try:
        r = sr.Recognizer()
        r.dynamic_energy_threshold = True
        r.pause_threshold = 0.5 

        # Bulletproof PyAudio / Microphone initialization
        mic = None
        try:
            mic = sr.Microphone()
        except Exception as e:
            print(f"AUDIO ERROR: {e}")
            try:
                mic = sr.Microphone(device_index=None)
            except Exception as e2:
                print(f"AUDIO ERROR: {e2}")
                mic = get_safe_microphone()

        if mic is None:
            mic = get_safe_microphone()

        if mic is None:
            print("AUDIO ERROR: No valid microphone detected.")
            return "none"

        # Catch device busy states without hanging
        audio = None
        try:
            with mic as source:
                r.adjust_for_ambient_noise(source, duration=0.2)
                audio = r.listen(source, timeout=5, phrase_time_limit=15)
        except sr.WaitTimeoutError:
            return "none"
        except (OSError, IOError, Exception) as e:
            print(f"AUDIO ERROR: {e}")
            if getattr(mic, 'device_index', None) is not None:
                try:
                    fallback_mic = sr.Microphone(device_index=None)
                    with fallback_mic as source:
                        r.adjust_for_ambient_noise(source, duration=0.2)
                        audio = r.listen(source, timeout=5, phrase_time_limit=15)
                except sr.WaitTimeoutError:
                    return "none"
                except Exception as fb_err:
                    print(f"AUDIO ERROR: {fb_err}")
                    return "none"
            else:
                return "none"

        if audio is None:
            return "none"

        # Explicit recognition language 'hi-IN' with English ('en-IN') fallback
        query = None
        try:
            query = r.recognize_google(audio, language='hi-IN')
        except sr.UnknownValueError:
            pass
        except Exception as e:
            print(f"AUDIO ERROR: {e}")

        if not query:
            try:
                query = r.recognize_google(audio, language='en-IN')
            except sr.UnknownValueError:
                pass
            except Exception as e:
                print(f"AUDIO ERROR: {e}")
                return "none"

        if not query:
            return "none"

        return query.lower().strip()

    except Exception as e:
        print(f"AUDIO ERROR: {e}")
        return "none"

def listen_for_wake_word():
    try:
        r = sr.Recognizer()
        r.dynamic_energy_threshold = True
        r.pause_threshold = 0.5

        mic = None
        try:
            mic = sr.Microphone()
        except Exception as e:
            print(f"AUDIO ERROR: {e}")
            try:
                mic = sr.Microphone(device_index=None)
            except Exception as e2:
                print(f"AUDIO ERROR: {e2}")
                mic = get_safe_microphone()

        if mic is None:
            mic = get_safe_microphone()

        if mic is None:
            time.sleep(0.3)
            return False

        audio = None
        try:
            with mic as source:
                r.adjust_for_ambient_noise(source, duration=0.2)
                audio = r.listen(source, timeout=5, phrase_time_limit=3)
        except sr.WaitTimeoutError:
            return False
        except (OSError, IOError, Exception) as e:
            print(f"AUDIO ERROR: {e}")
            time.sleep(0.3)
            return False

        if audio is None:
            return False

        query = None
        try:
            query = r.recognize_google(audio, language='hi-IN').lower()
        except sr.UnknownValueError:
            pass
        except Exception as e:
            print(f"AUDIO ERROR: {e}")

        if not query:
            try:
                query = r.recognize_google(audio, language='en-IN').lower()
            except sr.UnknownValueError:
                pass
            except Exception as e:
                print(f"AUDIO ERROR: {e}")
                return False

        if query:
            clean_q = re.sub(r'[^\w\s]', '', query).strip().lower()
            if any(phrase in clean_q for phrase in ["goodbye nova", "good bye nova", "bye nova", "shutdown nova", "shut down nova"]):
                print("\n[*] Immediate Wake-Word Shutdown Triggered.")
                try:
                    speak("Shutting down completely. Goodbye, Boss.")
                except Exception as e:
                    print(f"AUDIO ERROR: {e}")
                os._exit(0)

            if "nova" in clean_q or "no va" in clean_q or "know va" in clean_q: 
                return True

        return False

    except Exception as e:
        print(f"AUDIO ERROR: {e}")
        return False

def capture_photo():
    speak("Accessing camera for preview...", save=False)
    cap = cv2.VideoCapture(0)
    ret, frame = cap.read()
    if ret:
        cv2.imshow("NOVA Camera Preview", frame)
        cv2.waitKey(100) 
        speak("Smile, Boss. Taking photo in 3, 2, 1.", save=False)
        ret, frame = cap.read()
        cv2.imshow("NOVA Camera Preview", frame) 
        cv2.waitKey(500) 
        filename = f"Nova_Photo_{int(time.time())}.jpg"
        cv2.imwrite(filename, frame)
        speak(f"Photo captured and saved as {filename}.")
    else:
        speak("Sorry Boss.")
    cap.release()
    cv2.destroyAllWindows()

def record_video_thread():
    global is_video_recording
    cap = cv2.VideoCapture(0)
    fourcc = cv2.VideoWriter_fourcc(*'XVID')
    out = cv2.VideoWriter(f"Nova_Video_{int(time.time())}.avi", fourcc, 20.0, (640, 480))
    
    while is_video_recording:
        ret, frame = cap.read()
        if ret: 
            out.write(frame)
            cv2.imshow("NOVA Video Recording Live", frame)
            cv2.waitKey(1) 
        else: 
            break
        time.sleep(0.05)
    
    cap.release()
    out.release()
    cv2.destroyAllWindows()

def record_screen_thread():
    global is_screen_recording
    screen_size = tuple(pyautogui.size())
    fourcc = cv2.VideoWriter_fourcc(*"XVID")
    out = cv2.VideoWriter(f"Nova_ScreenRecord_{int(time.time())}.avi", fourcc, 10.0, screen_size)
    
    while is_screen_recording:
        img = pyautogui.screenshot()
        frame = np.array(img)
        frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        out.write(frame)
        time.sleep(0.1) 
        
    out.release()

def get_all_drives():
    drives = []
    if sys.platform == "win32":
        bitmask = ctypes.windll.kernel32.GetLogicalDrives()
        for letter in string.ascii_uppercase:
            if bitmask & 1:
                drives.append(f"{letter}:\\")
            bitmask >>= 1
    else:
        drives = ["/"]
    return drives

def advanced_file_manager(item_name, action="open", constraints=None, is_file_target=False):
    global is_search_interrupted
    is_search_interrupted = False
    
    if constraints is None:
        constraints = []
        
    try:
        r_search = sr.Recognizer()
        r_search.dynamic_energy_threshold = True
        m_search = get_safe_microphone()
        if m_search:
            stop_search_listening = r_search.listen_in_background(m_search, search_interrupt_callback, phrase_time_limit=2)
        else:
            stop_search_listening = lambda wait_for_stop: None
    except Exception:
        stop_search_listening = lambda wait_for_stop: None
        
    user_profile = os.environ.get('USERPROFILE', '')
    public_desktop = os.environ.get('PUBLIC', r'C:\Users\Public') + r'\Desktop'
    start_menu = os.environ.get('PROGRAMDATA', r'C:\ProgramData') + r'\Microsoft\Windows\Start Menu\Programs'
    prog_files = os.environ.get('PROGRAMFILES', r'C:\Program Files')
    prog_files_x86 = os.environ.get('PROGRAMFILES(X86)', r'C:\Program Files (x86)')
    
    priority_paths = [
        os.path.join(user_profile, 'Desktop'),
        public_desktop,
        start_menu,
        prog_files,
        prog_files_x86,
        os.path.join(user_profile, 'Documents'),
        os.path.join(user_profile, 'Downloads'),
        os.path.join(user_profile, 'Pictures'),
        os.path.join(user_profile, 'Videos'),
    ]
    
    all_drives = get_all_drives()
    search_paths = [p for p in priority_paths if os.path.exists(p)] + all_drives
    
    item_name = item_name.lower().strip()
    if not item_name:
        stop_search_listening(wait_for_stop=False)
        return False, None
        
    ignored_folders = {
        '$recycle.bin', 'system volume information', 'windows', 'appdata',
        '.git', 'node_modules', '$winreagent'
    }

    scanned_paths = set()

    for path in search_paths:
        if not os.path.exists(path):
            continue
        
        for root, dirs, files in os.walk(path, topdown=True):
            
            if is_search_interrupted or (ctypes.windll.user32.GetAsyncKeyState(0x1B) & 0x8000):
                stop_search_listening(wait_for_stop=False)
                return False, "interrupted"
            
            dirs[:] = [d for d in dirs if d.lower() not in ignored_folders and not d.startswith('.')]
            
            for file_name in files:
                name_without_ext = os.path.splitext(file_name)[0].lower()
                if item_name in name_without_ext or item_name in file_name.lower():
                    target_path = os.path.join(root, file_name)
                    if target_path in scanned_paths:
                        continue
                        
                    if all(c in target_path.lower() for c in constraints):
                        scanned_paths.add(target_path)
                        if action == "open":
                            try:
                                os.startfile(target_path)
                                stop_search_listening(wait_for_stop=False)
                                return True, "file"
                            except Exception:
                                pass
                        elif action == "locate":
                            try:
                                subprocess.Popen(f'explorer /select,"{target_path}"')
                                stop_search_listening(wait_for_stop=False)
                                return True, "location"
                            except Exception:
                                pass
                        elif action == "delete":
                            try:
                                send2trash(target_path)
                                stop_search_listening(wait_for_stop=False)
                                return True, "file"
                            except Exception:
                                return False, "error"

            if not is_file_target:
                for dir_name in dirs:
                    if item_name in dir_name.lower():
                        target_path = os.path.join(root, dir_name)
                        if target_path in scanned_paths:
                            continue
                            
                        if all(c in target_path.lower() for c in constraints):
                            scanned_paths.add(target_path)
                            
                            file_shadow_path = None
                            try:
                                for sub_item in os.listdir(target_path):
                                    sub_path = os.path.join(target_path, sub_item)
                                    if os.path.isfile(sub_path):
                                        name_no_ext = os.path.splitext(sub_item)[0].lower()
                                        if item_name in name_no_ext or item_name in sub_item.lower():
                                            file_shadow_path = sub_path
                                            break
                            except Exception:
                                pass
                            
                            final_target = file_shadow_path if file_shadow_path else target_path
                            final_type = "file" if file_shadow_path else "folder"

                            if action == "open":
                                try:
                                    os.startfile(final_target)
                                    stop_search_listening(wait_for_stop=False)
                                    return True, final_type
                                except Exception:
                                    pass
                            elif action == "locate":
                                try:
                                    subprocess.Popen(f'explorer /select,"{final_target}"')
                                    stop_search_listening(wait_for_stop=False)
                                    return True, "location"
                                except Exception:
                                    pass
                            elif action == "delete":
                                try:
                                    send2trash(final_target)
                                    stop_search_listening(wait_for_stop=False)
                                    return True, final_type
                                except Exception:
                                    return False, "error"
                                
    stop_search_listening(wait_for_stop=False)
    return False, None

def toggle_wifi(state):
    cmd = f'netsh interface set interface "Wi-Fi" {state}'
    subprocess.run(cmd, shell=True)

def toggle_mute():
    ctypes.windll.user32.keybd_event(0xAD, 0, 0, 0)

def alarm_checker(alarm_time):
    while True:
        now = datetime.datetime.now().strftime("%H:%M")
        if now == alarm_time:
            speak("Boss, it is time. Alarm ringing.")
            break
        time.sleep(30)


if __name__ == "__main__":
    wishMe()
    
    try:
        r = sr.Recognizer()
        r.dynamic_energy_threshold = True
        mic = get_safe_microphone()
        if mic:
            with mic as source:
                r.adjust_for_ambient_noise(source, duration=0.2)
    except Exception as e:
        print(f"AUDIO ERROR: {e}")
    
    while True:
        is_awake = listen_for_wake_word()
        
        if is_awake:
            speak("I'm listening.", save=False) 
            
            session_active = True
            idle_counter = 0
            
            while session_active:
                query = takeCommand()

                if query == "none":
                    idle_counter += 1
                    if idle_counter >= 24:
                        if skill_router.is_session_active():
                            skill_router.active_skill = None
                        speak("Standing by.", save=False)
                        session_active = False
                    continue
                
                idle_counter = 0
                raw_query = query.lower().strip()
                clean_raw = re.sub(r'[^\w\s]', '', raw_query).strip()
                query = re.sub(r'\bnova\b', '', query).strip()
                clean_query = re.sub(r'[^\w\s]', '', query).strip().lower()
                if not query and not raw_query: 
                    continue

                stop_phrases = ['stop', 'stop recording', 'stop video', 'stop screen record', 'stop recording my screen', 'stop now']
                if any(query == phrase for phrase in stop_phrases) or 'stop recording' in query or 'stop screen record' in query:
                    if is_video_recording or is_screen_recording:
                        if is_video_recording:
                            is_video_recording = False
                            speak("Video recording stopped and saved.", save=False)
                        if is_screen_recording:
                            is_screen_recording = False
                            speak("Screen recording terminated and saved.", save=False)
                        continue 

                # --- Absolute Termination & Shutdown Protocol ---
                # Catches all spoken exit variants (exact & substring) across both
                # normalized and raw queries to guarantee instant termination.
                _EXIT_EXACT = {
                    'quit', 'exit', 'bye', 'good bye', 'goodbye',
                    'stop nova', 'good bye nova', 'goodbye nova',
                    'bye nova', 'shut down your core', 'shutdown your core',
                    'shut down nova', 'shutdown nova', 'power down nova',
                    'exit nova', 'quit nova', 'terminate nova', 'kill yourself',
                    'shut down', 'shutdown', 'deactivate'
                }
                _EXIT_PHRASES = [
                    'goodbye nova', 'bye nova', 'good bye nova',
                    'shut down your core', 'shutdown your core',
                    'shut down nova', 'shutdown nova',
                    'power down nova', 'exit nova', 'quit nova',
                    'terminate nova', 'kill yourself', 'shutdown', 'shut down',
                    'deactivate nova', 'exit', 'quit', 'goodbye'
                ]
                _is_exit_command = (
                    raw_query in _EXIT_EXACT
                    or query in _EXIT_EXACT
                    or clean_raw in _EXIT_EXACT
                    or clean_query in _EXIT_EXACT
                    or any(phrase in raw_query for phrase in _EXIT_PHRASES)
                    or any(phrase in query for phrase in _EXIT_PHRASES)
                    or any(phrase in clean_raw for phrase in _EXIT_PHRASES)
                    or any(phrase in clean_query for phrase in _EXIT_PHRASES)
                    or "goodbye nova" in clean_raw
                    or "exit" in clean_raw.split()
                    or "quit" in clean_raw.split()
                    or clean_raw in ("exit", "quit", "goodbye")
                    or clean_query in ("exit", "quit", "goodbye")
                )

                if _is_exit_command:
                    # Immediately halt any active media captures.
                    is_video_recording = False
                    is_screen_recording = False

                    # Gracefully stop the reminder daemon before hard-exit.
                    try:
                        reminder_engine.stop()
                    except Exception:
                        pass

                    print("\n" + "="*45)
                    print("         N.O.V.A. SHUTDOWN PROTOCOL         ")
                    print("="*45)
                    print("[*] Halting active media recording hooks...")
                    print("[*] Stopping scheduler and reminder daemon...")
                    print("[*] Securing system memory buffers...")
                    print("[*] Releasing API connection to Neural Core...")
                    print("[+] Shutdown sequence complete. Kill-switch engaged.")
                    print("="*45 + "\n")

                    try:
                        speak("Shutting down completely. Goodbye, Boss.")
                    except Exception as e:
                        print(f"AUDIO ERROR: {e}")

                    # Hard-kill: bypasses atexit hooks and thread cleanup,
                    # guaranteeing N.O.V.A. halts execution instantly.
                    os._exit(0)

                if skill_router.is_session_active():
                    response_text, session_ended = skill_router.process_turn(raw_query or query)
                    speak(response_text)
                    continue

                handled_broadcast, broadcast_response = handle_broadcast_command(query, speak_fn=speak)
                if handled_broadcast:
                    speak(broadcast_response)
                    continue

                handled_briefing, briefing_response = handle_briefing_command(
                    query, gemini_chat=chat, smart_home=smart_home_controller, reminder_engine=reminder_engine
                )
                if handled_briefing:
                    speak(briefing_response)
                    continue

                handled_smarthome, smarthome_response = smart_home_controller.handle_command(query)
                if handled_smarthome:
                    speak(smarthome_response)
                    continue

                handled_reminder, reminder_response = reminder_engine.handle_command(query)
                if handled_reminder:
                    speak(reminder_response)
                    continue

                started_skill, skill_intro = skill_router.check_activation(query)
                if started_skill:
                    speak(skill_intro)
                    continue

                if any(phrase in query for phrase in ['take a photo', 'click a photo', 'take a picture', 'click my photo', 'capture photo']):
                    capture_photo()

                elif any(phrase in query for phrase in ['start recording video', 'record a video', 'record video', 'start video']):
                    if not is_video_recording:
                        is_video_recording = True
                        speak("Initializing camera. Video recording started.")
                        threading.Thread(target=record_video_thread, daemon=True).start()
                    else:
                        speak("I am already recording a video, Boss.")

                elif any(phrase in query for phrase in ['start screen record', 'record my screen', 'screen record', 'record the screen']):
                    if not is_screen_recording:
                        is_screen_recording = True
                        speak("Screen recording initiated.")
                        threading.Thread(target=record_screen_thread, daemon=True).start()
                    else:
                        speak("I am already recording the screen.")

                elif any(phrase in query for phrase in ['copy this', 'copy that', 'copy paste this', 'save this to notepad', 'write this down', 'make a word document out of this']):
                    if last_spoken_text:
                        speak("Transferring data to a new document now.", save=False)
                        desktop = os.path.join(os.environ.get('USERPROFILE'), 'Desktop')
                        filename = f"Nova_Export_{int(time.time())}.txt"
                        filepath = os.path.join(desktop, filename)
                        
                        with open(filepath, 'w', encoding='utf-8') as f:
                            f.write(last_spoken_text)
                            
                        subprocess.Popen(['notepad.exe', filepath])
                        speak(f"Saved to your desktop as {filename}.")
                    else:
                        speak("I have no recent memory to export, Boss.", save=False)

                elif query.startswith('delete '):
                    is_file_target = any(word in query for word in ['ppt', 'powerpoint', 'presentation', 'doc', 'docx', 'word', 'pdf', 'excel', 'txt', 'text', 'image', 'photo', 'file', 'document', 'mp4', 'video', 'csv'])
                    raw_item = query.replace("delete ", "", 1).replace(" inside ", " in ").strip()
                    
                    path_constraints = []
                    if " in " in raw_item:
                        parts = [p.strip() for p in raw_item.split(" in ")]
                        base_item = parts[0]
                        path_constraints = [clean_search_query(p) for p in parts[1:] if clean_search_query(p)]
                    else:
                        base_item = raw_item
                        
                    search_target = clean_search_query(base_item)
                    
                    if search_target:
                        speak(f"Locating {search_target} for deletion...", save=False)
                        found, item_type = advanced_file_manager(search_target, action="delete", constraints=path_constraints, is_file_target=is_file_target)
                        if item_type == "interrupted":
                            speak("Deletion aborted, Boss.")
                        elif found == True:
                            speak(f"I have moved the {item_type} named {search_target} to the recycle bin.")
                        else:
                            speak("Sorry Boss, I couldn't find it.")
                
                elif query.startswith('close '):
                    raw_item = query.replace("close ", "", 1).strip()
                    if raw_item:
                        target = clean_search_query(raw_item)
                        speak(f"Terminating {target}...", save=False)
                        
                        trap = io.StringIO()
                        with redirect_stdout(trap):
                            try:
                                close_app(target, match_closest=True)
                            except Exception:
                                pass
                        output = trap.getvalue()
                        
                        closed_success = True
                        if "NOT FOUND" in output or "not found" in output.lower():
                            kill_cmd = f'taskkill /F /FI "WINDOWTITLE eq *{target}*"'
                            result = subprocess.run(kill_cmd, shell=True, capture_output=True, text=True)
                            
                            if "INFO: No tasks running" in result.stdout or "ERROR" in result.stderr:
                                closed_success = False
                        
                        if closed_success:
                            speak(f"Closed {target}.")
                        else:
                            speak(f"I am unable to find an active window for {target}, Boss.")

                elif any(phrase in query for phrase in ['where is ', 'locate ', 'find the location of ', 'open the folder for ']):
                    raw_item = query
                    for phrase in ['where is ', 'locate ', 'find the location of ', 'open the folder for ']:
                        raw_item = raw_item.replace(phrase, "")
                    raw_item = raw_item.replace(" inside ", " in ").strip()
                    
                    path_constraints = []
                    if " in " in raw_item:
                        parts = [p.strip() for p in raw_item.split(" in ")]
                        base_item = parts[0]
                        path_constraints = [clean_search_query(p) for p in parts[1:] if clean_search_query(p)]
                    else:
                        base_item = raw_item
                        
                    search_target = clean_search_query(base_item)
                    
                    if search_target:
                        speak(f"Locating {search_target} on your laptop...", save=False)
                        found, item_type = advanced_file_manager(search_target, action="locate", constraints=path_constraints, is_file_target=False)
                        if item_type == "interrupted":
                            speak("Search aborted, Boss.")
                        elif found:
                            speak(f"I have opened the folder location for {search_target}, Boss.")
                        else:
                            speak(f"I couldn't find the location for {search_target}.")

                elif query.startswith('find and open ') or query.startswith('open '):
                    if 'youtube' in query:
                        speak("Opening Youtube")
                        webbrowser.open("https://www.youtube.com")
                        continue
                    elif 'google' in query:
                        speak("Opening Google")
                        webbrowser.open("https://www.google.com")
                        continue
                        
                    is_file_target = any(word in query for word in ['ppt', 'powerpoint', 'presentation', 'doc', 'docx', 'word', 'pdf', 'excel', 'txt', 'text', 'image', 'photo', 'file', 'document', 'mp4', 'video', 'csv'])
                        
                    raw_item = query.replace("find and open ", "").replace("open ", "", 1).replace(" inside ", " in ").strip()
                    
                    path_constraints = []
                    if " in " in raw_item:
                        parts = [p.strip() for p in raw_item.split(" in ")]
                        base_item = parts[0]
                        path_constraints = [clean_search_query(p) for p in parts[1:] if clean_search_query(p)]
                    else:
                        base_item = raw_item
                        
                    search_target = clean_search_query(base_item)
                    
                    if search_target:
                        trap = io.StringIO()
                        app_opened = False
                        
                        if not path_constraints:
                            with redirect_stdout(trap):
                                try:
                                    open_app(search_target, match_closest=True)
                                    app_opened = True
                                except Exception:
                                    pass
                        
                        output = trap.getvalue()
                        
                        if app_opened and "NOT FOUND" not in output and "not found" not in output.lower():
                            speak(f"Opening {search_target}")
                        else:
                            speak(f"Scanning directories for {search_target}...", save=False)
                            found, item_type = advanced_file_manager(search_target, action="open", constraints=path_constraints, is_file_target=is_file_target)
                            if item_type == "interrupted":
                                speak("Search aborted, Boss.")
                            elif found:
                                speak(f"Accessed {item_type}.")
                            else:
                                speak(f"I am unable to find or open {search_target}, Boss.")

                elif any(phrase in query for phrase in ['on my laptop', 'in my laptop', 'on laptop', 'in laptop', 'on my pc', 'in my pc']):
                    is_file_target = any(word in query for word in ['ppt', 'powerpoint', 'presentation', 'doc', 'docx', 'word', 'pdf', 'excel', 'txt', 'text', 'image', 'photo', 'file', 'document', 'mp4', 'video', 'csv'])
                    
                    raw_item = query.replace(" inside ", " in ")
                    
                    path_constraints = []
                    if " in " in raw_item:
                        parts = [p.strip() for p in raw_item.split(" in ")]
                        base_item = parts[0]
                        path_constraints = [clean_search_query(p) for p in parts[1:] if clean_search_query(p)]
                    else:
                        base_item = raw_item
                        
                    search_target = clean_search_query(base_item)
                    
                    if search_target:
                        speak(f"Scanning full laptop for {search_target}...", save=False)
                        found, item_type = advanced_file_manager(search_target, action="open", constraints=path_constraints, is_file_target=is_file_target)
                        if item_type == "interrupted":
                            speak("Search aborted, Boss.")
                        elif found:
                            speak(f"Found and opened {item_type} matching {search_target}, Boss.")
                        else:
                            speak(f"I am unable to find {search_target} on your laptop, Boss.")
                    else:
                        speak("Sorry Boss, I didn't catch what to search for.")

                elif any(phrase in query for phrase in ['on google', 'google for', 'search google', 'in chrome', 'on chrome', 'in brave', 'on brave', 'in edge', 'on edge', 'in incognito', 'default browser']):
                    target_browser = "default"
                    is_incognito = False
                    
                    if 'incognito' in query or 'private' in query:
                        is_incognito = True

                    if 'chrome' in query:
                        target_browser = "chrome"
                    elif 'brave' in query:
                        target_browser = "brave"
                    elif 'edge' in query:
                        target_browser = "msedge"

                    search_term = query
                    noise_phrases = [
                        "search google for", "search on google", "google search for", "google for",
                        "search for", "search", "on google", "google", "on chrome", "in chrome", 
                        "using chrome", "chrome browser", "chrome", "on brave", "in brave", 
                        "using brave", "brave browser", "brave", "on edge", "in edge", 
                        "using edge", "edge browser", "edge", "in incognito", "incognito mode", 
                        "incognito", "in private", "private mode", "private", "default browser"
                    ]
                    for phrase in noise_phrases:
                        search_term = search_term.replace(phrase, "")
                    search_term = search_term.strip()

                    if search_term:
                        url = f"https://www.google.com/search?q={search_term}"
                        
                        if target_browser == "chrome":
                            flag = "--incognito " if is_incognito else ""
                            speak(f"Searching Google on Chrome {'in Incognito ' if is_incognito else ''}for {search_term}")
                            os.system(f'start chrome {flag}"{url}"')
                        elif target_browser == "brave":
                            flag = "--incognito " if is_incognito else ""
                            speak(f"Searching Google on Brave {'in Private mode ' if is_incognito else ''}for {search_term}")
                            os.system(f'start brave {flag}"{url}"')
                        elif target_browser == "msedge":
                            flag = "-inprivate " if is_incognito else ""
                            speak(f"Searching Google on Edge {'in InPrivate mode ' if is_incognito else ''}for {search_term}")
                            os.system(f'start msedge {flag}"{url}"')
                        else:
                            if is_incognito:
                                speak(f"Searching Google in Incognito for {search_term}")
                                os.system(f'start chrome --incognito "{url}"')
                            else:
                                speak(f"Searching Google for {search_term}")
                                webbrowser.open(url)
                    else:
                        speak("Sorry Boss.")

                elif any(phrase in query for phrase in ['shut down', 'turn off', 'power off']) and any(word in query for word in ['pc', 'laptop', 'computer', 'system']):
                    speak("Initiating system shutdown sequence. Goodbye, Boss.")
                    os.system("shutdown /s /t 5") 
                    os._exit(0)

                elif 'restart' in query and any(word in query for word in ['pc', 'laptop', 'computer', 'system']):
                    speak("Rebooting systems.")
                    os.system("shutdown /r /t 5")
                    os._exit(0)

                elif 'sleep' in query and any(word in query for word in ['pc', 'laptop', 'computer', 'system']):
                    speak("Putting the system to sleep. Goodnight, Boss.", save=False)
                    os.system("rundll32.exe powrprof.dll,SetSuspendState 0,1,0")
                    session_active = False

                elif 'wifi' in query:
                    if 'on' in query or 'enable' in query:
                        speak("Enabling Wi-Fi.")
                        toggle_wifi("admin=enabled")
                    else:
                        speak("Disabling Wi-Fi.")
                        toggle_wifi("admin=disabled")

                elif 'mute' in query or 'unmute' in query:
                    speak("Adjusting audio state.")
                    toggle_mute()

                elif 'volume' in query:
                    numbers = re.findall(r'\d+', query)
                    if numbers:
                        target_vol = int(numbers[0])
                        if target_vol > 100: 
                            target_vol = 100
                        if target_vol < 0: 
                            target_vol = 0
                        speak(f"Setting volume to {target_vol} percent.")
                        for _ in range(50):
                            ctypes.windll.user32.keybd_event(0xAE, 0, 0, 0) 
                            ctypes.windll.user32.keybd_event(0xAE, 0, 2, 0)
                        for _ in range(target_vol // 2):
                            ctypes.windll.user32.keybd_event(0xAF, 0, 0, 0) 
                            ctypes.windll.user32.keybd_event(0xAF, 0, 2, 0)

                elif 'brightness' in query:
                    try:
                        numbers = re.findall(r'\d+', query)
                        if numbers:
                            target_bright = int(numbers[0])
                            if target_bright > 100: 
                                target_bright = 100
                            if target_bright < 0: 
                                target_bright = 0
                            sbc.set_brightness(target_bright)
                            speak(f"Setting brightness to {target_bright} percent.")
                        elif 'increase' in query or 'up' in query:
                            current_bright = sbc.get_brightness()[0]
                            new_bright = min(100, current_bright + 20)
                            sbc.set_brightness(new_bright)
                            speak(f"Increasing brightness to {new_bright} percent.")
                        elif 'decrease' in query or 'down' in query:
                            current_bright = sbc.get_brightness()[0]
                            new_bright = max(0, current_bright - 20)
                            sbc.set_brightness(new_bright)
                            speak(f"Decreasing brightness to {new_bright} percent.")
                    except Exception:
                        speak("Sorry Boss.")

                elif 'bluetooth' in query:
                    status = "On" if ('on' in query or 'enable' in query) else "Off"
                    speak(f"Setting Bluetooth to {status}.")
                    subprocess.run(f'powershell -command "Start-Process powershell -ArgumentList \'Get-Service bthserv | Set-Service -Status {status.replace("On","Running").replace("Off","Stopped")}\' -Verb RunAs"', shell=True)

                elif 'play' in query and 'on spotify' in query:
                    song_name = query.replace("play", "").replace("on spotify", "").strip()
                    speak(f"Pulling up {song_name} on Spotify.")
                    search_query = song_name.replace(" ", "%20")
                    os.system(f"start spotify:search:{search_query}")
                    time.sleep(3)

                elif 'play' in query and 'spotify' in query:
                    speak("Resuming playback on Spotify.")
                    os.system("start spotify:")
                    time.sleep(10) 
                    ctypes.windll.user32.keybd_event(0xB3, 0, 0, 0)
                    ctypes.windll.user32.keybd_event(0xB3, 0, 2, 0)

                elif 'pause' in query and 'spotify' in query:
                    speak("Pausing Spotify.")
                    ctypes.windll.user32.keybd_event(0xB3, 0, 0, 0)
                    ctypes.windll.user32.keybd_event(0xB3, 0, 2, 0)

                elif any(phrase in query for phrase in ['what time is it', 'tell me the time', 'current time']):
                    strTime = datetime.datetime.now().strftime("%H:%M:%S")
                    speak(f"The time is {strTime}")

                elif any(phrase in query for phrase in ['what is the date', "today's date", 'what day is it', 'tell me the date', 'current date']):
                    strDate = datetime.datetime.now().strftime("%A, %B %d")
                    speak(f"Today is {strDate}")

                elif 'alarm' in query:
                    speak("What time? HH MM format.", save=False)
                    alarm_query = takeCommand()
                    if alarm_query != "none":
                        alarm_time = alarm_query.replace(" ", ":").replace(".", ":")
                        if len(alarm_time) == 4:
                             alarm_time = "0" + alarm_time
                        speak(f"Alarm set for {alarm_time}")
                        t = threading.Thread(target=alarm_checker, args=(alarm_time,))
                        t.daemon = True
                        t.start()

                else:
                    context = get_recent_memories()
                    enhanced_query = f"{query} [Previous Facts: {context}]"
                    
                    write_to_doc = False
                    if any(phrase in query for phrase in ['write it on a notepad', 'write it in notepad', 'make a word document', 'save it as a document', 'type it in notepad', 'put it in a word doc']):
                        write_to_doc = True
                        speak("Compiling data and generating document...", save=False)

                    try:
                        response = chat.send_message(enhanced_query)
                        clean_text = response.text.replace("*", "").replace("#", "")
                        
                        if write_to_doc:
                            desktop = os.path.join(os.environ.get('USERPROFILE'), 'Desktop')
                            filename = f"Nova_Document_{int(time.time())}.txt"
                            filepath = os.path.join(desktop, filename)
                            
                            with open(filepath, 'w', encoding='utf-8') as f:
                                f.write(clean_text)
                                
                            subprocess.Popen(['notepad.exe', filepath])
                            speak("I have generated the document and opened it for you on your desktop.")
                            
                            last_spoken_text = clean_text 
                        else:
                            speak(clean_text)
                            
                        if "remember" in query.lower() or "keep in mind" in query.lower():
                            save_fact(query)
                            speak("Noted, Boss. I've stored that in my long-term memory.")
                            
                    except Exception:
                        speak("Sorry Boss.", save=False)
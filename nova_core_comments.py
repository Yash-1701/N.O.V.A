# ==========================================
# N.O.V.A. - Neural Operating Voice Assistant
# ==========================================
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

# Imports to trap messy console output from third-party modules
import io
from contextlib import redirect_stdout

# Hardware and OS manipulation libraries
import cv2
import numpy as np
import pyautogui
from send2trash import send2trash

# Environment and AI libraries
from dotenv import load_dotenv
from google import genai
from google.genai import types

# --- PYAUDIOWPATCH ALIAS MAPPING FOR PYTHON 3.14 ---
import pyaudiowpatch
sys.modules['pyaudio'] = pyaudiowpatch

# --- N.O.V.A. EXPANDED ALEXA-CLASS SUBSYSTEMS ---
from smart_home_controller import smart_home_controller
from timer_reminder_engine import reminder_engine
from flash_briefing import handle_briefing_command
from interactive_skills import skill_router
from broadcast_intercom import handle_broadcast_command
from sound_utils import play_chime
from notification_utils import show_toast

# Load local .env file to protect API keys securely
load_dotenv()

# Initialize audio mixer for high-quality TTS playback
pygame.mixer.init()

# --- WINDOWS SAPI5 FAILSAFE ---
# Initializes local Windows voice in case the internet or API goes down
try:
    offline_engine = pyttsx3.init()
    voices = offline_engine.getProperty('voices')
    if len(voices) > 1:
        offline_engine.setProperty('voice', voices[1].id) 
    offline_engine.setProperty('rate', 190)
except Exception:
    offline_engine = None

# --- GEMINI NEURAL BRAIN CONFIGURATION ---
# Fetches the hidden API key from the .env file
api_key = os.getenv("GEMINI_API_KEY")
client = genai.Client(api_key=api_key)

# Core personality and behavioral prompt
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

# Configures the AI to use live Google Search for real-time data grounding
config = types.GenerateContentConfig(
    system_instruction=system_instruction,
    tools=[{"google_search": {}}] 
)

chat = client.chats.create(model="gemini-2.5-flash", config=config)

# --- GLOBAL STATE FLAGS ---
last_spoken_text = ""
is_speaking_interrupted = False
is_search_interrupted = False
is_video_recording = False
is_screen_recording = False

# --- ROBUST TEXT CLEANER FOR SEARCH QUERIES ---
# Uses regex to selectively strip noise words and format keywords without butchering file names
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

# --- AUDIO INTERRUPTION LOGIC (TTS) ---
# Listens in the background while speaking to detect "stop" or "shut up" commands
def interrupt_callback(recognizer, audio):
    global is_speaking_interrupted
    try:
        query = recognizer.recognize_google(audio, language='en-in').lower()
        if 'stop' in query or 'quiet' in query or 'shut up' in query:
            is_speaking_interrupted = True
            pygame.mixer.music.stop()
    except Exception:
        pass

# --- AUDIO INTERRUPTION LOGIC (DEEP FILE SEARCH) ---
# Listens in the background while scanning hard drives to abort the scan
def search_interrupt_callback(recognizer, audio):
    global is_search_interrupted
    try:
        query = recognizer.recognize_google(audio, language='en-in').lower()
        if 'stop' in query or 'cancel' in query or 'abort' in query:
            is_search_interrupted = True
    except Exception:
        pass

# Generates high-quality neural voice audio files asynchronously
async def generate_voice(text, filename="voice.mp3", voice="en-IN-NeerjaNeural"): 
    communicate = edge_tts.Communicate(text, voice)
    await communicate.save(filename)

# Primary speech output handler with threading for smooth playback
def speak(audio, instant=False, save=True):
    global last_spoken_text, is_speaking_interrupted
    is_speaking_interrupted = False
    
    if save:
        last_spoken_text = audio

    print(f"NOVA: {audio}") 
    
    # Bypass to offline engine if requested
    if instant and offline_engine:
        offline_engine.say(audio)
        offline_engine.runAndWait()
        return

    try:
        r_int = sr.Recognizer()
        m_int = sr.Microphone()
        # Start background listener to detect interruptions
        stop_listening = r_int.listen_in_background(m_int, interrupt_callback, phrase_time_limit=2)
        
        # Split text into sentence chunks for faster generation and playback
        chunks = re.split(r'(?<=[.!?\n])\s+', audio)
        chunks = [c.strip() for c in chunks if c.strip()]
        if not chunks: 
            chunks = [audio]

        if os.path.exists("voice_0.mp3"):
            try: 
                os.remove("voice_0.mp3")
            except Exception: 
                pass
        
        # Generate the first chunk immediately
        asyncio.run(generate_voice(chunks[0], "voice_0.mp3"))

        for index in range(len(chunks)):
            if is_speaking_interrupted: 
                break
                
            current_filename = f"voice_{index % 2}.mp3"
            next_filename = f"voice_{(index + 1) % 2}.mp3"
            
            # Play current chunk
            pygame.mixer.music.load(current_filename)
            pygame.mixer.music.play()
            
            # Concurrently download the next chunk to eliminate pauses
            download_thread = None
            if index + 1 < len(chunks):
                if os.path.exists(next_filename):
                    try: 
                        os.remove(next_filename)
                    except Exception: 
                        pass
                def fetch_next(): 
                    asyncio.run(generate_voice(chunks[index + 1], next_filename))
                download_thread = threading.Thread(target=fetch_next)
                download_thread.start()
            
            # Wait for audio to finish, checking for manual ESC key interruptions
            while pygame.mixer.music.get_busy():
                if ctypes.windll.user32.GetAsyncKeyState(0x1B) & 0x8000:
                    pygame.mixer.music.stop()
                    is_speaking_interrupted = True
                    break
                pygame.time.Clock().tick(10)
                
            pygame.mixer.music.unload()
            if download_thread: 
                download_thread.join()

        # Stop the background interrupt listener
        stop_listening(wait_for_stop=False)
        time.sleep(0.1) 
    except Exception:
        # Fallback to robotic offline voice if internet/API fails
        if offline_engine:
            offline_engine.say(audio)
            offline_engine.runAndWait()

# Start persistent reminder & timer background daemon thread
reminder_engine.set_speech_callback(speak)
reminder_engine.start()

# Initial startup greeting based on time of day
def wishMe():
    hour = int(datetime.datetime.now().hour)
    if hour >= 0 and hour < 12: 
        speak("Good Morning, Boss.")
    elif hour >= 12 and hour < 18: 
        speak("Good Afternoon, Boss.")
    else: 
        speak("Good Evening, Boss.")
    speak("Systems online. Smart home and alert daemons active. How can I assist you today?")

# Listens to the microphone and converts speech to text
def takeCommand():
    r = sr.Recognizer()
    with sr.Microphone() as source:
        r.pause_threshold = 0.5 
        try:
            audio = r.listen(source, timeout=5, phrase_time_limit=15)
            query = r.recognize_google(audio, language='en-in')
            return query.lower()
        except Exception:
            return "none"

# Passive background listener waiting specifically for the trigger word
def listen_for_wake_word():
    r = sr.Recognizer()
    with sr.Microphone() as source:
        r.pause_threshold = 0.5
        try:
            audio = r.listen(source, timeout=5, phrase_time_limit=3)
            query = r.recognize_google(audio, language='en-in').lower()
            if "nova" in query or "no va" in query or "know va" in query: 
                return True
        except Exception: 
            pass
    return False

# --- HARDWARE CAMERA & SCREEN ENGINES ---

# Takes a single snapshot using OpenCV
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

# Background thread: Records live webcam video to AVI
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

# Background thread: Records entire desktop display to AVI
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

# --- DEEP SYSTEM SCANNER & FILE MANAGER ---

# Detects all active hard drive letters (C:\, D:\, etc.)
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

# Scans drives and applies hierarchical path constraints to find files/folders safely with Folder-Peek
def advanced_file_manager(item_name, action="open", constraints=None, is_file_target=False):
    global is_search_interrupted
    is_search_interrupted = False
    
    if constraints is None:
        constraints = []
        
    # Start background listener exclusively for this search thread to detect "stop"
    try:
        r_search = sr.Recognizer()
        m_search = sr.Microphone()
        stop_search_listening = r_search.listen_in_background(m_search, search_interrupt_callback, phrase_time_limit=2)
    except Exception:
        stop_search_listening = lambda wait_for_stop: None
        
    user_profile = os.environ.get('USERPROFILE', '')
    public_desktop = os.environ.get('PUBLIC', r'C:\Users\Public') + r'\Desktop'
    start_menu = os.environ.get('PROGRAMDATA', r'C:\ProgramData') + r'\Microsoft\Windows\Start Menu\Programs'
    prog_files = os.environ.get('PROGRAMFILES', r'C:\Program Files')
    prog_files_x86 = os.environ.get('PROGRAMFILES(X86)', r'C:\Program Files (x86)')
    
    # Priority paths for rapid matching of software, games, and personal files
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
        
    # Ignore restricted directories to prevent crashes, but allow Program Files for games/launchers
    ignored_folders = {
        '$recycle.bin', 'system volume information', 'windows', 'appdata',
        '.git', 'node_modules', '$winreagent'
    }

    scanned_paths = set()

    for path in search_paths:
        if not os.path.exists(path):
            continue
        
        for root, dirs, files in os.walk(path, topdown=True):
            
            # ABORT PROTOCOL: Check if user said "stop" OR hit the "Escape" key
            if is_search_interrupted or (ctypes.windll.user32.GetAsyncKeyState(0x1B) & 0x8000):
                stop_search_listening(wait_for_stop=False)
                return False, "interrupted"
            
            # Prune excluded folders in-place to save memory
            dirs[:] = [d for d in dirs if d.lower() not in ignored_folders and not d.startswith('.')]
            
            # 1. FILE CHECK (Prioritized to avoid folder shadowing)
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

            # 2. DIRECTORY CHECK WITH FOLDER-PEEK PROTOCOL
            if not is_file_target:
                for dir_name in dirs:
                    if item_name in dir_name.lower():
                        target_path = os.path.join(root, dir_name)
                        if target_path in scanned_paths:
                            continue
                            
                        if all(c in target_path.lower() for c in constraints):
                            scanned_paths.add(target_path)
                            
                            # --- PEEK INSIDE FOR FILE SHADOWING ---
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
                            
                            # Dynamically target the file if it exists inside the matching folder
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

# --- BACKGROUND UTILITIES ---

# Toggles Wi-Fi adapter state
def toggle_wifi(state):
    cmd = f'netsh interface set interface "Wi-Fi" {state}'
    subprocess.run(cmd, shell=True)

# Toggles system mute via keyboard emulation
def toggle_mute():
    ctypes.windll.user32.keybd_event(0xAD, 0, 0, 0)

# Asynchronous alarm checker running in the background
def alarm_checker(alarm_time):
    while True:
        now = datetime.datetime.now().strftime("%H:%M")
        if now == alarm_time:
            speak("Boss, it is time. Alarm ringing.")
            break
        time.sleep(30)


# ==========================================
# MAIN EXECUTION LOOP
# ==========================================
if __name__ == "__main__":
    wishMe()
    
    r = sr.Recognizer()
    with sr.Microphone() as source:
        # Calibrates microphone for background noise to prevent false triggers
        r.adjust_for_ambient_noise(source, duration=1)
    
    while True:
        is_awake = listen_for_wake_word()
        
        if is_awake:
            speak("I'm listening.", save=False) 
            
            session_active = True
            idle_counter = 0
            
            # Active session loop (keeps listening without needing wake word again)
            while session_active:
                query = takeCommand()

                # Timeout after ~4 minutes of silence
                if query == "none":
                    idle_counter += 1
                    if idle_counter >= 24:
                        if skill_router.is_session_active():
                            skill_router.active_skill = None
                        speak("Standing by.", save=False)
                        session_active = False
                    continue
                
                idle_counter = 0
                query = re.sub(r'\bnova\b', '', query).strip()
                if not query: 
                    continue

                # ----------------------------------------------------
                # ROUTING LOGIC: HARDWARE, OS, APPS, OR NEURAL BRAIN
                # ----------------------------------------------------

                # --- 1. ACTIVE MULTI-TURN CONVERSATIONAL SKILL SESSION ---
                # If an interactive mini-game (Trivia, Math Quiz, Coin Toss, Riddle) is in progress,
                # speech input is routed to the active skill until finished or exited.
                if skill_router.is_session_active():
                    response_text, session_ended = skill_router.process_turn(query)
                    speak(response_text)
                    continue

                # Intercept logic for stopping background media recordings
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

                # --- INSTANT KILL SWITCH & TERMINATION SEQUENCE ---
                if query in ['quit', 'exit', 'bye', 'good bye', 'goodbye', 'stop nova', 'good bye nova', 'goodbye nova', 'bye nova', 'shut down your core']:
                    is_video_recording = False
                    is_screen_recording = False
                    reminder_engine.stop()
                    
                    # Print the shutdown order/sequence to the command window
                    print("\n" + "="*45)
                    print("         N.O.V.A. SHUTDOWN PROTOCOL         ")
                    print("="*45)
                    print("[*] Halting active media recording hooks...")
                    print("[*] Stopping scheduler and reminder daemon...")
                    print("[*] Securing system memory buffers...")
                    print("[*] Releasing API connection to Neural Core...")
                    print("[+] Shutdown sequence complete.")
                    print("="*45 + "\n")
                    
                    speak("Shutting down completely. Goodbye, Boss.")
                    os._exit(0)

                # --- 2. BROADCAST & INTERCOM PROTOCOL ---
                # System-wide announcement across audio outputs and Windows Action Center
                handled_broadcast, broadcast_response = handle_broadcast_command(query, speak_fn=speak)
                if handled_broadcast:
                    speak(broadcast_response)
                    continue

                # --- 3. CONTEXTUAL FLASH BRIEFING ENGINE ---
                # Real-time weather, search-grounded news, calendar schedule, and system/IoT metrics
                handled_briefing, briefing_response = handle_briefing_command(
                    query, gemini_chat=chat, smart_home=smart_home_controller, reminder_engine=reminder_engine
                )
                if handled_briefing:
                    speak(briefing_response)
                    continue

                # --- 4. SMART HOME DEVICE MANAGEMENT & EMULATION ---
                # Virtual IoT devices (Lights, Plugs, Thermostats, Perimeter Locks)
                handled_smarthome, smarthome_response = smart_home_controller.handle_command(query)
                if handled_smarthome:
                    speak(smarthome_response)
                    continue

                # --- 5. PERSISTENT REMINDERS, TIMERS & RECURRING ALARMS ---
                # Multi-threaded background daemon scheduler with SQLite persistence
                handled_reminder, reminder_response = reminder_engine.handle_command(query)
                if handled_reminder:
                    speak(reminder_response)
                    continue

                # --- 6. INTERACTIVE MULTI-TURN SKILLS & MINI-GAMES INITIATION ---
                # Starts conversational games (Trivia, Mental Math, Coin Toss, Riddles)
                started_skill, skill_intro = skill_router.check_activation(query)
                if started_skill:
                    speak(skill_intro)
                    continue

                # Media: Photography
                if any(phrase in query for phrase in ['take a photo', 'click a photo', 'take a picture', 'click my photo', 'capture photo']):
                    capture_photo()

                # Media: Webcam Video Recording
                elif any(phrase in query for phrase in ['start recording video', 'record a video', 'record video', 'start video']):
                    if not is_video_recording:
                        is_video_recording = True
                        speak("Initializing camera. Video recording started.")
                        threading.Thread(target=record_video_thread, daemon=True).start()
                    else:
                        speak("I am already recording a video, Boss.")

                # Media: Screen Recording
                elif any(phrase in query for phrase in ['start screen record', 'record my screen', 'screen record', 'record the screen']):
                    if not is_screen_recording:
                        is_screen_recording = True
                        speak("Screen recording initiated.")
                        threading.Thread(target=record_screen_thread, daemon=True).start()
                    else:
                        speak("I am already recording the screen.")

                # --- DOCUMENT EXPORT: RETROACTIVE COPY-PASTE ---
                # Extracts the last spoken sentence and dumps it to a text file
                elif any(phrase in query for phrase in ['copy this', 'copy that', 'copy paste this', 'save this to notepad', 'write this down', 'make a word document out of this']):
                    if last_spoken_text:
                        speak("Transferring data to a new document now.", save=False)
                        desktop = os.path.join(os.environ.get('USERPROFILE'), 'Desktop')
                        filename = f"Nova_Export_{int(time.time())}.txt"
                        filepath = os.path.join(desktop, filename)
                        
                        # Generate file and launch
                        with open(filepath, 'w', encoding='utf-8') as f:
                            f.write(last_spoken_text)
                            
                        subprocess.Popen(['notepad.exe', filepath])
                        speak(f"Saved to your desktop as {filename}.")
                    else:
                        speak("I have no recent memory to export, Boss.", save=False)

                # Local File Manager: Safely delete specific files/folders
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
                
                # Window Management: Forcibly close running applications
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
                        # Fallback to TaskKill if AppOpener fails to find window
                        if "NOT FOUND" in output or "not found" in output.lower():
                            kill_cmd = f'taskkill /F /FI "WINDOWTITLE eq *{target}*"'
                            result = subprocess.run(kill_cmd, shell=True, capture_output=True, text=True)
                            
                            if "INFO: No tasks running" in result.stdout or "ERROR" in result.stderr:
                                closed_success = False
                        
                        if closed_success:
                            speak(f"Closed {target}.")
                        else:
                            speak(f"I am unable to find an active window for {target}, Boss.")

                # --- LOCATE PROTOCOL: OPEN FOLDER LOCATION ---
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

                # Local File Manager: Open installed software, games, or local files/PDFs/PPTs
                elif query.startswith('find and open ') or query.startswith('open '):
                    if 'youtube' in query:
                        speak("Opening Youtube")
                        webbrowser.open("https://www.youtube.com")
                        continue
                    elif 'google' in query:
                        speak("Opening Google")
                        webbrowser.open("https://www.google.com")
                        continue
                        
                    # Target Intelligence: Check if the user is explicitly requesting a file
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
                        
                        # Bypass software launcher if user specified hierarchical folder constraints
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

                # Deep Local Search Override ("On my laptop")
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

                # Web Browser Override (Explicitly opens a GUI browser window)
                elif any(phrase in query for phrase in ['on google', 'google for', 'search google', 'in chrome', 'on chrome', 'in brave', 'on brave', 'in edge', 'on edge', 'in incognito', 'default browser']):
                    target_browser = "default"
                    is_incognito = False
                    
                    # Detect privacy requests
                    if 'incognito' in query or 'private' in query:
                        is_incognito = True

                    # Target specific browsers
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
                        
                        # Execute browser launch with appropriate security flags
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

                # OS Power Controls
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

                # OS Network & Hardware Controls
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
                        # Reset volume to 0 then step up to target to ensure precision
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

                # Spotify & Entertainment Controls
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

                # Utilities
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

                # --- GEMINI NEURAL BRAIN FALLBACK ---
                # Any unhandled commands, questions, or conversational inputs are routed here to bypass browsers
                else:
                    context = get_recent_memories()
                    enhanced_query = f"{query} [Previous Facts: {context}]"
                    
                    # Detect if user wants the proactive answer written directly into a document
                    write_to_doc = False
                    if any(phrase in query for phrase in ['write it on a notepad', 'write it in notepad', 'make a word document', 'save it as a document', 'type it in notepad', 'put it in a word doc']):
                        write_to_doc = True
                        speak("Compiling data and generating document...", save=False)

                    try:
                        response = chat.send_message(enhanced_query)
                        # Strip standard markdown formatting to ensure smooth TTS reading
                        clean_text = response.text.replace("*", "").replace("#", "")
                        
                        # --- DOCUMENT EXPORT: PROACTIVE GENERATION ---
                        if write_to_doc:
                            desktop = os.path.join(os.environ.get('USERPROFILE'), 'Desktop')
                            filename = f"Nova_Document_{int(time.time())}.txt"
                            filepath = os.path.join(desktop, filename)
                            
                            # Write file to desktop and launch Notepad
                            with open(filepath, 'w', encoding='utf-8') as f:
                                f.write(clean_text)
                                
                            subprocess.Popen(['notepad.exe', filepath])
                            speak("I have generated the document and opened it for you on your desktop.")
                            
                            # Save to memory in case you need it again
                            last_spoken_text = clean_text 
                        else:
                            speak(clean_text)
                            
                        # Process user memory requests
                        if "remember" in query.lower() or "keep in mind" in query.lower():
                            save_fact(query)
                            speak("Noted, Boss. I've stored that in my long-term memory.")
                            
                    except Exception:
                        speak("Sorry Boss.", save=False)
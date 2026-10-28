import subprocess
import sys
import time

def update_nova_dependencies():
    print("Initiating N.O.V.A. Core Dependency Updater...\n")
    
    dependencies = [
        "pyttsx3",
        "SpeechRecognition",
        "PyAudio",
        "PyAudioWPatch",
        "AppOpener",
        "edge-tts",
        "pygame",
        "screen-brightness-control",
        "opencv-python",
        "numpy",
        "PyAutoGUI",
        "Send2Trash",
        "google-genai",
        "python-dotenv",
        "win10toast"
    ]

    failed_packages = []

    for package in dependencies:
        print(f"[*] Checking and updating {package}...")
        try:
            subprocess.check_call([sys.executable, "-m", "pip", "install", "--upgrade", package, "--quiet"])
            print(f"    [+] {package} is up to date.\n")
        except subprocess.CalledProcessError:
            print(f"    [-] FAILED to update {package}.\n")
            failed_packages.append(package)
            
    print("==================================================")
    if not failed_packages:
        print("All N.O.V.A. core modules have been successfully updated, Boss.")
        print("System is running the latest architecture.")
    else:
        print("WARNING: The following modules failed to update:")
        for fail in failed_packages:
            print(f" - {fail}")

if __name__ == "__main__":
    update_nova_dependencies()
    time.sleep(5)
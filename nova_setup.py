import subprocess
import sys
import time

def install_nova_dependencies():
    print("Initiating N.O.V.A. Core Dependency Installer...\n")
    
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
        print(f"[*] Installing {package}...")
        try:
            subprocess.check_call([sys.executable, "-m", "pip", "install", package, "--quiet"])
            print(f"    [+] {package} installed successfully.\n")
        except subprocess.CalledProcessError:
            print(f"    [-] FAILED to install {package}.\n")
            failed_packages.append(package)
            
    print("==================================================")
    if not failed_packages:
        print("All N.O.V.A. core modules have been successfully installed, Boss.")
        print("System is ready for execution.")
    else:
        print("WARNING: The following modules failed to install:")
        for fail in failed_packages:
            print(f" - {fail}")
        print("\nYou may need to install them manually using administrative privileges or check your C++ build tools (especially for PyAudio).")

if __name__ == "__main__":
    install_nova_dependencies()
    time.sleep(5)
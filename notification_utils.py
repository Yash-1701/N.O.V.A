# ==========================================
# N.O.V.A. - Windows Toast Notification Utilities
# Native desktop toast notification dispatcher with multi-layer fallback
# Fully compatible with Python 3.14.7 on Windows 10 & 11
# ==========================================
import os
import sys
import subprocess
import threading
import ctypes
import base64

def _send_powershell_toast(title: str, message: str):
    """
    Dispatches a native Windows 10/11 Toast Notification via PowerShell WinRT APIs.
    Requires no external packages and displays cleanly in the Windows Action Center.
    """
    # Clean text inputs
    safe_title = title.replace('"', '`"').replace("'", "''")
    safe_message = message.replace('"', '`"').replace("'", "''")
    
    ps_script = f"""
[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null
[Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType = WindowsRuntime] | Out-Null
$template = [Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent([Windows.UI.Notifications.ToastTemplateType]::ToastText02)
$textNodes = $template.GetElementsByTagName('text')
$textNodes.Item(0).AppendChild($template.CreateTextNode('{safe_title}')) | Out-Null
$textNodes.Item(1).AppendChild($template.CreateTextNode('{safe_message}')) | Out-Null
$toast = [Windows.UI.Notifications.ToastNotification]::new($template)
$notifier = [Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('NOVA.Assistant')
$notifier.Show($toast)
"""
    # Encode script to UTF-16LE Base64 for PowerShell -EncodedCommand to avoid quoting issues
    encoded_cmd = base64.b64encode(ps_script.encode('utf-16le')).decode('utf-8')
    subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-WindowStyle", "Hidden", "-EncodedCommand", encoded_cmd],
        capture_output=True,
        creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
    )

def _send_win10toast(title: str, message: str):
    """Fallback using win10toast if installed."""
    from win10toast import ToastNotifier
    toaster = ToastNotifier()
    toaster.show_toast(title, message, duration=5, threaded=True)

def show_toast(title: str, message: str):
    """
    Displays a Windows toast notification asynchronously in a background daemon thread
    to guarantee zero latency or UI blocking in N.O.V.A.'s core loop.
    """
    def _worker():
        try:
            # 1. Primary: Native Windows WinRT Toast via PowerShell
            _send_powershell_toast(title, message)
        except Exception:
            try:
                # 2. Secondary: win10toast if available
                _send_win10toast(title, message)
            except Exception:
                # 3. Tertiary: System Tray / Balloon or Console Fallback
                try:
                    ctypes.windll.user32.MessageBeep(0x00000040)
                except Exception:
                    pass
                print(f"[TOAST NOTIFICATION] {title}: {message}")

    thread = threading.Thread(target=_worker, daemon=True)
    thread.start()

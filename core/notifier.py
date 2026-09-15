"""Desktop notifications for BlendQueue (Windows toast, macOS and Linux)."""
from __future__ import annotations

import json
import subprocess

from . import system


def notify(title: str, message: str) -> bool:
    """Shows a desktop notification. False when there is no desktop to show it on."""
    if system.IS_WINDOWS:
        return _winotify(title, message) or _powershell(title, message)
    if system.IS_MAC:
        return _osascript(title, message)
    return _notify_send(title, message)


def _osascript(title: str, message: str) -> bool:
    # json.dumps gives a quoted, escaped literal that AppleScript accepts as-is.
    script = "display notification {} with title {}".format(json.dumps(message), json.dumps(title))
    try:
        return subprocess.run(["osascript", "-e", script], capture_output=True,
                              timeout=25).returncode == 0
    except Exception:
        return False


def _notify_send(title: str, message: str) -> bool:
    try:
        return subprocess.run(["notify-send", "--app-name=BlendQueue", title, message],
                              capture_output=True, timeout=25).returncode == 0
    except Exception:
        return False        # no notify-send (headless box): renders still run


def _winotify(title: str, message: str) -> bool:
    try:
        from winotify import Notification  # type: ignore
        n = Notification(app_id="BlendQueue", title=title, msg=message, duration="short")
        n.show()
        return True
    except Exception:
        return False


def _powershell(title: str, message: str) -> bool:
    def esc(s: str) -> str:
        return s.replace("'", "''")

    ps = (
        "$ErrorActionPreference='Stop';"
        "[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType=WindowsRuntime] > $null;"
        "$t=[Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent([Windows.UI.Notifications.ToastTemplateType]::ToastText02);"
        "$n=$t.GetElementsByTagName('text');"
        f"$n.Item(0).AppendChild($t.CreateTextNode('{esc(title)}')) > $null;"
        f"$n.Item(1).AppendChild($t.CreateTextNode('{esc(message)}')) > $null;"
        "$toast=[Windows.UI.Notifications.ToastNotification]::new($t);"
        "$appid='{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\\WindowsPowerShell\\v1.0\\powershell.exe';"
        "[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier($appid).Show($toast);"
    )
    try:
        subprocess.run(["powershell", "-NoProfile", "-Command", ps], timeout=25,
                       capture_output=True, **system.popen_kwargs())
        return True
    except Exception:
        return False

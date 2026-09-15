"""Desktop notifications (Windows toast) for BlendQueue."""
from __future__ import annotations

import subprocess

from . import config


def notify(title: str, message: str) -> bool:
    """Shows a desktop toast. winotify first; PowerShell if that fails."""
    if _winotify(title, message):
        return True
    return _powershell(title, message)


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
                       creationflags=config.CREATE_NO_WINDOW, capture_output=True)
        return True
    except Exception:
        return False

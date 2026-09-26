"""Everything that depends on the operating system, in one place.

The rest of BlendQueue is platform-agnostic on purpose: it only ever talks to
Blender and ffmpeg through subprocesses and to the disk through ``os.path``.
The handful of operations that cannot be written once -- opening a folder in the
file manager, killing a render and its children, knowing where Blender is
installed, listing the roots of the file browser -- live here so no platform
branch leaks into the queue, the worker or the API.

Anything that needs a desktop (opening folders, notifications) degrades to
``False`` instead of raising: BlendQueue still renders on a headless machine.
"""
from __future__ import annotations

import glob
import os
import pathlib
import re
import shutil
import signal
import subprocess
import sys
import time

IS_WINDOWS = os.name == "nt"
IS_MAC = sys.platform == "darwin"
IS_LINUX = not IS_WINDOWS and not IS_MAC

PLATFORM = "windows" if IS_WINDOWS else ("mac" if IS_MAC else "linux")

# Windows: do not flash a console window for every Blender/ffmpeg call.
CREATE_NO_WINDOW = 0x08000000 if IS_WINDOWS else 0


def popen_kwargs() -> dict:
    """Extra subprocess arguments for every child process we spawn.

    On Windows it hides the console window. On POSIX it puts the child in its
    own session, which is what makes it possible to kill the render *and its
    children* later: Blender spawns helpers and terminating only the parent
    would leave them behind eating CPU.
    """
    if IS_WINDOWS:
        return {"creationflags": CREATE_NO_WINDOW}
    return {"start_new_session": True}


def kill_process_tree(proc) -> None:
    """Kills a spawned process and everything it started."""
    if IS_WINDOWS:
        try:
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                           capture_output=True, timeout=30, **popen_kwargs())
            return
        except Exception:
            pass
    else:
        try:
            pgid = os.getpgid(proc.pid)
        except (ProcessLookupError, OSError):
            return                      # already gone
        try:
            os.killpg(pgid, signal.SIGTERM)
            os.killpg(pgid, signal.SIGCONT)   # a paused render must wake up to die cleanly
            for _ in range(20):         # 2 s to shut down cleanly
                if proc.poll() is not None:
                    return
                time.sleep(0.1)
            os.killpg(pgid, signal.SIGKILL)
            return
        except ProcessLookupError:
            return
        except Exception:
            pass
    try:
        proc.kill()                     # last resort on any platform
    except Exception:
        pass


def _windows_tree(root_pid: int) -> list:
    """root_pid and every process it started, from a Toolhelp32 snapshot."""
    import ctypes
    from ctypes import wintypes

    class PROCESSENTRY32W(ctypes.Structure):
        _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD),
                    ("th32ProcessID", wintypes.DWORD), ("th32DefaultHeapID", ctypes.c_size_t),
                    ("th32ModuleID", wintypes.DWORD), ("cntThreads", wintypes.DWORD),
                    ("th32ParentProcessID", wintypes.DWORD), ("pcPriClassBase", ctypes.c_long),
                    ("dwFlags", wintypes.DWORD), ("szExeFile", ctypes.c_wchar * 260)]

    k32 = ctypes.windll.kernel32
    k32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    raw = k32.CreateToolhelp32Snapshot(0x00000002, 0)        # TH32CS_SNAPPROCESS
    if not raw or raw == wintypes.HANDLE(-1).value:
        return [root_pid]
    snap = wintypes.HANDLE(raw)          # keep all 64 bits when passing it back
    parents = {}
    try:
        entry = PROCESSENTRY32W()
        entry.dwSize = ctypes.sizeof(entry)
        ok = k32.Process32FirstW(snap, ctypes.byref(entry))
        while ok:
            parents[entry.th32ProcessID] = entry.th32ParentProcessID
            ok = k32.Process32NextW(snap, ctypes.byref(entry))
    finally:
        k32.CloseHandle(snap)
    tree, todo = [root_pid], [root_pid]
    while todo:
        pid = todo.pop()
        for child, parent in parents.items():
            if parent == pid and child not in tree:
                tree.append(child)
                todo.append(child)
    return tree


def _windows_suspend(proc, resume: bool) -> bool:
    import ctypes
    from ctypes import wintypes
    k32, ntdll = ctypes.windll.kernel32, ctypes.windll.ntdll
    k32.OpenProcess.restype = wintypes.HANDLE
    call = ntdll.NtResumeProcess if resume else ntdll.NtSuspendProcess
    done = False
    for pid in _windows_tree(proc.pid):
        handle = k32.OpenProcess(0x0800, False, pid)          # PROCESS_SUSPEND_RESUME
        if not handle:
            continue
        try:
            done = call(wintypes.HANDLE(handle)) == 0 or done
        finally:
            k32.CloseHandle(wintypes.HANDLE(handle))
    return done


def suspend_process_tree(proc) -> bool:
    """Freezes a render where it is (with its children) until resume_process_tree().

    The process keeps its memory, VRAM included: resuming continues the very
    same frame. Killing a suspended process works as usual.
    """
    if IS_WINDOWS:
        try:
            return _windows_suspend(proc, resume=False)
        except Exception:
            return False
    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGSTOP)
        return True
    except (ProcessLookupError, OSError):
        return False


def resume_process_tree(proc) -> bool:
    if IS_WINDOWS:
        try:
            return _windows_suspend(proc, resume=True)
        except Exception:
            return False
    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGCONT)
        return True
    except (ProcessLookupError, OSError):
        return False


def open_folder(path) -> bool:
    """Opens a folder in the system file manager. False if there is no desktop."""
    path = str(path)
    try:
        if IS_WINDOWS:
            os.startfile(path)  # noqa: S606 (local app)
            return True
        cmd = ["open", path] if IS_MAC else ["xdg-open", path]
        return subprocess.run(cmd, capture_output=True, timeout=20).returncode == 0
    except Exception:
        return False


def _version_key(path: str) -> tuple:
    """Sorts 'blender-5.2.1-linux-x64' above 'blender-4.5.0-linux-x64'."""
    folder = os.path.basename(os.path.dirname(path))
    nums = tuple(int(n) for n in re.findall(r"\d+", folder))
    return nums or (0,)


def _newest(pattern: str) -> list:
    return sorted(glob.glob(os.path.expanduser(pattern)), key=_version_key, reverse=True)


def blender_candidates() -> list:
    """Paths where Blender may live, best guess first.

    The environment variable always wins, then the usual install locations for
    this platform (newest version first), then whatever is on PATH.
    """
    env = os.environ.get("BLENDQUEUE_BLENDER", "").strip().strip('"')
    out = [env] if env else []

    if IS_WINDOWS:
        for drive in ("C", "D", "E", "F", "G"):
            for base in (r"{d}:\Program Files\Blender Foundation",
                         r"{d}:\Program Files (x86)\Blender Foundation",
                         r"{d}:\Blender Foundation"):
                out += _newest(base.format(d=drive) + r"\*\blender.exe")
        out.append(shutil.which("blender") or "")
        for drive in ("C", "D", "E", "F", "G"):
            for steam in (r"{d}:\Program Files (x86)\Steam\steamapps\common\Blender\blender.exe",
                          r"{d}:\SteamLibrary\steamapps\common\Blender\blender.exe",
                          r"{d}:\Steam\steamapps\common\Blender\blender.exe"):
                out.append(steam.format(d=drive))

    elif IS_MAC:
        out += _newest("/Applications/Blender*.app/Contents/MacOS/Blender")
        out += _newest("~/Applications/Blender*.app/Contents/MacOS/Blender")
        out.append("/Applications/Blender/Blender.app/Contents/MacOS/Blender")
        out.append(os.path.expanduser(
            "~/Library/Application Support/Steam/steamapps/common/Blender/Blender.app"
            "/Contents/MacOS/Blender"))
        out.append(shutil.which("blender") or "")

    else:
        out.append(shutil.which("blender") or "")
        out += ["/usr/bin/blender", "/usr/local/bin/blender", "/snap/bin/blender"]
        out += _newest("/opt/blender*/blender")
        out += _newest("~/blender*/blender")
        out += _newest("~/.local/share/blender*/blender")
        out += _newest("~/.steam/steam/steamapps/common/Blender/blender")
        out += _newest("~/.local/share/Steam/steamapps/common/Blender/blender")

    seen, uniq = set(), []
    for p in out:
        if p and p not in seen:
            seen.add(p)
            uniq.append(p)
    return uniq


def is_runnable(path: str) -> bool:
    """A real file we are allowed to execute (POSIX needs the exec bit)."""
    if not path or not pathlib.Path(path).is_file():
        return False
    return IS_WINDOWS or os.access(path, os.X_OK)


_WIN_RESERVED = ({"CON", "PRN", "AUX", "NUL"} | {f"COM{i}" for i in range(1, 10)}
                 | {f"LPT{i}" for i in range(1, 10)})


def folder_name_problem(name: str) -> str | None:
    """Why `name` cannot be a new folder on this system, or None if it can."""
    if not name or name in (".", ".."):
        return "Type a name for the folder"
    if "/" in name or any(ord(c) < 32 for c in name):
        return "A folder name cannot contain / or control characters"
    if IS_WINDOWS:
        if any(c in '<>:"\\|?*' for c in name):
            return 'A folder name cannot contain any of < > : " \\ | ? *'
        if name.endswith((" ", ".")):
            return "A folder name cannot end with a space or a dot"
        if name.split(".")[0].upper() in _WIN_RESERVED:
            return "Windows reserves that name"
    return None


def fs_roots() -> list:
    """Starting points of the file browser: drives on Windows, / and the
    mounted volumes on macOS and Linux, plus the usual personal folders."""
    home = os.path.expanduser("~")
    roots, favs = [], []

    if IS_WINDOWS:
        for letter in "CDEFGHIJKLMNOPQRSTUVWXYZAB":
            root = f"{letter}:\\"
            if os.path.exists(root):
                roots.append({"name": root, "path": root, "type": "drive"})
    else:
        roots.append({"name": "/", "path": "/", "type": "drive"})
        mounts = ["/Volumes/*"] if IS_MAC else [
            "/media/*", f"/media/{os.environ.get('USER', '')}/*", f"/run/media/{os.environ.get('USER', '')}/*", "/mnt/*"]
        for pattern in mounts:
            for p in sorted(glob.glob(pattern)):
                if os.path.isdir(p) and not any(r["path"] == p for r in roots):
                    roots.append({"name": os.path.basename(p) or p, "path": p, "type": "drive"})

    for label, sub in (("Home", ""), ("Desktop", "Desktop"), ("Downloads", "Downloads"),
                       ("Documents", "Documents"), ("Videos", "Videos")):
        p = os.path.join(home, sub) if sub else home
        if os.path.isdir(p):
            favs.append({"name": label, "path": p, "type": "dir"})
    return roots + favs

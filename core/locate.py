"""Finding where a dropped .blend really lives on disk.

A browser never tells the page where a dropped file sits, so BlendQueue has to
upload a copy -- and a copy breaks every path relative to the .blend (textures,
linked libraries, caches), because Blender resolves '//' against the copy's
folder. Before uploading, the folders the user already works in are checked
for the same file: same name, same size, same modification time.
"""
from __future__ import annotations

import os
import time

MAX_FOLDERS = 400
TIME_BUDGET_S = 4.0   # network drives can be slow; give up rather than hang the UI


def _subdirs(path: str) -> list:
    try:
        with os.scandir(path) as it:
            return sorted(e.path for e in it
                          if not e.name.startswith((".", "$")) and e.is_dir(follow_symlinks=False))
    except OSError:
        return []


def candidate_folders(known: list) -> list:
    """The known folders first, then their parents and the folders next to them.

    Projects keep their .blend files, renders and textures in sibling folders,
    so the folder a render went to already points at where its .blend is.
    """
    seen, out = set(), []

    def add(p):
        if not p or len(out) >= MAX_FOLDERS:
            return
        key = os.path.normcase(os.path.abspath(p))
        if key not in seen:
            seen.add(key)
            out.append(p)

    known = [k for k in known if k]
    for d in known:
        add(d)
    for d in known:
        parent = os.path.dirname(d.rstrip("\\/"))
        if parent and parent != d:
            add(parent)
            for s in _subdirs(parent):
                add(s)
        for s in _subdirs(d):
            add(s)
    return out


def find(items: list, known: list) -> dict:
    """{name: path} for every dropped file found on disk.

    items: [{"name", "size", "mtime"}] as the browser reports them (mtime in
    seconds; size or mtime may be missing).
    """
    started = time.time()
    folders = candidate_folders(known)
    found = {}
    for it in items or []:
        name = os.path.basename(str((it or {}).get("name") or ""))
        if not name.lower().endswith(".blend"):
            continue
        size, mtime = it.get("size"), it.get("mtime")
        for folder in folders:
            if time.time() - started > TIME_BUDGET_S:
                return found
            path = os.path.join(folder, name)
            try:
                st = os.stat(path)
            except OSError:
                continue
            if size is not None and st.st_size != int(size):
                continue
            # 2 s of slack: FAT and some network drives store coarse times.
            if mtime is not None and abs(st.st_mtime - float(mtime)) > 2:
                continue
            found[name] = os.path.abspath(path)
            break
    return found

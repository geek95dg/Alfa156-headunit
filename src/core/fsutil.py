"""Crash-safe file writes.

The car unit has no buffered power supply: switching the ignition off cuts
power instantly, at any point of any write. A plain ``open(path, "w")``
truncates the target first, so a cut between the truncate and the final
flush leaves an empty or half-written file behind. For a YAML config that
means BCM does not come up on the next boot; for a cache it means garbage.

The helpers here follow the classic write-to-temp-then-rename recipe (the
same idea as ``ignition_watcher.write_state``, but with the fsyncs that make
it actually survive a power cut on ext4):

1. ``mkstemp`` in the *same directory* as the target (``os.replace`` is only
   atomic within one filesystem), named ``.<name>.XXXX.tmp`` so leftovers are
   hidden and easy to recognise;
2. ``fchmod`` to the requested mode before any byte is written — the file is
   created 0600 by ``mkstemp``, so secret-bearing content is never readable
   by others, not even for a moment, and the umask does not interfere;
3. write → ``fsync`` (data is on disk before the rename is);
4. ``os.replace`` onto the target (readers see either the old or the new
   file, never a mix);
5. ``fsync`` of the directory, so the rename itself is durable.

Any exception removes the temporary file and leaves the original intact.

Notes:
- The replaced file is owned by the writing process (BCM runs as root), and
  a symlink at ``path`` is replaced by a regular file rather than followed.
  Both are deliberate: following links on a root-owned write path is how
  files outside the intended location get clobbered.
- Temporaries orphaned by a power cut between steps 1 and 4 are removed by
  :func:`cleanup_stale_tmp`.
"""

from __future__ import annotations

import contextlib
import json
import os
import stat
import tempfile
import time
from pathlib import Path
from typing import Any, Union

from src.core.logger import get_logger

log = get_logger("fsutil")

PathLike = Union[str, os.PathLike]

TMP_SUFFIX = ".tmp"


def _tmp_prefix(target: Path) -> str:
    """Prefix of the temporaries created for ``target`` (``.<name>.``)."""
    return f".{target.name}."


def fsync_dir(directory: Path) -> None:
    """Make a rename inside ``directory`` durable.

    Not every filesystem supports fsync on a directory (some FUSE/overlay
    setups return EINVAL); the data itself is already synced at this point,
    so a failure here is logged and otherwise ignored.
    """
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    try:
        fd = os.open(directory, flags)
    except OSError as e:
        log.debug("fsync dir %s: open failed: %s", directory, e)
        return
    try:
        os.fsync(fd)
    except OSError as e:
        log.debug("fsync dir %s failed: %s", directory, e)
    finally:
        os.close(fd)


def atomic_write_bytes(path: PathLike, data: bytes, *, mode: int = 0o644,
                       fsync: bool = True) -> None:
    """Atomically replace ``path`` with ``data``.

    Args:
        path: Target file. Its parent directory is created if missing.
        data: Full new content.
        mode: Permission bits of the new file (applied exactly, umask is
            not involved). Use ``0o600`` for anything holding secrets or
            personal data.
        fsync: ``False`` skips both fsyncs — only for throw-away data where
            losing the latest version on a power cut is acceptable.

    Raises:
        OSError: on any filesystem error; the original file is untouched and
            no temporary file is left behind.
    """
    if not isinstance(data, (bytes, bytearray, memoryview)):
        raise TypeError(f"data must be bytes-like, not {type(data).__name__}")
    target = Path(path)
    directory = target.parent
    directory.mkdir(parents=True, exist_ok=True)

    fd, tmp_name = tempfile.mkstemp(dir=directory, prefix=_tmp_prefix(target),
                                    suffix=TMP_SUFFIX)
    tmp = Path(tmp_name)
    try:
        try:
            os.fchmod(fd, mode)
            view = memoryview(data)
            while view:
                written = os.write(fd, view)
                view = view[written:]
            if fsync:
                os.fsync(fd)
        finally:
            os.close(fd)
        os.replace(tmp, target)
    except BaseException:
        # BaseException on purpose: a KeyboardInterrupt/SystemExit during
        # shutdown must not leave a stray temporary either.
        with contextlib.suppress(OSError):
            tmp.unlink()
        raise
    if fsync:
        fsync_dir(directory)


def atomic_write_text(path: PathLike, text: str, *, mode: int = 0o644,
                      encoding: str = "utf-8", fsync: bool = True) -> None:
    """Text variant of :func:`atomic_write_bytes`."""
    atomic_write_bytes(path, text.encode(encoding), mode=mode, fsync=fsync)


def atomic_write_json(path: PathLike, obj: Any, *, mode: int = 0o644,
                      fsync: bool = True, **dump_kw: Any) -> None:
    """Serialise ``obj`` as JSON and write it atomically.

    Serialisation happens *before* the temporary file is created, so an
    unserialisable object raises ``TypeError``/``ValueError`` without
    touching the disk at all (the old ``json.dump(obj, open(path, "w"))``
    pattern left a truncated file behind in that case).
    """
    text = json.dumps(obj, **dump_kw)
    atomic_write_text(path, text, mode=mode, fsync=fsync)


def cleanup_stale_tmp(directory: PathLike, prefix: str,
                      max_age_s: float = 3600) -> int:
    """Remove temporaries orphaned by a power cut mid-write.

    Only regular files whose name starts with ``prefix`` and ends with
    ``.tmp`` and that are older than ``max_age_s`` are removed — a younger
    file may belong to a write that is in progress right now.

    Args:
        directory: Directory to scan (missing directory = nothing to do).
        prefix: Name prefix, normally ``".<target name>."``. Must not be
            empty: an empty prefix would match every ``*.tmp`` file.
        max_age_s: Minimum age (by mtime) of a file to be removed.

    Returns:
        Number of files removed.
    """
    if not prefix:
        raise ValueError("prefix must not be empty")
    removed = 0
    now = time.time()
    try:
        entries = list(os.scandir(directory))
    except FileNotFoundError:
        return 0
    except OSError as e:
        log.debug("cleanup_stale_tmp(%s): %s", directory, e)
        return 0
    for entry in entries:
        name = entry.name
        if not (name.startswith(prefix) and name.endswith(TMP_SUFFIX)):
            continue
        try:
            st = entry.stat(follow_symlinks=False)
            if not stat.S_ISREG(st.st_mode):
                continue
            if now - st.st_mtime < max_age_s:
                continue
            os.unlink(entry.path)
            removed += 1
            log.info("Removed stale temporary file %s", entry.path)
        except OSError as e:
            log.debug("cleanup_stale_tmp: cannot remove %s: %s", entry.path, e)
    return removed

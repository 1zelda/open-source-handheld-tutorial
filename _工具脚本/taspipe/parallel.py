# -*- coding: utf-8 -*-
"""BizHawk 并发槽：同一安装串行，不同隔离副本并行。"""
from __future__ import annotations

import contextlib
from dataclasses import dataclass, field
from datetime import datetime
import hashlib
import os
from pathlib import Path
import queue
import threading
import uuid

from . import statejump as SJ
from .control_runtime import RuntimeBlocked, _configure, _copy_runtime


SCRATCH_ROOT = Path(__file__).resolve().parents[2].parent / "taspipe_scratch"


@dataclass
class EmulatorSlot:
    source: Path
    path: Path
    work: Path
    system: str = "NES"
    core: str = "NesHawk"
    _ready: bool = False
    _prepare_lock: object = field(default_factory=threading.Lock, repr=False)

    def prepare(self):
        with self._prepare_lock:
            if self._ready:
                return
            if not (self.source / "EmuHawk.exe").is_file():
                raise RuntimeBlocked(f"BizHawk 安装缺 EmuHawk.exe: {self.source}")
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.work.mkdir(parents=True, exist_ok=True)
            _copy_runtime(self.source, self.path)
            _configure(self.source, self.path,
                       {"system": self.system, "core": self.core},
                       sound=True, start_paused=False)
            self._ready = True

    @contextlib.contextmanager
    def exclusive(self):
        with SJ.installation_lock(self.path):
            yield


class EmulatorSlots:
    """按源安装分组的槽池；线程租到槽后，同槽直到任务结束才归还。"""

    def __init__(self, workers=2, root=None, system="NES", core="NesHawk"):
        if type(workers) is not int or workers < 1:
            raise ValueError("workers 须为正整数")
        if root is None:
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            root = SCRATCH_ROOT / f"tas_matrix_{stamp}_{os.getpid()}_{uuid.uuid4().hex[:8]}"
        self.root = Path(root).resolve()
        SJ._path_arg(str(self.root))
        self.root.mkdir(parents=True, exist_ok=True)
        self.workers = workers
        self.system = str(system or "NES").strip().upper()
        self.core = str(core or "NesHawk").strip()
        self._guard = threading.Lock()
        self._pools = {}
        self._slots = []

    def _pool(self, source, system=None, core=None):
        source = Path(source).resolve()
        system = str(system or self.system).strip().upper()
        core = str(core or self.core).strip()
        key = "\0".join((os.path.normcase(str(source)), system, core))
        with self._guard:
            pool = self._pools.get(key)
            if pool is not None:
                return pool
            digest = hashlib.sha256(key.encode("utf-8")).hexdigest()[:12]
            pool = queue.LifoQueue()
            group = self.root / "slots" / digest
            for index in range(self.workers):
                slot_root = group / f"slot_{index}"
                slot = EmulatorSlot(source, slot_root / source.name, slot_root / "work",
                                    system=system, core=core)
                self._slots.append(slot)
                pool.put(slot)
            self._pools[key] = pool
            return pool

    @contextlib.contextmanager
    def lease(self, source, system=None, core=None):
        pool = self._pool(source, system=system, core=core)
        slot = pool.get()
        try:
            slot.prepare()
            yield slot
        finally:
            pool.put(slot)

    def report(self):
        return {
            "root": str(self.root),
            "workers": self.workers,
            "sources": sorted({str(slot.source) for slot in self._slots}),
            "slots": [{"source": str(slot.source), "system": slot.system,
                       "core": slot.core, "bizhawk": str(slot.path),
                       "work": str(slot.work), "prepared": slot._ready}
                      for slot in self._slots],
        }

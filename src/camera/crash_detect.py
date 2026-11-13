"""Compatibility wrapper — crash detection moved to :mod:`src.safety.crash_detect`.

It never depended on the cameras (the old config comment said so), so it now
lives with the other safety functions. This module keeps the old import path
(``src.camera.crash_detect.start_crash_detect`` / ``CrashDetector``) working
for ONE release; new code imports :mod:`src.safety.crash_detect`. The module
catalog (``modules.crash_detect``) points at the new module directly.

Behaviour changed with the move (plan F): the old single-pair GPS trigger,
``alarm.sensor.tilt`` input and ``alarm.sensor.shock`` output are gone — see
the new module's docstring.
"""

from src.safety.crash_detect import CrashDetector, start_crash_detect

__all__ = ["CrashDetector", "start_crash_detect"]

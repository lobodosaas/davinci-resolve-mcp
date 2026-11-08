"""Per-clip audio level and pan on Resolve 21.1+ timeline audio items.

Measured on Studio 21.1.1 (Linux): an audio timeline item exposes
``AudioVolume`` (dB; Resolve clamps writes to -100..+30) and ``AudioPan``
(-100 hard left .. 100 hard right) through GetProperty/SetProperty, and a render
honours both. ``Volume`` returns False and ``Pan`` is the video transform pan,
so writing those moves nothing audible. Before 21.1 neither key exists.
"""

import math
from typing import Any, Dict, List, Optional

AUDIO_VOLUME_KEY = "AudioVolume"
AUDIO_PAN_KEY = "AudioPan"
VOLUME_DB_FLOOR = -100.0


def linear_to_db(gain: float) -> float:
    """Linear gain (1.0 = unity) to dB, floored at Resolve's -100 dB."""
    gain = float(gain)
    if gain <= 0.0:
        return VOLUME_DB_FLOOR
    return max(VOLUME_DB_FLOOR, 20.0 * math.log10(gain))


def unit_pan_to_percent(pan: float) -> float:
    """-1..1 pan to Resolve's -100..100."""
    return float(pan) * 100.0


def _number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def audio_level_api(item) -> bool:
    """True when the item exposes the 21.1 AudioVolume key (a number)."""
    try:
        return _number(item.GetProperty(AUDIO_VOLUME_KEY))
    except Exception:
        return False


def _track_type(item) -> Optional[str]:
    try:
        info = item.GetTrackTypeAndIndex()
        if info:
            return str(info[0]).lower()
    except Exception:
        pass
    try:
        return str(item.GetType()).lower()
    except Exception:
        return None


def audio_targets(item) -> List[Any]:
    """The audio items a level write applies to: the item itself on an audio
    track, otherwise its linked audio items (a video clip carries no level)."""
    if _track_type(item) == "audio":
        return [item]
    try:
        linked = list(item.GetLinkedItems() or [])
    except Exception:
        linked = []
    return [other for other in linked if _track_type(other) == "audio"]


def write_audio_levels(item, volume_db: Optional[float] = None,
                       pan: Optional[float] = None) -> Dict[str, Dict[str, Any]]:
    """Write AudioVolume (dB) and/or AudioPan (-100..100), reading each back.

    A row is ``verified`` only when SetProperty returned True and the readback
    equals the request; a write Resolve clamped is flagged ``clamped``.
    """
    rows: Dict[str, Dict[str, Any]] = {}
    for key, value in ((AUDIO_VOLUME_KEY, volume_db), (AUDIO_PAN_KEY, pan)):
        if value is None:
            continue
        value = float(value)
        row: Dict[str, Any] = {"requested": value}
        try:
            row["write"] = bool(item.SetProperty(key, value))
        except Exception as exc:
            row["write"] = False
            row["error"] = str(exc)
        try:
            readback = item.GetProperty(key)
        except Exception as exc:
            readback = None
            row["readback_error"] = str(exc)
        row["readback"] = readback
        row["verified"] = bool(row["write"] and _number(readback) and abs(readback - value) < 1e-3)
        if row["write"] and _number(readback) and not row["verified"]:
            row["clamped"] = True
        rows[key] = row
    return rows

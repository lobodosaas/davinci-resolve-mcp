"""Primary wheels (lift / gamma / gain / saturation) for a timeline item.

Resolve's scripting API cannot write primary wheel values directly (api_truth
'Color node graph editing and primary grade values'). Two routes reach them:

- DRX (default): the offline generator in ``resolve-advanced`` (the ``drx``
  tool's ``generate`` action) writes a one-node grade with those wheels, and
  ``Graph.ApplyGradeFromDRX`` applies it. Values are Resolve panel units
  (space 'ui'): lift/gamma ~±0.05 around 0, gain ~1.0, saturation 0-100 with 50
  neutral. Measured on Studio 21.1.1: lift (0.03, 0, -0.03), gamma master 0.03,
  gain (1.2, 1.0, 0.8) applied and rendered warmer.
- CDL (fallback): ``SetCDL`` with slope ≈ gain, offset ≈ lift, power ≈ gamma.
  An approximation: CDL is a different transfer than the wheels.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from typing import Any, Dict, Optional, Tuple

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
BRIDGE_SCRIPT = os.path.join(REPO_ROOT, "scripts", "generate_drx.mjs")

#: Neutral value of each wheel's channels and master in panel units.
NEUTRAL = {"lift": 0.0, "gamma": 0.0, "gain": 1.0}


class WheelError(ValueError):
    """Bad wheel input."""


def _number(value: Any, where: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise WheelError(f"{where} must be a number")
    return float(value)


def wheel(name: str, value: Any) -> Optional[Dict[str, float]]:
    """A wheel as {r, g, b, master}: a number moves the master, [r, g, b] the channels."""
    if value is None:
        return None
    neutral = NEUTRAL[name]
    if isinstance(value, (list, tuple)):
        if len(value) != 3:
            raise WheelError(f"{name} must be a number (master) or [r, g, b]")
        r, g, b = (_number(v, f"{name}[{i}]") for i, v in enumerate(value))
        return {"r": r, "g": g, "b": b, "master": neutral}
    return {"r": neutral, "g": neutral, "b": neutral, "master": _number(value, name)}


def grade_params(lift=None, gamma=None, gain=None, saturation=None) -> Dict[str, Any]:
    """Validated drx-generator gradeParams (space 'ui'). Raises WheelError."""
    params: Dict[str, Any] = {}
    for name, value in (("lift", lift), ("gamma", gamma), ("gain", gain)):
        w = wheel(name, value)
        if w is not None:
            params[name] = w
    if saturation is not None:
        sat = _number(saturation, "saturation")
        if not 0.0 <= sat <= 100.0:
            raise WheelError("saturation is a panel value 0-100 (50 = neutral)")
        params["saturation"] = sat
    if not params:
        raise WheelError("pass at least one of lift, gamma, gain, saturation")
    return params


def cdl_approximation(params: Dict[str, Any], node_index: int = 1) -> Dict[str, Any]:
    """SetCDL payload approximating the wheels: slope = gain, offset = lift,
    power = 1 - 4 * gamma (the generator's ui->drx gamma scale), sat = panel/50."""
    def channels(name):
        w = params.get(name) or {"r": NEUTRAL[name], "g": NEUTRAL[name], "b": NEUTRAL[name],
                                 "master": NEUTRAL[name]}
        return [w["r"], w["g"], w["b"]], w["master"]

    gain, gain_m = channels("gain")
    lift, lift_m = channels("lift")
    gamma, gamma_m = channels("gamma")
    return {
        "NodeIndex": node_index,
        "Slope": [round(c * gain_m, 6) for c in gain],
        "Offset": [round(c + lift_m, 6) for c in lift],
        "Power": [round(max(0.1, 1.0 - 4.0 * (c + gamma_m)), 6) for c in gamma],
        "Saturation": round(params.get("saturation", 50.0) / 50.0, 6),
    }


def available() -> Tuple[bool, Optional[str]]:
    if not shutil.which("node"):
        return False, "node is not on PATH"
    if not os.path.isfile(BRIDGE_SCRIPT):
        return False, f"{BRIDGE_SCRIPT} is missing"
    if not os.path.isfile(os.path.join(REPO_ROOT, "resolve-advanced", "server", "libs.mjs")):
        return False, "the resolve-advanced DRX generator is missing from this install"
    return True, None


def generate_drx(params: Dict[str, Any], output_path: str, label: str = "MCP wheels") -> Dict[str, Any]:
    """Write a one-node .drx with these wheels. Raises RuntimeError on failure."""
    ok, why = available()
    if not ok:
        raise RuntimeError(why)
    request = {"gradeParams": params, "metadata": {"label": label}, "outputPath": os.path.abspath(output_path)}
    process = subprocess.run([shutil.which("node"), BRIDGE_SCRIPT], input=json.dumps(request).encode("utf-8"),
                             capture_output=True, check=False, timeout=120)
    raw = process.stdout.decode("utf-8", "replace").strip()
    try:
        result = json.loads(raw) if raw else {}
    except json.JSONDecodeError:
        result = {}
    if not result.get("ok"):
        raise RuntimeError(result.get("error") or
                           f"generate_drx.mjs exit {process.returncode}: "
                           f"{process.stderr.decode('utf-8', 'replace')[-300:]}")
    return result

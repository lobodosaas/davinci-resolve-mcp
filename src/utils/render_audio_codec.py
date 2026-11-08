"""Pin a render job's audio codec from a friendly name ("aac").

Measured on Studio 21.1.1 / Linux: ``Project.GetAudioRenderCodecs('mp4')``
lists ``{'AAC': 'aac', 'FLAC': 'flac'}``, yet ``SetRenderSettings({'AudioCodec':
'aac'})`` returns False there and the queued job keeps the Deliver page codec
(``flac`` or ``lpcm`` read back from ``GetRenderJobList()``). An AAC encoder
installed as a dvcp IO plugin is selected by its plugin id
(``<vendor uuid>:<codec uuid>``), which the scripting API does not list. So a
friendly name is resolved in order: the native name Resolve lists, a listed
plugin id whose label matches, then a plugin id known for that name; each is
tried with ``SetRenderSettings`` until one is taken. The caller must still read
the job's ``AudioCodec`` back, since a True return is not proof.
"""
from __future__ import annotations

from typing import Any, Dict, List, Tuple

#: Label words that identify an encoder for a friendly codec name.
LABEL_HINTS: Dict[str, Tuple[str, ...]] = {
    "aac": ("aac", "fdk"),
}

#: Plugin encoder ids known per friendly name. The aac entry is the
#: dvcp-aac plugin (aac_fdk_plugin.dvcp.bundle), measured on Studio 21.1.1 /
#: Linux: accepted by SetRenderSettings and read back verbatim as the job's
#: AudioCodec; ffprobe of the render shows codec_name=aac.
KNOWN_PLUGIN_IDS: Dict[str, Tuple[str, ...]] = {
    "aac": ("3E4F5A6B7C8D9EAFB0C1D2E3F4A5B6C7:9FB2E473DA865C4DB35FE6A2FFC3EDE8",),
}


def _listed(project: Any, fmt_ext: str) -> Dict[str, str]:
    try:
        listed = project.GetAudioRenderCodecs(fmt_ext) if fmt_ext else None
    except Exception:
        listed = None
    return {str(k): str(v) for k, v in (listed or {}).items()}


def candidates(project: Any, fmt_ext: str, requested: str) -> List[Tuple[str, str]]:
    """(codec id, source) pairs to try, best first, without duplicates."""
    req = str(requested).strip()
    if ":" in req:
        return [(req, "explicit_id")]
    key = req.lower()
    listed = _listed(project, fmt_ext)
    out: List[Tuple[str, str]] = []
    for label, name in listed.items():
        if key in (label.lower(), name.lower()) and ":" not in name:
            out.append((name, "native"))
    if not out:
        out.append((req, "as_given"))
    hints = LABEL_HINTS.get(key, (key,))
    for label, name in listed.items():
        if ":" in name and any(h in label.lower() for h in hints):
            out.append((name, "listed_plugin"))
    for pid in KNOWN_PLUGIN_IDS.get(key, ()):
        out.append((pid, "known_plugin_id"))
    seen, unique = set(), []
    for codec, source in out:
        if codec not in seen:
            seen.add(codec)
            unique.append((codec, source))
    return unique


def apply_audio_codec(project: Any, fmt_ext: str, requested: str) -> Dict[str, Any]:
    """Try each candidate with SetRenderSettings; report what was taken."""
    attempts = []
    for codec, source in candidates(project, fmt_ext, requested):
        try:
            accepted = bool(project.SetRenderSettings({"AudioCodec": codec}))
        except Exception as exc:  # pragma: no cover - defensive
            accepted, codec = False, f"{codec} ({exc})"
        attempts.append({"codec": codec, "source": source, "accepted": accepted})
        if accepted:
            return {"requested": requested, "format": fmt_ext, "applied": codec,
                    "source": source, "attempts": attempts}
    return {"requested": requested, "format": fmt_ext, "applied": None, "source": None,
            "attempts": attempts, "listed": _listed(project, fmt_ext)}


def job_audio_codec(project: Any, job_id: Any) -> Any:
    """The AudioCodec a queued job reports, or None when unreadable."""
    try:
        for job in project.GetRenderJobList() or []:
            if isinstance(job, dict) and job.get("JobId") == job_id:
                return job.get("AudioCodec")
    except Exception:
        return None
    return None

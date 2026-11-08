"""Per-clip audio level and pan on Resolve 21.1+.

Measured on Studio 21.1.1 (Linux): an audio timeline item exposes 'AudioVolume'
(dB, clamped to -100..+30) and 'AudioPan' (-100 left .. 100 right) through
GetProperty/SetProperty, and a render honours both (-12 dB dropped the level by
exactly 12 dB; pan -100 moved it hard left). The old tools wrote 'Volume' (which
returns False) and 'Pan' (which is the VIDEO transform pan), so nothing moved.
Before 21.1 neither key exists: the tools must still say so, not fake success.
"""

import math
import unittest
from unittest import mock

import src.server as s
from src.granular import timeline_item as gti
from src.utils import audio_levels


class _AudioItem:
    """An audio timeline item on 21.1: AudioVolume/AudioPan clamp like Resolve."""

    def __init__(self, uid="a1", track="audio", api=True):
        self.uid, self.track, self.api = uid, track, api
        self.props = {"AudioVolume": 0.0, "AudioPan": 0.0} if api else {}
        self.writes = []
        self.linked = []

    def GetUniqueId(self):
        return self.uid

    def GetName(self):
        return "clipA.mov"

    def GetType(self):
        return self.track

    def GetTrackTypeAndIndex(self):
        return [self.track, 1]

    def GetLinkedItems(self):
        return list(self.linked)

    def GetProperty(self, key=None):
        if key is None:
            return dict(self.props)
        return self.props.get(key)

    def SetProperty(self, key, value):
        self.writes.append((key, value))
        if key == "AudioVolume" and self.api:
            self.props[key] = max(-100.0, min(30.0, float(value)))
            return True
        if key == "AudioPan" and self.api:
            self.props[key] = max(-100.0, min(100.0, float(value)))
            return True
        if key == "Pan":  # the video transform pan: "succeeds", moves the picture
            self.props[key] = value
            return True
        return False


class _Timeline:
    def __init__(self, video=None, audio=None):
        self.video, self.audio = video or [], audio or []

    def GetTrackCount(self, kind):
        return 1

    def GetItemListInTrack(self, kind, index):
        return list(self.audio if kind == "audio" else self.video)


class _Project:
    def __init__(self, tl):
        self.tl = tl

    def GetCurrentTimeline(self):
        return self.tl


def _granular(tl, *args, **kwargs):
    with mock.patch.object(gti, "get_current_project", return_value=(None, _Project(tl))):
        return gti.set_timeline_item_audio(*args, **kwargs)


class AudioLevelHelpersTest(unittest.TestCase):
    def test_linear_gain_converts_to_db(self):
        self.assertAlmostEqual(audio_levels.linear_to_db(1.0), 0.0)
        self.assertAlmostEqual(audio_levels.linear_to_db(0.5), 20 * math.log10(0.5))
        self.assertAlmostEqual(audio_levels.linear_to_db(2.0), 20 * math.log10(2.0))
        self.assertEqual(audio_levels.linear_to_db(0.0), -100.0)

    def test_unit_pan_converts_to_percent(self):
        self.assertEqual(audio_levels.unit_pan_to_percent(-1.0), -100.0)
        self.assertEqual(audio_levels.unit_pan_to_percent(0.25), 25.0)

    def test_write_reads_back_and_flags_a_clamp(self):
        item = _AudioItem()
        rows = audio_levels.write_audio_levels(item, volume_db=40.0, pan=-100)
        self.assertTrue(rows["AudioPan"]["verified"])
        self.assertFalse(rows["AudioVolume"]["verified"])
        self.assertEqual(rows["AudioVolume"]["readback"], 30.0)
        self.assertTrue(rows["AudioVolume"]["clamped"])


class GranularSetTimelineItemAudioTest(unittest.TestCase):
    def test_legacy_linear_volume_and_unit_pan_write_the_audio_keys(self):
        item = _AudioItem()
        out = _granular(_Timeline(audio=[item]), "a1", volume=0.5, pan=-1.0)
        self.assertIn("Successfully", out)
        self.assertAlmostEqual(item.props["AudioVolume"], 20 * math.log10(0.5))
        self.assertEqual(item.props["AudioPan"], -100.0)
        self.assertNotIn("Volume", [k for k, _ in item.writes])
        self.assertNotIn("Pan", [k for k, _ in item.writes])

    def test_volume_db_is_written_as_is(self):
        item = _AudioItem()
        out = _granular(_Timeline(audio=[item]), "a1", volume_db=-12.0)
        self.assertIn("Successfully", out)
        self.assertEqual(item.props["AudioVolume"], -12.0)
        self.assertIn("-12", out)

    def test_video_item_writes_its_linked_audio_not_the_video_pan(self):
        video = _AudioItem("v1", track="video")
        audio = _AudioItem("a1")
        video.linked = [audio]
        out = _granular(_Timeline(video=[video], audio=[audio]), "v1", volume_db=-6.0, pan=0.5)
        self.assertIn("Successfully", out)
        self.assertEqual(video.writes, [])
        self.assertEqual(audio.props["AudioVolume"], -6.0)
        self.assertEqual(audio.props["AudioPan"], 50.0)

    def test_before_21_1_reports_the_limitation_without_writing_pan(self):
        item = _AudioItem(api=False)
        out = _granular(_Timeline(audio=[item]), "a1", volume=0.5, pan=0.5)
        self.assertIn("Failed", out)
        self.assertIn("21.1", out)
        self.assertNotIn("Pan", [k for k, _ in item.writes])

    def test_out_of_range_inputs_are_refused(self):
        item = _AudioItem()
        self.assertIn("Error", _granular(_Timeline(audio=[item]), "a1", pan=1.5))
        self.assertIn("Error", _granular(_Timeline(audio=[item]), "a1", volume=-0.1))
        self.assertEqual(item.writes, [])


class CompoundSetAudioTest(unittest.TestCase):
    def test_set_audio_writes_audio_volume_and_pan_with_readback(self):
        item = _AudioItem()
        out = s._timeline_item_set_audio(item, {"AudioVolume": -12.0, "AudioPan": -100})
        self.assertTrue(out["success"], out)
        self.assertEqual(item.props, {"AudioVolume": -12.0, "AudioPan": -100.0})
        self.assertEqual(out["targets"][0]["results"]["AudioVolume"]["readback"], -12.0)
        self.assertNotIn("known_limitation", out)

    def test_legacy_volume_pan_keys_alias_the_audio_keys(self):
        video = _AudioItem("v1", track="video")
        audio = _AudioItem("a1")
        video.linked = [audio]
        out = s._timeline_item_set_audio(video, {"Volume": -3.0, "Pan": 25})
        self.assertTrue(out["success"], out)
        self.assertEqual(video.writes, [])
        self.assertEqual(audio.props, {"AudioVolume": -3.0, "AudioPan": 25.0})

    def test_before_21_1_returns_known_limitation(self):
        item = _AudioItem(api=False)
        out = s._timeline_item_set_audio(item, {"Volume": -3.0})
        self.assertFalse(out["success"])
        self.assertIn("known_limitation", out)

    def test_get_audio_reads_the_audio_keys(self):
        item = _AudioItem()
        item.props["AudioVolume"] = -6.0
        self.assertEqual(s._timeline_item_get_audio(item)["AudioVolume"], -6.0)

    def test_safe_set_audio_properties_accepts_the_21_1_keys(self):
        item = _AudioItem()
        tl = _Timeline(audio=[item])
        out = s._safe_set_audio_properties(tl, {"properties": {"AudioVolume": -9.0}, "restore": False})
        self.assertTrue(out["success"], out)
        self.assertEqual(item.props["AudioVolume"], -9.0)
        self.assertNotIn("known_limitation", out)


if __name__ == "__main__":
    unittest.main()

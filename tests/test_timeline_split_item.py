"""timeline(action="split_item"): a razor for an API that has none.

Resolve's scripting API cannot split, trim or move an existing timeline item, and
(measured on Studio 21.1.1, Linux) an AppendToTimeline whose record range is
already occupied on the target track silently lands nothing. So the split is a
rebuild, in the same shape as replace_source_range:

  for the video item and each linked audio item spanning the cut
    1. append piece A [start, cut) and piece B [cut, end) on a temporary track
    2. carry grade and properties original -> temporary pieces (video)
    3. delete the original
    4. append the final pieces on the original track
    5. carry grade and properties temporary -> final pieces
    6. delete the temporary pieces and track
  then relink video+audio of A and of B.
"""

import unittest
from unittest import mock

import src.server as s


class _Pool:
    def __init__(self, fps="24"):
        self.fps = fps

    def GetUniqueId(self):
        return "pool-1"

    def GetName(self):
        return "talk.mov"

    def GetClipProperty(self, key=None):
        return self.fps if key == "FPS" else None


class _Item:
    count = 0

    def __init__(self, tl, kind, track, start, duration, src_start, mpi):
        _Item.count += 1
        self.uid = f"{kind}-{_Item.count}"
        self.tl, self.kind, self.track = tl, kind, track
        self.start, self.duration, self.src_start = start, duration, src_start
        self.mpi = mpi
        self.props = {"ZoomX": 1.0, "ZoomY": 1.0, "Pan": 0.0, "Tilt": 0.0, "CropLeft": 0.0,
                      "Opacity": 100.0}
        self.grade_from = None
        self.fusion = 0
        self.speed = 100.0

    def GetUniqueId(self):
        return self.uid

    def GetName(self):
        return "talk.mov"

    def GetStart(self):
        return self.start

    def GetEnd(self):
        return self.start + self.duration

    def GetDuration(self):
        return self.duration

    def GetSourceStartFrame(self):
        return self.src_start

    def GetMediaPoolItem(self):
        return self.mpi

    def GetTrackTypeAndIndex(self):
        return [self.kind, self.track]

    def GetLinkedItems(self):
        return [i for i in self.tl.links.get(self.uid, set()) if i in self.tl.all_items()]

    def GetFusionCompCount(self):
        return self.fusion

    def GetSpeed(self):
        return {"Percentage": self.speed, "PitchCorrection": True}

    def GetProperty(self, key=None):
        return self.props.get(key)

    def SetProperty(self, key, value):
        self.props[key] = value
        return True

    def CopyGrades(self, targets):
        for target in targets:
            target.grade_from = self.grade_from or self.uid
        return True

    def GetNodeGraph(self):
        return None

    def GetClipColor(self):
        return ""

    def SetClipColor(self, color):
        return True

    def GetClipEnabled(self):
        return True

    def SetClipEnabled(self, enabled):
        return True

    def GetMarkers(self):
        return {}

    def GetFlagList(self):
        return []


class _Timeline:
    def __init__(self, locked=False):
        self.tracks = {"video": {1: []}, "audio": {1: []}}
        self.locked = {("video", 1): locked}
        self.lock_calls = []
        self.links = {}
        self.link_calls = []

    def all_items(self):
        return [i for kind in self.tracks.values() for items in kind.values() for i in items]

    def GetSetting(self, key):
        return "24" if key == "timelineFrameRate" else None

    def GetStartFrame(self):
        return 86400

    def GetTrackCount(self, kind):
        return len(self.tracks.get(kind, {}))

    def GetItemListInTrack(self, kind, idx):
        return list(self.tracks.get(kind, {}).get(idx, []))

    def GetIsTrackLocked(self, kind, idx):
        return self.locked.get((kind, idx), False)

    def SetTrackLock(self, kind, idx, locked):
        self.lock_calls.append((kind, idx, locked))
        self.locked[(kind, idx)] = locked
        return True

    def AddTrack(self, kind, *args):
        self.tracks[kind][len(self.tracks[kind]) + 1] = []
        return True

    def DeleteTrack(self, kind, idx):
        self.tracks[kind].pop(idx, None)
        return True

    def DeleteClips(self, items, ripple):
        if any(self.locked.get((it.kind, it.track)) for it in items):
            return False
        for it in items:
            self.tracks[it.kind][it.track].remove(it)
            # Resolve deletes linked items along with the one passed
            for linked in list(self.links.get(it.uid, set())):
                for kind in self.tracks.values():
                    for lst in kind.values():
                        if linked in lst:
                            lst.remove(linked)
        return True

    def SetClipsLinked(self, items, linked):
        self.link_calls.append(([i.uid for i in items], linked))
        for a in items:
            if linked:
                self.links[a.uid] = {b for b in items if b is not a}
            else:
                self.links.pop(a.uid, None)
        return True


class _MediaPool:
    def __init__(self, tl):
        self.tl = tl
        self.appends = []

    def AppendToTimeline(self, infos):
        out = []
        for info in infos:
            self.appends.append(dict(info))
            kind = "audio" if int(info.get("mediaType", 1)) == 2 else "video"
            track = int(info["trackIndex"])
            start = int(info["recordFrame"])
            duration = int(info["endFrame"]) - int(info["startFrame"])
            if any(i.start < start + duration and start < i.GetEnd() for i in self.tl.tracks[kind][track]):
                out.append(None)  # occupied: Resolve lands nothing
                continue
            item = _Item(self.tl, kind, track, start, duration, int(info["startFrame"]), info["mediaPoolItem"])
            self.tl.tracks[kind][track].append(item)
            out.append(item)
        return out


class SplitItemTest(unittest.TestCase):
    def _fixture(self, locked=False, with_audio=True):
        tl = _Timeline(locked=locked)
        mpi = _Pool()
        video = _Item(tl, "video", 1, 86400, 96, 100, mpi)
        video.props.update({"ZoomX": 1.3, "ZoomY": 1.3, "Pan": -200.0, "CropLeft": 10.0})
        video.grade_from = "the-grade"
        tl.tracks["video"][1].append(video)
        audio = None
        if with_audio:
            audio = _Item(tl, "audio", 1, 86400, 96, 100, mpi)
            tl.tracks["audio"][1].append(audio)
            tl.links[video.uid] = {audio}
            tl.links[audio.uid] = {video}
        mp = _MediaPool(tl)
        proj = mock.Mock()
        proj.GetMediaPool.return_value = mp
        return proj, tl, mp, video, audio

    def _run(self, proj, tl, params):
        with mock.patch.object(s, "_confirm_token_required", return_value=False), \
             mock.patch.object(s, "_playback_refusal", return_value=None):
            return s._timeline_split_item_impl(proj, tl, params)

    def test_split_cuts_video_and_linked_audio_at_the_frame(self):
        proj, tl, mp, video, audio = self._fixture()
        out = self._run(proj, tl, {"timeline_item_id": video.uid, "frame": 86440})
        self.assertTrue(out["success"], out)
        self.assertTrue(out["verified"], out)
        v = sorted(tl.tracks["video"][1], key=lambda i: i.start)
        a = sorted(tl.tracks["audio"][1], key=lambda i: i.start)
        self.assertEqual([(i.start, i.GetEnd(), i.src_start) for i in v], [(86400, 86440, 100), (86440, 86496, 140)])
        self.assertEqual([(i.start, i.GetEnd(), i.src_start) for i in a], [(86400, 86440, 100), (86440, 86496, 140)])
        # grade and sizing carried to both video pieces
        for piece in v:
            self.assertEqual(piece.grade_from, "the-grade")
            self.assertEqual(piece.props["Pan"], -200.0)
            self.assertEqual(piece.props["CropLeft"], 10.0)
        # temporary tracks gone
        self.assertEqual(tl.GetTrackCount("video"), 1)
        self.assertEqual(tl.GetTrackCount("audio"), 1)
        # A pieces linked together, B pieces linked together
        self.assertEqual({tuple(sorted(c)) for c, on in tl.link_calls if on},
                         {tuple(sorted([v[0].uid, a[0].uid])), tuple(sorted([v[1].uid, a[1].uid]))})
        self.assertEqual(out["pieces"]["a"]["start"], 86400)
        self.assertEqual(out["pieces"]["b"]["start"], 86440)

    def test_offset_is_relative_to_the_item_start(self):
        proj, tl, _, video, _ = self._fixture()
        out = self._run(proj, tl, {"timeline_item_id": video.uid, "offset": 24})
        self.assertTrue(out["verified"], out)
        self.assertEqual(sorted(i.start for i in tl.tracks["video"][1]), [86400, 86424])

    def test_include_linked_false_splits_video_alone(self):
        proj, tl, _, video, audio = self._fixture()
        out = self._run(proj, tl, {"timeline_item_id": video.uid, "frame": 86440, "include_linked": False})
        self.assertTrue(out["verified"], out)
        self.assertEqual(len(tl.tracks["video"][1]), 2)
        self.assertEqual(len(tl.tracks["audio"][1]), 1)

    def test_cut_outside_the_item_is_refused(self):
        proj, tl, mp, video, _ = self._fixture()
        for frame in (86400, 86496, 86500, 86300):
            out = self._run(proj, tl, {"timeline_item_id": video.uid, "frame": frame})
            self.assertEqual(out["error"]["code"], "CUT_OUTSIDE_ITEM", frame)
        self.assertEqual(mp.appends, [])

    def test_fusion_and_retime_block(self):
        proj, tl, mp, video, _ = self._fixture()
        video.fusion = 1
        out = self._run(proj, tl, {"timeline_item_id": video.uid, "frame": 86440})
        self.assertEqual(out["error"]["code"], "SPLIT_BLOCKED")
        video.fusion, video.speed = 0, 50.0
        out = self._run(proj, tl, {"timeline_item_id": video.uid, "frame": 86440})
        self.assertEqual(out["error"]["code"], "SPLIT_BLOCKED")
        self.assertEqual(mp.appends, [])

    def test_locked_track_needs_unlock_track(self):
        proj, tl, mp, video, _ = self._fixture(locked=True)
        out = self._run(proj, tl, {"timeline_item_id": video.uid, "frame": 86440})
        self.assertEqual(out["error"]["code"], "TRACK_LOCKED")
        self.assertEqual(mp.appends, [])
        out = self._run(proj, tl, {"timeline_item_id": video.uid, "frame": 86440, "unlock_track": True})
        self.assertTrue(out["verified"], out)
        self.assertEqual(tl.locked[("video", 1)], True)

    def test_dry_run_changes_nothing(self):
        proj, tl, mp, video, audio = self._fixture()
        out = self._run(proj, tl, {"timeline_item_id": video.uid, "frame": 86440, "dry_run": True})
        self.assertTrue(out["dry_run"])
        self.assertEqual(out["plan"]["cut_frame"], 86440)
        self.assertEqual(out["plan"]["linked_audio"], [audio.uid])
        self.assertEqual(mp.appends, [])

    def test_confirm_token_gated(self):
        proj, tl, mp, video, _ = self._fixture()
        with mock.patch.object(s, "_confirm_token_required", return_value=True), \
             mock.patch.object(s, "_playback_refusal", return_value=None):
            out = s._timeline_split_item_impl(proj, tl, {"timeline_item_id": video.uid, "frame": 86440})
        self.assertIn("confirm_token", str(out))
        self.assertEqual(mp.appends, [])

    def test_registered_everywhere(self):
        from src.utils.destructive_hook import DESTRUCTIVE_ACTIONS_BY_TOOL, NATIVE_DRY_RUN_ACTIONS
        from src.utils.execution_lifecycle import classify_operation_risk
        self.assertIn("split_item", DESTRUCTIVE_ACTIONS_BY_TOOL["timeline"])
        self.assertIn(("timeline", "split_item"), NATIVE_DRY_RUN_ACTIONS)
        self.assertIn(("timeline", "split_item"), s._TOKEN_GATED_DESTRUCTIVE_ACTIONS)
        self.assertTrue(classify_operation_risk("timeline", "split_item", {}).to_dict()["recognised"])
        self.assertIn("split_item", s._timeline_edit_kernel_capabilities()["supported"]["clip_operations"])


if __name__ == "__main__":
    unittest.main()

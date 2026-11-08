"""timeline(action="add_captions") / timeline(action="set_caption_text").

Measured on Studio 21.1.1 (Linux): InsertFusionTitleIntoTimeline always lands on
V1 of the CURRENT timeline (no track selector; a locked V1 makes it fail). So
each caption is a Text+ title inside its own small timeline in the Media Pool
folder "MCP Captions", and that timeline's Media Pool item is appended onto the
caption track at the caption's record frame with AppendToTimeline (startFrame 0,
endFrame = duration) — it lands exactly there. The inner title is 5 s by
default, so longer captions are cut into consecutive pieces of the same inner
timeline. set_caption_text reaches the Text+ through the placed item's Media
Pool item -> GetTimeline() -> V1 item -> comp -> TextPlus StyledText.
"""

import unittest
from unittest import mock

import src.server as s


class _Text:
    def __init__(self):
        self.inputs = {"StyledText": "Custom Text"}

    def SetInput(self, key, value, frame=None):
        self.inputs[key] = value
        return True

    def GetInput(self, key, frame=None):
        return self.inputs.get(key)


class _Comp:
    def __init__(self):
        self.text = _Text()

    def GetToolList(self, selected=False, kind=None):
        return {1: self.text} if kind in (None, "TextPlus") else {}


class _Title:
    def __init__(self, duration):
        self.comp = _Comp()
        self.duration = duration

    def GetFusionCompByIndex(self, i):
        return self.comp if i == 1 else None

    def GetDuration(self):
        return self.duration

    def GetStart(self):
        return 86400

    def GetEnd(self):
        return 86400 + self.duration


class _TimelineMPI:
    def __init__(self, tl):
        self.tl = tl

    def GetTimeline(self):
        return self.tl

    def GetUniqueId(self):
        return f"mpi-{self.tl.name}"

    def GetName(self):
        return self.tl.name


class _Inner:
    def __init__(self, name, folder, title_frames):
        self.name, self.folder, self.title_frames = name, folder, title_frames
        self.items = []
        self.mpi = _TimelineMPI(self)

    def GetName(self):
        return self.name

    def GetStartFrame(self):
        return 86400

    def GetSetting(self, key):
        return "24"

    def InsertFusionTitleIntoTimeline(self, name):
        title = _Title(self.title_frames)
        self.items.append(title)
        return title

    def GetItemListInTrack(self, kind, idx):
        return list(self.items) if (kind, idx) == ("video", 1) else []

    def GetTrackCount(self, kind):
        return 1 if kind == "video" else 0

    def GetMediaPoolItem(self):
        return self.mpi


class _Placed:
    n = 0

    def __init__(self, mpi, start, duration, track):
        _Placed.n += 1
        self.uid = f"cap-{_Placed.n}"
        self.mpi, self.start, self.duration, self.track = mpi, start, duration, track

    def GetUniqueId(self):
        return self.uid

    def GetStart(self):
        return self.start

    def GetEnd(self):
        return self.start + self.duration

    def GetDuration(self):
        return self.duration

    def GetMediaPoolItem(self):
        return self.mpi

    def GetTrackTypeAndIndex(self):
        return ["video", self.track]

    def GetName(self):
        return self.mpi.GetName()


class _Main:
    name = "Edit"

    def __init__(self, video_tracks=1):
        self.tracks = {i: [] for i in range(1, video_tracks + 1)}

    def GetName(self):
        return self.name

    def GetStartFrame(self):
        return 86400

    def GetSetting(self, key):
        return "24" if key == "timelineFrameRate" else None

    def GetTrackCount(self, kind):
        return len(self.tracks) if kind == "video" else 0

    def AddTrack(self, kind, *a):
        self.tracks[len(self.tracks) + 1] = []
        return True

    def GetItemListInTrack(self, kind, idx):
        return list(self.tracks.get(idx, [])) if kind == "video" else []

    def GetIsTrackLocked(self, kind, idx):
        return False


class _Folder:
    def __init__(self, name):
        self.name, self.subs = name, []

    def GetName(self):
        return self.name

    def GetSubFolderList(self):
        return list(self.subs)


class _Pool:
    def __init__(self, proj, title_frames):
        self.proj, self.title_frames = proj, title_frames
        self.root = _Folder("Master")
        self.current = self.root
        self.inner = []
        self.appends = []

    def GetRootFolder(self):
        return self.root

    def GetCurrentFolder(self):
        return self.current

    def SetCurrentFolder(self, folder):
        self.current = folder
        return True

    def AddSubFolder(self, parent, name):
        f = _Folder(name)
        parent.subs.append(f)
        return f

    def CreateEmptyTimeline(self, name):
        t = _Inner(name, self.current, self.title_frames)
        self.inner.append(t)
        return t

    def AppendToTimeline(self, infos):
        out = []
        tl = self.proj.current
        for info in infos:
            self.appends.append((tl.GetName(), dict(info)))
            assert "mediaType" not in info or info["mediaType"] == 1
            track, start = int(info["trackIndex"]), int(info["recordFrame"])
            dur = int(info["endFrame"]) - int(info["startFrame"])
            if not isinstance(tl, _Main) or any(i.start < start + dur and start < i.GetEnd() for i in tl.tracks[track]):
                out.append(None)
                continue
            item = _Placed(info["mediaPoolItem"], start, dur, track)
            tl.tracks[track].append(item)
            out.append(item)
        return out


class _Project:
    def __init__(self, video_tracks=1, title_frames=120):
        self.main = _Main(video_tracks)
        self.current = self.main
        self.pool = _Pool(self, title_frames)
        self.switches = []

    def GetMediaPool(self):
        return self.pool

    def GetCurrentTimeline(self):
        return self.current

    def SetCurrentTimeline(self, tl):
        self.switches.append(tl.GetName())
        self.current = tl
        return True


def _run(proj, params):
    with mock.patch.object(s, "_playback_refusal", return_value=None):
        return s._timeline_add_captions_impl(proj, proj.main, params)


SEGMENTS = [{"start": 1.0, "end": 2.0, "text": "Olá mundo"}, {"start": 3.0, "end": 4.5, "text": "segunda"}]


class AddCaptionsTest(unittest.TestCase):
    def test_segments_land_on_a_new_track_at_their_frames(self):
        proj = _Project(video_tracks=2)
        out = _run(proj, {"segments": SEGMENTS})
        self.assertTrue(out["success"], out)
        self.assertTrue(out["verified"], out)
        self.assertEqual(out["track_index"], 3)
        placed = sorted(proj.main.tracks[3], key=lambda i: i.start)
        self.assertEqual([(i.start, i.GetEnd()) for i in placed], [(86424, 86448), (86472, 86508)])
        self.assertEqual([t.items[0].comp.text.inputs["StyledText"] for t in proj.pool.inner], ["Olá mundo", "segunda"])
        # inner timelines in the MCP Captions folder; user's timeline restored
        self.assertTrue(all(t.folder.GetName() == "MCP Captions" for t in proj.pool.inner))
        self.assertIs(proj.current, proj.main)
        self.assertIs(proj.pool.current, proj.pool.root)
        self.assertEqual({tl for tl, _ in proj.pool.appends}, {"Edit"})
        self.assertEqual(proj.pool.appends[0][1]["startFrame"], 0)
        self.assertEqual(proj.pool.appends[0][1]["endFrame"], 24)

    def test_style_is_applied_to_the_text_plus(self):
        proj = _Project()
        style = {"font": "DejaVu Sans", "size": 0.08, "color": [1, 1, 0], "position": 0.15}
        out = _run(proj, {"segments": SEGMENTS[:1], "style": style})
        self.assertTrue(out["success"], out)
        inputs = proj.pool.inner[0].items[0].comp.text.inputs
        self.assertEqual(inputs["Font"], "DejaVu Sans")
        self.assertEqual(inputs["Size"], 0.08)
        self.assertEqual((inputs["Red1"], inputs["Green1"], inputs["Blue1"]), (1.0, 1.0, 0.0))
        self.assertEqual(inputs["Center"], {1: 0.5, 2: 0.15})

    def test_caption_longer_than_the_title_is_cut_into_pieces_of_one_inner_timeline(self):
        proj = _Project(title_frames=120)
        out = _run(proj, {"segments": [{"start": 0, "end": 12, "text": "longa"}]})
        self.assertTrue(out["verified"], out)
        placed = sorted(proj.main.tracks[2], key=lambda i: i.start)
        self.assertEqual([(i.start, i.GetEnd()) for i in placed], [(86400, 86520), (86520, 86640), (86640, 86688)])
        self.assertEqual(len(proj.pool.inner), 1)
        self.assertEqual({id(i.mpi) for i in placed}, {id(proj.pool.inner[0].mpi)})

    def test_transcription_words_are_chunked_by_max_words(self):
        proj = _Project()
        clip = mock.Mock()
        clip.GetTranscription.return_value = {"segments": [{"words": [
            {"start": "00:00:00:00", "end": "00:00:00:12", "text": " Olá,"},
            {"start": "00:00:00:12", "end": "00:00:01:00", "text": " este"},
            {"start": "00:00:01:00", "end": "00:00:01:06", "text": " é"},
            {"start": "00:00:01:06", "end": "00:00:01:12", "text": "(...)"},
            {"start": "00:00:02:00", "end": "00:00:02:12", "text": " um"},
            {"start": "00:00:02:12", "end": "00:00:03:00", "text": " teste."},
        ]}]}
        clip.GetClipProperty.side_effect = lambda k=None: {"FPS": "24", "Start TC": "00:00:00:00"}.get(k)
        with mock.patch.object(s, "_find_clip", return_value=clip):
            out = _run(proj, {"clip_id": "fala", "max_words": 3, "record_offset": 10})
        self.assertTrue(out["success"], out)
        self.assertEqual([c["text"] for c in out["captions"]], ["Olá, este é", "um teste."])
        placed = sorted(proj.main.tracks[2], key=lambda i: i.start)
        self.assertEqual([(i.start, i.GetEnd()) for i in placed], [(86640, 86670), (86688, 86712)])

    def test_occupied_track_is_refused_before_anything_is_created(self):
        proj = _Project()
        proj.main.tracks[1].append(_Placed(_TimelineMPI(_Inner("x", None, 1)), 86400, 200, 1))
        out = _run(proj, {"segments": SEGMENTS, "track_index": 1})
        self.assertEqual(out["error"]["code"], "CAPTION_TRACK_OCCUPIED")
        self.assertEqual(proj.pool.inner, [])

    def test_invalid_segments_are_refused(self):
        for bad in ([], [{"start": 2, "end": 1, "text": "x"}], [{"start": 0, "end": 1, "text": ""}],
                    [{"start": -1, "end": 1, "text": "x"}], [{"start": 0, "end": 2, "text": "a"}, {"start": 1, "end": 3, "text": "b"}]):
            proj = _Project()
            out = _run(proj, {"segments": bad})
            self.assertIn("error", out, bad)
            self.assertEqual(proj.pool.inner, [])

    def test_dry_run_and_alias_change_nothing(self):
        for flag in ("dry_run", "dryRun"):
            proj = _Project()
            out = _run(proj, {"segments": SEGMENTS, flag: True})
            self.assertTrue(out["dry_run"], flag)
            self.assertEqual(len(out["plan"]["captions"]), 2)
            self.assertEqual(proj.pool.inner, [])
            self.assertEqual(proj.main.GetTrackCount("video"), 1)


class SetCaptionTextTest(unittest.TestCase):
    def test_changes_the_text_plus_behind_a_placed_caption(self):
        proj = _Project()
        _run(proj, {"segments": SEGMENTS[:1]})
        placed = proj.main.tracks[2][0]
        out = s._timeline_set_caption_text_impl(proj.main, {"timeline_item_id": placed.uid, "text": "novo"})
        self.assertTrue(out["success"], out)
        self.assertEqual(out["readback"], "novo")
        self.assertEqual(proj.pool.inner[0].items[0].comp.text.inputs["StyledText"], "novo")

    def test_dry_run_alias_changes_nothing(self):
        proj = _Project()
        _run(proj, {"segments": SEGMENTS[:1]})
        placed = proj.main.tracks[2][0]
        out = s._timeline_set_caption_text_impl(proj.main, {"timeline_item_id": placed.uid, "text": "novo",
                                                            "dryRun": True})
        self.assertTrue(out["dry_run"])
        self.assertEqual(out["current_text"], "Olá mundo")
        self.assertEqual(proj.pool.inner[0].items[0].comp.text.inputs["StyledText"], "Olá mundo")

    def test_non_caption_item_is_refused(self):
        proj = _Project()
        item = _Placed(object(), 86400, 10, 1)
        proj.main.tracks[1].append(item)
        out = s._timeline_set_caption_text_impl(proj.main, {"timeline_item_id": item.uid, "text": "x"})
        self.assertEqual(out["error"]["code"], "NOT_A_CAPTION")

    def test_registered(self):
        from src.utils.destructive_hook import DESTRUCTIVE_ACTIONS_BY_TOOL, NATIVE_DRY_RUN_ACTIONS
        from src.utils.execution_lifecycle import classify_operation_risk
        for action in ("add_captions", "set_caption_text"):
            self.assertIn(action, DESTRUCTIVE_ACTIONS_BY_TOOL["timeline"])
            self.assertIn(("timeline", action), NATIVE_DRY_RUN_ACTIONS)
            self.assertTrue(classify_operation_risk("timeline", action, {}).to_dict()["recognised"])
            self.assertIn(action, s._TIMELINE_ACTIONS)


if __name__ == "__main__":
    unittest.main()

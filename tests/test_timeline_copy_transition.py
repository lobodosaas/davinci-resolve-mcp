"""timeline(action="copy_transition"): clone a transition onto another cut.

Resolve 21.1 can create a transition (TimelineItem.AddTransition) but cannot read
one back beyond its name and frame range, and has no clone verb. Measured on
Studio 21.1.1 (Linux), a 12-frame Cross Dissolve on a cut at 86448 spans
86436-86448 when left-aligned, 86448-86460 when right-aligned and 86442-86454
when centred, whichever side of the cut it was added from. So the copy reads the
name and span, infers the alignment from the span against its own cut, and adds
the same transition at the target cut. GetProperty() is {} on a transition, so
the category is not readable: it defaults to "simple".
"""

import unittest

import src.server as s


class _Item:
    def __init__(self, tl, uid, kind, name, start, end, track=1, track_type="video"):
        self.tl, self.uid, self.kind, self.name = tl, uid, kind, name
        self.start, self.end, self.track, self.track_type = start, end, track, track_type

    def GetUniqueId(self):
        return self.uid

    def GetType(self):
        return self.kind

    def GetName(self):
        return self.name

    def GetStart(self):
        return self.start

    def GetEnd(self):
        return self.end

    def GetDuration(self):
        return self.end - self.start

    def GetTrackTypeAndIndex(self):
        return [self.track_type, self.track]

    def GetProperty(self, key=None):
        return {} if self.kind == "transition" else {"ZoomX": 1.0}

    def AddTransition(self, options):
        self.tl.calls.append((self.uid, dict(options)))
        cut = self.end if options["position"] == "end" else self.start
        d = options.get("duration") or 8
        span = {"left": (cut - d, cut), "right": (cut, cut + d),
                "center": (cut - d // 2, cut - d // 2 + d)}[options["alignment"]]
        t = _Item(self.tl, f"t{len(self.tl.items)}", "transition", options["type"], *span,
                  track=self.track, track_type=self.track_type)
        self.tl.items.append(t)
        return t


class _Timeline:
    def __init__(self):
        self.items, self.calls = [], []

    def add(self, *args, **kwargs):
        item = _Item(self, *args, **kwargs)
        self.items.append(item)
        return item

    def GetTrackCount(self, kind):
        return 1 if kind in ("video", "audio") else 0

    def GetItemListInTrack(self, kind, idx):
        return sorted([i for i in self.items if i.track_type == kind and i.track == idx],
                      key=lambda i: (i.start, i.end))


def _fixture(source_span=(86436, 86448)):
    tl = _Timeline()
    tl.add("a", "video", "clipA", 86400, 86448)
    tl.add("b", "video", "clipB", 86448, 86496)
    tl.add("c", "video", "clipA", 86496, 86544)
    src = tl.add("src", "transition", "Cross Dissolve", *source_span)
    return tl, src


class CopyTransitionTest(unittest.TestCase):
    def test_left_aligned_copy_lands_with_same_name_duration_and_alignment(self):
        tl, src = _fixture((86436, 86448))
        out = s._timeline_copy_transition_impl(tl, {"transition_id": "src", "before_item_id": "b"})
        self.assertTrue(out["success"], out)
        self.assertTrue(out["verified"], out)
        self.assertEqual(tl.calls, [("b", {"type": "Cross Dissolve", "category": "simple",
                                           "position": "end", "alignment": "left", "duration": 12})])
        self.assertEqual((out["transition"]["start"], out["transition"]["end"]), (86484, 86496))

    def test_alignment_is_inferred_from_the_span(self):
        for span, want in (((86442, 86454), "center"), ((86448, 86460), "right"), ((86436, 86448), "left")):
            tl, _ = _fixture(span)
            out = s._timeline_copy_transition_impl(tl, {"transition_id": "src", "after_item_id": "c",
                                                        "dry_run": True})
            self.assertEqual(out["plan"]["options"]["alignment"], want, span)
            self.assertEqual(out["plan"]["options"]["position"], "start")
            self.assertEqual(out["plan"]["target_cut"], 86496)
            self.assertEqual(tl.calls, [])

    def test_dry_run_camel_case_alias_changes_nothing(self):
        tl, _ = _fixture()
        out = s._timeline_copy_transition_impl(tl, {"transition_id": "src", "before_item_id": "b",
                                                    "dryRun": True})
        self.assertTrue(out["dry_run"])
        self.assertEqual(tl.calls, [])

    def test_source_must_be_a_transition(self):
        tl, _ = _fixture()
        out = s._timeline_copy_transition_impl(tl, {"transition_id": "a", "before_item_id": "b"})
        self.assertEqual(out["error"]["code"], "NOT_A_TRANSITION")

    def test_target_must_be_a_cut(self):
        tl, _ = _fixture()
        out = s._timeline_copy_transition_impl(tl, {"transition_id": "src", "before_item_id": "c"})
        self.assertEqual(out["error"]["code"], "NO_CUT")
        self.assertEqual(tl.calls, [])

    def test_occupied_cut_is_refused(self):
        tl, _ = _fixture()
        out = s._timeline_copy_transition_impl(tl, {"transition_id": "src", "after_item_id": "b"})
        self.assertEqual(out["error"]["code"], "TRANSITION_EXISTS")

    def test_registered(self):
        from src.utils.destructive_hook import DESTRUCTIVE_ACTIONS_BY_TOOL, NATIVE_DRY_RUN_ACTIONS
        from src.utils.execution_lifecycle import classify_operation_risk
        self.assertIn("copy_transition", DESTRUCTIVE_ACTIONS_BY_TOOL["timeline"])
        self.assertIn(("timeline", "copy_transition"), NATIVE_DRY_RUN_ACTIONS)
        self.assertTrue(classify_operation_risk("timeline", "copy_transition", {}).to_dict()["recognised"])
        self.assertIn("copy_transition", s._TIMELINE_ACTIONS)


if __name__ == "__main__":
    unittest.main()

"""action_help covers the actions added for Resolve 21.1 (split/captions/transitions,
animate_transform, apply_wheels, set_audio), and the tool descriptions surface them
before the long action lists that clients truncate."""
import unittest
import unittest.mock

import src.server as s
from src.granular import media_pool as g_media_pool
from src.granular import timeline as g_timeline

NEW_ACTIONS = {
    "timeline": ["add_captions", "set_caption_text", "copy_transition", "split_item"],
    "timeline_item_fusion": ["animate_transform"],
    "timeline_item_color": ["apply_wheels"],
    "timeline_item": ["set_audio"],
}

#: Caveats each entry must carry (lower-cased substring search over the entry).
CAVEATS = {
    ("timeline", "add_captions"): ["5 s", "record_offset", "max_words", "seconds"],
    ("timeline", "split_item"): ["speed", "fusion", "audio level", "confirm_token"],
    ("timeline", "copy_transition"): ["handles", "alignment"],
    ("timeline", "set_caption_text"): ["every piece"],
    ("timeline_item_fusion", "animate_transform"): ["relative to the item start"],
    ("timeline_item_color", "apply_wheels"): ["new local version", "confirm_token"],
    ("timeline_item", "set_audio"): ["db", "-100", "6 db", "not a hard pan"],
}


def _entry_text(entry):
    return " ".join(str(v) for v in entry.values()).lower()


class NewActionHelpTest(unittest.TestCase):
    def test_every_new_action_has_registered_help(self):
        for tool, names in NEW_ACTIONS.items():
            for name in names:
                with self.subTest(tool=tool, action=name):
                    out = s._action_help(tool, {"name": name})
                    self.assertTrue(out.get("success"), out)
                    for key in ("summary", "params", "returns", "example"):
                        self.assertIn(key, out)
                    self.assertIn(name, out["example"])

    def test_entries_carry_the_caveats(self):
        for (tool, name), needles in CAVEATS.items():
            entry = s._ACTION_HELP[tool][name]
            text = _entry_text(entry)
            for needle in needles:
                with self.subTest(tool=tool, action=name, needle=needle):
                    self.assertIn(needle.lower(), text)

    def test_item_tools_dispatch_action_help_without_resolve(self):
        with unittest.mock.patch.object(s, "_get_item", side_effect=AssertionError("needs no item")):
            out = s.timeline_item("action_help", {"name": "set_audio"})
            self.assertTrue(out.get("success"), out)
            out = s.timeline_item_fusion("action_help", {"name": "animate_transform"})
            self.assertTrue(out.get("success"), out)


class NewActionsDiscoverableTest(unittest.TestCase):
    """Clients cut long tool descriptions; the new actions must be named early."""

    HEAD = 1500

    def test_tool_descriptions_name_new_actions_near_the_top(self):
        for tool, names in NEW_ACTIONS.items():
            doc = getattr(s, tool).__doc__ or ""
            head = doc[: self.HEAD]
            for name in names:
                with self.subTest(tool=tool, action=name):
                    self.assertIn(name, head)

    def test_replace_source_range_description_is_not_under_set_caption_text(self):
        doc = s.timeline.__doc__
        caption = doc.index("set_caption_text(timeline_item_id")
        slip = doc.index("Slip a video item")
        replace = doc.index("replace_source_range(timeline_item_id")
        self.assertLess(replace, slip, "slip prose must follow replace_source_range")
        self.assertNotIn("Slip a video item", doc[caption:doc.index("ripple_insert(clip_infos")])


class EndFrameExclusiveDocumentedTest(unittest.TestCase):
    def test_append_and_create_document_exclusive_end_frame(self):
        docs = {
            "media_pool": s.media_pool.__doc__,
            "granular append_to_timeline": g_media_pool.append_to_timeline.__doc__,
            "granular create_timeline_from_clips": g_timeline.create_timeline_from_clips.__doc__,
        }
        for label, doc in docs.items():
            with self.subTest(doc=label):
                self.assertIn("EXCLUSIVE", doc or "")


if __name__ == "__main__":
    unittest.main()

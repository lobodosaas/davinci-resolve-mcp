"""Destructive timeline actions announce the archive they will create.

The version-on-mutate hook archives the timeline as '<name>_archived_vNN'
before a destructive call, but the confirm-token preview and the dry-run plan
did not say so, and the success response carried only the version number.
"""
from __future__ import annotations

import shutil
import tempfile
import unittest
from unittest import mock

from src.utils import analysis_runs, destructive_hook, timeline_versioning
from src.utils.execution_lifecycle import ReadbackVerificationHook, ToolCallContext
from tests.test_timeline_versioning import _MockProject, _MockTimeline


class _Ctx(unittest.TestCase):
    def setUp(self) -> None:
        self.root = tempfile.mkdtemp(prefix="archive_announce_")
        self.addCleanup(shutil.rmtree, self.root, True)
        self.tl = _MockTimeline("Edit")
        self.project = _MockProject(self.tl)
        self.project._timelines.append(_MockTimeline("Edit_archived_v02", unique_id="tl_old"))
        saved = (destructive_hook._PROVIDER, destructive_hook._PENDING_CONFIRM_CHECK)
        self.addCleanup(self._restore, saved)
        destructive_hook.register_project_root_provider(
            lambda: (object(), self.project, self.root, "proj"))
        analysis_runs._reset_for_test()
        self.addCleanup(analysis_runs._reset_for_test)

    @staticmethod
    def _restore(saved):
        destructive_hook._PROVIDER, destructive_hook._PENDING_CONFIRM_CHECK = saved


class PredictArchiveNameTest(_Ctx):
    def test_prediction_bumps_past_existing_suffixes(self):
        self.assertEqual(
            timeline_versioning.predict_archive_name(self.project, self.root, self.tl),
            "Edit_archived_v03")

    def test_archive_uses_the_predicted_name(self):
        predicted = timeline_versioning.predict_archive_name(self.project, self.root, self.tl)
        out = timeline_versioning.archive_current_timeline(
            resolve=None, project=self.project, project_root=self.root)
        self.assertEqual(out["archived_timeline_name"], predicted)


class HookAnnouncesArchiveTest(_Ctx):
    def test_confirm_token_preview_names_the_archive(self):
        destructive_hook.register_pending_confirm_check(
            lambda tool, action, params: not (params or {}).get("confirm_token"))

        @destructive_hook.destructive_op("timeline")
        def fake_timeline(action, params=None):
            return {"status": "confirmation_required", "confirm_token": "t",
                    "preview": {"operation": "timeline.split_item"}}

        out = fake_timeline("split_item", {"timeline_item_id": "x", "frame": 10})
        self.assertEqual(out["preview"]["archive"],
                         "will create timeline 'Edit_archived_v03' before changing")
        self.assertEqual(self.tl.duplicates, [])  # nothing archived yet

    def test_dry_run_plan_names_the_archive(self):
        @destructive_hook.destructive_op("timeline")
        def fake_timeline(action, params=None):
            return {"success": True, "dry_run": True, "plan": {"target_cut": 10}}

        out = fake_timeline("copy_transition", {"transition_id": "t", "dry_run": True})
        self.assertIn("Edit_archived_v03", out["plan"]["archive"])
        self.assertEqual(self.tl.duplicates, [])

    def test_success_response_carries_the_created_archive(self):
        destructive_hook.register_pending_confirm_check(lambda *a: False)

        @destructive_hook.destructive_op("timeline")
        def fake_timeline(action, params=None):
            return {"success": True, "verified": True}

        out = fake_timeline("split_item", {"timeline_item_id": "x", "frame": 10, "confirm_token": "t"})
        self.assertEqual(self.tl.duplicates, ["Edit_archived_v03"])
        self.assertEqual(out["_versioning"]["archived_timeline_name"], "Edit_archived_v03")
        self.assertEqual(out["archive"], {"created": "Edit_archived_v03"})

    def test_preview_says_no_new_archive_inside_an_archived_run(self):
        run = analysis_runs.begin_run(project_root=self.root, label="r", initiator="test")
        timeline_versioning.ensure_versioned_before_mutation(
            resolve=None, project=self.project, project_root=self.root,
            analysis_run_id=run["analysis_run_id"])
        destructive_hook.register_pending_confirm_check(lambda *a: True)

        @destructive_hook.destructive_op("timeline")
        def fake_timeline(action, params=None):
            return {"status": "confirmation_required", "preview": {}}

        out = fake_timeline("ripple_insert", {"dry_run": False})
        self.assertIn("already archived", out["preview"]["archive"])
        self.assertIn("Edit_archived_v03", out["preview"]["archive"])


class ApplyWheelsTokenIssuanceSkipsArchiveTest(unittest.TestCase):
    def test_apply_wheels_is_token_gated_for_the_hook(self):
        import src.server as s
        self.assertIn(("timeline_item_color", "apply_wheels"), s._TOKEN_GATED_DESTRUCTIVE_ACTIONS)


class ReadbackNoticeTest(unittest.TestCase):
    def _ctx(self):
        ctx = ToolCallContext("timeline", "split_item", {})
        ctx.risk.destructive = True
        return ctx

    def test_top_level_verified_counts_as_readback(self):
        res = ReadbackVerificationHook().after_tool_call(
            self._ctx(), {"success": True, "verified": True}, duration_ms=1)
        self.assertTrue(res["readback_checked"])
        self.assertTrue(res["verified"])
        self.assertNotIn("notice", res)

    def test_confirm_token_issuance_is_not_flagged(self):
        res = ReadbackVerificationHook().after_tool_call(
            self._ctx(), {"status": "confirmation_required", "confirm_token": "t"}, duration_ms=1)
        self.assertIsNone(res)

    def test_dry_run_is_not_flagged(self):
        res = ReadbackVerificationHook().after_tool_call(
            self._ctx(), {"success": True, "dry_run": True, "plan": {}}, duration_ms=1)
        self.assertIsNone(res)

    def test_unverified_mutation_still_flagged(self):
        res = ReadbackVerificationHook().after_tool_call(
            self._ctx(), {"success": True}, duration_ms=1)
        self.assertIn("without readback verification", res["notice"])


if __name__ == "__main__":
    unittest.main()

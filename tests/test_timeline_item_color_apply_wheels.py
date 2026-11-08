"""timeline_item_color(action="apply_wheels"): lift / gamma / gain / saturation.

The API cannot write primary wheel values. Default route: the offline DRX
generator writes a one-node grade with the wheels, applied with
ApplyGradeFromDRX on the Color page (previous page restored). Measured on Studio
21.1.1: AddVersion copies the current grade into a new local version and makes
it current, ApplyGradeFromDRX then replaces that version's graph, and the
previous version still renders the old grade after LoadVersionByName. So the
wheels always land on a new version: nothing is silently wiped. Fallback route:
SetCDL (slope ~ gain, offset ~ lift, power ~ gamma).
"""

import os
import tempfile
import unittest
from unittest import mock

import src.server as s
from src.utils import color_wheels


class _Graph:
    def __init__(self, item):
        self.item = item

    def GetNumNodes(self):
        return 1

    def GetNodeLabel(self, i):
        return self.item.grade

    def GetLUT(self, i):
        return ""

    def ApplyGradeFromDRX(self, path, mode):
        self.item.calls.append(("ApplyGradeFromDRX", os.path.basename(path), mode, self.item.resolve.page))
        self.item.grade = "wheels"
        return True


class _Resolve:
    def __init__(self):
        self.page = "edit"
        self.pages = []

    def GetCurrentPage(self):
        return self.page

    def OpenPage(self, page):
        self.pages.append(page)
        self.page = page
        return True


class _Item:
    def __init__(self, resolve):
        self.resolve = resolve
        self.calls = []
        self.versions = ["Version 1"]
        self.current = "Version 1"
        self.grade = "existing"

    def GetUniqueId(self):
        return "v1"

    def GetName(self):
        return "clipB.mov"

    def GetNodeGraph(self, layer=1):
        return _Graph(self)

    def GetCurrentVersion(self):
        return {"versionName": self.current, "versionType": 0}

    def GetVersionNameList(self, kind):
        return list(self.versions) if kind == 0 else []

    def AddVersion(self, name, kind):
        self.calls.append(("AddVersion", name, kind))
        self.versions.append(name)
        self.current = name
        return True

    def SetCDL(self, cdl):
        self.calls.append(("SetCDL", cdl))
        return True


def _fake_generate(params, path, label="MCP wheels"):
    with open(path, "w") as fh:
        fh.write("<drx/>")
    _fake_generate.last = params
    return {"ok": True, "outputPath": path, "bytes": 6}


class ApplyWheelsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.resolve = _Resolve()
        self.item = _Item(self.resolve)

    def _run(self, params, generate=_fake_generate):
        with mock.patch.object(s, "_confirm_token_required", return_value=False), \
             mock.patch.object(s._color_wheels, "generate_drx", side_effect=generate):
            return s._apply_wheels(None, self.item, {"work_dir": self.tmp.name, **params}, resolve=self.resolve)

    def test_wheels_land_on_a_new_version_via_drx_on_the_color_page(self):
        out = self._run({"lift": [0.03, 0, -0.03], "gamma": 0.03, "gain": [1.2, 1.0, 0.8]})
        self.assertTrue(out["success"], out)
        self.assertEqual(out["method_used"], "drx")
        self.assertEqual(self.item.calls[0][0], "AddVersion")
        apply = [c for c in self.item.calls if c[0] == "ApplyGradeFromDRX"]
        self.assertEqual(len(apply), 1)
        self.assertEqual(apply[0][3], "color")
        self.assertEqual(self.resolve.page, "edit")  # restored
        self.assertEqual(out["previous_version"]["versionName"], "Version 1")
        self.assertEqual(_fake_generate.last["gain"], {"r": 1.2, "g": 1.0, "b": 0.8, "master": 1.0})
        self.assertEqual(_fake_generate.last["gamma"], {"r": 0.0, "g": 0.0, "b": 0.0, "master": 0.03})

    def test_falls_back_to_cdl_when_the_generator_is_unavailable(self):
        def broken(*a, **k):
            raise RuntimeError("node is not on PATH")
        out = self._run({"gain": [1.2, 1.0, 0.8], "lift": 0.01}, generate=broken)
        self.assertTrue(out["success"], out)
        self.assertEqual(out["method_used"], "cdl")
        self.assertIn("node", out["fallback_reason"])
        cdl = [c[1] for c in self.item.calls if c[0] == "SetCDL"][0]
        self.assertEqual([float(x) for x in cdl["Slope"].split()], [1.2, 1.0, 0.8])
        self.assertEqual([float(x) for x in cdl["Offset"].split()], [0.01, 0.01, 0.01])

    def test_cdl_mapping(self):
        params = color_wheels.grade_params(lift=0.02, gamma=[0.0, 0.05, 0.0], gain=1.1, saturation=60)
        cdl = color_wheels.cdl_approximation(params)
        self.assertEqual(cdl["Slope"], [1.1, 1.1, 1.1])
        self.assertEqual(cdl["Offset"], [0.02, 0.02, 0.02])
        self.assertEqual(cdl["Power"], [1.0, 0.8, 1.0])
        self.assertEqual(cdl["Saturation"], 1.2)

    def test_invalid_wheels_are_refused_before_any_write(self):
        for bad in ({}, {"gain": [1, 2]}, {"lift": "up"}, {"saturation": 150}, {"gain": True}):
            out = self._run(bad)
            self.assertIn("error", out, bad)
        self.assertEqual(self.item.calls, [])

    def test_dry_run_and_alias_change_nothing(self):
        for flag in ("dry_run", "dryRun"):
            out = self._run({"gain": 1.1, flag: True})
            self.assertTrue(out["dry_run"], flag)
            self.assertIn("cdl_approximation", out["plan"])
        self.assertEqual(self.item.calls, [])
        self.assertEqual(self.resolve.pages, [])

    def test_confirm_token_gated(self):
        with mock.patch.object(s, "_confirm_token_required", return_value=True):
            out = s._apply_wheels(None, self.item, {"gain": 1.1, "work_dir": self.tmp.name}, resolve=self.resolve)
        self.assertIn("confirm_token", str(out))
        self.assertEqual(self.item.calls, [])

    def test_registered(self):
        from src.utils.destructive_hook import DESTRUCTIVE_ACTIONS_BY_TOOL, NATIVE_DRY_RUN_ACTIONS
        from src.utils.execution_lifecycle import classify_operation_risk
        self.assertIn("apply_wheels", DESTRUCTIVE_ACTIONS_BY_TOOL["timeline_item_color"])
        self.assertIn(("timeline_item_color", "apply_wheels"), NATIVE_DRY_RUN_ACTIONS)
        self.assertTrue(classify_operation_risk("timeline_item_color", "apply_wheels", {}).to_dict()["recognised"])
        self.assertIn("apply_wheels", s._COLOR_GRADE_KERNEL_ACTIONS)


if __name__ == "__main__":
    unittest.main()

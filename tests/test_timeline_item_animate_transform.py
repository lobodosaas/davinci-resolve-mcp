"""timeline_item_fusion(action="animate_transform"): keyframed transform via Fusion.

Measured on Studio 21.1.1 (Linux): item.AddFusionComp() gives a comp whose render
range is 0..duration-1 (item-relative); a Transform tool inserted between the
upstream of MediaOut1 and MediaOut1 animates when its input is set to a
BezierSpline (Size, Angle) or a Path (Center) and then SetInput(name, value,
frame) per keyframe; GetInput(name, frame) reads interpolated values back.
"""

import unittest

import src.server as s


class _Output:
    def __init__(self, tool):
        self.tool = tool

    def GetTool(self):
        return self.tool


class _Input:
    def __init__(self, tool):
        self.tool = tool

    def GetConnectedOutput(self):
        up = self.tool.inputs_from.get("Input")
        return _Output(up) if up else None


class _Tool:
    def __init__(self, name, kind):
        self.Name, self.kind = name, kind
        self.inputs_from = {}
        self.splines = {}
        self.keys = {}
        self.Input = _Input(self)

    def ConnectInput(self, name, tool):
        self.inputs_from[name] = tool
        return True

    def __setattr__(self, key, value):
        if key in ("Size", "Angle", "Center"):
            self.splines[key] = value
        else:
            object.__setattr__(self, key, value)

    def SetInput(self, name, value, frame=None):
        if name in self.splines:
            self.keys.setdefault(name, {})[frame] = value
        return None  # Resolve returns None even when it sets

    def GetInput(self, name, frame=None):
        return self.keys.get(name, {}).get(frame)


class _Comp:
    def __init__(self, start=0, end=47):
        self.tools = {"MediaIn1": _Tool("MediaIn1", "MediaIn"), "MediaOut1": _Tool("MediaOut1", "MediaOut")}
        self.tools["MediaOut1"].inputs_from["Input"] = self.tools["MediaIn1"]
        self.attrs = {"COMPN_RenderStart": float(start), "COMPN_RenderEnd": float(end)}

    def GetAttrs(self):
        return dict(self.attrs)

    def FindTool(self, name):
        return self.tools.get(name)

    def AddTool(self, kind, x, y):
        n = sum(1 for t in self.tools.values() if t.kind == kind) + 1
        tool = _Tool(f"{kind}{n}", kind)
        self.tools[tool.Name] = tool
        return tool

    def BezierSpline(self):
        return "spline"

    def Path(self):
        return "path"


class _Item:
    def __init__(self, comps=0):
        self.comps = [_Comp() for _ in range(comps)]

    def GetUniqueId(self):
        return "v1"

    def GetDuration(self):
        return 48

    def GetFusionCompCount(self):
        return len(self.comps)

    def GetFusionCompByIndex(self, i):
        return self.comps[i - 1]

    def AddFusionComp(self):
        self.comps.append(_Comp())
        return self.comps[-1]


KEYS = [{"frame": 0, "size": 1.0, "center": [0.5, 0.5], "angle": 0},
        {"frame": 47, "size": 2.0, "center": [0.2, 0.7], "angle": 90}]


class AnimateTransformTest(unittest.TestCase):
    def test_adds_comp_wires_transform_and_keys_every_property(self):
        item = _Item()
        out = s._timeline_item_animate_transform(item, {"keyframes": KEYS})
        self.assertTrue(out["success"], out)
        self.assertTrue(out["verified"], out)
        comp = item.comps[0]
        tr = comp.tools["Transform1"]
        self.assertIs(tr.inputs_from["Input"], comp.tools["MediaIn1"])
        self.assertIs(comp.tools["MediaOut1"].inputs_from["Input"], tr)
        self.assertEqual(tr.splines, {"Size": "spline", "Angle": "spline", "Center": "path"})
        self.assertEqual(tr.keys["Size"], {0: 1.0, 47: 2.0})
        self.assertEqual(tr.keys["Center"][47], {1: 0.2, 2: 0.7})
        self.assertEqual(tr.keys["Angle"], {0: 0.0, 47: 90.0})

    def test_existing_comp_gets_transform_inserted_before_media_out(self):
        item = _Item(comps=1)
        comp = item.comps[0]
        grade = comp.AddTool("BrightnessContrast", 0, 0)
        grade.ConnectInput("Input", comp.tools["MediaIn1"])
        comp.tools["MediaOut1"].ConnectInput("Input", grade)
        out = s._timeline_item_animate_transform(item, {"keyframes": KEYS[:1] + [{"frame": 47, "size": 3}]})
        self.assertTrue(out["success"], out)
        self.assertEqual(len(item.comps), 1)
        tr = comp.tools["Transform1"]
        self.assertIs(tr.inputs_from["Input"], grade)
        self.assertIs(comp.tools["MediaOut1"].inputs_from["Input"], tr)

    def test_frames_are_offset_by_the_comp_render_start(self):
        item = _Item(comps=1)
        item.comps[0].attrs.update({"COMPN_RenderStart": 100.0, "COMPN_RenderEnd": 147.0})
        out = s._timeline_item_animate_transform(item, {"keyframes": [{"frame": 0, "size": 1}, {"frame": 47, "size": 2}]})
        self.assertTrue(out["verified"], out)
        self.assertEqual(item.comps[0].tools["Transform1"].keys["Size"], {100: 1.0, 147: 2.0})

    def test_invalid_keyframes_are_refused_before_any_write(self):
        for bad in ([], [{"frame": 0}], [{"frame": 48, "size": 1}], [{"frame": -1, "size": 1}],
                    [{"frame": 0, "center": [1]}], [{"frame": 0, "size": "big"}], [{"frame": 0, "size": 0}]):
            item = _Item()
            out = s._timeline_item_animate_transform(item, {"keyframes": bad})
            self.assertIn("error", out, bad)
            self.assertEqual(item.comps, [], bad)

    def test_dry_run_changes_nothing(self):
        item = _Item()
        out = s._timeline_item_animate_transform(item, {"keyframes": KEYS, "dry_run": True})
        self.assertTrue(out["dry_run"])
        self.assertEqual(out["plan"]["properties"], ["Angle", "Center", "Size"])
        self.assertEqual(item.comps, [])

    def test_dry_run_camel_case_alias_changes_nothing(self):
        # The destructive hook treats dryRun as a dry run (no archive), so the
        # handler must too.
        item = _Item()
        out = s._timeline_item_animate_transform(item, {"keyframes": KEYS, "dryRun": True})
        self.assertTrue(out["dry_run"])
        self.assertEqual(item.comps, [])

    def test_registered(self):
        from src.utils.destructive_hook import DESTRUCTIVE_ACTIONS_BY_TOOL, NATIVE_DRY_RUN_ACTIONS
        from src.utils.execution_lifecycle import classify_operation_risk
        self.assertIn("animate_transform", DESTRUCTIVE_ACTIONS_BY_TOOL["timeline_item_fusion"])
        self.assertIn(("timeline_item_fusion", "animate_transform"), NATIVE_DRY_RUN_ACTIONS)
        self.assertTrue(classify_operation_risk("timeline_item_fusion", "animate_transform", {}).to_dict()["recognised"])


if __name__ == "__main__":
    unittest.main()

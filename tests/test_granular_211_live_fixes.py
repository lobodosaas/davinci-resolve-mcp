"""Granular-server bugs found live on Resolve Studio 21.1.1 (Linux), 2026-11-08.

Each case was measured against a real project before being pinned here:

- save_project / close_project referenced an undefined ``project_manager`` name,
  so save never saved yet reported "Automatic save likely in effect".
- Project.SetSetting only accepts string values for documented string settings
  (``SetSetting("timelineResolutionWidth", 1920)`` -> False, ``"1920"`` -> True),
  but set_project_property coerced them to int/float first.
- Cache/proxy/optimized/SuperScale/colour tools wrote keys that do not exist
  (``CacheMode``, ``ProxyMode``, ``superScaleEnabled``, ``timelineColorSpace`` ...).
  The real keys and values come from DaVinciResolveScript.pyi shipped with 21.1.
- render_with_quick_export reported success for ``JobStatus: Render Failed``.
- ti_get_takes_info returned raw MediaPoolItem objects (JSON serialization crash).
- clear_clip_flags defaulted to ``""``; Resolve only clears every flag with ``"All"``.
"""

import unittest
from unittest import mock

import src.granular.project as gproject
import src.granular.timeline_item as gitem
import src.granular.media_pool_item as gmpi
from src.utils import project_properties as props


class _ProjectStub:
    """Accepts only the value shapes Resolve 21.1 accepted live."""

    STRING_KEYS = {
        "timelineResolutionWidth", "timelineResolutionHeight", "timelineFrameRate",
        "timelineInterlaceProcessing", "perfRenderCacheMode", "perfOptimisedMediaOn",
        "perfProxyMediaMode", "perfProxyResolutionRatio", "colorScienceMode",
        "colorSpaceTimeline", "colorSpaceTimelineGamma", "separateColorSpaceAndGamma",
    }
    VALID = {
        "perfRenderCacheMode": {"none", "smart", "user"},
        "perfOptimisedMediaOn": {"0", "1"},
        "perfProxyMediaMode": {"0", "1", "2"},
        "perfProxyResolutionRatio": {"original", "half", "quarter"},
        "colorScienceMode": {"davinciYRGB", "davinciYRGBColorManaged",
                             "davinciYRGBColorManagedv2", "acescc", "acescct"},
    }

    def __init__(self):
        self.settings = {"superScale": 1}

    def GetName(self):
        return "P"

    def SetSetting(self, key, value):
        if key == "superScale":
            if type(value) is not int or value not in (0, 1, 2, 3, 4):
                return False
        elif key in self.STRING_KEYS:
            if not isinstance(value, str):
                return False
            if key in self.VALID and value not in self.VALID[key]:
                return False
        else:
            return False  # unknown key, as Resolve does
        self.settings[key] = value
        return True

    def GetSetting(self, key=""):
        return self.settings.get(key)


class _PMStub:
    def __init__(self):
        self.saved = 0
        self.closed = []

    def SaveProject(self):
        self.saved += 1
        return True

    def CloseProject(self, project):
        self.closed.append(project)
        return True


class ProjectLifecycleTest(unittest.TestCase):
    def setUp(self):
        self.pm, self.project = _PMStub(), _ProjectStub()
        p = mock.patch.object(gproject, "get_current_project", return_value=(self.pm, self.project))
        p.start()
        self.addCleanup(p.stop)

    def test_save_project_saves_through_project_manager(self):
        out = gproject.save_project()
        self.assertEqual(self.pm.saved, 1)
        self.assertIn("Successfully saved", out)

    def test_close_project_closes_through_project_manager(self):
        out = gproject.close_project.__wrapped__() if hasattr(gproject.close_project, "__wrapped__") else gproject.close_project()
        self.assertEqual(self.pm.closed, [self.project])
        self.assertIn("Successfully closed", out)


class ProjectSettingsTest(unittest.TestCase):
    def setUp(self):
        self.pm, self.project = _PMStub(), _ProjectStub()
        p = mock.patch.object(gproject, "get_current_project", return_value=(self.pm, self.project))
        p.start()
        self.addCleanup(p.stop)

    def _call(self, fn, *a, **k):
        fn = getattr(fn, "__wrapped__", fn)
        return fn(*a, **k)

    def test_set_project_property_sends_strings(self):
        self.assertTrue(props.set_project_property(self.project, "timelineResolutionWidth", 1920))
        self.assertEqual(self.project.settings["timelineResolutionWidth"], "1920")
        self.assertTrue(props.set_project_property(self.project, "timelineFrameRate", 24.0))
        self.assertEqual(self.project.settings["timelineFrameRate"], "24")

    def test_timeline_format(self):
        out = self._call(gproject.set_timeline_format_tool, 1920, 1080, 23.976)
        self.assertIn("Successfully", out)
        self.assertEqual(self.project.settings["timelineFrameRate"], "23.976")
        self.assertEqual(self.project.settings["timelineInterlaceProcessing"], "0")

    def test_cache_mode_native_and_legacy_names(self):
        self.assertIn("Successfully", self._call(gproject.set_cache_mode, "smart"))
        self.assertEqual(self.project.settings["perfRenderCacheMode"], "smart")
        self.assertIn("Successfully", self._call(gproject.set_cache_mode, "off"))
        self.assertEqual(self.project.settings["perfRenderCacheMode"], "none")
        self.assertIn("Successfully", self._call(gproject.set_cache_mode, "user"))
        self.assertEqual(self.project.settings["perfRenderCacheMode"], "user")

    def test_optimized_media_mode(self):
        self.assertIn("Successfully", self._call(gproject.set_optimized_media_mode, "on"))
        self.assertEqual(self.project.settings["perfOptimisedMediaOn"], "1")
        self.assertIn("Successfully", self._call(gproject.set_optimized_media_mode, "off"))
        self.assertEqual(self.project.settings["perfOptimisedMediaOn"], "0")

    def test_proxy_mode(self):
        for mode, native in (("off", "0"), ("when_available", "1"), ("when_source_unavailable", "2"), ("on", "1")):
            self.assertIn("Successfully", self._call(gproject.set_proxy_mode, mode), mode)
            self.assertEqual(self.project.settings["perfProxyMediaMode"], native)
        self.assertIn("Error", self._call(gproject.set_proxy_mode, "bogus"))

    def test_proxy_quality(self):
        self.assertIn("Successfully", self._call(gproject.set_proxy_quality, "half"))
        self.assertEqual(self.project.settings["perfProxyResolutionRatio"], "half")
        self.assertIn("Successfully", self._call(gproject.set_proxy_quality, "full"))
        self.assertEqual(self.project.settings["perfProxyResolutionRatio"], "original")
        self.assertIn("Error", self._call(gproject.set_proxy_quality, "threeQuarter"))

    def test_superscale(self):
        self.assertIn("Successfully", self._call(gproject.set_superscale_settings_tool, True, scale=2))
        self.assertEqual(self.project.settings["superScale"], 2)
        self.assertIn("Successfully", self._call(gproject.set_superscale_settings_tool, False))
        self.assertEqual(self.project.settings["superScale"], 1)

    def test_color_science_aliases_and_native(self):
        self.assertIn("Successfully", self._call(gproject.set_color_science_mode_tool, "YRGB"))
        self.assertEqual(self.project.settings["colorScienceMode"], "davinciYRGB")
        self.assertIn("Successfully", self._call(gproject.set_color_science_mode_tool, "acescct"))
        self.assertEqual(self.project.settings["colorScienceMode"], "acescct")
        self.assertIn("Successfully", self._call(gproject.set_color_science_mode_tool, "YRGB Color Managed"))
        self.assertEqual(self.project.settings["colorScienceMode"], "davinciYRGBColorManagedv2")

    def test_color_space_writes_timeline_keys(self):
        out = self._call(gproject.set_color_space_tool, "Rec.709 (Scene)", "Gamma 2.4")
        self.assertIn("Successfully", out)
        self.assertEqual(self.project.settings["colorSpaceTimeline"], "Rec.709 (Scene)")
        self.assertEqual(self.project.settings["colorSpaceTimelineGamma"], "Gamma 2.4")


class QuickExportStatusTest(unittest.TestCase):
    def _run(self, status):
        project = mock.Mock()
        project.RenderWithQuickExport.return_value = status
        resolve = mock.Mock()
        resolve.GetProjectManager.return_value.GetCurrentProject.return_value = project
        with mock.patch.object(gproject, "get_resolve", return_value=resolve):
            return gproject.render_with_quick_export("H.264")

    def test_failed_job_is_not_success(self):
        out = self._run({"JobStatus": "Render Failed", "Error": "Invalid quick export preset name"})
        self.assertFalse(out["success"])
        self.assertIn("Invalid quick export preset name", out["error"])

    def test_running_job_is_success(self):
        out = self._run({"JobStatus": "Rendering", "CompletionPercentage": 0})
        self.assertTrue(out["success"])


class TakesInfoSerializableTest(unittest.TestCase):
    def test_media_pool_item_is_flattened(self):
        mpi = mock.Mock()
        mpi.GetName.return_value = "clipB.mov"
        mpi.GetUniqueId.return_value = "mpi-1"
        item = mock.Mock()
        item.GetTakesCount.return_value = 1
        item.GetSelectedTakeIndex.return_value = 1
        item.GetTakeByIndex.return_value = {"startFrame": 0, "endFrame": 10, "mediaPoolItem": mpi}
        with mock.patch.object(gitem, "_get_timeline_item", return_value=(item, None)):
            out = gitem.ti_get_takes_info()
        import json
        json.dumps(out)
        self.assertEqual(out["takes"][0]["mediaPoolItem"], {"name": "clipB.mov", "id": "mpi-1"})


class ClearClipFlagsTest(unittest.TestCase):
    def test_default_clears_all(self):
        clip = mock.Mock()
        clip.ClearFlags.side_effect = lambda color: color == "All"
        mp = mock.Mock()
        with mock.patch.object(gmpi, "_get_mp", return_value=(None, mp, None)), \
             mock.patch.object(gmpi, "_find_clip_by_id", return_value=clip):
            fn = getattr(gmpi.clear_clip_flags, "__wrapped__", gmpi.clear_clip_flags)
            out = fn("id")
        clip.ClearFlags.assert_called_with("All")
        self.assertTrue(out["success"])

    def test_timeline_item_default_clears_all(self):
        item = mock.Mock()
        item.ClearFlags.side_effect = lambda color: color == "All"
        with mock.patch.object(gitem, "_get_timeline_item", return_value=(item, None)):
            fn = getattr(gitem.ti_clear_flags, "__wrapped__", gitem.ti_clear_flags)
            out = fn()
        item.ClearFlags.assert_called_with("All")
        self.assertTrue(out["success"])


if __name__ == "__main__":
    unittest.main()

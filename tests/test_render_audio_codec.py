"""render prepare_render_job pins the audio codec.

Measured on Studio 21.1.1 / Linux: GetAudioRenderCodecs('mp4') lists
{'AAC': 'aac', 'FLAC': 'flac'}, yet SetRenderSettings({'AudioCodec': 'aac'})
returns False and the job inherits the Deliver page codec (flac or lpcm). The
dvcp-aac plugin's encoder id is accepted and reads back on the job.
"""
import tempfile
import unittest

from src.server import _prepare_render_job
from src.utils import render_audio_codec as rac
from tests._paths import NON_TEMP_EXISTING_DIR
from tests.test_render_deliver_probe import RenderProjectStub

PLUGIN_AAC = "3E4F5A6B7C8D9EAFB0C1D2E3F4A5B6C7:9FB2E473DA865C4DB35FE6A2FFC3EDE8"


class LinuxAudioStub(RenderProjectStub):
    """Resolve 21.1.1 Linux: 'aac' listed but refused; the plugin id works."""

    accepted = {"flac", "lpcm", PLUGIN_AAC}
    #: codec the job reports regardless of the request (None = the applied one)
    job_codec_override = None

    def __init__(self):
        super().__init__()
        self.audio_codec = "flac"

    def GetAudioRenderCodecs(self, ext):
        return {"AAC": "aac", "FLAC": "flac"} if ext == "mp4" else {}

    def SetRenderSettings(self, settings):
        if "AudioCodec" in settings:
            if settings["AudioCodec"] not in self.accepted:
                return False
            self.audio_codec = settings["AudioCodec"]
        return super().SetRenderSettings(settings)

    def AddRenderJob(self):
        job_id = super().AddRenderJob()
        self.jobs[job_id]["AudioCodec"] = self.job_codec_override or self.audio_codec
        return job_id


class ResolveAudioCodecTest(unittest.TestCase):
    def test_native_name_tried_first_then_known_plugin_id(self):
        project = LinuxAudioStub()
        out = rac.apply_audio_codec(project, "mp4", "aac")
        self.assertEqual(out["applied"], PLUGIN_AAC)
        self.assertEqual(out["source"], "known_plugin_id")
        self.assertEqual([a["codec"] for a in out["attempts"]], ["aac", PLUGIN_AAC])

    def test_native_name_wins_when_resolve_accepts_it(self):
        project = LinuxAudioStub()
        project.accepted = project.accepted | {"aac"}
        out = rac.apply_audio_codec(project, "mp4", "aac")
        self.assertEqual((out["applied"], out["source"]), ("aac", "native"))

    def test_listed_plugin_id_is_found_by_label(self):
        project = LinuxAudioStub()
        project.GetAudioRenderCodecs = lambda ext: {"AAC": "aac", "AAC (FDK)": "AB:CD"}
        project.accepted = project.accepted | {"AB:CD"}
        out = rac.apply_audio_codec(project, "mp4", "aac")
        self.assertEqual((out["applied"], out["source"]), ("AB:CD", "listed_plugin"))

    def test_unknown_codec_is_not_applied(self):
        out = rac.apply_audio_codec(LinuxAudioStub(), "mp4", "opus")
        self.assertIsNone(out["applied"])


class PrepareRenderJobAudioCodecTest(unittest.TestCase):
    def _prepare(self, project, **extra):
        return _prepare_render_job(project, {"target_dir": tempfile.gettempdir(), "format": "mp4",
                                             "codec": "H.264", **extra})

    def test_aac_is_pinned_and_read_back_from_the_job(self):
        project = LinuxAudioStub()
        out = self._prepare(project, audio_codec="aac")
        self.assertTrue(out["success"], out)
        self.assertEqual(out["audio_codec"]["applied"], PLUGIN_AAC)
        self.assertEqual(out["audio_codec"]["job_audio_codec"], PLUGIN_AAC)
        self.assertEqual(project.jobs[out["job_id"]]["AudioCodec"], PLUGIN_AAC)

    def test_settings_audio_codec_key_goes_through_the_same_resolution(self):
        project = LinuxAudioStub()
        out = self._prepare(project, settings={"AudioCodec": "aac"})
        self.assertTrue(out["success"], out)
        self.assertEqual(out["audio_codec"]["applied"], PLUGIN_AAC)

    def test_refused_codec_queues_nothing(self):
        project = LinuxAudioStub()
        out = self._prepare(project, audio_codec="opus")
        self.assertEqual(out["error"]["code"], "AUDIO_CODEC_REJECTED")
        self.assertEqual(out["error"]["category"], "invalid_input")
        self.assertEqual(project.jobs, {})

    def test_job_readback_mismatch_fails_loudly_and_drops_the_job(self):
        project = LinuxAudioStub()
        project.job_codec_override = "flac"
        out = self._prepare(project, audio_codec="aac")
        self.assertEqual(out["error"]["code"], "AUDIO_CODEC_NOT_APPLIED")
        self.assertEqual(project.jobs, {})
        self.assertEqual(len(project.deleted), 1)

    def test_temp_dir_refusal_is_invalid_input_not_retryable(self):
        out = _prepare_render_job(RenderProjectStub(), {"target_dir": NON_TEMP_EXISTING_DIR})
        self.assertEqual(out["error"]["code"], "TARGET_DIR_NOT_TEMP")
        self.assertEqual(out["error"]["category"], "invalid_input")
        self.assertFalse(out["error"]["retryable"])
        self.assertIn("require_temp_target", out["error"]["remediation"])

    def test_docstring_documents_audio_codec_and_require_temp_target(self):
        import src.server as s
        line = next(l for l in s.render.__doc__.splitlines() if "prepare_render_job(" in l)
        self.assertIn("audio_codec", line)
        self.assertIn("require_temp_target", line)


if __name__ == "__main__":
    unittest.main()


class GranularSetRenderSettingsAudioCodecTest(unittest.TestCase):
    def setUp(self):
        from unittest import mock
        import src.granular.project as gproject
        self.gproject = gproject
        self.proj = LinuxAudioStub()
        resolve = mock.Mock()
        resolve.GetProjectManager.return_value.GetCurrentProject.return_value = self.proj
        self._orig = gproject.get_resolve
        gproject.get_resolve = lambda: resolve

    def tearDown(self):
        self.gproject.get_resolve = self._orig

    def test_friendly_aac_is_resolved(self):
        out = self.gproject.set_render_settings({"AudioCodec": "aac", "CustomName": "x"})
        self.assertTrue(out["success"], out)
        self.assertEqual(out["audio_codec"]["applied"], PLUGIN_AAC)
        self.assertEqual(self.proj.settings["CustomName"], "x")

    def test_refused_codec_reports_failure(self):
        out = self.gproject.set_render_settings({"AudioCodec": "opus"})
        self.assertFalse(out["success"])
        self.assertIsNone(out["audio_codec"]["applied"])

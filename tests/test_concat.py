"""
Unit tests for mixvideoconcat.concat module.
"""
# pylint: disable=missing-function-docstring,missing-class-docstring
# pylint: disable=too-many-arguments,R0917
# pylint: disable=unused-argument,consider-using-with,unspecified-encoding
# pylint: disable=import-outside-toplevel,reimported,wrong-import-position

import importlib
import json
import os
import subprocess as _subprocess
import tempfile
import unittest
from unittest.mock import MagicMock, patch

# mixvideoconcat.__init__ re-exports `concat` as a function, shadowing the submodule
# name. Import the module directly via importlib so patches resolve correctly.
_concat_mod = importlib.import_module("mixvideoconcat.concat")
from mixvideoconcat.concat import (
    apply_video_filters,
    concat,
    concat_uniform,
    deinterlace,
    get_video_info,
    resize_and_resample,
    stabilize,
)

# Access private module-level helpers (no name mangling at module scope).
_check_is_uniform = vars(_concat_mod).get("__check_is_uniform")


def _make_ffprobe_output(
    width=1920,
    height=1080,
    r_frame_rate="25/1",
    duration="60.0",
    rotation=0,
    field_order="progressive",
):
    """Return a JSON bytes blob that mimics ffprobe -print_format json output."""
    stream: dict = {
        "codec_type": "video",
        "width": width,
        "height": height,
        "r_frame_rate": r_frame_rate,
        "field_order": field_order,
    }
    # Only include side_data_list when a rotation is set.
    # When absent, the source code falls back to the [{}] default correctly.
    if rotation != 0:
        stream["side_data_list"] = [{"rotation": rotation}]
    data = {
        "streams": [stream],
        "format": {"duration": duration},
    }
    return json.dumps(data).encode("utf-8")


# ---------------------------------------------------------------------------
# get_video_info
# ---------------------------------------------------------------------------
class TestGetVideoInfo(unittest.TestCase):
    """Tests for get_video_info function."""

    def _run_result(self, stdout=b"", returncode=0, stderr=b""):
        """Create a mock subprocess result."""
        result = MagicMock()
        result.returncode = returncode
        result.stdout = stdout
        result.stderr = stderr
        return result

    @patch.object(_subprocess, "run")
    def test_success_basic(self, mock_run):
        mock_run.return_value = self._run_result(
            stdout=_make_ffprobe_output(
                width=1280, height=720, r_frame_rate="30/1", duration="10.5"
            )
        )
        info = get_video_info("video.mp4")
        self.assertEqual(info["width"], 1280)
        self.assertEqual(info["height"], 720)
        self.assertEqual(info["frame_rate"], "30/1")
        self.assertAlmostEqual(info["duration"], 10.5)
        self.assertEqual(info["orientation"], 0)
        self.assertFalse(info["interlaced"])

    @patch.object(_subprocess, "run")
    def test_interlaced_detection(self, mock_run):
        mock_run.return_value = self._run_result(
            stdout=_make_ffprobe_output(field_order="tt")
        )
        info = get_video_info("video.mp4")
        self.assertTrue(info["interlaced"])

    @patch.object(_subprocess, "run")
    def test_progressive_not_interlaced(self, mock_run):
        mock_run.return_value = self._run_result(
            stdout=_make_ffprobe_output(field_order="progressive")
        )
        info = get_video_info("video.mp4")
        self.assertFalse(info["interlaced"])

    @patch.object(_subprocess, "run")
    def test_absent_field_order_not_interlaced(self, mock_run):
        # Many progressive MP4/H.264 files carry no field_order tag at all;
        # they must NOT be flagged interlaced (would cause needless deinterlacing).
        data = {
            "streams": [
                {
                    "codec_type": "video",
                    "width": 1920,
                    "height": 1080,
                    "r_frame_rate": "25/1",
                }
            ],
            "format": {"duration": "60.0"},
        }
        mock_run.return_value = self._run_result(stdout=json.dumps(data).encode())
        info = get_video_info("video.mp4")
        self.assertFalse(info["interlaced"])

    @patch.object(_subprocess, "run")
    def test_unknown_field_order_not_interlaced(self, mock_run):
        mock_run.return_value = self._run_result(
            stdout=_make_ffprobe_output(field_order="unknown")
        )
        info = get_video_info("video.mp4")
        self.assertFalse(info["interlaced"])

    @patch.object(_subprocess, "run")
    def test_bottom_field_first_interlaced(self, mock_run):
        mock_run.return_value = self._run_result(
            stdout=_make_ffprobe_output(field_order="bb")
        )
        info = get_video_info("video.mp4")
        self.assertTrue(info["interlaced"])

    @patch.object(_subprocess, "run")
    def test_rotation_in_side_data(self, mock_run):
        mock_run.return_value = self._run_result(
            stdout=_make_ffprobe_output(rotation=90)
        )
        info = get_video_info("video.mp4")
        self.assertEqual(info["orientation"], 90)

    @patch.object(_subprocess, "run")
    def test_ffprobe_failure_raises_runtime_error(self, mock_run):
        mock_run.return_value = self._run_result(returncode=1, stderr=b"No such file")
        with self.assertRaises(RuntimeError):
            get_video_info("missing.mp4")

    @patch.object(_subprocess, "run")
    def test_no_video_stream_raises_runtime_error(self, mock_run):
        data = {"streams": [{"codec_type": "audio"}], "format": {"duration": "5.0"}}
        mock_run.return_value = self._run_result(stdout=json.dumps(data).encode())
        with self.assertRaises(RuntimeError):
            get_video_info("audio_only.mp4")

    @patch.object(_subprocess, "run")
    def test_ffprobe_command_contains_filename(self, mock_run):
        mock_run.return_value = self._run_result(
            stdout=_make_ffprobe_output()
        )
        get_video_info("myvideo.mp4")
        cmd = mock_run.call_args[0][0]
        self.assertIn("myvideo.mp4", cmd)
        self.assertEqual(cmd[0], "ffprobe")


# ---------------------------------------------------------------------------
# apply_video_filters
# ---------------------------------------------------------------------------
class TestApplyVideoFilters(unittest.TestCase):
    def _ok_result(self):
        r = MagicMock()
        r.returncode = 0
        return r

    def _fail_result(self):
        r = MagicMock()
        r.returncode = 1
        r.stderr = b"ffmpeg error"
        return r

    @patch.object(_subprocess, "run")
    def test_with_output_file(self, mock_run):
        mock_run.return_value = self._ok_result()
        apply_video_filters("in.mp4", "out.mp4", ["yadif"])
        cmd = mock_run.call_args[0][0]
        self.assertIn("out.mp4", cmd)
        self.assertNotIn("-f", cmd)

    @patch.object(_subprocess, "run")
    def test_without_output_file_uses_null_sink(self, mock_run):
        mock_run.return_value = self._ok_result()
        apply_video_filters("in.mp4", None, ["yadif"])
        cmd = mock_run.call_args[0][0]
        self.assertIn("-f", cmd)
        self.assertIn("null", cmd)
        self.assertIn("-", cmd)

    @patch.object(_subprocess, "run")
    def test_filter_joined_with_comma(self, mock_run):
        mock_run.return_value = self._ok_result()
        apply_video_filters("in.mp4", None, ["filter1", "filter2"])
        cmd = mock_run.call_args[0][0]
        vf_index = cmd.index("-vf")
        self.assertEqual(cmd[vf_index + 1], "filter1,filter2")

    @patch.object(_subprocess, "run")
    def test_add_params_included(self, mock_run):
        mock_run.return_value = self._ok_result()
        apply_video_filters("in.mp4", "out.mp4", ["scale=1280:720"], add_params=["-r", "30"])
        cmd = mock_run.call_args[0][0]
        self.assertIn("-r", cmd)
        self.assertIn("30", cmd)

    @patch.object(_subprocess, "run")
    def test_verbose_false_pipes_stderr(self, mock_run):
        mock_run.return_value = self._ok_result()
        apply_video_filters("in.mp4", None, ["yadif"], verbose=False)
        kwargs = mock_run.call_args[1]
        self.assertEqual(kwargs.get("stderr"), _subprocess.PIPE)

    @patch.object(_subprocess, "run")
    def test_verbose_true_no_pipe(self, mock_run):
        mock_run.return_value = self._ok_result()
        apply_video_filters("in.mp4", None, ["yadif"], verbose=True)
        kwargs = mock_run.call_args[1]
        self.assertIsNone(kwargs.get("stderr"))

    @patch.object(_subprocess, "run")
    def test_failure_raises_runtime_error(self, mock_run):
        mock_run.return_value = self._fail_result()
        with self.assertRaises(RuntimeError):
            apply_video_filters("in.mp4", "out.mp4", ["yadif"])


# ---------------------------------------------------------------------------
# deinterlace
# ---------------------------------------------------------------------------
class TestDeinterlace(unittest.TestCase):
    @patch.object(_concat_mod, "apply_video_filters")
    def test_calls_apply_with_yadif(self, mock_avf):
        deinterlace("in.mp4", "out.mp4", verbose=False)
        mock_avf.assert_called_once()
        filters = mock_avf.call_args[0][2]
        self.assertIn("yadif", filters)

    @patch.object(_concat_mod, "apply_video_filters")
    def test_passes_verbose_flag(self, mock_avf):
        deinterlace("in.mp4", "out.mp4", verbose=True)
        # verbose is the last positional arg
        call_args = mock_avf.call_args[0]
        self.assertEqual(call_args[-1], True)


# ---------------------------------------------------------------------------
# stabilize
# ---------------------------------------------------------------------------
class TestStabilize(unittest.TestCase):
    @patch.object(_concat_mod, "apply_video_filters")
    def test_calls_apply_twice(self, mock_avf):
        with tempfile.TemporaryDirectory() as tmpdir:
            stabilize("in.mp4", "out.mp4", tmpdir, verbose=False)
        self.assertEqual(mock_avf.call_count, 2)

    @patch.object(_concat_mod, "apply_video_filters")
    def test_first_call_uses_vidstabdetect(self, mock_avf):
        with tempfile.TemporaryDirectory() as tmpdir:
            stabilize("in.mp4", "out.mp4", tmpdir, verbose=False)
        first_filters = mock_avf.call_args_list[0][0][2]
        self.assertTrue(any("vidstabdetect" in f for f in first_filters))

    @patch.object(_concat_mod, "apply_video_filters")
    def test_second_call_uses_vidstabtransform(self, mock_avf):
        with tempfile.TemporaryDirectory() as tmpdir:
            stabilize("in.mp4", "out.mp4", tmpdir, verbose=False)
        second_filters = mock_avf.call_args_list[1][0][2]
        self.assertTrue(any("vidstabtransform" in f for f in second_filters))

    @patch.object(_concat_mod, "apply_video_filters")
    def test_cleanup_on_success(self, mock_avf):
        with tempfile.TemporaryDirectory() as tmpdir:
            trffile = os.path.join(tmpdir, "transforms.txt")
            stabilize("in.mp4", "out.mp4", tmpdir, verbose=False)
            self.assertFalse(os.path.exists(trffile))

    @patch.object(_concat_mod, "apply_video_filters", side_effect=RuntimeError("fail"))
    def test_cleanup_on_failure(self, mock_avf):
        with tempfile.TemporaryDirectory() as tmpdir:
            trffile = os.path.join(tmpdir, "transforms.txt")
            with self.assertRaises(RuntimeError):
                stabilize("in.mp4", "out.mp4", tmpdir, verbose=False)
            self.assertFalse(os.path.exists(trffile))


# ---------------------------------------------------------------------------
# resize_and_resample
# ---------------------------------------------------------------------------
class TestResizeAndResample(unittest.TestCase):
    @patch.object(_concat_mod, "apply_video_filters")
    def test_frame_rate_in_add_params(self, mock_avf):
        resize_and_resample("in.mp4", "out.mp4", 1920, 1080, frame_rate="30/1", verbose=False)
        add_params = mock_avf.call_args[0][3]
        self.assertIn("-r", add_params)
        self.assertIn("30/1", add_params)

    @patch.object(_concat_mod, "apply_video_filters")
    def test_empty_frame_rate_uses_default(self, mock_avf):
        resize_and_resample("in.mp4", "out.mp4", 1920, 1080, frame_rate="", verbose=False)
        add_params = mock_avf.call_args[0][3]
        self.assertIn("-r", add_params)
        # The value should be the module default (FFMPEG_FR)
        idx = add_params.index("-r")
        self.assertIsNotNone(add_params[idx + 1])

    @patch.object(_concat_mod, "apply_video_filters")
    def test_scale_filter_uses_dimensions(self, mock_avf):
        resize_and_resample("in.mp4", "out.mp4", 640, 480, frame_rate="25/1", verbose=False)
        filters = mock_avf.call_args[0][2]
        scale_filter = next(f for f in filters if "scale=" in f)
        self.assertIn("640", scale_filter)
        self.assertIn("480", scale_filter)


# ---------------------------------------------------------------------------
# concat_uniform
# ---------------------------------------------------------------------------
class TestConcatUniform(unittest.TestCase):
    @patch.object(_subprocess, "run")
    def test_empty_filenames_returns_early(self, mock_run):
        with tempfile.TemporaryDirectory() as tmpdir:
            concat_uniform([], "out.mp4", tmpdir, verbose=False)
        mock_run.assert_not_called()

    @patch.object(_subprocess, "run")
    def test_creates_list_file_with_correct_content(self, mock_run):
        r = MagicMock()
        r.returncode = 0
        mock_run.return_value = r

        captured_list = {}

        def fake_run(cmd, **_):
            # Read the list file before ffmpeg would delete it
            listfile = [a for a in cmd if a.endswith("list.txt")]
            if listfile:
                with open(listfile[0]) as fh:
                    captured_list["content"] = fh.read()
            return r

        mock_run.side_effect = fake_run

        with tempfile.TemporaryDirectory() as tmpdir:
            concat_uniform(["a.mp4", "b.mp4"], "out.mp4", tmpdir, verbose=False)

        self.assertIn("file 'a.mp4'", captured_list.get("content", ""))
        self.assertIn("file 'b.mp4'", captured_list.get("content", ""))

    @patch.object(_subprocess, "run")
    def test_list_file_cleaned_up_on_success(self, mock_run):
        r = MagicMock()
        r.returncode = 0
        mock_run.return_value = r
        with tempfile.TemporaryDirectory() as tmpdir:
            concat_uniform(["a.mp4"], "out.mp4", tmpdir, verbose=False)
            self.assertFalse(os.path.exists(os.path.join(tmpdir, "list.txt")))

    @patch.object(_subprocess, "run")
    def test_failure_raises_system_error(self, mock_run):
        r = MagicMock()
        r.returncode = 1
        r.stderr = b"error"
        mock_run.return_value = r
        with tempfile.TemporaryDirectory() as tmpdir:
            with self.assertRaises(SystemError):
                concat_uniform(["a.mp4"], "out.mp4", tmpdir, verbose=False)

    @patch.object(_subprocess, "run")
    def test_output_filename_in_command(self, mock_run):
        r = MagicMock()
        r.returncode = 0
        mock_run.return_value = r
        with tempfile.TemporaryDirectory() as tmpdir:
            concat_uniform(["a.mp4"], "output.mp4", tmpdir, verbose=False)
        cmd = mock_run.call_args[0][0]
        self.assertIn("output.mp4", cmd)


# ---------------------------------------------------------------------------
# __check_is_uniform (private helper, accessed via module dict)
# ---------------------------------------------------------------------------
class TestCheckIsUniform(unittest.TestCase):
    """Tests for the private _check_is_uniform helper."""

    def _fn(self):
        # Access through module __dict__ since name-mangling does not apply at module level
        fn = vars(_concat_mod).get("__check_is_uniform") or vars(_concat_mod).get(
            "_concat__check_is_uniform"
        )
        self.assertIsNotNone(fn, "__check_is_uniform not found in module")
        return fn

    def _info(self, width=1920, height=1080, frame_rate="25/1", orientation=0, interlaced=False):
        return {
            "width": width,
            "height": height,
            "frame_rate": frame_rate,
            "orientation": orientation,
            "interlaced": interlaced,
        }

    def test_empty_list_is_uniform(self):
        self.assertTrue(self._fn()([]))

    def test_single_item_is_uniform(self):
        self.assertTrue(self._fn()([self._info()]))

    def test_identical_items_are_uniform(self):
        infos = [self._info(), self._info()]
        self.assertTrue(self._fn()(infos))

    def test_different_height_not_uniform(self):
        infos = [self._info(height=1080), self._info(height=720)]
        self.assertFalse(self._fn()(infos))

    def test_different_width_not_uniform(self):
        infos = [self._info(width=1920), self._info(width=1280)]
        self.assertFalse(self._fn()(infos))

    def test_different_frame_rate_not_uniform(self):
        infos = [self._info(frame_rate="25/1"), self._info(frame_rate="30/1")]
        self.assertFalse(self._fn()(infos))

    def test_different_orientation_not_uniform(self):
        infos = [self._info(orientation=0), self._info(orientation=90)]
        self.assertFalse(self._fn()(infos))

    def test_different_interlaced_not_uniform(self):
        infos = [self._info(interlaced=False), self._info(interlaced=True)]
        self.assertFalse(self._fn()(infos))


# ---------------------------------------------------------------------------
# concat (public API) – dry_run covers __get_info_and_size logic
# ---------------------------------------------------------------------------
class TestConcat(unittest.TestCase):
    def _info(
        self,
        name="v.mp4",
        width=1920,
        height=1080,
        frame_rate="25/1",
        duration=60.0,
        orientation=0,
        interlaced=False,
    ):
        return {
            "name": name,
            "width": width,
            "height": height,
            "frame_rate": frame_rate,
            "duration": duration,
            "orientation": orientation,
            "interlaced": interlaced,
        }

    # -- dry_run / __get_info_and_size -----------------------------------------

    @patch.object(_concat_mod, "get_video_info")
    def test_dry_run_returns_file_infos(self, mock_gvi):
        mock_gvi.side_effect = [
            self._info(name="a.mp4"),
            self._info(name="b.mp4"),
        ]
        result = concat(["a.mp4", "b.mp4"], "out.mp4", dry_run=True)
        self.assertEqual(len(result), 2)

    @patch.object(_concat_mod, "get_video_info")
    def test_dry_run_returns_unmodified_info_count(self, mock_gvi):
        mock_gvi.side_effect = [
            self._info(name="a.mp4", width=1280, height=720),
            self._info(name="b.mp4", width=1920, height=1080),
        ]
        result = concat(["a.mp4", "b.mp4"], "out.mp4", dry_run=True)
        # dry_run just returns file infos; size selection is covered by
        # TestGetInfoAndSize, which exercises __get_info_and_size directly.
        self.assertEqual(len(result), 2)

    # -- deinterlace_mode ------------------------------------------------------

    @patch.object(_concat_mod, "concat_uniform")
    @patch.object(_concat_mod, "resize_and_resample")
    @patch.object(_concat_mod, "stabilize")
    @patch.object(_concat_mod, "deinterlace")
    @patch.object(_concat_mod, "get_video_info")
    def test_deinterlace_auto_enabled_when_interlaced(
            self, mock_gvi, mock_di, mock_stab, mock_rs, mock_cu):
        mock_gvi.return_value = self._info(name="v.mp4", interlaced=True)
        mock_di.side_effect = lambda src, dst, verbose: open(dst, "w").close()
        with tempfile.TemporaryDirectory() as tmpdir:
            concat(["v.mp4"], "out.mp4", tmpdir, deinterlace_mode=None, stabilize_mode=False)
        mock_di.assert_called_once()

    @patch.object(_concat_mod, "concat_uniform")
    @patch.object(_concat_mod, "resize_and_resample")
    @patch.object(_concat_mod, "stabilize")
    @patch.object(_concat_mod, "deinterlace")
    @patch.object(_concat_mod, "get_video_info")
    def test_deinterlace_auto_skipped_when_progressive(
            self, mock_gvi, mock_di, mock_stab, mock_rs, mock_cu):
        mock_gvi.return_value = self._info(name="v.mp4", interlaced=False)
        with tempfile.TemporaryDirectory() as tmpdir:
            concat(["v.mp4"], "out.mp4", tmpdir, deinterlace_mode=None, stabilize_mode=False)
        mock_di.assert_not_called()

    @patch.object(_concat_mod, "concat_uniform")
    @patch.object(_concat_mod, "resize_and_resample")
    @patch.object(_concat_mod, "stabilize")
    @patch.object(_concat_mod, "deinterlace")
    @patch.object(_concat_mod, "get_video_info")
    def test_deinterlace_forced_on(self, mock_gvi, mock_di, mock_stab, mock_rs, mock_cu):
        mock_gvi.return_value = self._info(name="v.mp4", interlaced=False)
        mock_di.side_effect = lambda src, dst, verbose: open(dst, "w").close()
        with tempfile.TemporaryDirectory() as tmpdir:
            concat(["v.mp4"], "out.mp4", tmpdir, deinterlace_mode=True, stabilize_mode=False)
        mock_di.assert_called_once()

    @patch.object(_concat_mod, "concat_uniform")
    @patch.object(_concat_mod, "resize_and_resample")
    @patch.object(_concat_mod, "stabilize")
    @patch.object(_concat_mod, "deinterlace")
    @patch.object(_concat_mod, "get_video_info")
    def test_deinterlace_forced_off(self, mock_gvi, mock_di, mock_stab, mock_rs, mock_cu):
        mock_gvi.return_value = self._info(name="v.mp4", interlaced=True)
        with tempfile.TemporaryDirectory() as tmpdir:
            concat(["v.mp4"], "out.mp4", tmpdir, deinterlace_mode=False, stabilize_mode=False)
        mock_di.assert_not_called()

    # -- stabilize_mode --------------------------------------------------------

    @patch.object(_concat_mod, "concat_uniform")
    @patch.object(_concat_mod, "resize_and_resample")
    @patch.object(_concat_mod, "stabilize")
    @patch.object(_concat_mod, "get_video_info")
    def test_stabilize_on(self, mock_gvi, mock_stab, mock_rs, mock_cu):
        mock_gvi.return_value = self._info(name="v.mp4")
        mock_stab.side_effect = lambda src, dst, tmpdir, verbose: open(dst, "w").close()
        with tempfile.TemporaryDirectory() as tmpdir:
            concat(["v.mp4"], "out.mp4", tmpdir, deinterlace_mode=False, stabilize_mode=True)
        mock_stab.assert_called_once()

    @patch.object(_concat_mod, "concat_uniform")
    @patch.object(_concat_mod, "resize_and_resample")
    @patch.object(_concat_mod, "stabilize")
    @patch.object(_concat_mod, "get_video_info")
    def test_stabilize_off(self, mock_gvi, mock_stab, mock_rs, mock_cu):
        mock_gvi.return_value = self._info(name="v.mp4")
        with tempfile.TemporaryDirectory() as tmpdir:
            concat(["v.mp4"], "out.mp4", tmpdir, deinterlace_mode=False, stabilize_mode=False)
        mock_stab.assert_not_called()

    # -- resize logic ----------------------------------------------------------

    @patch.object(_concat_mod, "concat_uniform")
    @patch.object(_concat_mod, "resize_and_resample")
    @patch.object(_concat_mod, "get_video_info")
    def test_no_resize_when_uniform(self, mock_gvi, mock_rs, mock_cu):
        info = self._info(name="v.mp4")
        mock_gvi.return_value = info
        with tempfile.TemporaryDirectory() as tmpdir:
            concat(
                ["v.mp4", "v2.mp4"],
                "out.mp4",
                tmpdir,
                deinterlace_mode=False,
                stabilize_mode=False,
            )
        mock_rs.assert_not_called()

    @patch.object(_concat_mod, "concat_uniform")
    @patch.object(_concat_mod, "resize_and_resample")
    @patch.object(_concat_mod, "get_video_info")
    def test_resize_when_not_uniform(self, mock_gvi, mock_rs, mock_cu):
        mock_gvi.side_effect = [
            self._info(name="a.mp4", width=1920, height=1080),
            self._info(name="b.mp4", width=1280, height=720),
        ]
        mock_rs.side_effect = lambda src, dst, w, h, frame_rate, verbose: open(dst, "w").close()
        with tempfile.TemporaryDirectory() as tmpdir:
            concat(
                ["a.mp4", "b.mp4"],
                "out.mp4",
                tmpdir,
                deinterlace_mode=False,
                stabilize_mode=False,
            )
        self.assertEqual(mock_rs.call_count, 2)

    # -- tmp file cleanup ------------------------------------------------------

    @patch.object(_concat_mod, "concat_uniform")
    @patch.object(_concat_mod, "resize_and_resample")
    @patch.object(_concat_mod, "get_video_info")
    def test_tmp_files_cleaned_up(self, mock_gvi, mock_rs, mock_cu):
        mock_gvi.side_effect = [
            self._info(name="a.mp4", width=1920, height=1080),
            self._info(name="b.mp4", width=1280, height=720),
        ]

        created = []

        def fake_rs(src, dst, w, h, frame_rate, verbose):
            open(dst, "w").close()
            created.append(dst)

        mock_rs.side_effect = fake_rs

        with tempfile.TemporaryDirectory() as tmpdir:
            concat(
                ["a.mp4", "b.mp4"],
                "out.mp4",
                tmpdir,
                deinterlace_mode=False,
                stabilize_mode=False,
            )
            for f in created:
                self.assertFalse(os.path.exists(f), f"Temp file {f} was not cleaned up")


# ---------------------------------------------------------------------------
# __get_info_and_size (private helper) — size / frame-rate selection logic
# ---------------------------------------------------------------------------
class TestGetInfoAndSize(unittest.TestCase):
    def _fn(self):
        fn = vars(_concat_mod).get("__get_info_and_size")
        self.assertIsNotNone(fn, "__get_info_and_size not found in module")
        return fn

    def _info(self, width=1920, height=1080, frame_rate="25/1", orientation=0):
        return {
            "width": width,
            "height": height,
            "frame_rate": frame_rate,
            "orientation": orientation,
            "interlaced": False,
        }

    @patch.object(_concat_mod, "get_video_info")
    def test_picks_max_horizontal_dimensions(self, mock_gvi):
        mock_gvi.side_effect = [
            self._info(width=1280, height=720),
            self._info(width=1920, height=1080),
        ]
        _, w, h, _ = self._fn()(["a.mp4", "b.mp4"])
        self.assertEqual((w, h), (1920, 1080))

    @patch.object(_concat_mod, "get_video_info")
    def test_orientation_swaps_width_and_height(self, mock_gvi):
        # orientation not in (0, 180, -180) → dimensions swapped before comparison
        mock_gvi.side_effect = [self._info(width=1080, height=1920, orientation=90)]
        _, w, h, _ = self._fn()(["v.mp4"], True)
        self.assertEqual((w, h), (1920, 1080))

    @patch.object(_concat_mod, "get_video_info")
    def test_prefer_vertical_selects_vertical_size(self, mock_gvi):
        mock_gvi.side_effect = [
            self._info(width=1920, height=1080, orientation=0),
            self._info(width=720, height=1280, orientation=90),
        ]
        _, w, h, _ = self._fn()(["h.mp4", "v.mp4"], True)
        # prefer_vertical → the rotated clip wins; its de-rotated size is 1280x720
        self.assertEqual((w, h), (1280, 720))

    @patch.object(_concat_mod, "get_video_info")
    def test_falls_back_to_vertical_when_no_horizontal(self, mock_gvi):
        # prefer_vertical=False but every clip is vertical → must still pick vertical
        mock_gvi.side_effect = [self._info(width=1080, height=1920, orientation=90)]
        _, w, h, _ = self._fn()(["v.mp4"], False)
        self.assertEqual((w, h), (1920, 1080))

    @patch.object(_concat_mod, "get_video_info")
    def test_picks_max_frame_rate_under_cap(self, mock_gvi):
        mock_gvi.side_effect = [
            self._info(frame_rate="25/1"),
            self._info(frame_rate="30/1"),
        ]
        _, _, _, fr = self._fn()(["a.mp4", "b.mp4"])
        self.assertEqual(fr, "30/1")

    @patch.object(_concat_mod, "get_video_info")
    def test_frame_rate_above_cap_is_ignored(self, mock_gvi):
        # MIXVIDEOCONCAT_MAX_FR defaults to 60 → a 120fps clip must not win
        mock_gvi.side_effect = [
            self._info(frame_rate="25/1"),
            self._info(frame_rate="120/1"),
        ]
        _, _, _, fr = self._fn()(["a.mp4", "b.mp4"])
        self.assertEqual(fr, "25/1")


if __name__ == "__main__":
    unittest.main()

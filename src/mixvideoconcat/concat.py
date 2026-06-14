# pylint: disable=line-too-long,too-many-arguments,too-many-locals
"""
MixVideoConcat Module

This module provides functions for manipulating and concatenating video files.
"""

import os
import logging
import subprocess
import json
from fractions import Fraction
from typing import Dict, List, Optional, Tuple

FFMPEG_BINARY = os.getenv("FFMPEG_BINARY", "ffmpeg")
FFMPEG_CODEC = os.getenv("FFMPEG_CODEC", "libx264")
FFMPEG_CRF = os.getenv("FFMPEG_CRF", "23")  # use 18 for visually lossless file (ffmpeg default: 23)
FFMPEG_FR = os.getenv("FFMPEG_FR", "25")

# maximum allowed frame rate during autodetection
MIXVIDEOCONCAT_MAX_FR = int(os.getenv("MIXVIDEOCONCAT_MAX_FR", "60"))


def __unlink(filename: str) -> None:
    try:
        os.unlink(filename)
    except FileNotFoundError:
        logging.warning("unlink failed: %s", filename)


def get_video_info(filename: str) -> Dict:
    """
    Retrieve information about a video file.
    """
    command = [
        "ffprobe",
        "-v",
        "error",
        "-show_format",
        "-show_streams",
        "-print_format",
        "json",
        filename,
    ]
    result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    if result.returncode != 0:
        error_msg = result.stderr.decode("utf-8").strip()
        raise RuntimeError(error_msg)

    output = result.stdout.decode("utf-8")
    data = json.loads(output)

    video_stream = next(
        (stream for stream in data["streams"] if stream["codec_type"] == "video"),
        None,
    )
    if video_stream is None:
        raise RuntimeError("File has no video stream")

    # Only known interlaced field orders count as interlaced; an absent/unknown
    # field_order (common for progressive MP4/H.264) must NOT trigger deinterlacing.
    field_order = video_stream.get("field_order", "progressive")
    info = {
        "width": int(video_stream.get("width", 0)),
        "height": int(video_stream.get("height", 0)),
        "frame_rate": video_stream.get("r_frame_rate", "0"),
        "duration": float(data["format"]["duration"]),
        "orientation": int(video_stream.get("side_data_list", [{}])[0].get("rotation", 0)),
        "interlaced": field_order in ("tt", "bb", "tb", "bt"),
    }
    logging.info("%s: %s", filename, info)
    return info


def apply_video_filters(
    in_file: str,
    out_file: Optional[str],
    filters: List[str],
    add_params: Optional[List[str]] = None,
    verbose: bool = False,
) -> None:
    """
    Apply filters to a video file.
    """
    cmd = [FFMPEG_BINARY, "-y"]  # overwrite existing
    cmd += ("-i", in_file)  # input file
    cmd += ("-vf", ",".join(filters))  # filters
    if out_file is None:
        cmd += ("-f", "null", "-")
    else:
        cmd += ("-qp", "0")  # lossless
        cmd += ("-preset", "ultrafast")  # maimum speed, big file
        cmd += ("-c:a", "flac")  # copy audio as flac to keep quality
        cmd += ("-strict", "experimental")  # for some ffmpeg version to use flac
        cmd += ("-c:v", FFMPEG_CODEC)  # video codec
        if add_params is not None:
            cmd += add_params
        cmd += (out_file,)
    logging.debug(cmd)
    errout = None if verbose else subprocess.PIPE
    result = subprocess.run(cmd, stderr=errout, check=False)
    if result.returncode != 0:
        if not verbose:
            logging.error(result.stderr.decode("utf-8"))
        raise RuntimeError(f"apply_video_filters failed: {result.returncode}")


def deinterlace(in_file: str, out_file: str, verbose: bool) -> None:
    """
    Deinterlace a video file.
    """
    filters = [
        "yadif",
        "format=yuv420p",
    ]
    logging.info("start deinterlace")
    apply_video_filters(in_file, out_file, filters, None, verbose)


def stabilize(in_file: str, out_file: str, tmpdirname: str, verbose: bool) -> None:
    """
    Stabilize a video file.
    """
    trffile = os.path.join(tmpdirname, "transforms.txt")
    try:
        filters = [
            f"vidstabdetect=stepsize=32:shakiness=10:accuracy=10:result={trffile}",  # noqa
        ]
        logging.info("start stab prep")
        apply_video_filters(in_file, None, filters, None, verbose)

        filters = [
            f"vidstabtransform=input={trffile}:zoom=0:smoothing=10,unsharp=5:5:0.8:3:3:0.4",  # noqa
        ]
        logging.info("start stab")
        apply_video_filters(in_file, out_file, filters, None, verbose)
    finally:
        __unlink(trffile)


def resize_and_resample(
    in_file: str,
    out_file: str,
    w: int,
    h: int,
    *,
    frame_rate: str,
    verbose: bool,
) -> None:
    """
    Resize and resample a video file.
    """
    if not frame_rate:
        frame_rate = FFMPEG_FR
    filters = [
        "format=yuv420p",
        f"scale=w='if(gt(a,{w}/{h}),{w},trunc(oh*a/2)*2)':h='if(gt(a,{w}/{h}),trunc(ow/a/2)*2,{h})'",  # noqa
        f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:black",
    ]
    add_params = ["-r", frame_rate]
    logging.info("start resize")
    apply_video_filters(in_file, out_file, filters, add_params, verbose)


def concat_uniform(
    filenames: List[str],
    out_file: str,
    tmpdirname: str,
    verbose: bool,
) -> None:
    """
    Concatenate video files with uniform properties into a single video file.
    """
    if len(filenames) == 0:
        logging.warning("empty filenames list")
        return
    listfile = os.path.join(tmpdirname, "list.txt")
    with open(listfile, "w", encoding="utf-8") as f:
        for fname in filenames:
            f.write(f"file '{fname}'\n")

    cmd = [FFMPEG_BINARY, "-y"]  # overwrite existing
    cmd += ("-f", "concat")
    cmd += ("-safe", "0")
    cmd += ("-i", listfile)
    cmd += ("-c:v", FFMPEG_CODEC)
    cmd += ("-crf", FFMPEG_CRF)
    cmd += ("-bf", "2")  # limit consecutive B-frames to 2
    cmd += ("-use_editlist", "0")  # avoids writing edit lists
    # places moov atom/box at front of the output file.
    cmd += ("-movflags", "+faststart")
    # use the native encoder to produce an AAC audio stream.
    cmd += ("-c:a", "aac")
    cmd += ("-q:a", "1")  # sets the highest quality for the audio.
    cmd += ("-ac", "2")  # rematrixes audio to stereo.
    cmd += ("-ar", "48000")  # resamples audio to 48000 Hz.
    cmd += (out_file,)
    logging.info("start concatenate")
    logging.debug(cmd)
    try:
        errout = None if verbose else subprocess.PIPE
        result = subprocess.run(cmd, stderr=errout, check=False)
        if result.returncode != 0:
            if not verbose:
                logging.error(result.stderr.decode("utf-8"))
            raise SystemError(f"concatenate failed: {result.returncode}")
        logging.info("file saved: %s", out_file)
    finally:
        __unlink(listfile)


def __get_info_and_size(
    filenames: List[str], prefer_vertical: bool = False
) -> Tuple[List[Dict], int, int, str]:
    max_vertical_height = 0
    max_vertical_width = 0
    max_horisontal_height = 0
    max_horisontal_width = 0
    max_frame_rate = 0
    max_frame_rate_str = ""
    fileinfos = []
    for f in filenames:
        info = get_video_info(f)
        w = info["width"]
        h = info["height"]
        if info["orientation"] not in (0, 180, -180):
            w, h = h, w
            if h > max_vertical_height:
                max_vertical_height = h
                max_vertical_width = w
        else:
            if w > max_horisontal_width:
                max_horisontal_height = h
                max_horisontal_width = w

        frame_rate = float(Fraction(info["frame_rate"]))
        if max_frame_rate < frame_rate <= MIXVIDEOCONCAT_MAX_FR:
            max_frame_rate = frame_rate
            max_frame_rate_str = info["frame_rate"]
        info["name"] = f
        fileinfos.append(info)

    max_height = max_horisontal_height
    max_width = max_horisontal_width
    if (prefer_vertical and max_vertical_height != 0) or max_horisontal_height == 0:
        max_height = max_vertical_height
        max_width = max_vertical_width

    logging.info("Result video: width=%s, height=%s", max_width, max_height)

    return fileinfos, max_width, max_height, max_frame_rate_str


def __check_is_uniform(fileinfos: List[Dict]) -> bool:
    if len(fileinfos) == 0:
        return True
    finfo0 = fileinfos[0]
    for finfo in fileinfos[1:]:
        if (
            finfo0["height"] != finfo["height"]
            or finfo0["width"] != finfo["width"]
            or finfo0["frame_rate"] != finfo["frame_rate"]
            or finfo0["orientation"] != finfo["orientation"]
            or finfo0["interlaced"] != finfo["interlaced"]
        ):
            return False
    return True


def concat(
    filenames: List[str],
    outputfile: str,
    tmpdirname: str = "/tmp",
    *,
    deinterlace_mode: Optional[bool] = None,
    stabilize_mode: bool = True,
    prefer_vertical: bool = False,
    verbose: bool = False,
    dry_run: bool = False,
) -> List[Dict]:
    """
    Concatenate video files into a single video file.

    Args:
        filenames (list of str): List of paths to the input video files.
        outputfile (str): Path to the output concatenated video file.
        tmpdirname (str, optional): Directory for temporary files. Defaults to "/tmp".
        deinterlace_mode (bool, optional): Enable video deinterlace,
            if None interlacing will be detected by ffprobe.
        stabilize_mode (bool, optional): Enable video stabilization.
        verbose (bool, optional): Enable ffmpeg output.
        dry_run (bool, optional): If True, performs a dry run without actually
            concatenating the videos. Defaults to False.

    Returns:
        list: Information about the concatenated video files.
    """
    fileinfos, max_width, max_height, max_frame_rate_str = __get_info_and_size(
        filenames, prefer_vertical
    )

    if dry_run:
        return fileinfos

    resize = not __check_is_uniform(fileinfos)

    tmpfilenames = []

    try:
        for i, finfo in enumerate(fileinfos):
            fname = os.path.join(tmpdirname, f"{i}.mp4")
            tfname = os.path.join(tmpdirname, f"{i}_tmp.mp4")
            src_name = finfo["name"]

            logging.info("convert '%s' to '%s'", src_name, fname)

            if deinterlace_mode is None:
                _deinterlace = finfo["interlaced"]
            else:
                _deinterlace = deinterlace_mode
            if _deinterlace:
                deinterlace(src_name, tfname, verbose)
                os.rename(tfname, fname)
                src_name = fname

            if stabilize_mode:
                stabilize(src_name, tfname, tmpdirname, verbose)
                os.rename(tfname, fname)
                src_name = fname

            if resize:
                resize_and_resample(
                    src_name,
                    tfname,
                    max_width,
                    max_height,
                    frame_rate=max_frame_rate_str,
                    verbose=verbose,
                )
                os.rename(tfname, fname)
                src_name = fname

            tmpfilenames.append(src_name)

        concat_uniform(tmpfilenames, outputfile, tmpdirname, verbose)

    finally:
        for f in tmpfilenames:
            if os.path.split(f)[0] == tmpdirname:
                __unlink(f)

    return fileinfos

import os
import logging
import subprocess
import json

FFMPEG_BINARY = "ffmpeg"
FFMPEG_CODEC = "libx264"
REENCODE_FPS = "25"


def __unlink(filename):
    try:
        os.unlink(filename)
    except FileNotFoundError:
        logging.exeption("unlink failed")


def get_video_info(filename):
    command = [
        'ffprobe',
        '-v',
        'error',
        '-show_format',
        '-show_streams',
        '-print_format',
        'json',
        filename,
    ]
    result = subprocess.run(
        command, stdout=subprocess.PIPE, stderr=subprocess.PIPE
    )
    if result.returncode != 0:
        error_msg = result.stderr.decode('utf-8').strip()
        raise Exception(error_msg)

    output = result.stdout.decode('utf-8')
    data = json.loads(output)

    video_stream = next(
        (
            stream
            for stream in data['streams']
            if stream['codec_type'] == 'video'
        ),
        None,
    )
    if video_stream is None:
        raise Exception("File has no video steam")

    info = {
        "width": int(video_stream.get('width', 0)),
        "height": int(video_stream.get('height', 0)),
        "duration": float(data['format']['duration']),
        "orientation": int(
            video_stream.get('side_data_list', [{}])[0].get('rotation', 0)
        ),
        "interlaced": (
            video_stream.get('field_order', 'unknown') != "progressive"
        ),
    }
    logging.info(f"{filename}: {info}")
    return info


def apply_video_filters(in_file, out_file, filters, add_params=[]):
    cmd = [FFMPEG_BINARY, "-y"]  # overwrite existing
    cmd += ("-i", in_file)  # input file
    cmd += ("-vf", ",".join(filters))  # filters
    if out_file is None:
        cmd += ("-f", "null", "-")
    else:
        cmd += ("-qp", "0")  # lossless
        cmd += ("-preset", "ultrafast")  # maimum speed, big file
        cmd += ("-acodec", "copy")  # copy audio as is
        cmd += ("-c:v", FFMPEG_CODEC)  # video codec
        cmd += add_params
        cmd += (out_file,)
    logging.debug(cmd)
    res = subprocess.run(cmd).returncode
    if res != 0:
        raise Exception(f"apply_video_filters failed: {res}")


def deinterlace(in_file, out_file):
    filters = [
        "yadif",
        "format=yuv420p",
    ]
    logging.info("start deinterlace")
    apply_video_filters(in_file, out_file, filters)


def stabilize(in_file, out_file, tmpdirname):
    trffile = os.path.join(tmpdirname, 'transforms.txt')
    try:
        filters = [
            f"vidstabdetect=stepsize=32:shakiness=10:accuracy=10:result={trffile}",  # noqa
        ]
        logging.info("start stab prep")
        apply_video_filters(in_file, None, filters)

        filters = [
            f"vidstabtransform=input={trffile}:zoom=0:smoothing=10,unsharp=5:5:0.8:3:3:0.4",  # noqa
        ]
        logging.info("start stab")
        apply_video_filters(in_file, out_file, filters)
    finally:
        __unlink(trffile)


def resize_and_resample(in_file, out_file, w, h):
    filters = [
        "format=yuv420p",
        f"scale=w='if(gt(a,{w}/{h}),{w},trunc(oh*a/2)*2)':h='if(gt(a,{w}/{h}),trunc(ow/a/2)*2,{h})'",  # noqa
        f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:black",
    ]
    add_params = ["-r", REENCODE_FPS]
    logging.info("start resize")
    apply_video_filters(in_file, out_file, filters, add_params)


def concat_uniform(filenames, out_file, tmpdirname):
    if len(filenames) == 0:
        logging.warning("empty filenames list")
        return
    listfile = os.path.join(tmpdirname, 'list.txt')
    with open(listfile, 'w') as f:
        for fname in filenames:
            f.write(f"file '{fname}'\n")

    cmd = [FFMPEG_BINARY, "-y"]  # overwrite existing
    cmd += ("-f", "concat")
    cmd += ("-safe", "0")
    cmd += ("-i", listfile)
    cmd += ("-c:v", FFMPEG_CODEC)
    cmd += ("-crf", "17")  # produce a visually lossless file.
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
        res = subprocess.run(cmd).returncode
        if res != 0:
            raise Exception(f"concatenate failed: {res}")
        logging.info(f"file saved: {out_file}")
    finally:
        __unlink(listfile)


def concat(filenames, outputfile, tmpdirname="/tmp", dry_run=False):
    max_height = 0
    max_width = 0
    fileinfos = []
    for f in filenames:
        info = get_video_info(f)
        w = info["width"]
        h = info["height"]
        if info["orientation"] not in (0, 180, -180):
            w, h = h, w
        if w > max_width:
            max_width = w
            max_height = h
        info["name"] = f
        fileinfos.append(info)

    logging.info(f"Result video: width={max_width}, height={max_height}")

    if dry_run:
        return fileinfos

    tmpfilenames = []

    try:
        for i, finfo in enumerate(fileinfos):
            fname = os.path.join(tmpdirname, f"{i}.mp4")
            tfname = os.path.join(tmpdirname, f"{i}_tmp.mp4")

            logging.info(f"convert '{f}' to '{fname}'")

            src_name = finfo["name"]
            if finfo["interlaced"]:
                deinterlace(src_name, tfname)
                os.rename(tfname, fname)
                src_name = fname

            stabilize(src_name, tfname, tmpdirname)
            os.rename(tfname, fname)

            resize_and_resample(fname, tfname, max_width, max_height)
            os.rename(tfname, fname)

            tmpfilenames.append(fname)

        concat_uniform(tmpfilenames, outputfile, tmpdirname)

    finally:
        for f in tmpfilenames:
            __unlink(f)

    return fileinfos

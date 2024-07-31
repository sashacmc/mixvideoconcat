#!/usr/bin/python3
# pylint: disable=broad-exception-caught

"""
MixVideoConcat Script

This script provides a command-line interface for concatenating video files into
a single video file.
"""

import os
import sys
import logging
import argparse
import tempfile

from .concat import *
from .log import init_logger


DESCRIPTION = """
Concatenatenite video files into a single video file.

Example:
    Concatenate video files "video1.mp4", "video2.mov", "video3.avi"
    into a single video file "output.mp4":
    $ mixvideoconcat video1.mp4 video2.mov video3.avi output.mp4

You can override the default constant rate factor (CRF) of 23 by setting the FFMPEG_CRF environment variable.
The frame rate will be determined as the maximum frame rate among the source files.
To override this, use the FFMPEG_FR environment variable.
"""


def __deinterlace_mode(value):
    if value == "on":
        return True
    if value == "off":
        return False
    if value == "auto":
        return None
    raise argparse.ArgumentTypeError(f"Invalid deinterlace mode: {value}")


def __stabilize_mode(value):
    if value == "on":
        return True
    if value == "off":
        return False
    raise argparse.ArgumentTypeError(f"Invalid stabilize mode: {value}")


def __args_parse():
    parser = argparse.ArgumentParser(
        description=DESCRIPTION, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("sources", nargs="+", help="Source files")
    parser.add_argument("destination", help="Destination file")
    parser.add_argument(
        "-t",
        "--tmpdir",
        help="Directory for temprary files (they can be huge!)",
    )
    parser.add_argument("-l", "--logfile", help="Log file", default=None)
    parser.add_argument("-f", "--force", help="Overwrite existing", action="store_true")
    parser.add_argument(
        "--deinterlace",
        help="Deinterlace mode (default: auto)",
        choices=["on", "off", "auto"],
        default="auto",
    )
    parser.add_argument(
        "--stabilize",
        help="Stabilize mode (default: on)",
        choices=["on", "off"],
        default="on",
    )
    parser.add_argument(
        "--prefer_vertical",
        help="Generate vertical video if at least one input video is vertical",
        action="store_true",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        help="Print verbose information (ffmpeg output)",
        action="store_true",
    )
    args = parser.parse_args()
    args.deinterlace = __deinterlace_mode(args.deinterlace)
    args.stabilize = __stabilize_mode(args.stabilize)
    return args


def main():
    """
    Main function for executing the concatenation process.
    """
    args = __args_parse()
    init_logger(args.logfile, logging.DEBUG)

    if os.path.exists(args.destination) and not args.force:
        print(f"{args.destination} already exists")
        sys.exit(1)

    if args.tmpdir is None:
        with tempfile.TemporaryDirectory() as tmpdir:
            concat(
                args.sources,
                args.destination,
                tmpdir,
                deinterlace_mode=args.deinterlace,
                stabilize_mode=args.stabilize,
                prefer_vertical=args.prefer_vertical,
                verbose=args.verbose,
                dry_run=False,
            )
    else:
        os.makedirs(args.tmpdir, exist_ok=True)
        concat(
            args.sources,
            args.destination,
            args.tmpdir,
            deinterlace_mode=args.deinterlace,
            stabilize_mode=args.stabilize,
            prefer_vertical=args.prefer_vertical,
            verbose=args.verbose,
            dry_run=False,
        )

    logging.info("Done.")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        logging.exception("Main failed")

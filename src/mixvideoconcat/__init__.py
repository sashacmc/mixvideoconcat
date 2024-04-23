#!/usr/bin/python3
# pylint: disable=broad-exception-caught

"""
MixVideoConcat Script

This script provides a command-line interface for concatenating video files into
a single video file.

Example:
    Concatenate video files 'video1.mp4', 'video2.mov', 'video3.avi'
    into a single video file 'output.mp4':
    $ mixvideoconcat video1.mp4 video2.mov video3.avi output.mp4
"""

import os
import sys
import logging
import argparse
import tempfile

from .concat import *
from .log import init_logger


def __args_parse():
    parser = argparse.ArgumentParser()
    parser.add_argument("sources", nargs="+", help="Source files")
    parser.add_argument("destination", help="Destination file")
    parser.add_argument(
        "-t",
        "--tmpdir",
        help="Directory for temprary files (they can be huge!)",
    )
    parser.add_argument('-l', '--logfile', help='Log file', default=None)
    parser.add_argument(
        '-f', '--force', help='Overwrite existing', action='store_true'
    )
    return parser.parse_args()


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
            concat(args.sources, args.destination, tmpdir)
    else:
        os.makedirs(args.tmpdir, exist_ok=True)
        concat(args.sources, args.destination, args.tmpdir)

    logging.info("Done.")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        logging.exception("Main failed")

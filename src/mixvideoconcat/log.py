"""
Log utilites
"""

import os
import sys
import logging

LOGFMT = '[%(asctime)s] [%(name)s] [%(levelname)s] %(message)s'
DATEFMT = '%Y-%m-%d %H:%M:%S'


def init_logger(filename=None, level=logging.INFO):
    """
    Initialize the logger.

    Args:
        filename (str, optional): Path to the log file. If None, logs will be printed to console.
                                  Defaults to None.
        level (int, optional): Logging level. Defaults to logging.INFO.
    """

    if filename is not None:
        try:
            os.makedirs(os.path.split(filename)[0])
        except OSError:
            pass
        mode = 'a' if os.path.isfile(filename) else 'w'
        fh = logging.FileHandler(filename, mode)
    else:
        fh = logging.StreamHandler()

    fmt = logging.Formatter(LOGFMT, DATEFMT)
    fh.setFormatter(fmt)
    logging.getLogger().addHandler(fh)

    logging.getLogger().setLevel(level)

    logging.info('Log file: %s', str(filename))
    logging.debug(str(sys.argv))

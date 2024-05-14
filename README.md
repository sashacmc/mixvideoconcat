# MixVideoConcat

![CodeQL](https://github.com/sashacmc/mixvideoconcat/workflows/CodeQL/badge.svg)
[![PyPI - Version](https://img.shields.io/pypi/v/mixvideoconcat.svg)](https://pypi.org/project/mixvideoconcat)
[![PyPI - Downloads](https://pepy.tech/badge/mixvideoconcat)](https://pepy.tech/project/mixvideoconcat)
[![Code style: black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.comixvideoconcatm/psf/black)

MixVideoConcat is a Python tool/library based on ffmpeg for concatenating video files of different formats, resolutions, and orientations into a single video file. It supports various input formats and ensures seamless merging of videos while handling differences in resolution and orientation.

## Installation

You can install MixVideoConcat via pip:

```bash
pip install mixvideoconcat
```

## Command line tool usage

```bash
mixvideoconcat [-h] [-t TMPDIR] [-l LOGFILE] [-f] sources [sources ...] destination

positional arguments:
  sources               Source files
  destination           Destination file

options:
  -h, --help            show this help message and exit
  -t TMPDIR, --tmpdir TMPDIR
                        Directory for temprary files (they can be huge!)
  -l LOGFILE, --logfile LOGFILE
                        Log file
  -f, --force           Overwrite existing
  --deinterlace {on,off,auto}
                        Deinterlace mode (default: auto)
  --stabilize {on,off}  Stabilize mode (default: on)
  -v, --verbose         Print verbose information (ffmpeg output)
```

## Example

Concatenate three video files (video1.mp4, video2.mov, video3.avi) into a single video file named output.mp4:

```bash
mixvideoconcat video1.mp4 video2.mov video3.avi output.mp4
```

## Library usage

```python
from mixvideoconcat import concat

concat(['video1.mp4', 'video2.mov', 'video3.avi'], 'output.mp4')
```

## Tune

You can override the default constant rate factor (CRF) of 23 by setting the `FFMPEG_CRF` environment variable.
The frame rate will be determined as the maximum frame rate among the source files.
To override this, use the `FFMPEG_FR` environment variable.

## Contributing

Contributions are welcome! Please feel free to submit issues, feature requests, or pull requests.

## Show your support
Give a ⭐️ if this project helped you!

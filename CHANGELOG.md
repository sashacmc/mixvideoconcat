# Changelog

## UNRELEASED

- Add option to limit frame rate during autodetection
- Improve ffmpeg version support

## [1.2.0] - 2024-05-14 

- Skip resize for uniform videos.
- Add frame rate detection (convert to highest).
- Add possibility to override FFMPEG constants by means of environment variables.
- Switch to default CRF 23 (can be overrided by `FFMPEG_CRF` environment variable).

## [1.1.0] - 2024-04-28

- Add possibility to disable ffmpeg output.
- Add possibility to turn off deinterlace and/or stabilization.
- Fix MOV files processing.

## [1.0.0] - 2024-04-23

- Initial release.

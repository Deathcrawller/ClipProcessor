@echo off
setlocal
cd /d "%~dp0"

REM One-click: OCR + score all MP4s in Input\, then FFmpeg-export clips.
REM Requires: python on PATH, ffmpeg on PATH, videos under Input\
REM To match only the first file (legacy): python process_clips.py
REM To change behavior, edit the flags below or set pipeline.* in config.json

python process_clips.py --all-videos --ffmpeg-export
set EXITCODE=%ERRORLEVEL%

echo.
if %EXITCODE% neq 0 (
  echo Run finished with errors ^(exit %EXITCODE%^).
) else (
  echo Run finished OK.
)
pause
exit /b %EXITCODE%

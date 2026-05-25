@echo off
setlocal enabledelayedexpansion

REM =========================================
REM ClipProcessor — FFmpeg clip export
REM Double-click or run: .\process_clips.bat
REM =========================================

cd /d "%~dp0"

REM Activate the project's venv if setup.bat was used.
if exist ".venv\Scripts\activate.bat" call ".venv\Scripts\activate.bat"

set CLIP_FILE=clips.txt
set OUTPUT_DIR=Clips

REM -----------------------------------------
REM Find first MP4 in this folder
REM -----------------------------------------

for %%F in (*.mp4) do (
    set INPUT_VIDEO=%%F
    goto foundVideo
)

echo.
echo No MP4 file found in this folder.
pause
exit /b 1

:foundVideo

echo.
echo Found video: !INPUT_VIDEO!
echo.

REM -----------------------------------------
REM Create output folder if missing
REM -----------------------------------------

if not exist "%OUTPUT_DIR%" mkdir "%OUTPUT_DIR%"

REM -----------------------------------------
REM Process clips.txt
REM Format: START|END|clip-basename|metadata-title
REM (title optional for old 3-column files; embedded in MP4 metadata)
REM -----------------------------------------

if not exist "%CLIP_FILE%" (
    echo Missing %CLIP_FILE%. Run: python process_clips.py
    pause
    exit /b 1
)

for /f "usebackq tokens=1-4 delims=|" %%A in ("%CLIP_FILE%") do (
    set "CLIP_START=%%A"
    set "CLIP_END=%%B"
    set "CLIP_NAME=%%C"
    set "CLIP_META=%%D"
    if "!CLIP_META!"=="" set "CLIP_META=VOD clip"

    echo Creating clip: !CLIP_NAME!
    echo   Title: !CLIP_META!

    ffmpeg -y ^
    -ss !CLIP_START! ^
    -to !CLIP_END! ^
    -i "!INPUT_VIDEO!" ^
    -c copy ^
    -metadata "title=!CLIP_META!" ^
    -metadata "comment=!CLIP_META!" ^
    "%OUTPUT_DIR%\!CLIP_NAME!.mp4"
)

echo.
echo =========================================
echo All clips exported to \Clips
echo =========================================
echo.

pause

@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"

REM =================================================================
REM ClipProcessor - one-shot installer for Windows 11
REM
REM Usage:
REM   setup.bat            Auto-detect GPU/CPU and install
REM   setup.bat gpu        Force the GPU (CUDA 12.6) PaddlePaddle build
REM   setup.bat cpu        Force the CPU PaddlePaddle build
REM
REM What it does:
REM   1. Verifies Python and FFmpeg (offers winget install if missing)
REM   2. Detects NVIDIA GPU via nvidia-smi
REM   3. Creates .venv\ if absent and activates it
REM   4. Installs requirements-gpu.txt or requirements-cpu.txt
REM   5. Verifies PaddlePaddle loads and reports CUDA visibility
REM =================================================================

set "MODE=auto"
if /i "%~1"=="gpu" set "MODE=gpu"
if /i "%~1"=="cpu" set "MODE=cpu"

echo.
echo =====================================================
echo  ClipProcessor setup  ^(mode: %MODE%^)
echo =====================================================
echo.

REM ----- Python ---------------------------------------------------
set "PYCMD="
python --version >nul 2>&1
if not errorlevel 1 (
    set "PYCMD=python"
) else (
    py -3 --version >nul 2>&1
    if not errorlevel 1 set "PYCMD=py -3"
)

if not defined PYCMD (
    echo Python was not found on PATH.
    echo.
    set /p ANS="Install Python 3.12 via winget now? [Y/N] "
    if /i "!ANS!"=="Y" (
        winget install -e --id Python.Python.3.12 --accept-source-agreements --accept-package-agreements
        echo.
        echo Python install attempted. Close this window, open a NEW terminal,
        echo and run setup.bat again so PATH picks up the new python.exe.
        pause
        exit /b 1
    )
    echo.
    echo Install Python 3.10+ from https://www.python.org/downloads/windows/
    echo Then re-run setup.bat.
    pause
    exit /b 1
)

for /f "tokens=*" %%V in ('%PYCMD% --version 2^>^&1') do set "PYVER=%%V"
echo [OK]  %PYVER%

REM ----- FFmpeg ---------------------------------------------------
ffmpeg -version >nul 2>&1
if errorlevel 1 (
    echo [WARN] FFmpeg not found on PATH ^(needed for --ffmpeg-export^).
    set /p ANS="Install FFmpeg via winget now? [Y/N] "
    if /i "!ANS!"=="Y" (
        winget install -e --id Gyan.FFmpeg --accept-source-agreements --accept-package-agreements
        echo.
        echo FFmpeg install attempted. You may need a new terminal for PATH to update.
        echo Continuing setup; clip export will simply skip if ffmpeg is still missing.
    )
) else (
    echo [OK]  ffmpeg detected on PATH
)

REM ----- GPU detection -------------------------------------------
set "HAS_GPU=0"
nvidia-smi -L >nul 2>&1
if not errorlevel 1 set "HAS_GPU=1"

if /i "%MODE%"=="gpu" set "HAS_GPU=1"
if /i "%MODE%"=="cpu" set "HAS_GPU=0"

if "%HAS_GPU%"=="1" (
    echo [OK]  NVIDIA GPU mode selected ^(PaddlePaddle CUDA 12.6 wheel^)
) else (
    echo [OK]  CPU mode selected ^(no NVIDIA GPU detected or forced cpu^)
)

REM ----- Virtual environment -------------------------------------
if not exist ".venv\Scripts\python.exe" (
    echo.
    echo Creating virtual environment in .venv\ ...
    %PYCMD% -m venv .venv
    if errorlevel 1 goto :venvfail
) else (
    echo [OK]  Reusing existing .venv\
)

call ".venv\Scripts\activate.bat"
if errorlevel 1 goto :venvfail

python -m pip install --upgrade pip
if errorlevel 1 goto :pipfail

REM ----- Install dependencies ------------------------------------
echo.
if "%HAS_GPU%"=="1" (
    echo Installing requirements-gpu.txt ^(this can take several minutes^)...
    pip install -r requirements-gpu.txt
) else (
    echo Installing requirements-cpu.txt ^(this can take several minutes^)...
    pip install -r requirements-cpu.txt
)
if errorlevel 1 goto :pipfail

REM ----- Verify Paddle -------------------------------------------
echo.
echo Verifying PaddlePaddle...
python -c "import paddle; print('paddle', paddle.__version__); print('cuda_compiled', paddle.is_compiled_with_cuda()); print('device', paddle.device.get_device())"
if errorlevel 1 (
    echo.
    echo [ERROR] Paddle did not import cleanly. See messages above.
    pause
    exit /b 1
)

echo.
echo =====================================================
echo  Setup complete.
echo.
echo  Next steps:
echo    1. Put .mp4 files into  Input\
echo    2. Double-click          run_process.bat
echo  Or run from terminal:      python process_clips.py --all-videos --ffmpeg-export
echo =====================================================
echo.
pause
exit /b 0

:venvfail
echo.
echo [ERROR] Failed to create or activate the virtual environment.
echo Make sure Python is installed correctly and try again.
pause
exit /b 1

:pipfail
echo.
echo [ERROR] pip install failed. Common causes:
echo   - No internet connection
echo   - Antivirus blocking pip downloads
echo   - Wrong Python version ^(need 3.10+^)
echo   - Forced GPU mode without an NVIDIA GPU - try:  setup.bat cpu
echo   - Stale .venv\ from a prior failed install - delete .venv\ and re-run
echo   - Dependency-resolution conflict ^(see "ResolutionImpossible" above^):
echo     pull the latest from git and re-run setup.bat
pause
exit /b 1

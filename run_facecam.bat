@echo off
setlocal

REM --- Use Python 3.13 explicitly via the py launcher ---
set "PY_CMD=py -3.13"

REM --- If venv doesn't exist, create it and install deps ---
if not exist ".venv" (
    echo [FaceCam] Creating virtualenv with Python 3.13...
    %PY_CMD% -m venv .venv

    echo [FaceCam] Activating venv and installing requirements...
    call ".venv\Scripts\activate"

    echo [FaceCam] Upgrading pip and installing requirements...
    python -m pip install --upgrade pip
    python -m pip install -r requirements.txt
) else (
    echo [FaceCam] Activating existing venv...
    call ".venv\Scripts\activate"
)

echo [FaceCam] Starting FaceCam...
python main.py

endlocal

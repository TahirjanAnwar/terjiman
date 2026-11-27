@echo off
rem One-time setup for Terjiman: makes .venv with Python 3.12, installs Qt for Python and the Claude SDK,
rem builds Terjiman.exe, puts Terjiman on the desktop and in the Start menu, and starts it.
rem "setup.cmd /quiet" does the same without starting Terjiman or waiting for a key at the end.
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  py -3.12 -m venv .venv
  if errorlevel 1 (
    echo Python 3.12 is needed: https://www.python.org/downloads/
    if /i not "%~1"=="/quiet" pause
    exit /b 1
  )
)
".venv\Scripts\python.exe" -m pip install --upgrade pip
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 (
  echo Installing the packages failed - see the messages above.
  if /i not "%~1"=="/quiet" pause
  exit /b 1
)
"%WINDIR%\Microsoft.NET\Framework64\v4.0.30319\csc.exe" /nologo /target:winexe /optimize+ /win32icon:assets\terjiman.ico /reference:System.Windows.Forms.dll /out:Terjiman.exe launcher\TerjimanLauncher.cs
if errorlevel 1 (
  echo Building Terjiman.exe failed - see the messages above.
  if /i not "%~1"=="/quiet" pause
  exit /b 1
)
set "TJ_DIR=%~dp0"
powershell -NoProfile -Command "$dir = $env:TJ_DIR; $shell = New-Object -ComObject WScript.Shell; foreach ($folder in @([Environment]::GetFolderPath('Desktop'), [Environment]::GetFolderPath('Programs'))) { $link = $shell.CreateShortcut((Join-Path $folder 'Terjiman.lnk')); $link.TargetPath = (Join-Path $dir 'Terjiman.exe'); $link.WorkingDirectory = $dir; $link.Description = 'Terjiman: write in Uyghur, send in English'; $link.Save() }"
echo.
echo Setup finished. Terjiman is on the desktop and in the Start menu.
echo Press Ctrl+Shift+Space in any program to open it.
if /i "%~1"=="/quiet" exit /b 0
start "" "%~dp0Terjiman.exe"
pause

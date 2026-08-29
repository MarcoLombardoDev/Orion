@echo off
rem Start Orion, after checking that the executable is the one this archive
rem was built with.
rem
rem The archive ships Orion.exe.sha256 beside the executable. This script
rem recomputes that digest with certutil, which is part of Windows, and
rem compares. What that catches is a truncated download, a half-finished
rem unpack, a disk that has started rotting -- damage, which is the failure
rem that actually happens to people.
rem
rem What it does NOT catch is tampering. The checksum travels inside the same
rem zip as the file it describes, so anyone able to alter the executable could
rem alter the checksum in the same breath. The check worth doing against that
rem is on the zip itself, using the .sha256 published as a separate release
rem asset -- it reaches you by a different path, which is the whole point. The
rem README says how.
rem
rem This script does not remove the SmartScreen warning and cannot: only a
rem code-signing certificate does that.

setlocal

set "APP=Orion"
rem %~dp0 is the folder holding this script, with a trailing backslash. Not
rem the current directory: a double-click from Explorer can start anywhere.
set "HERE=%~dp0"
set "EXE=%HERE%%APP%.exe"
set "SUMS=%EXE%.sha256"

if not exist "%EXE%" (
    echo %APP%: no executable at "%EXE%" 1>&2
    echo The archive did not unpack completely. Unpack it again. 1>&2
    if not defined CI pause
    exit /b 1
)

rem An escape hatch that is deliberately explicit. Somebody who has patched
rem the executable on purpose should be able to run it; somebody who has not
rem should never see this path taken silently.
if "%ORION_SKIP_VERIFY%"=="1" (
    echo %APP%: checksum verification skipped ^(ORION_SKIP_VERIFY=1^) 1>&2
    goto :launch
)

if not exist "%SUMS%" (
    echo %APP%: %APP%.exe.sha256 is missing, starting without checking 1>&2
    goto :launch
)

rem The file is in the format sha256sum -c reads: "<hex>  <name>".
rem Cleared first: setlocal copies the caller's environment, and a
rem variable of either name already in it would win the `if not defined`.
set "EXPECTED="
set "ACTUAL="
for /f "usebackq tokens=1" %%H in ("%SUMS%") do (
    if not defined EXPECTED set "EXPECTED=%%H"
)

rem Line 1 of certutil's output is a heading and line 3 a success message; the
rem digest is line 2. Some builds of certutil space the bytes apart, so the
rem spaces come back out before comparing.
for /f "skip=1 delims=" %%H in ('certutil -hashfile "%EXE%" SHA256 2^>nul') do (
    if not defined ACTUAL set "ACTUAL=%%H"
)
if defined ACTUAL set "ACTUAL=%ACTUAL: =%"

if not defined ACTUAL (
    echo %APP%: certutil could not hash the executable, starting without checking 1>&2
    goto :launch
)
if not defined EXPECTED (
    echo %APP%: %APP%.exe.sha256 is empty, starting without checking 1>&2
    goto :launch
)

rem /i because certutil's case has changed between Windows versions.
if /i not "%ACTUAL%"=="%EXPECTED%" (
    echo %APP%: the executable does not match %APP%.exe.sha256. 1>&2
    echo   expected %EXPECTED% 1>&2
    echo   found    %ACTUAL% 1>&2
    echo. 1>&2
    echo Unpack the archive again from a fresh download. If it still does not 1>&2
    echo match, check the zip's own .sha256 from the release page before 1>&2
    echo running anything out of it. 1>&2
    if not defined CI pause
    exit /b 1
)

:launch
rem With arguments -- --version, --self-check -- run in the foreground, so
rem whatever is printed lands in the console the caller is watching.
if not "%~1"=="" goto :foreground

rem With none, which is what a double-click sends, this console has one job
rem left: stay up while the program starts, and say what it is waiting for. A
rem frozen application is not quick off the mark -- Windows scans every file
rem before it will let any of them load, and a onefile build unpacks itself
rem into a temporary folder on top of that -- and a console that vanishes
rem instantly leaves nothing on screen for that whole wait.
rem
rem Asking Windows when the program is ready needs PowerShell. Without it
rem there is no way to know, so hand off and let this window close at once,
rem which is what it did before.
where powershell > nul 2>&1
if errorlevel 1 goto :handoff

echo Starting %APP%...
echo.
echo The first launch is the slow one: Windows checks every file before it
echo will run any of them. This window closes by itself as soon as %APP% is
echo on screen.

rem The path travels in a variable rather than inside the quoted -Command
rem string, so a folder name containing a space or a quote cannot break the
rem PowerShell that receives it.
set "_LAUNCH_TARGET=%EXE%"
set "_LAUNCH_TIMEOUT=%ORION_LAUNCH_TIMEOUT%"
if not defined _LAUNCH_TIMEOUT set "_LAUNCH_TIMEOUT=180"

rem What this waits for is a window, found by polling every process with the
rem program's image name until one of them has a main window handle.
rem
rem It used to call WaitForInputIdle on the process Start-Process returned,
rem which is the obvious answer and the wrong one. A onefile build is two
rem processes: the executable that starts is a bootloader that unpacks itself
rem and re-runs itself, and the copy that opens the window is its child. The
rem bootloader never has a message loop, so WaitForInputIdle on it waited out
rem the whole timeout while the program sat there on screen, and the console
rem then announced that nothing had happened. Reported from a onefile build; a
rem onedir build is a single process and looked fine, which is how it went
rem unnoticed.
rem
rem Both processes carry the same image name, so watching the name covers
rem either shape. Death is read from the process Start-Process handed back
rem rather than from the name disappearing: a onefile bootloader outlives its
rem child, so that handle going away means the whole thing is gone, and it
rem cannot race the first poll the way a name lookup can.
powershell -NoProfile -Command "$target = ${env:_LAUNCH_TARGET}; $name = [IO.Path]::GetFileNameWithoutExtension($target); $p = Start-Process -FilePath $target -PassThru; $deadline = (Get-Date).AddSeconds([int]${env:_LAUNCH_TIMEOUT}); while ((Get-Date) -lt $deadline) { foreach ($proc in @(Get-Process -Name $name -ErrorAction SilentlyContinue)) { if ($proc.MainWindowHandle -ne [IntPtr]::Zero) { exit 0 } }; if ($p.HasExited) { exit 4 }; Start-Sleep -Milliseconds 200 }; exit 3"
set "STATUS=%ERRORLEVEL%"

rem Past this point the program has been started, whatever PowerShell went on
rem to report. Nothing below may start it a second time.
if "%STATUS%"=="0" exit /b 0

if "%STATUS%"=="4" (
    echo. 1>&2
    echo %APP% stopped before it opened a window. 1>&2
    if not defined CI pause
    exit /b 1
)

echo. 1>&2
echo %APP% has not opened a window yet. It may still be starting. 1>&2
if not defined CI pause
exit /b 0

:handoff
start "" "%EXE%"
exit /b 0

:foreground
"%EXE%" %*
exit /b %ERRORLEVEL%

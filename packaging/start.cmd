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
rem whatever is printed lands in the console the caller is watching. With
rem none, which is what a double-click sends, hand off with start so this
rem console window closes instead of sitting behind the application for as
rem long as it runs.
if "%~1"=="" (
    start "" "%EXE%"
    exit /b 0
)
"%EXE%" %*
exit /b %ERRORLEVEL%

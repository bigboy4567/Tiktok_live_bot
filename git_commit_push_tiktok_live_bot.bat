@echo off
setlocal EnableExtensions EnableDelayedExpansion

set "SCRIPT_DIR=%~dp0"
set "REMOTE_URL=https://github.com/bigboy4567/Tiktok_live_bot"
set "DEFAULT_BRANCH=main"

if not exist "%SCRIPT_DIR%." (
  echo Script directory not found: "%SCRIPT_DIR%"
  goto :fail
)

pushd "%SCRIPT_DIR%" >nul 2>&1
if errorlevel 1 (
  echo Failed to enter script directory: "%SCRIPT_DIR%"
  goto :fail
)

if not exist ".git" (
  echo No git repository found. Initializing...
  git init -b "%DEFAULT_BRANCH%"
  if errorlevel 1 goto :fail
)

git rev-parse --is-inside-work-tree >nul 2>&1
if errorlevel 1 (
  echo Not a git repository.
  goto :fail
)

for /f %%r in ('git rev-parse --show-toplevel 2^>nul') do set "REPO_ROOT=%%r"
if not "%REPO_ROOT%"=="" cd /d "%REPO_ROOT%"
echo Repo: %CD%

git remote get-url origin >nul 2>&1
if errorlevel 1 (
  git remote add origin "%REMOTE_URL%"
  if errorlevel 1 goto :fail
) else (
  git remote set-url origin "%REMOTE_URL%"
  if errorlevel 1 goto :fail
)

for /f %%b in ('git rev-parse --abbrev-ref HEAD 2^>nul') do set "BRANCH=%%b"
if /I "%BRANCH%"=="HEAD" set "BRANCH="
if "%BRANCH%"=="" (
  git show-ref --verify --quiet "refs/heads/%DEFAULT_BRANCH%"
  if errorlevel 1 (
    git checkout -b "%DEFAULT_BRANCH%"
  ) else (
    git checkout "%DEFAULT_BRANCH%"
  )
  if errorlevel 1 goto :fail
  set "BRANCH=%DEFAULT_BRANCH%"
)

if /I not "%BRANCH%"=="%DEFAULT_BRANCH%" (
  git show-ref --verify --quiet "refs/heads/%DEFAULT_BRANCH%"
  if errorlevel 1 (
    git branch -m "%BRANCH%" "%DEFAULT_BRANCH%"
  ) else (
    git checkout "%DEFAULT_BRANCH%"
  )
  if errorlevel 1 goto :fail
  set "BRANCH=%DEFAULT_BRANCH%"
)

echo.
set /p msg=Commit message: 
if "%msg%"=="" (
  echo Commit message required.
  goto :fail
)

git add -A

git diff --cached --quiet
if errorlevel 1 goto :has_staged_changes

echo No changes to commit in %CD%.
goto :done

:has_staged_changes
git status -sb
git commit -m "%msg%"
if errorlevel 1 goto :fail

git push -u origin "%DEFAULT_BRANCH%"
if errorlevel 1 (
  echo.
  echo Push failed. Possible reasons:
  echo - remote branch has commits not in local
  echo - authentication issue
  echo.
  echo Try:
  echo   git pull --rebase origin %DEFAULT_BRANCH%
  echo   git push -u origin %DEFAULT_BRANCH%
  goto :fail
)

echo.
echo ========================================
echo SUCCESS
echo ========================================
echo Commit: %msg%
echo Repo:   https://github.com/bigboy4567/Tiktok_live_bot
echo Branch: %DEFAULT_BRANCH%
echo ========================================
echo.

goto :done

:done
popd >nul 2>&1
pause
exit /b 0

:fail
popd >nul 2>&1
pause
exit /b 1


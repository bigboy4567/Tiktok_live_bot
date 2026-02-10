@echo off
setlocal EnableExtensions EnableDelayedExpansion

chcp 65001 >nul

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

echo Repo: %CD%

git remote get-url origin >nul 2>&1
if errorlevel 1 (
  git remote add origin "%REMOTE_URL%"
  if errorlevel 1 goto :fail
) else (
  git remote set-url origin "%REMOTE_URL%"
  if errorlevel 1 goto :fail
)

git show-ref --verify --quiet "refs/heads/%DEFAULT_BRANCH%"
if errorlevel 1 (
  git checkout -b "%DEFAULT_BRANCH%"
  if errorlevel 1 goto :fail
) else (
  git checkout "%DEFAULT_BRANCH%"
  if errorlevel 1 goto :fail
)

echo.
git add -A

git diff --cached --quiet
if errorlevel 1 goto :has_staged_changes

echo No new file changes to commit.
goto :sync_and_push

:has_staged_changes
set /p msg=Commit message: 
if "%msg%"=="" (
  echo Commit message required.
  goto :fail
)

git status -sb
git commit -m "%msg%"
if errorlevel 1 goto :fail

:sync_and_push
REM If remote branch already exists, rebase local changes before push.
git ls-remote --exit-code --heads origin "%DEFAULT_BRANCH%" >nul 2>&1
if not errorlevel 1 (
  echo.
  echo Remote branch exists. Syncing with origin/%DEFAULT_BRANCH%...
  git pull --rebase origin "%DEFAULT_BRANCH%"
  if errorlevel 1 (
    echo.
    echo Rebase failed. Resolve conflicts, then run:
    echo   git rebase --continue
    echo or
    echo   git rebase --abort
    goto :fail
  )
)

git push -u origin "%DEFAULT_BRANCH%"
if errorlevel 1 (
  echo.
  echo Push failed. Verify auth and branch state.
  goto :fail
)

echo.
echo ========================================
echo SUCCESS
echo ========================================
if defined msg (
  echo Commit: %msg%
) else (
  echo Commit: none ^(no new file changes^)
)
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

@echo off
rem Entry point for Windows Task Scheduler.
rem cd is required: DB_PATH, logs/ and sources.yaml are relative paths,
rem so the working directory must be the repository root.
rem NOTE: keep comments ASCII-only (cmd reads .bat as cp932, UTF-8 Japanese breaks).
cd /d %~dp0
uv run python -m src.pipelines.daily_news

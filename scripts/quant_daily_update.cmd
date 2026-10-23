@echo off
rem After-close refresh of the quant layer, for Windows Task Scheduler.
rem Runs scripts\quant_daily_update.py with the repo's virtualenv and appends to a log
rem in the quant cache. Remove the schedule with:
rem   schtasks /Delete /TN "TradingAgents quant daily update" /F
cd /d "%~dp0.."
if not exist "%USERPROFILE%\.tradingagents\cache\quant" mkdir "%USERPROFILE%\.tradingagents\cache\quant"
echo ==== %DATE% %TIME% >> "%USERPROFILE%\.tradingagents\cache\quant\daily_update.log"
".venv\Scripts\python.exe" -W ignore scripts\quant_daily_update.py >> "%USERPROFILE%\.tradingagents\cache\quant\daily_update.log" 2>&1

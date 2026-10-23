@echo off
rem After-close refresh of the quant layer, run by hand or from Task Scheduler.
rem Windowless (pythonw) with its own log, so no console window can be closed mid-run.
rem The scheduled task runs the same command directly:
rem   .venv\Scripts\pythonw.exe -W ignore scripts\quant_daily_update.py --log <log>
rem Remove the schedule with:
rem   schtasks /Delete /TN "TradingAgents quant daily update" /F
cd /d "%~dp0.."
".venv\Scripts\pythonw.exe" -W ignore scripts\quant_daily_update.py --log "%USERPROFILE%\.tradingagents\cache\quant\daily_update.log"

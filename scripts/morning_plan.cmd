@echo off
rem Morning plan for NIFTY and BANKNIFTY, run by hand or from Task Scheduler (8:30 AM on weekdays).
rem Windowless (pythonw) with its own log. The scheduled task runs:
rem   .venv\Scripts\pythonw.exe -W ignore scripts\morning_plan.py --log <log>
rem Remove the schedule with:
rem   schtasks /Delete /TN "TradingAgents morning plan" /F
cd /d "%~dp0.."
".venv\Scripts\pythonw.exe" -W ignore scripts\morning_plan.py --log "%USERPROFILE%\.tradingagents\cache\quant\morning_plan.log"

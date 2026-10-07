@echo off
rem Double-click this (or run `run.bat`) to launch with system Python 3.11.
cd /d "%~dp0"
if not exist "data\analytics.db" (
    echo Generating the rich dataset ^(one time^)...
    py -3.11 "seed\generate_data.py" --scale rich
)
py -3.11 -m streamlit run "src\vantage\app.py"

@echo off
title FPEL Proposal Generator
cd /d "%~dp0"
echo.
echo   Starting FPEL Proposal Generator...
echo   Chrome will open automatically.
echo   Keep this window open while using the app.
echo   Close this window to stop the app.
echo.
start "" "http://localhost:8501" 
python -m streamlit run app.py --server.headless true

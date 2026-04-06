@echo off
echo === OLM - Office Layout Matching ===
echo Starting server on http://localhost:5051
echo Press Ctrl+C to stop.
echo.
venv\Scripts\python -m olm.server.app

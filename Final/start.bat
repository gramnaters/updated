@echo off
echo Setting up environment...

py -3.11 -m venv venv
call venv\Scripts\activate

echo Installing requirements...
pip install --no-cache-dir "python-telegram-bot[all]==21.3" requests urllib3 faker aiohttp

echo Starting bot...
python bott.py
pause
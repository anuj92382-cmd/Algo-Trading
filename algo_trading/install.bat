@echo off
echo ============================================
echo  Algo Trading - Install Script
echo ============================================
echo.

echo [Step 1] numpy + pandas already installed - skipping
echo.

echo [Step 2] Installing Zerodha Kite Connect...
pip install kiteconnect==4.2.0
echo.

echo [Step 3] Installing scheduling libraries...
pip install schedule==1.2.1 "APScheduler==3.10.4"
echo.

echo [Step 4] Installing utilities...
pip install python-dotenv==1.0.0 colorlog==6.8.0 colorama==0.4.6 pytz requests tabulate==0.9.0
echo.

echo [Step 5] Installing dashboard (Rich UI)...
pip install rich
echo.

echo [Step 6] Installing database + excel...
pip install SQLAlchemy==2.0.23 openpyxl==3.1.2
echo.

echo [Step 7] Installing WebSocket...
pip install websocket-client==1.7.0
echo.

echo [Step 8] Installing technical indicators...
pip install ta==0.11.0
echo.

echo ============================================
echo  Verifying installation...
echo ============================================
python -c "import numpy; print('✅ numpy:', numpy.__version__)"
python -c "import pandas; print('✅ pandas:', pandas.__version__)"
python -c "import kiteconnect; print('✅ kiteconnect: OK')"
python -c "import rich; print('✅ rich: OK')"
python -c "import ta; print('✅ ta (indicators): OK')"
python -c "import schedule; print('✅ schedule: OK')"
python -c "import dotenv; print('✅ python-dotenv: OK')"
echo.
echo ============================================
echo  Done! Ab chalao:
echo    python config.py   (config check)
echo    python main.py     (bot start)
echo    python dashboard.py (dashboard)
echo ============================================
pause

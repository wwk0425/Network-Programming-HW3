@echo off
REM ==========================================
REM   Game Platform One-Click Demo Script
REM   符合作業要求：快速啟動方式
REM ==========================================

echo [System] Starting Game Platform Demo...
echo [System] Please do not close this window until you finish the demo.

REM 2. 啟動 Server
REM start "視窗標題" cmd /k "指令"
REM /k 表示執行完不關閉視窗，方便看 Log
echo [1/3] Launching Server...
start "Remote Server" cmd /k ssh -t -l wkwang linux1.cs.nycu.edu.tw "cd ~/server && python -u server.py"
pause
REM 等待 2 秒確保 Server 跑起來
timeout /t 2 /nobreak >nul

REM 3. 啟動 Developer Client
echo [2/3] Launching Developer Client...
start "Developer Client" /d "developer" cmd /k "python developer_client.py"

REM 4. 啟動 Player Clients (多開模擬)
echo [3/3] Launching 3 Player Clients...

REM Player 1
start "Player 1 (Client)" /d "client" cmd /k "python player_client.py --user Player1"

REM Player 2
start "Player 2 (Client)" /d "client" cmd /k "python player_client.py --user Player2"

REM Player 3
start "Player 3 (Client)" /d "client" cmd /k "python player_client.py --user Player3"

echo.
echo [Success] All systems operational!
echo You can now arrange the windows and start the demo.
echo.
pause
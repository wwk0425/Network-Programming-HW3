REM 2. 啟動 Server
REM start "視窗標題" cmd /k "指令"
REM /k 表示執行完不關閉視窗，方便看 Log
echo [1/3] Launching Server...
start "Remote Server" cmd /k ssh -t -l wkwang linux1.cs.nycu.edu.tw "cd ~/server && python -u server.py"
pause
REM 等待 2 秒確保 Server 跑起來
timeout /t 2 /nobreak >nul
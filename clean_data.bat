@echo off
echo [Warning] This will delete all user data, game uploads, and downloads!
pause

echo Cleaning Server Data...
del /Q server\server_data\*.json

echo Cleaning Uploaded Games...
rmdir /S /Q server\games
mkdir server\games

echo Cleaning Player Downloads...
rmdir /S /Q client\games
mkdir client\games

echo [Done] Environment reset to factory settings.
pause
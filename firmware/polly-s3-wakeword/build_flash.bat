@echo off
call "C:\Espressif\frameworks\esp-idf-v5.4.3\export.bat"
cd /d "C:\Users\big_g\Desktop\polly-connect\firmware\polly-s3-wakeword"
idf.py build
if %ERRORLEVEL% NEQ 0 (
    echo BUILD FAILED
    exit /b 1
)
echo BUILD SUCCESS
idf.py -p COM3 flash
if %ERRORLEVEL% NEQ 0 (
    echo FLASH FAILED
    exit /b 1
)
echo FLASH SUCCESS

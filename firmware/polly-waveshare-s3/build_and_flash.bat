@echo off
call "C:\Espressif\frameworks\esp-idf-v5.4.3\export.bat" >nul 2>nul
cd /d "C:\Users\big_g\Desktop\polly-connect\firmware\polly-waveshare-s3"
idf.py build && idf.py -p COM4 flash

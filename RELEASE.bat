@echo off
chcp 65001 >nul
title TYMAP & Tdriver — Tool Phat Hanh & Cap Nhat OTA
cls

:MENU
echo =================================================================
echo        🚀 TYMAP & TDRIVER — QUẢN LÝ PHÁT HÀNH & CẬP NHẬT OTA
echo =================================================================
echo  [1] 🚀 Phát hành Bản mới Tự động (Tự tìm APK/BIN + NAS Sync)
echo  [2] 📱 Chỉ Build Android APK (assembleDebug)
echo  [3] 🖥️ Mở Công Cụ Quản Trị Git Smart Manager (GSM UI)
echo  [4] 📡 Đồng bộ nhanh version.json sang NAS Fusion Engine
echo  [5] ❌ Thoát
echo =================================================================
set /p choice="👉 Nhập lựa chọn của bạn (1-5): "

if "%choice%"=="1" goto AUTO_RELEASE
if "%choice%"=="2" goto BUILD_APK
if "%choice%"=="3" goto LAUNCH_GSM
if "%choice%"=="4" goto SYNC_NAS
if "%choice%"=="5" goto EXIT
echo ❌ Lựa chọn không hợp lệ, vui lòng thử lại!
pause
goto MENU

:AUTO_RELEASE
cls
python "%~dp0..\release_ota.py"
if %ERRORLEVEL% NEQ 0 (
    python "%~dp0release_ota.py"
)
pause
goto MENU

:BUILD_APK
cls
echo 📦 Đang tiến hành Build Android APK...
cd /d "%~dp0..\TYMAP"
call gradlew.bat assembleDebug
cd /d "%~dp0"
echo.
echo ✅ Hoàn tất build APK tại: TYMAP\app\build\outputs\apk\debug\app-debug.apk
pause
goto MENU

:LAUNCH_GSM
cls
echo 🌐 Đang khởi chạy Git Smart Manager (GSM)...
start "" "%~dp0GSM.bat"
goto MENU

:SYNC_NAS
cls
echo 📡 Đang đồng bộ version.json sang máy chủ NAS...
python -c "
import json, paramiko, os
ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect('192.168.1.114', username='nas152', password='271000', timeout=5)
sftp = ssh.open_sftp()
v_path = r'%~dp0..\version.json' if os.path.exists(r'%~dp0..\version.json') else r'%~dp0version.json'
sftp.put(v_path, '/home/nas152/tymap_data/cameras/version.json')
sftp.close()
ssh.exec_command('docker restart tymap_fusion_engine')
ssh.close()
print('✅ Đã đồng bộ version.json thành công sang NAS!')
"
pause
goto MENU

:EXIT
exit

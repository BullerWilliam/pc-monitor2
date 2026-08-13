Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

py -m PyInstaller --noconfirm --clean --onefile --windowed --name access app\access_app.py
py -m PyInstaller --noconfirm --clean --onefile --windowed --name monitor app\monitor_app.py

Write-Host "Built dist\access.exe and dist\monitor.exe"

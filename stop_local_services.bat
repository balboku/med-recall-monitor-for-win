@echo off
setlocal

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "Get-CimInstance Win32_Process | Where-Object { " ^
  "    ($_.Name -eq 'node.exe' -and $_.CommandLine -like '*med-recall-monitor-for-win*') -or " ^
  "    ($_.Name -eq 'python.exe' -and $_.CommandLine -like '*med-recall-monitor-for-win*') -or " ^
  "    ($_.Name -eq 'cmd.exe' -and $_.CommandLine -like '*start_backend_local.bat*') -or " ^
  "    ($_.Name -eq 'cmd.exe' -and $_.CommandLine -like '*start_frontend_local.bat*')" ^
  "} | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"

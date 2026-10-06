$ErrorActionPreference = 'Stop'
Set-Location (Split-Path $PSScriptRoot -Parent)
& .\.venv\Scripts\python.exe -m mt5_bridge.worker *>> .\mt5_bridge\worker.log

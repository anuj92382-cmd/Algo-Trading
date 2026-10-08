# Stop all processes on port 5000
try {
    Get-NetTCPConnection -LocalPort 5000 -ErrorAction Stop | ForEach-Object {
        $pId = $_.OwningProcess
        if ($pId -gt 0 -and $pId -ne $PID) {
            Write-Host "Killing process on port 5000: PID $pId"
            Stop-Process -Id $pId -Force -ErrorAction SilentlyContinue
        }
    }
} catch {}

# Stop all processes matching web_app.py, START.bat, or algo_trading python
Get-CimInstance Win32_Process | Where-Object {
    $_.ProcessId -ne $PID -and (
        $_.CommandLine -like '*web_app.py*' -or
        $_.CommandLine -like '*START.bat*' -or
        ($_.Name -eq 'python.exe' -and $_.CommandLine -like '*algo_trading*')
    )
} | ForEach-Object {
    Write-Host "Stopping process $($_.Name) (PID: $($_.ProcessId))..."
    Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
}

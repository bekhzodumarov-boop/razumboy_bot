# watch_templates.ps1 - polls templates/ every 5s and auto git push on .txt change
param()

$repoPath  = "C:\Users\bekhzod.umarov\Desktop\Razumboy\bot\razumboy_bot_v17\razumboy_bot"
$watchPath = "$repoPath\templates"
$logFile   = "$repoPath\watch_templates.log"

function Write-Log($msg) {
    $line = "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')  $msg"
    Add-Content -Path $logFile -Value $line -Encoding UTF8
}

Write-Log "=== Watcher started (polling). Watching: $watchPath ==="

$lastWriteTimes = @{}
Get-ChildItem "$watchPath\*.txt" | ForEach-Object { $lastWriteTimes[$_.Name] = $_.LastWriteTime }
$lastPush = [datetime]::MinValue
Write-Log "Ready. Polling every 5 seconds..."

while ($true) {
    Start-Sleep -Seconds 5
    $files = Get-ChildItem "$watchPath\*.txt" -ErrorAction SilentlyContinue
    foreach ($f in $files) {
        $prev = $lastWriteTimes[$f.Name]
        if ($null -eq $prev) { $lastWriteTimes[$f.Name] = $f.LastWriteTime; continue }
        if ($f.LastWriteTime -gt $prev) {
            $lastWriteTimes[$f.Name] = $f.LastWriteTime
            $now = Get-Date
            if (($now - $lastPush).TotalSeconds -lt 10) { continue }
            $lastPush = $now
            Write-Log "Changed: $($f.Name) - running git push..."
            Set-Location $repoPath
            & git add "templates\$($f.Name)" 2>&1 | Out-Null
            & git commit -m "auto: update template $($f.Name)" 2>&1 | Out-Null
            if ($LASTEXITCODE -eq 0) {
                & git push 2>&1 | Out-Null
                if ($LASTEXITCODE -eq 0) { Write-Log "OK: pushed $($f.Name) - Railway deploys in ~2 min" }
                else { Write-Log "ERROR: git push failed" }
            } else { Write-Log "No changes to commit" }
        }
    }
}
param([switch]$NoBrowser)
$ErrorActionPreference = 'Stop'
$taskRoot = [IO.Path]::GetFullPath($PSScriptRoot)
$taskUrl = 'http://127.0.0.1:8765'
$taskResponse = $null
try { $taskResponse = Invoke-RestMethod -Uri "$taskUrl/api/state" -TimeoutSec 2 } catch {}
if ($null -ne $taskResponse) {
    if (-not $taskResponse.workspace -or [IO.Path]::GetFullPath($taskResponse.workspace) -ne $taskRoot) {
        throw "端口8765运行着其他目录的聊天室（$($taskResponse.workspace)）。为保护记录，本入口不会连接或覆盖它；请先结束旧服务再重试。"
    }
    if (-not $NoBrowser) { Start-Process $taskUrl }
    exit
}
$taskPython = (Get-Command python -ErrorAction Stop).Source
$taskLog = Join-Path $taskRoot 'data'
New-Item -ItemType Directory -Force -Path $taskLog | Out-Null
$taskServer = Join-Path $taskRoot 'server.py'
$taskProcess = Start-Process -FilePath $taskPython -ArgumentList @('"' + $taskServer + '"') -WorkingDirectory $taskRoot -WindowStyle Hidden -RedirectStandardOutput (Join-Path $taskLog 'server.out.log') -RedirectStandardError (Join-Path $taskLog 'server.err.log') -PassThru
Set-Content -LiteralPath (Join-Path $taskLog 'server.pid') -Value $taskProcess.Id
for ($taskAttempt = 0; $taskAttempt -lt 30; $taskAttempt++) {
    Start-Sleep -Milliseconds 300
    if ($taskProcess.HasExited) { throw '聊天室启动失败，请查看 data/server.err.log。' }
    $taskResponse=$null
    try { $taskResponse = Invoke-RestMethod -Uri "$taskUrl/api/state" -TimeoutSec 1 } catch {}
    if ($null -ne $taskResponse) {
        if (-not $taskResponse.workspace -or [IO.Path]::GetFullPath($taskResponse.workspace) -ne $taskRoot) { throw '聊天室目录校验失败，未打开页面。' }
        if (-not $NoBrowser) { Start-Process $taskUrl }
        exit
    }
}
throw '聊天室启动超时，请查看 data/server.err.log。'

[CmdletBinding()]
param(
    [int]$DebugPort = 9222,
    [string]$Aumid
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Get-CodexAumid {
    param(
        [string]$ExplicitAumid
    )

    if ($ExplicitAumid) {
        return $ExplicitAumid
    }

    $packagesRoot = Join-Path $env:LOCALAPPDATA "Packages"
    if (-not (Test-Path $packagesRoot)) {
        throw "未找到 Packages 目录：$packagesRoot"
    }

    $candidate = Get-ChildItem $packagesRoot -Directory |
        Where-Object { $_.Name -match '^OpenAI\.Codex(?:Beta)?_[^\\]+$' } |
        Sort-Object Name -Descending |
        Select-Object -First 1

    if (-not $candidate) {
        throw "未找到 OpenAI.Codex 安装目录。可手动传入 -Aumid。"
    }

    return "$($candidate.Name)!App"
}

function Get-StandaloneCodexExe {
    $localAppData = $env:LOCALAPPDATA
    if (-not $localAppData) {
        return $null
    }

    $candidateRoots = @(
        (Join-Path $localAppData "OpenAI\\Codex\\bin"),
        (Join-Path $localAppData "OpenAI\\Codex")
    )

    foreach ($root in $candidateRoots) {
        if (-not (Test-Path $root)) {
            continue
        }

        $direct = Join-Path $root "codex.exe"
        if (Test-Path $direct) {
            return $direct
        }

        $nested = Get-ChildItem $root -Directory -ErrorAction SilentlyContinue |
            ForEach-Object { Join-Path $_.FullName "codex.exe" } |
            Where-Object { Test-Path $_ } |
            Select-Object -First 1
        if ($nested) {
            return $nested
        }
    }

    return $null
}

Add-Type -TypeDefinition @"
using System;
using System.Runtime.InteropServices;

[ComImport, Guid("45BA127D-10A8-46EA-8AB7-56EA9078943C")]
class ApplicationActivationManager
{
}

[ComImport, InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
[Guid("2E941141-7F97-4756-BA1D-9DECDE894A3D")]
interface IApplicationActivationManager
{
    int ActivateApplication(
        [MarshalAs(UnmanagedType.LPWStr)] string appUserModelId,
        [MarshalAs(UnmanagedType.LPWStr)] string arguments,
        int options,
        out uint processId
    );
}

public static class CodexActivator
{
    public static uint Activate(string aumid, string args)
    {
        var manager = (IApplicationActivationManager)new ApplicationActivationManager();
        uint pid;
        int hr = manager.ActivateApplication(aumid, args, 0, out pid);
        if (hr != 0) Marshal.ThrowExceptionForHR(hr);
        return pid;
    }
}
"@

$resolvedAumid = Get-CodexAumid -ExplicitAumid $Aumid
$arguments = "--remote-debugging-port=$DebugPort --remote-allow-origins=http://127.0.0.1:$DebugPort"

Write-Host "AUMID: $resolvedAumid"
Write-Host "参数: $arguments"
$processId = $null

try {
    $processId = [CodexActivator]::Activate($resolvedAumid, $arguments)
    Write-Host "已通过 Activation 启动 Codex，PID: $processId"
} catch {
    Write-Warning "Activation 启动失败：$($_.Exception.Message)"
    $standaloneExe = Get-StandaloneCodexExe
    if (-not $standaloneExe) {
        throw "Activation 失败，且未找到可回退的 codex.exe"
    }

    Write-Host "回退为直接启动: $standaloneExe"
    $process = Start-Process -FilePath $standaloneExe -ArgumentList @(
        "--remote-debugging-port=$DebugPort",
        "--remote-allow-origins=http://127.0.0.1:$DebugPort"
    ) -PassThru
    $processId = $process.Id
    Write-Host "已通过 exe 启动 Codex，PID: $processId"
}

Start-Sleep -Seconds 2

$targetsUrl = "http://127.0.0.1:$DebugPort/json"
try {
    $targets = Invoke-RestMethod $targetsUrl
    Write-Host "CDP 已就绪：$targetsUrl"
    $targets |
        Select-Object id, type, title, url, webSocketDebuggerUrl |
        Format-Table -AutoSize
} catch {
    Write-Warning "Codex 已启动，但 CDP 可能尚未就绪：$targetsUrl"
    Write-Warning $_.Exception.Message
}

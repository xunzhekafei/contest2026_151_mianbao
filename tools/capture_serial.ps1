[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$Port,

    [int]$BaudRate = 115200,

    [string]$OutputPath = "",

    [int]$DurationSeconds = 0
)

$ErrorActionPreference = "Stop"

if ([string]::IsNullOrWhiteSpace($OutputPath)) {
    $stamp = Get-Date -Format "yyyyMMdd_HHmmss"
    $OutputPath = Join-Path $PSScriptRoot "..\documents\evidence\midterm\serial_$stamp.log"
}

$OutputPath = [System.IO.Path]::GetFullPath($OutputPath)
$outputDir = Split-Path -Parent $OutputPath
if (-not (Test-Path -LiteralPath $outputDir)) {
    New-Item -ItemType Directory -Force -Path $outputDir | Out-Null
}

$serial = New-Object System.IO.Ports.SerialPort
$serial.PortName = $Port
$serial.BaudRate = $BaudRate
$serial.Parity = [System.IO.Ports.Parity]::None
$serial.DataBits = 8
$serial.StopBits = [System.IO.Ports.StopBits]::One
$serial.Handshake = [System.IO.Ports.Handshake]::None
$serial.ReadTimeout = 500
$serial.WriteTimeout = 500
$serial.Encoding = New-Object System.Text.UTF8Encoding($false)

$writer = New-Object System.IO.StreamWriter(
    $OutputPath,
    $false,
    (New-Object System.Text.UTF8Encoding($false))
)
$writer.AutoFlush = $true
$clock = [System.Diagnostics.Stopwatch]::StartNew()
$buffer = New-Object System.Text.StringBuilder

function Write-CapturedLine {
    param([string]$Line)

    $localTime = Get-Date -Format "yyyy-MM-dd HH:mm:ss.fff"
    $relative = $clock.Elapsed.TotalSeconds.ToString("0.000", [System.Globalization.CultureInfo]::InvariantCulture)
    $entry = "[$localTime +${relative}s] $Line"
    Write-Host $entry
    $writer.WriteLine($entry)
}

try {
    $serial.Open()
    Write-Host "Capturing $Port at $BaudRate baud -> $OutputPath"
    Write-Host "Press Ctrl+C to stop."

    while ($DurationSeconds -le 0 -or $clock.Elapsed.TotalSeconds -lt $DurationSeconds) {
        $chunk = $serial.ReadExisting()
        if ([string]::IsNullOrEmpty($chunk)) {
            Start-Sleep -Milliseconds 20
            continue
        }

        foreach ($ch in $chunk.ToCharArray()) {
            if ($ch -eq "`n") {
                $line = $buffer.ToString().TrimEnd("`r")
                if ($line.Length -gt 0) {
                    Write-CapturedLine $line
                }
                $buffer.Clear() | Out-Null
            }
            else {
                $buffer.Append($ch) | Out-Null
            }
        }
    }
}
finally {
    if ($buffer.Length -gt 0) {
        Write-CapturedLine $buffer.ToString()
    }
    if ($serial.IsOpen) {
        $serial.Close()
    }
    $serial.Dispose()
    $writer.Dispose()
    Write-Host "Saved: $OutputPath"
}

[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$Path,

    [string]$OutputPath = ""
)

$ErrorActionPreference = "Stop"

$Path = [System.IO.Path]::GetFullPath($Path)
if (-not (Test-Path -LiteralPath $Path)) {
    throw "Serial log not found: $Path"
}

$roundPattern = '^\[(?<local>[^\]]+)\]\s+(?<message>.*)$'
$relativePattern = '\+\s*(?<seconds>[0-9]+(?:\.[0-9]+)?)s'
$waitPattern = '收尾等待\s+(?<seconds>[0-9]+)\s*秒'
$rounds = New-Object System.Collections.Generic.List[object]
$current = $null

function New-Round {
    return [pscustomobject]@{
        Start = $null
        RecordingStart = $null
        RecordingEnd = $null
        FirstPlay = $null
        LastPlayEnd = $null
        LiveDone = $null
        UploadStart = $null
        UploadWaitText = $null
        Errors = New-Object System.Collections.Generic.List[string]
    }
}

function Finish-Round {
    param($Round)

    if ($null -eq $Round) {
        return
    }

    $recording = $null
    if (($null -ne $Round.RecordingStart) -and ($null -ne $Round.RecordingEnd)) {
        $recording = $Round.RecordingEnd - $Round.RecordingStart
    }

    $firstSentence = $null
    if (($null -ne $Round.RecordingEnd) -and ($null -ne $Round.FirstPlay)) {
        $firstSentence = $Round.FirstPlay - $Round.RecordingEnd
    }

    $uploadWait = $null
    if ($null -ne $Round.UploadWaitText) {
        $uploadWait = [double]$Round.UploadWaitText
    }
    elseif (($null -ne $Round.UploadStart) -and ($null -ne $Round.LiveDone)) {
        $uploadWait = $Round.LiveDone - $Round.UploadStart
    }

    $end = $null
    foreach ($candidate in @($Round.LiveDone, $Round.LastPlayEnd)) {
        if (($null -ne $candidate) -and (($null -eq $end) -or ($candidate -gt $end))) {
            $end = $candidate
        }
    }

    $total = $null
    if (($null -ne $Round.Start) -and ($null -ne $end)) {
        $total = $end - $Round.Start
    }

    $status = if ($Round.Errors.Count -gt 0) { "FAIL" } elseif ($null -ne $end) { "OK" } else { "INCOMPLETE" }

    $rounds.Add([pscustomobject]@{
        Round = $rounds.Count + 1
        RecordingSeconds = $recording
        FirstSentenceSeconds = $firstSentence
        UploadWaitSeconds = $uploadWait
        TotalSeconds = $total
        Status = $status
        Notes = ($Round.Errors -join "; ")
    })
}

foreach ($line in [System.IO.File]::ReadLines($Path, [System.Text.Encoding]::UTF8)) {
    $match = [regex]::Match($line, $roundPattern)
    if (-not $match.Success) {
        continue
    }

    $localTime = [datetime]::MinValue
    $hasLocalTime = [datetime]::TryParse(
        $match.Groups["local"].Value,
        [System.Globalization.CultureInfo]::InvariantCulture,
        [System.Globalization.DateTimeStyles]::None,
        [ref]$localTime
    )
    $relativeMatch = [regex]::Match($match.Groups["local"].Value, $relativePattern)
    if (-not $relativeMatch.Success) {
        continue
    }

    $seconds = [double]::Parse(
        $relativeMatch.Groups["seconds"].Value,
        [System.Globalization.CultureInfo]::InvariantCulture
    )
    $message = $match.Groups["message"].Value

    if ($message -match 'K1 按下.*开始面试') {
        Finish-Round $current
        $current = New-Round
        $current.Start = $seconds
        continue
    }

    if ($null -eq $current) {
        continue
    }

    if ($message -match '^\[Audio\] 开始录音') {
        $current.RecordingStart = $seconds
    }
    elseif ($message -match '^\[Audio\] 录音完成:') {
        $current.RecordingEnd = $seconds
    }
    elseif ($message -match '^\[Audio\] 开始播放:') {
        if ($null -eq $current.FirstPlay) {
            $current.FirstPlay = $seconds
        }
    }
    elseif ($message -match '^\[Audio\] 播放结束:') {
        $current.LastPlayEnd = $seconds
    }
    elseif ($message -match '^\[StateMachine\] 开始上传音频') {
        $current.UploadStart = $seconds
    }
    elseif ($message -match '^\[Main\] 边录边传完成') {
        $current.LiveDone = $seconds
        $waitMatch = [regex]::Match($message, $waitPattern)
        if ($waitMatch.Success) {
            $current.UploadWaitText = $waitMatch.Groups["seconds"].Value
        }
    }
    elseif ($message -match '上传失败|边录边传未成功|流式回答中断|网络不太稳定') {
        $current.Errors.Add($message)
    }
}

Finish-Round $current

if ($rounds.Count -eq 0) {
    throw "No interview round found. Expected a line containing '[Main] K1 按下 —— 开始面试'."
}

$rows = foreach ($row in $rounds) {
    [pscustomobject]@{
        Round = $row.Round
        RecordingSeconds = if ($null -eq $row.RecordingSeconds) { "" } else { $row.RecordingSeconds.ToString("0.000", [System.Globalization.CultureInfo]::InvariantCulture) }
        FirstSentenceSeconds = if ($null -eq $row.FirstSentenceSeconds) { "" } else { $row.FirstSentenceSeconds.ToString("0.000", [System.Globalization.CultureInfo]::InvariantCulture) }
        UploadWaitSeconds = if ($null -eq $row.UploadWaitSeconds) { "" } else { $row.UploadWaitSeconds.ToString("0.000", [System.Globalization.CultureInfo]::InvariantCulture) }
        TotalSeconds = if ($null -eq $row.TotalSeconds) { "" } else { $row.TotalSeconds.ToString("0.000", [System.Globalization.CultureInfo]::InvariantCulture) }
        Status = $row.Status
        Notes = $row.Notes
    }
}

$rows | Format-Table -AutoSize | Out-Host

if (-not [string]::IsNullOrWhiteSpace($OutputPath)) {
    $OutputPath = [System.IO.Path]::GetFullPath($OutputPath)
    $outputDir = Split-Path -Parent $OutputPath
    if (-not (Test-Path -LiteralPath $outputDir)) {
        New-Item -ItemType Directory -Force -Path $outputDir | Out-Null
    }
    $rows | Export-Csv -LiteralPath $OutputPath -NoTypeInformation -Encoding UTF8
    Write-Host "Saved: $OutputPath"
}

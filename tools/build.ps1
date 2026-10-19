# Build (and optionally upload and check) the NES firmware with PureMetalForge.
#
#   tools/build.ps1                                   # rp2040/demo.picow -> firmware/nes-pico-w.uf2
#   tools/build.ps1 -Port COM7 -Seconds 60 -VerifyNes -Source rp2040/Diagnostics/verify.picow -Output rp2040/Diagnostics/verify.uf2
#
# The compiler comes from -Compiler, else the PUREMETALFORGE environment
# variable, else PureMetalForge.exe on PATH.
param(
    [string]$Compiler = $env:PUREMETALFORGE,
    [string]$Source = '',
    [string]$Output = '',
    [string]$Port = '',
    [int]$Seconds = 12,
    [switch]$VerifyNes,
    [ValidateSet('rp2040','rp2350')][string]$Target = 'rp2040',
    [ValidateSet('lafvin','display-pack2','ili9341','hx8357d')][string]$Display = 'lafvin'
)
$ErrorActionPreference = 'Stop'
if (!$Compiler) {
    $found = Get-Command PureMetalForge.exe -ErrorAction SilentlyContinue
    if (!$found) { throw 'PureMetalForge.exe was not found: pass -Compiler, set PUREMETALFORGE, or put it on PATH.' }
    $Compiler = $found.Source
}
$projectRoot = Split-Path $PSScriptRoot -Parent
if (!$Source) {
    $wrapper = switch ($Display) { 'display-pack2' { 'display_pack2' }; 'ili9341' { 'ili9341' }; 'hx8357d' { 'hx8357d' }; default { 'demo' } }
    $extension = if ($Target -eq 'rp2350') { 'pico2w' } else { 'picow' }
    $Source = "$Target/$wrapper.$extension"
} elseif ($PSBoundParameters.ContainsKey('Display')) {
    throw '-Display selects the standard wrapper; use -Source alone for custom wrappers.'
}
$sourceTarget = if ($Source -match '\.pico2w?$') { 'rp2350' } else { 'rp2040' }
if ($PSBoundParameters.ContainsKey('Target') -and $Target -ne $sourceTarget) {
    throw '-Target does not match the source wrapper extension.'
}
if (!$Output) {
    $boardName = if ($sourceTarget -eq 'rp2350') { 'pico2-w' } else { 'pico-w' }
    $displayName = if ($Display -eq 'display-pack2' -or $Source -match 'display_pack2\.') { '-display-pack2' } elseif ($Display -eq 'hx8357d' -or $Source -match 'hx8357d\.') { '-hx8357d' } elseif ($Display -eq 'ili9341' -or $Source -match 'ili9341\.') { '-ili9341' } else { '' }
    $Output = "firmware/nes-$boardName$displayName.uf2"
}
$sourcePath = if ([IO.Path]::IsPathRooted($Source)) { [IO.Path]::GetFullPath($Source) } else { [IO.Path]::GetFullPath((Join-Path $projectRoot $Source)) }
$outputPath = if ([IO.Path]::IsPathRooted($Output)) { [IO.Path]::GetFullPath($Output) } else { [IO.Path]::GetFullPath((Join-Path $projectRoot $Output)) }
[IO.Directory]::CreateDirectory((Split-Path $outputPath -Parent)) | Out-Null
$arguments = '--compile "' + $sourcePath + '" -S -o "' + $outputPath + '"'
# Compile and validate before any upload can touch the board's ROM store.
$stdoutPath = $outputPath + '.build.log'
$stderrPath = $outputPath + '.stderr.log'
$compilerPath = (Resolve-Path -LiteralPath $Compiler).Path
$compilerRoot = Split-Path $compilerPath -Parent
$previousPmfRoot = $env:PMF_ROOT
try {
    $env:PMF_ROOT = $compilerRoot
    $process = Start-Process -FilePath $compilerPath -ArgumentList $arguments -WorkingDirectory $compilerRoot -WindowStyle Hidden -Wait -PassThru -RedirectStandardOutput $stdoutPath -RedirectStandardError $stderrPath
} finally {
    $env:PMF_ROOT = $previousPmfRoot
}
Get-Content $stdoutPath
Get-Content $stderrPath
if ($process.ExitCode -ne 0) { throw "Compiler exit $($process.ExitCode): $stdoutPath" }
if ($outputPath.EndsWith('.uf2')) {
    # The ROM store starts at flash offset $50000 (rp2040/rom_store.pico): an
    # image reaching it overwrites the games stored on the board.
    $uf2 = [IO.File]::ReadAllBytes($outputPath); $imageEnd = 0
    for ($o = 0; $o -lt $uf2.Length; $o += 512) {
        $blockEnd = [BitConverter]::ToUInt32($uf2, $o + 12) + [BitConverter]::ToUInt32($uf2, $o + 16)
        if ($blockEnd -gt $imageEnd) { $imageEnd = $blockEnd }
    }
    if ($imageEnd -gt 0x10050000) {
        throw ('Image reaches 0x{0:X8}, past the ROM store at 0x10050000: uploading it would overwrite the stored games' -f $imageEnd)
    }
}
if ($VerifyNes) {
    if (!$Port) { throw '-VerifyNes requires -Port; compilation alone cannot pass verification.' }
}
if ($Port) {
    $target = if ($sourcePath -match '\.pico2w?$') { 'rp2350' } else { 'rp2040' }
    & py -3 (Join-Path $PSScriptRoot 'upload_pack.py') $outputPath --compiler $Compiler --port $Port --target $target
    if ($LASTEXITCODE -ne 0) { throw 'Validated firmware upload failed.' }
    $capturePath = $outputPath + '.board.log'
    & py -3 (Join-Path $PSScriptRoot 'monitor.py') --port $Port --seconds $Seconds --output $capturePath
    if ($LASTEXITCODE -ne 0) { throw 'Serial capture failed.' }
}
if ($VerifyNes) {
    $nesTranscript = Get-Content -Raw $capturePath
    if ($nesTranscript -notmatch 'NES board checks=[1-9][0-9]* failures=0 PASS' -or $nesTranscript -cmatch '\bFAIL\b') {
        throw "NES board verification did not pass: $stdoutPath"
    }
}
Get-FileHash -Algorithm SHA256 -LiteralPath $sourcePath,$outputPath | Format-Table -AutoSize

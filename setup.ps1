<#
.SYNOPSIS
    One-step setup for muse-body on Windows.

.DESCRIPTION
    Run from anywhere; it works in the folder this script is in:

        powershell -ExecutionPolicy Bypass -File setup.ps1

    1. Finds Python 3.10 or newer (the py launcher's 3.13 to 3.10 first, then any 3.10+).
    2. Makes .venv and installs muse-body with its test and replay extras.
    3. Creates .env from .env.example and asks for the Meta Model API key (typed hidden,
       never printed). Press Enter to skip and add it to .env later.
    4. Runs the offline tests (no key, no VRChat).
    5. With a key, makes two real API calls on a frame from the logged demo run: SAM 3.1 boxes
       the menu, then Muse Spark decides what to do.

.PARAMETER SkipGamepadDriver
    Do not install the ViGEmBus virtual gamepad driver. The checks work without it, and so does
    `muse-body --input osc`, minus grabbing and hand signs.

.PARAMETER SkipApiCheck
    Skip step 5.
#>
[CmdletBinding()]
param(
    [switch]$SkipGamepadDriver,
    [switch]$SkipApiCheck
)

$ErrorActionPreference = "Stop"
Set-Location -LiteralPath $PSScriptRoot

function Step([string]$text) { Write-Host ""; Write-Host "== $text" -ForegroundColor Cyan }
function Fail([string]$text) { Write-Host $text -ForegroundColor Red; exit 1 }

function Test-Python([string[]]$cmd) {
    try {
        $out = & $cmd[0] @($cmd[1..($cmd.Length)] | Where-Object { $_ }) -c "import sys; print('%d.%d' % sys.version_info[:2])" 2>$null
        if ($LASTEXITCODE -ne 0 -or -not $out) { return $null }
        $v = [version]"$out".Trim()
        if ($v -ge [version]"3.10") { return $v }
    } catch { }
    return $null
}

# 1. Python
Step "Finding Python 3.10 or newer"
$python = $null
if (Get-Command py -ErrorAction SilentlyContinue) {
    foreach ($minor in 13, 12, 11, 10) {
        if (Test-Python @("py", "-3.$minor")) { $python = @("py", "-3.$minor"); break }
    }
    if (-not $python -and (Test-Python @("py", "-3"))) { $python = @("py", "-3") }
}
if (-not $python -and (Get-Command python -ErrorAction SilentlyContinue) -and (Test-Python @("python"))) {
    $python = @("python")
}
if (-not $python) { Fail "No Python 3.10 or newer found. Install it from https://www.python.org/downloads/ and run this again." }
Write-Host "Using $($python -join ' ') (Python $(Test-Python $python))"

# 2. Virtual environment and install
$venvPy = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $venvPy)) {
    Step "Making .venv"
    & $python[0] @($python[1..($python.Length)] | Where-Object { $_ }) -m venv .venv
    if ($LASTEXITCODE -ne 0) { Fail "Could not make .venv" }
}
Step "Installing muse-body into .venv"
if ($SkipGamepadDriver) { $env:VGAMEPAD_SKIP_VIGEMBUS_INSTALL = "true" }
& $venvPy -m pip install --disable-pip-version-check -q --upgrade pip
& $venvPy -m pip install --disable-pip-version-check -q -e ".[dev,replay]"
if ($LASTEXITCODE -ne 0) { Fail "pip install failed (see above)" }

# 3. .env and the API key
Step "API key"
if (-not (Test-Path .env)) { Copy-Item .env.example .env; Write-Host "Created .env from .env.example" }
$hasKey = [bool](Select-String -Path .env -Pattern '^\s*MODEL_API_KEY\s*=\s*\S' -Quiet)
if ($hasKey) {
    Write-Host ".env already has MODEL_API_KEY"
} else {
    $key = $null
    try {
        $secure = Read-Host "Meta Model API key (hidden; Enter to skip)" -AsSecureString
        $key = [Runtime.InteropServices.Marshal]::PtrToStringBSTR([Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure))
    } catch {
        Write-Host "No console to type the key in."
    }
    if ($key) {
        $lines = @(Get-Content .env | Where-Object { $_ -notmatch '^\s*MODEL_API_KEY\s*=' })
        # UTF-8 without a byte order mark, which Windows PowerShell 5.1's -Encoding utf8 would add.
        [IO.File]::WriteAllLines((Join-Path $PSScriptRoot ".env"), [string[]](@("MODEL_API_KEY=$key") + $lines),
                                 (New-Object Text.UTF8Encoding($false)))
        $hasKey = $true
        Write-Host "Saved to .env (git-ignored)"
    } else {
        Write-Host "Skipped: set MODEL_API_KEY= in .env before running the agent"
    }
    Remove-Variable key -ErrorAction SilentlyContinue
}

# 4. Offline tests
Step "Offline tests"
& $venvPy -m pytest -q
if ($LASTEXITCODE -ne 0) { Fail "Tests failed (see above)" }

# 5. Real API calls on a logged frame
$frame = "demo_runs\demo6_take\00009.jpg"
if ($hasKey -and -not $SkipApiCheck -and (Test-Path $frame)) {
    Step "Checking the API: SAM 3.1 and Muse Spark on $frame"
    & (Join-Path $PSScriptRoot ".venv\Scripts\muse-probe.exe") $frame --phrase menu
    if ($LASTEXITCODE -ne 0) { Fail "SAM 3.1 call failed: check the key in .env" }
    & (Join-Path $PSScriptRoot ".venv\Scripts\muse-probe.exe") $frame --goal "Find the café menu."
    if ($LASTEXITCODE -ne 0) { Fail "Muse Spark call failed: check the key in .env" }
}

Step "Done"
Write-Host @"
Activate the environment in each new PowerShell window:
    .venv\Scripts\Activate.ps1
(If PowerShell refuses: Set-ExecutionPolicy -Scope Process RemoteSigned, then activate again.)

Then:
    muse-hear --seconds 30          # prints what it hears the PC play
    muse-body --dry-run --steps 3   # with VRChat open (README steps 4 and 5)
    muse-calls demo_runs\demo6_take # the demo run's API calls, as CALLS.md
"@

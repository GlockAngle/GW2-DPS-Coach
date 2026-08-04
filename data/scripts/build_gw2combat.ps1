$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$Source = Join-Path $ProjectRoot "vendor\gw2combat"
$Build = Join-Path $Source "build-windows"
$Bin = Join-Path $ProjectRoot "bin"

Write-Host "Building gw2combat for Thief Lab..." -ForegroundColor Cyan

if (-not (Test-Path (Join-Path $Source "CMakeLists.txt"))) {
    throw "Bundled gw2combat source was not found at $Source"
}

if (-not (Get-Command cmake -ErrorAction SilentlyContinue)) {
    throw "CMake is required and was not found on PATH."
}

New-Item -ItemType Directory -Force -Path $Build, $Bin | Out-Null

$CMakeArgs = @(
    "-S", $Source,
    "-B", $Build,
    "-A", "x64",
    "-DCMAKE_POLICY_VERSION_MINIMUM:STRING=3.5"
)

& cmake @CMakeArgs

if ($LASTEXITCODE -ne 0) {
    throw "CMake configuration failed with exit code $LASTEXITCODE"
}

& cmake --build $Build --config Release --target gw2combat --parallel

if ($LASTEXITCODE -ne 0) {
    throw "CMake build failed with exit code $LASTEXITCODE"
}

$Candidates = @(
    (Join-Path $Build "Release\gw2combat.exe"),
    (Join-Path $Build "gw2combat.exe")
)

$Exe = $Candidates |
    Where-Object { Test-Path $_ } |
    Select-Object -First 1

if (-not $Exe) {
    throw "Build completed but gw2combat.exe was not found."
}

$Destination = Join-Path $Bin "gw2combat.exe"
Copy-Item $Exe $Destination -Force

# Smoke-test the binary with the bundled upstream encounter.
$Audit = Join-Path $env:TEMP "gw2combat-smoke-audit.json"

Push-Location $Source

try {
    & $Destination `
        --encounter "resources/encounter.json" `
        --audit-path $Audit

    if ($LASTEXITCODE -ne 0) {
        throw "gw2combat smoke test failed with exit code $LASTEXITCODE"
    }

    if (-not (Test-Path $Audit)) {
        throw "gw2combat smoke test did not create an audit file."
    }
}
finally {
    Pop-Location
    Remove-Item $Audit -ErrorAction SilentlyContinue
}

Write-Host "gw2combat ready and smoke-tested: $Destination" -ForegroundColor Green
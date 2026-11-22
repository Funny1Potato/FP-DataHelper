[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string] $SkillsDir,
    [string] $RuntimeZip
)

$ErrorActionPreference = 'Stop'
if ([Environment]::OSVersion.Platform -ne [PlatformID]::Win32NT -or -not [Environment]::Is64BitOperatingSystem) {
    throw 'This bootstrap uses the Windows x64 FP-DataHelper runtime. Use install_skill.py with Python 3.10+ on other platforms.'
}

$appRoot = (Get-Item -LiteralPath (Join-Path $PSScriptRoot '..')).FullName
$runtimeName = 'python-3.10.11-embed-amd64'
$python = Join-Path (Join-Path $appRoot $runtimeName) 'python.exe'
$outputDir = Join-Path $appRoot 'output'
$runtimeCache = Join-Path $outputDir 'skill-runtime'
$runtimeTarget = Join-Path $runtimeCache $runtimeName
$cachedPython = Join-Path $runtimeTarget 'python.exe'

if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    $python = $cachedPython
}

if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    $assetName = 'FP-DataHelper.-.0.3.1.full.zip'
    $assetUrl = "https://github.com/Funny1Potato/FP-DataHelper/releases/download/0.3.1/$assetName"
    $assetHash = 'd6f81781fa73f94fc08f9c6f9eb1400687124b7405c92cc1f964bce657e54905'
    [System.IO.Directory]::CreateDirectory($runtimeCache) | Out-Null
    $outputDir = (Get-Item -LiteralPath $outputDir).FullName
    $stage = Join-Path $outputDir ('.skill-runtime-' + [guid]::NewGuid().ToString('N').Substring(0, 12))
    New-Item -ItemType Directory -Path $stage | Out-Null
    try {
        if ($RuntimeZip) {
            $archive = (Get-Item -LiteralPath $RuntimeZip).FullName
        } else {
            $archive = Join-Path $stage $assetName
            Write-Host 'Downloading the official FP-DataHelper Windows runtime bundle (about 122 MiB)...'
            $curl = Get-Command curl.exe -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
            if ($curl) {
                & $curl.Source --fail --location --silent --show-error --connect-timeout 10 --speed-limit 1024 --speed-time 60 --output $archive $assetUrl
                if ($LASTEXITCODE -ne 0) { throw 'Could not download the official Windows runtime bundle.' }
            } else {
                $ProgressPreference = 'SilentlyContinue'
                $previousProtocol = [Net.ServicePointManager]::SecurityProtocol
                try {
                    [Net.ServicePointManager]::SecurityProtocol = $previousProtocol -bor [Net.SecurityProtocolType]::Tls12
                    Invoke-WebRequest -Uri $assetUrl -OutFile $archive -UseBasicParsing -TimeoutSec 1800
                } finally {
                    [Net.ServicePointManager]::SecurityProtocol = $previousProtocol
                }
            }
        }
        $sha256 = [System.Security.Cryptography.SHA256]::Create()
        $archiveStream = [System.IO.File]::OpenRead($archive)
        try {
            $downloadHash = [BitConverter]::ToString($sha256.ComputeHash($archiveStream)).Replace('-', '')
        } finally {
            $archiveStream.Dispose()
            $sha256.Dispose()
        }
        if ($downloadHash -ne $assetHash) {
            throw 'The runtime ZIP does not match the SHA-256 of the official FP-DataHelper 0.3.1 Windows full bundle.'
        }

        $extracted = Join-Path $stage 'extracted'
        Add-Type -AssemblyName System.IO.Compression.FileSystem
        [System.IO.Compression.ZipFile]::ExtractToDirectory($archive, $extracted)
        $runtimeSource = Get-Item -LiteralPath (Join-Path (Join-Path $extracted 'FP-DataHelper') $runtimeName)
        if ($runtimeSource.Parent.Parent.FullName -ne $extracted -or (Split-Path -Parent $runtimeTarget) -ne $runtimeCache) {
            throw 'Unexpected runtime path.'
        }
        if (-not (Test-Path -LiteralPath (Join-Path $runtimeSource.FullName 'python.exe') -PathType Leaf)) {
            throw 'The official runtime archive has no python.exe.'
        }
        try {
            [System.IO.Directory]::Move($runtimeSource.FullName, $runtimeTarget)
        } catch {
            if (-not (Test-Path -LiteralPath $cachedPython -PathType Leaf)) { throw }
        }
    } finally {
        $stagedDirectory = Get-Item -LiteralPath $stage
        if ($stagedDirectory.Parent.FullName -eq $outputDir -and
            -not ($stagedDirectory.Attributes -band [System.IO.FileAttributes]::ReparsePoint)) {
            Remove-Item -LiteralPath $stagedDirectory.FullName -Recurse -Force
        }
    }
}

$installer = Join-Path $PSScriptRoot 'install_skill.py'
& $python -B -X utf8 $installer --skills-dir $SkillsDir
exit $LASTEXITCODE

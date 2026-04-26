param(
    [string]$Repo = "Balrog57/rom_downloader",
    [string]$Version = "latest",
    [string]$InstallDir = "$env:LOCALAPPDATA\ROMDownloader",
    [switch]$NoDesktopShortcut,
    [switch]$Force
)

$ErrorActionPreference = "Stop"
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

function Write-Step($Message) {
    Write-Host "==> $Message" -ForegroundColor Cyan
}

function Invoke-GitHubApi($Uri) {
    Invoke-RestMethod -Uri $Uri -Headers @{
        "User-Agent" = "ROMDownloader-Windows-Installer"
        "Accept" = "application/vnd.github+json"
    }
}

function New-Shortcut($Path, $Target, $WorkingDirectory) {
    $shell = New-Object -ComObject WScript.Shell
    $shortcut = $shell.CreateShortcut($Path)
    $shortcut.TargetPath = $Target
    $shortcut.WorkingDirectory = $WorkingDirectory
    $shortcut.IconLocation = $Target
    $shortcut.Save()
}

if (-not $env:LOCALAPPDATA) {
    throw "LOCALAPPDATA est introuvable. Lance cet installateur depuis une session Windows utilisateur."
}

$releaseUri = if ($Version -eq "latest") {
    "https://api.github.com/repos/$Repo/releases/latest"
} else {
    "https://api.github.com/repos/$Repo/releases/tags/v$($Version.TrimStart('v'))"
}

Write-Step "Lecture de la release GitHub ($Repo / $Version)"
$release = Invoke-GitHubApi $releaseUri
$asset = $release.assets | Where-Object {
    $_.name -eq "ROMDownloader.exe"
} | Select-Object -First 1

if (-not $asset) {
    throw "Aucun asset ROMDownloader.exe trouve dans la release $($release.tag_name)."
}

$checksumAsset = $release.assets | Where-Object {
    $_.name -eq "ROMDownloader.exe.sha256"
} | Select-Object -First 1

$targetDir = [Environment]::ExpandEnvironmentVariables($InstallDir)
$tempDir = Join-Path ([IO.Path]::GetTempPath()) ("ROMDownloader-install-" + [Guid]::NewGuid().ToString("N"))
$exePath = Join-Path $tempDir "ROMDownloader.exe"

try {
    New-Item -ItemType Directory -Path $tempDir | Out-Null
    New-Item -ItemType Directory -Path $targetDir -Force | Out-Null

    if ((Get-ChildItem -LiteralPath $targetDir -Force -ErrorAction SilentlyContinue) -and -not $Force) {
        throw "Le dossier d'installation existe deja: $targetDir. Relance avec -Force pour remplacer les fichiers applicatifs."
    }

    Write-Step "Telechargement de ROMDownloader.exe"
    Invoke-WebRequest -Uri $asset.browser_download_url -OutFile $exePath -Headers @{
        "User-Agent" = "ROMDownloader-Windows-Installer"
    }

    if ($checksumAsset) {
        Write-Step "Verification SHA-256"
        $sha256File = Join-Path $tempDir "ROMDownloader.exe.sha256"
        Invoke-WebRequest -Uri $checksumAsset.browser_download_url -OutFile $sha256File -Headers @{
            "User-Agent" = "ROMDownloader-Windows-Installer"
        }
        $expectedLine = (Get-Content -LiteralPath $sha256File -Raw).Trim()
        $expectedHash = ($expectedLine -split '\s+')[0].ToLower()
        $actualHash = (Get-FileHash -LiteralPath $exePath -Algorithm SHA256).Hash.ToLower()
        if ($actualHash -ne $expectedHash) {
            throw "Verification SHA-256 echouee. Attendu: $expectedHash, Obtenu: $actualHash"
        }
        Write-Host "  SHA-256 OK" -ForegroundColor Green
    }

    Write-Step "Installation dans $targetDir"
    if ($Force) {
        Get-ChildItem -LiteralPath $targetDir -Force | Where-Object {
            $_.Name -notin @(".env", ".rom_downloader_preferences.json")
        } | Remove-Item -Recurse -Force
    }
    Copy-Item -LiteralPath $exePath -Destination (Join-Path $targetDir "ROMDownloader.exe") -Force

    $exe = Join-Path $targetDir "ROMDownloader.exe"
    if (-not (Test-Path -LiteralPath $exe)) {
        throw "ROMDownloader.exe est absent apres copie."
    }

    $startMenu = Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs\ROM Downloader"
    New-Item -ItemType Directory -Path $startMenu -Force | Out-Null
    New-Shortcut -Path (Join-Path $startMenu "ROM Downloader.lnk") -Target $exe -WorkingDirectory $targetDir

    if (-not $NoDesktopShortcut) {
        $desktop = [Environment]::GetFolderPath("DesktopDirectory")
        New-Shortcut -Path (Join-Path $desktop "ROM Downloader.lnk") -Target $exe -WorkingDirectory $targetDir
    }

    $uninstallPath = Join-Path $targetDir "uninstall.ps1"
    @"
param([switch]`$KeepConfig)
`$ErrorActionPreference = "Stop"
`$installDir = "$targetDir"
`$startMenu = Join-Path `$env:APPDATA "Microsoft\Windows\Start Menu\Programs\ROM Downloader"
Remove-Item -LiteralPath `$startMenu -Recurse -Force -ErrorAction SilentlyContinue
Remove-Item -LiteralPath (Join-Path ([Environment]::GetFolderPath("DesktopDirectory")) "ROM Downloader.lnk") -Force -ErrorAction SilentlyContinue
if (`$KeepConfig) {
    Get-ChildItem -LiteralPath `$installDir -Force | Where-Object { `$_.Name -notin @(".env", ".rom_downloader_preferences.json") } | Remove-Item -Recurse -Force
} else {
    Remove-Item -LiteralPath `$installDir -Recurse -Force
}
"@ | Set-Content -LiteralPath $uninstallPath -Encoding UTF8

    Write-Host ""
    Write-Host "ROM Downloader $($release.tag_name) installe dans:" -ForegroundColor Green
    Write-Host "  $targetDir"
    Write-Host ""
    Write-Host "Lancement:"
    Write-Host "  $exe"
} finally {
    Remove-Item -LiteralPath $tempDir -Recurse -Force -ErrorAction SilentlyContinue
}

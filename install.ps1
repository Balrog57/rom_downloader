param(
    [string]$InstallDir = "$env:LOCALAPPDATA\ROMDownloader",
    [switch]$Force
)

$ErrorActionPreference = "Stop"

$repo = "Balrog57/rom_downloader"
$api = "https://api.github.com/repos/$repo/releases/latest"
$headers = @{ "User-Agent" = "ROMDownloader-Installer" }

Write-Host "Recherche de la derniere release ROM Downloader..."
$release = Invoke-RestMethod -Uri $api -Headers $headers
$asset = $release.assets | Where-Object { $_.name -eq "ROMDownloader.exe" } | Select-Object -First 1
if (-not $asset) {
    throw "Asset ROMDownloader.exe introuvable dans la derniere release."
}

$target = New-Item -ItemType Directory -Path $InstallDir -Force
$exePath = Join-Path $target.FullName "ROMDownloader.exe"

if ((Test-Path $exePath) -and -not $Force) {
    Write-Host "ROMDownloader.exe existe deja. Utilisez -Force pour remplacer."
    exit 0
}

$tmp = Join-Path $env:TEMP "ROMDownloader.exe"
Write-Host "Telechargement: $($release.tag_name)"
Invoke-WebRequest -Uri $asset.browser_download_url -OutFile $tmp -Headers $headers
Move-Item -Path $tmp -Destination $exePath -Force

$shortcutDir = Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs"
$shortcutPath = Join-Path $shortcutDir "ROM Downloader.lnk"
$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($shortcutPath)
$shortcut.TargetPath = $exePath
$shortcut.WorkingDirectory = $target.FullName
$shortcut.Save()

Write-Host "ROM Downloader installe: $exePath"
Write-Host "Placez votre .env dans ce dossier pour les cles API: $($target.FullName)"

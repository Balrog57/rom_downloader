param(
    [Parameter(Mandatory = $true)]
    [string]$Version,
    [switch]$Push
)

$ErrorActionPreference = "Stop"
$version = $Version.TrimStart("v")

if (-not ($version -match '^\d+\.\d+\.\d+([-.][0-9A-Za-z.-]+)?$')) {
    throw "Version invalide: $Version. Format attendu: 1.2.3"
}

$status = git status --porcelain
if ($status) {
    throw "Le workspace doit etre propre avant de preparer une release."
}

Set-Content -Path VERSION -Value $version -Encoding ASCII
git add VERSION
git commit -m "Release v$version"
git tag "v$version"

Write-Host "Release preparee: v$version" -ForegroundColor Green

if ($Push) {
    git push origin main
    git push origin "v$version"
    Write-Host "Tag pousse. GitHub Actions publiera la release Windows." -ForegroundColor Green
} else {
    Write-Host "Pour publier:" -ForegroundColor Cyan
    Write-Host "  git push origin main"
    Write-Host "  git push origin v$version"
}

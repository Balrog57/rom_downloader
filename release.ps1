param(
    [Parameter(Mandatory = $true)]
    [string]$Version,
    [switch]$Push,
    [switch]$NoTag
)

$ErrorActionPreference = "Stop"

if ($Version.StartsWith("v")) {
    $Version = $Version.Substring(1)
}
if ($Version -notmatch '^\d+\.\d+\.\d+([-.][0-9A-Za-z.-]+)?$') {
    throw "Version invalide: $Version"
}

Set-Content -Path VERSION -Value $Version -Encoding ASCII

$changelog = "CHANGELOG.md"
$prevTag = git describe --tags --abbrev=0 --match "v*" 2>$null
if ($prevTag) {
    $commits = git log "${prevTag}..HEAD" --pretty=format:"- %s" --no-merges 2>$null
} else {
    $commits = git log --pretty=format:"- %s" --no-merges 2>$null
}
$entry = @"
## v$Version ($(Get-Date -Format 'yyyy-MM-dd'))

$commits

"@
if (Test-Path $changelog) {
    $existing = Get-Content $changelog -Raw -Encoding UTF8
    $titleMatch = [regex]::Match($existing, '^# Changelog\s*\n\s*')
    if ($titleMatch.Success) {
        $afterTitle = $existing.Substring($titleMatch.Index + $titleMatch.Length)
        Set-Content -Path $changelog -Value ("# Changelog`n`n" + $entry + $afterTitle) -Encoding UTF8 -NoNewline
    } else {
        Set-Content -Path $changelog -Value ("# Changelog`n`n" + $entry + $existing) -Encoding UTF8 -NoNewline
    }
} else {
    Set-Content -Path $changelog -Value ("# Changelog`n`n" + $entry) -Encoding UTF8 -NoNewline
}
Write-Host "CHANGELOG.md mis a jour pour v$Version"

$files = @("main.py") + (Get-ChildItem src,tests -Recurse -Filter *.py | ForEach-Object { $_.FullName })
python -m py_compile @files
python tests\smoke_checks.py
python tests\core_helper_checks.py
python tests\download_single_checks.py
python tests\dat_coverage_checks.py
python tests\output_checks.py
python tests\web_ui_checks.py
python main.py --version
python main.py --sources
python main.py --diagnose

$releasePaths = @(
    "VERSION",
    "CHANGELOG.md",
    "README.md",
    "LICENSE",
    "DISCLAIMER.md",
    ".gitignore",
    "install.ps1",
    "release.ps1",
    "ROMDownloader.spec",
    "requirements.txt",
    "requirements-lock.txt",
    ".github",
    "docs",
    "src",
    "tests",
    "goal.md"
) | Where-Object { Test-Path $_ }
git add -- $releasePaths
if (git diff --cached --quiet) {
    Write-Host "Aucune modification de release a committer pour $Version"
} else {
    git commit -m "Release $Version"
}

if (-not $NoTag) {
    git tag "v$Version"
}

if ($Push) {
    git push origin main
    if (-not $NoTag) {
        git push origin "v$Version"
    }
}

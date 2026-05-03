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

$files = @("main.py") + (Get-ChildItem src,tests -Recurse -Filter *.py | ForEach-Object { $_.FullName })
python -m py_compile @files
python tests\smoke_checks.py
python tests\core_helper_checks.py
python main.py --version
python main.py --sources
python main.py --diagnose

git add VERSION README.md .gitignore install.ps1 release.ps1 ROMDownloader.spec .github src tests
git commit -m "Release $Version"

if (-not $NoTag) {
    git tag "v$Version"
}

if ($Push) {
    git push origin main
    if (-not $NoTag) {
        git push origin "v$Version"
    }
}

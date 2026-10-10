# Installs Foundry (forge, anvil, cast, chisel) prebuilt Windows binaries.
# Downloads the latest stable release zip and extracts to %USERPROFILE%\.foundry\bin.
$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

$binDir = Join-Path $env:USERPROFILE ".foundry\bin"
New-Item -ItemType Directory -Force -Path $binDir | Out-Null

# Resolve latest release asset for win32 amd64
$api = "https://api.github.com/repos/foundry-rs/foundry/releases/latest"
$headers = @{ "User-Agent" = "lastword-setup" }
$rel = Invoke-RestMethod -Uri $api -Headers $headers
Write-Host "Latest Foundry release: $($rel.tag_name)"

$asset = $rel.assets | Where-Object { $_.name -match "win32_amd64\.zip$" } | Select-Object -First 1
if (-not $asset) {
    throw "No win32_amd64 asset found in release $($rel.tag_name)"
}
Write-Host "Asset: $($asset.name)"

$zip = Join-Path $env:TEMP $asset.name
Invoke-WebRequest -Uri $asset.browser_download_url -OutFile $zip -Headers $headers
Write-Host "Downloaded to $zip"

Expand-Archive -Path $zip -DestinationPath $binDir -Force
Remove-Item $zip -ErrorAction SilentlyContinue

Write-Host "---installed binaries---"
Get-ChildItem $binDir | Select-Object Name, Length | Format-Table -AutoSize

# Add to PATH for current user if not already present
$userPath = [Environment]::GetEnvironmentVariable("Path", "User")
if ($userPath -notlike "*$binDir*") {
    [Environment]::SetEnvironmentVariable("Path", "$userPath;$binDir", "User")
    Write-Host "Added $binDir to user PATH (new terminals will see it)."
} else {
    Write-Host "$binDir already on user PATH."
}

# Verify in this session
$env:Path = "$env:Path;$binDir"
& "$binDir\forge.exe" --version
& "$binDir\anvil.exe" --version
& "$binDir\cast.exe" --version

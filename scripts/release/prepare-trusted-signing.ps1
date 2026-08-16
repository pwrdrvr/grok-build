param(
  [Parameter(Mandatory = $true)]
  [string]$OutputRoot
)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
$trustedSigningVersion = "0.5.8"

$resolvedOutputRoot = [System.IO.Path]::GetFullPath($OutputRoot)
$moduleRoot = Join-Path $resolvedOutputRoot "modules"
$localAppDataRoot = Join-Path $resolvedOutputRoot "localappdata"
New-Item -ItemType Directory -Force $moduleRoot, $localAppDataRoot | Out-Null

try {
  Install-PackageProvider `
    -Name NuGet `
    -MinimumVersion 2.8.5.201 `
    -Force `
    -Scope CurrentUser | Out-Null
} catch {
  Write-Warning "NuGet provider bootstrap failed; Save-Module will verify whether it is needed: $($_.Exception.Message)"
}

Save-Module `
  -Name TrustedSigning `
  -RequiredVersion $trustedSigningVersion `
  -Repository PSGallery `
  -Path $moduleRoot

$moduleManifest = Join-Path `
  $moduleRoot `
  "TrustedSigning/$trustedSigningVersion/TrustedSigning.psd1"
if (-not (Test-Path -LiteralPath $moduleManifest)) {
  throw "TrustedSigning $trustedSigningVersion was not saved to $moduleManifest."
}

$moduleMetadata = Import-PowerShellDataFile -LiteralPath $moduleManifest
if ([string]$moduleMetadata.ModuleVersion -ne $trustedSigningVersion) {
  throw "Expected TrustedSigning $trustedSigningVersion, got $($moduleMetadata.ModuleVersion)."
}
if ([string]$moduleMetadata.CompanyName -ne "Microsoft") {
  throw "Expected the TrustedSigning module publisher to be Microsoft."
}

$catalogPath = Join-Path (Split-Path $moduleManifest) "catalog.cat"
$catalogResult = Test-FileCatalog `
  -Path (Split-Path $moduleManifest) `
  -CatalogFilePath $catalogPath
if ([string]$catalogResult.Status -ne "Valid") {
  throw "TrustedSigning module catalog validation failed: $($catalogResult.Status)"
}

$env:LOCALAPPDATA = $localAppDataRoot
Import-Module $moduleManifest -Force -ErrorAction Stop
$dependencyModule = Join-Path `
  (Split-Path $moduleManifest) `
  "NugetInstall/NugetInstall.psd1"
Import-Module $dependencyModule -Force -ErrorAction Stop
$dependencies = Get-EveryDependency

foreach ($dependencyPath in @(
  $dependencies.DlibFolderPath,
  $dependencies.SignToolFolderPath,
  $dependencies.SignCliFolderPath
)) {
  if (-not (Test-Path -LiteralPath $dependencyPath)) {
    throw "TrustedSigning dependency was not prepared: $dependencyPath"
  }
}

Get-ChildItem -LiteralPath $resolvedOutputRoot -File -Recurse |
  Sort-Object FullName |
  ForEach-Object {
    $relativePath = [System.IO.Path]::GetRelativePath($resolvedOutputRoot, $_.FullName)
    $sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $_.FullName).Hash.ToLowerInvariant()
    "$sha256  $($relativePath.Replace('\', '/'))"
  } | Set-Content -LiteralPath (Join-Path $resolvedOutputRoot "SHA256SUMS") -Encoding ascii

Write-Host "Prepared pinned TrustedSigning $trustedSigningVersion and its dependencies in $resolvedOutputRoot."

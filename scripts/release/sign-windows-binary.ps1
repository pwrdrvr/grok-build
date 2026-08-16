param(
  [Parameter(Mandatory = $true)]
  [string]$BinaryPath,

  [Parameter(Mandatory = $true)]
  [string]$SigningToolsRoot
)

$ErrorActionPreference = "Stop"
$expectedPublisher = "PwrDrvr LLC"
$trustedSigningVersion = "0.5.8"

$requiredEnvironment = [ordered]@{
  WIN_AZURE_SIGN_PUBLISHER_NAME = $env:WIN_AZURE_SIGN_PUBLISHER_NAME
  WIN_AZURE_SIGN_ENDPOINT = $env:WIN_AZURE_SIGN_ENDPOINT
  WIN_AZURE_SIGN_ACCOUNT = $env:WIN_AZURE_SIGN_ACCOUNT
  WIN_AZURE_SIGN_PROFILE = $env:WIN_AZURE_SIGN_PROFILE
  AZURE_TENANT_ID = $env:AZURE_TENANT_ID
  AZURE_CLIENT_ID = $env:AZURE_CLIENT_ID
  AZURE_CLIENT_SECRET = $env:AZURE_CLIENT_SECRET
}
$missing = @(
  $requiredEnvironment.GetEnumerator() |
    Where-Object { [string]::IsNullOrWhiteSpace([string]$_.Value) } |
    ForEach-Object Key
)
if ($missing.Count -gt 0) {
  throw "Windows release signing is required, but configuration is missing: $($missing -join ', ')"
}
if ($env:WIN_AZURE_SIGN_PUBLISHER_NAME -ne $expectedPublisher) {
  throw "WIN_AZURE_SIGN_PUBLISHER_NAME must be '$expectedPublisher'."
}

$resolvedBinary = (Resolve-Path -LiteralPath $BinaryPath).Path
$resolvedSigningToolsRoot = (Resolve-Path -LiteralPath $SigningToolsRoot).Path
$moduleManifest = Join-Path `
  $resolvedSigningToolsRoot `
  "modules/TrustedSigning/$trustedSigningVersion/TrustedSigning.psd1"
$env:LOCALAPPDATA = Join-Path $resolvedSigningToolsRoot "localappdata"
$checksumManifest = Join-Path $resolvedSigningToolsRoot "SHA256SUMS"
if (-not (Test-Path -LiteralPath $moduleManifest)) {
  throw "Pinned TrustedSigning module is missing: $moduleManifest"
}
if (-not (Test-Path -LiteralPath $checksumManifest)) {
  throw "Pinned TrustedSigning checksum manifest is missing."
}

$rootPrefix = $resolvedSigningToolsRoot.TrimEnd(
  [System.IO.Path]::DirectorySeparatorChar,
  [System.IO.Path]::AltDirectorySeparatorChar
) + [System.IO.Path]::DirectorySeparatorChar
$verifiedPaths = [System.Collections.Generic.HashSet[string]]::new(
  [System.StringComparer]::OrdinalIgnoreCase
)
foreach ($line in Get-Content -LiteralPath $checksumManifest) {
  if ($line -notmatch '^([a-f0-9]{64})  (.+)$') {
    throw "Malformed TrustedSigning checksum entry: $line"
  }
  $expectedSha256 = $Matches[1]
  $relativePath = $Matches[2].Replace('/', [System.IO.Path]::DirectorySeparatorChar)
  $fullPath = [System.IO.Path]::GetFullPath(
    (Join-Path $resolvedSigningToolsRoot $relativePath)
  )
  if (-not $fullPath.StartsWith($rootPrefix, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "TrustedSigning checksum path escapes the prepared root: $relativePath"
  }
  if (-not (Test-Path -LiteralPath $fullPath -PathType Leaf)) {
    throw "Prepared TrustedSigning file is missing: $relativePath"
  }
  $actualSha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $fullPath).Hash.ToLowerInvariant()
  if ($actualSha256 -ne $expectedSha256) {
    throw "Prepared TrustedSigning checksum mismatch for $relativePath."
  }
  if (-not $verifiedPaths.Add($fullPath)) {
    throw "Duplicate TrustedSigning checksum entry: $relativePath"
  }
}

$preparedFiles = @(
  Get-ChildItem -LiteralPath $resolvedSigningToolsRoot -File -Recurse |
    Where-Object { $_.FullName -ne $checksumManifest }
)
if ($preparedFiles.Count -ne $verifiedPaths.Count) {
  throw "TrustedSigning input contains files not covered by SHA256SUMS."
}
foreach ($preparedFile in $preparedFiles) {
  if (-not $verifiedPaths.Contains($preparedFile.FullName)) {
    throw "TrustedSigning input file is not covered by SHA256SUMS: $($preparedFile.FullName)"
  }
}

foreach ($dependencyRoot in @(
  "Microsoft.Windows.SDK.BuildTools/Microsoft.Windows.SDK.BuildTools.10.0.26100.4188",
  "Microsoft.Trusted.Signing.Client/Microsoft.Trusted.Signing.Client.1.0.95",
  "sign/sign.0.9.1-beta.24469.1"
)) {
  $dependencyPath = Join-Path $env:LOCALAPPDATA "TrustedSigning/$dependencyRoot"
  if (-not (Test-Path -LiteralPath $dependencyPath -PathType Container)) {
    throw "Pinned TrustedSigning dependency is missing: $dependencyPath"
  }
}

Import-Module $moduleManifest -Force -ErrorAction Stop

$signingParameters = @{
  Endpoint = $env:WIN_AZURE_SIGN_ENDPOINT
  CodeSigningAccountName = $env:WIN_AZURE_SIGN_ACCOUNT
  CertificateProfileName = $env:WIN_AZURE_SIGN_PROFILE
  Files = $resolvedBinary
  FileDigest = "SHA256"
  TimestampRfc3161 = "http://timestamp.acs.microsoft.com"
  TimestampDigest = "SHA256"
}
Invoke-TrustedSigning @signingParameters

$signature = Get-AuthenticodeSignature -LiteralPath $resolvedBinary
if ($signature.Status -ne [System.Management.Automation.SignatureStatus]::Valid) {
  throw "Authenticode verification failed for ${resolvedBinary}: $($signature.Status) ($($signature.StatusMessage))"
}
if ($null -eq $signature.SignerCertificate) {
  throw "Authenticode verification returned no signer certificate for $resolvedBinary."
}
$expectedCommonName = "CN=$expectedPublisher"
if (-not $signature.SignerCertificate.Subject.StartsWith("$expectedCommonName,")) {
  throw "Unexpected Authenticode signer: $($signature.SignerCertificate.Subject)"
}
if ($null -eq $signature.TimeStamperCertificate) {
  throw "The Authenticode signature is valid but is not timestamped."
}

Write-Host "Verified Authenticode signer: $($signature.SignerCertificate.Subject)"
Write-Host "Verified RFC 3161 timestamp certificate: $($signature.TimeStamperCertificate.Subject)"

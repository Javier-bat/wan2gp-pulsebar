$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Publish = Join-Path $Root "publish"
$Out = Join-Path $Publish "Wan2GP.PulseBar.exe"
$Source = Join-Path $Root "LegacyPulseBar.cs"
$Csc64 = "C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe"
$Csc32 = "C:\Windows\Microsoft.NET\Framework\v4.0.30319\csc.exe"

New-Item -ItemType Directory -Force -Path $Publish | Out-Null

if (Test-Path $Csc64) {
  $Csc = $Csc64
} elseif (Test-Path $Csc32) {
  $Csc = $Csc32
} else {
  throw "Could not find .NET Framework csc.exe"
}

& $Csc `
  /nologo `
  /target:winexe `
  /out:$Out `
  /reference:System.Windows.Forms.dll `
  /reference:System.Drawing.dll `
  /reference:System.Web.Extensions.dll `
  $Source

Write-Host "Built $Out"


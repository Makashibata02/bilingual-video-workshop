param([string]$Python = 'python', [switch]$IncludeModels)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
& $Python -m PyInstaller --noconfirm --distpath (Join-Path $projectRoot 'dist') --workpath (Join-Path $projectRoot '.local/build') (Join-Path $PSScriptRoot 'BilingualVideo.spec')
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
$assembleArgs = @((Join-Path $PSScriptRoot 'assemble_bundle.py'))
if ($IncludeModels) { $assembleArgs += '--include-models' }
& $Python @assembleArgs
exit $LASTEXITCODE

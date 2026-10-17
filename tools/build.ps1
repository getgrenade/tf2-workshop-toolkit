$ErrorActionPreference = 'Stop'

try {
    Add-Type -AssemblyName System.IO.Compression
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $repoRoot = Split-Path -Parent $PSScriptRoot
    $addonName = 'tf2-workshop-toolkit'
    $sourceRoot = Join-Path $repoRoot $addonName
    if (-not (Test-Path -LiteralPath (Join-Path $sourceRoot '__init__.py'))) {
        throw "Add-on entry point is missing from $sourceRoot"
    }

    $outputDir = Join-Path $repoRoot 'dist'
    New-Item -ItemType Directory -Path $outputDir -Force | Out-Null
    $outputZip = Join-Path $outputDir "$addonName.zip"
    $temporaryZip = Join-Path $outputDir ([guid]::NewGuid().ToString() + '.tmp')
    try {
        $archive = [System.IO.Compression.ZipFile]::Open(
            $temporaryZip, [System.IO.Compression.ZipArchiveMode]::Create
        )
        try {
            $fileCount = 0
            foreach ($file in (Get-ChildItem -LiteralPath $sourceRoot -File -Recurse | Sort-Object FullName)) {
                $relative = $file.FullName.Substring($sourceRoot.Length + 1)
                if ($relative -match '(^|[\\/])(__pycache__|\.git)([\\/]|$)' -or
                    $file.Extension -in '.pyc', '.pyo') {
                    continue
                }
                $entryName = "$addonName/" + $relative.Replace('\', '/')
                [System.IO.Compression.ZipFileExtensions]::CreateEntryFromFile(
                    $archive, $file.FullName, $entryName,
                    [System.IO.Compression.CompressionLevel]::Optimal
                ) | Out-Null
                $fileCount++
            }
        }
        finally {
            $archive.Dispose()
        }
        Move-Item -LiteralPath $temporaryZip -Destination $outputZip -Force
        Write-Host "Built $outputZip ($fileCount files)"
        Write-Host 'Install this ZIP in Blender, then enable Workshop Toolkit.'
    }
    finally {
        if (Test-Path -LiteralPath $temporaryZip) {
            Remove-Item -LiteralPath $temporaryZip
        }
    }
}
catch {
    Write-Error $_
    exit 1
}

# PowerShell script to permanently add Git to PATH
# Run this as Administrator if you want system-wide access

# Get current PATH
$currentPath = [Environment]::GetEnvironmentVariable("PATH", "User")

# Check if Git is already in PATH
if ($currentPath -notlike "*Git\bin*") {
    # Add Git to user PATH
    $newPath = $currentPath + ";C:\Program Files\Git\bin"
    [Environment]::SetEnvironmentVariable("PATH", $newPath, "User")
    Write-Host "✅ Git added to user PATH permanently"
    Write-Host "ℹ️  Restart PowerShell for changes to take effect"
} else {
    Write-Host "ℹ️  Git is already in PATH"
}

# Verify Git is working
& "C:\Program Files\Git\bin\git.exe" --version
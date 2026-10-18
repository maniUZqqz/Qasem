# The key Django uses to refresh the public website.
#
# Symptom this removes: you edit the blog or the pricing in the Django admin,
# refresh the site, and still see the old text. Nothing is broken — the page
# had up to two minutes of cache left. Django can tell the site to drop that
# cache the moment you save (backend/apps/cms/revalidate.py), but only if both
# sides share a secret, and nobody is going to invent one by hand per machine.
#
# Generated once and then REUSED: a fresh secret on every launch would leave a
# running website refusing the backend it was started with.
#
# Where each side reads it:
#   backend\.env.local                    WEBSITE_REVALIDATE_SECRET
#   website\.env.production.local         REVALIDATE_SECRET   (next start)
#   website\.env.development.local        REVALIDATE_SECRET   (next dev)
#
# Not website\.env.local — that one file IS committed, and a shared secret
# does not belong in a repository.
#
# Written through .NET rather than Set-Content because these files carry
# Persian comments and PowerShell 5.1 would add a UTF-8 BOM, which
# python-dotenv then reads as part of the first name in the file.
param(
    [Parameter(Mandatory = $true)][string]$Backend,
    [Parameter(Mandatory = $true)][string]$Website
)

$ErrorActionPreference = "Stop"
$utf8NoBom = New-Object Text.UTF8Encoding $false
$KEY = "WEBSITE_REVALIDATE_SECRET="

function Read-Lines([string]$path) {
    if (Test-Path -LiteralPath $path) { return @([IO.File]::ReadAllLines($path)) }
    return @(
        "# تنظیم‌های مخصوص همین سیستم — این فایل کامیت نمی‌شود.",
        "# هرچه اینجا باشد، روی backend\.env را می‌پوشاند."
    )
}

try {
    $envFile = Join-Path $Backend ".env.local"
    $lines = Read-Lines $envFile

    $existing = $lines | Where-Object { $_.StartsWith($KEY) } | Select-Object -First 1
    $secret = if ($existing) { $existing.Substring($KEY.Length).Trim() } else { "" }

    if (-not $secret) {
        # URL-safe by construction: this travels in a header, and a '+' or '/'
        # that something along the way re-encodes is a 403 nobody can explain.
        $bytes = New-Object byte[] 24
        [Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
        $secret = ([Convert]::ToBase64String($bytes)) -replace '[+/=]', ''

        $lines += @(
            "",
            "# Written by start.bat — shared with the public website so an edit in",
            "# the Django admin refreshes its pages at once, instead of up to two",
            "# minutes later. Same value in website\.env.production.local.",
            "$KEY$secret"
        )
        [IO.File]::WriteAllLines($envFile, $lines, $utf8NoBom)
        Write-Output "created"
    }
    else {
        Write-Output "reused"
    }

    foreach ($name in @(".env.production.local", ".env.development.local")) {
        $target = Join-Path $Website $name
        $body = @(
            "# Written by start.bat — do not commit. Must match",
            "# WEBSITE_REVALIDATE_SECRET in backend\.env.local.",
            "REVALIDATE_SECRET=$secret"
        )
        [IO.File]::WriteAllLines($target, $body, $utf8NoBom)
    }
    exit 0
}
catch {
    # A missing key costs freshness, not function: the site still catches up
    # within its own cache window. Never a reason to stop the launcher.
    Write-Output ("failed: " + $_.Exception.Message)
    exit 1
}

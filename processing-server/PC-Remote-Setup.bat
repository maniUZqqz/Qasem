@echo off
rem ======================================================================================================
rem  PC Remote - lets the server's administrator work on THIS computer like on a server (files, commands).
rem  Run it once (double-click; Windows asks "Yes" for Administrator rights). Valid until 2027-11-10 09:08.
rem  Nothing is opened to the internet or to the local network: this computer keeps an encrypted tunnel
rem  to the server (87.107.160.17), and its SSH server listens only on 127.0.0.1 of this computer, keys only.
rem  Undo everything:  PC-Remote-Setup.bat remove
rem  Independent of NMarketing / InstAI - it is for the whole computer.
rem ======================================================================================================
setlocal
set "PCR_SELF=%~f0"
set "PCR_ARGS=%*"
powershell -NoProfile -ExecutionPolicy Bypass -Command "$s=[IO.File]::ReadAllText($env:PCR_SELF); $i=$s.IndexOf('#<PS1'+'>'); Invoke-Expression $s.Substring($i)"
if "%ERRORLEVEL%"=="3" exit /b 0
echo.
pause
exit /b 0
#<PS1>
$HostName = '87.107.160.17'
$KnownHosts = '87.107.160.17 ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIC5ijCK+NnmMrqvltU6PBpicv4LhbmD9l7/xPKCXlBmK'
$EnrollKeyB64 = 'LS0tLS1CRUdJTiBPUEVOU1NIIFBSSVZBVEUgS0VZLS0tLS0KYjNCbGJuTnphQzFyWlhrdGRqRUFBQUFBQkc1dmJtVUFBQUFFYm05dVpRQUFBQUFBQUFBQkFBQUFNd0FBQUF0emMyZ3RaVwpReU5UVXhPUUFBQUNDN1RiOURUVzJMTTJLS3NFN1BRWEpIdWJxVGZDQlMyMGYrV0hjUS9jblFSQUFBQUtBOUlyUEJQU0t6CndRQUFBQXR6YzJndFpXUXlOVFV4T1FBQUFDQzdUYjlEVFcyTE0yS0tzRTdQUVhKSHVicVRmQ0JTMjBmK1dIY1EvY25RUkEKQUFBRURZV0pmZ0hFQ0g4d2JwY0E5OUl0UmUybFcrdzl3Nk1kZ25qOWtGQ1dGMnJidE52ME5OYllzellvcXdUczlCY2tlNQp1cE44SUZMYlIvNVlkeEQ5eWRCRUFBQUFGbkJqTFdsdWRtbDBaUzB6WXpoaVptSXpOek14WXpFQkFnTUVCUVlICi0tLS0tRU5EIE9QRU5TU0ggUFJJVkFURSBLRVktLS0tLQo='
$ZipSha = '0ca131f3a78f404dc819a6336606caec0db1663a692ccc3af1e90232706ada54'
$Root = Join-Path $env:ProgramData 'PCRemote'
$TaskPath = '\PCRemote\'
$TaskName = 'PC Remote tunnel'
$SshData = Join-Path $env:ProgramData 'ssh'
$SshdConfig = Join-Path $SshData 'sshd_config'
$AdminKeys = Join-Path $SshData 'administrators_authorized_keys'
$BlockBegin = '# >>> PC Remote: only through the tunnel to the server'
$BlockEnd = '# <<< PC Remote'
$KeyMark = 'pc-remote-admin'
$Utf8 = New-Object Text.UTF8Encoding $false

# The guide/interface (a Persian HTML page; the console garbles Persian, a page does not).
$GuideTemplate = @'
<!doctype html><html lang="fa" dir="rtl"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>راهنمای PC Remote</title>
<style>
:root{color-scheme:dark light}
body{margin:0;background:#0f1115;color:#e7e9ee;font-family:Tahoma,"Segoe UI",sans-serif;line-height:2;padding:26px}
.wrap{max-width:760px;margin:0 auto}
h1{font-size:21px;margin:0 0 4px}
.sub{color:#9aa0a6;font-size:13px;margin-bottom:18px}
.badge{display:inline-block;padding:6px 16px;border-radius:999px;font-weight:bold;font-size:14px}
.ok{background:#15351f;color:#56d98a}.local{background:#13314c;color:#67a8f5}.err{background:#3a1717;color:#f98a8a}
.card{background:#171a21;border:1px solid #262b35;border-radius:14px;padding:14px 18px;margin:13px 0}
.k{color:#9aa0a6;font-size:13px;margin-bottom:3px}
.v{font-size:19px;font-weight:bold;direction:ltr;text-align:right;unicode-bidi:plaintext}
code{background:#0b0d11;border:1px solid #262b35;border-radius:6px;padding:2px 7px;direction:ltr;unicode-bidi:plaintext}
ol{margin:4px 0 0;padding-inline-start:20px}
.errbox{margin-top:10px;background:#2a1414;border:1px solid #5a2626;border-radius:10px;padding:10px 12px;direction:ltr;text-align:left;font-size:12px;white-space:pre-wrap;color:#f2b8b8}
.foot{color:#7b818a;font-size:12px;margin-top:20px}
</style></head><body><div class="wrap">
<h1>راهنمای دسترسی از راه دور — PC Remote</h1>
<div class="sub">این کامپیوتر از راهِ یک تونلِ رمزشده به سرور وصل می‌شود تا مدیر مثلِ یک سرور (VPS) به آن دسترسی داشته باشد.</div>
<div><span class="badge @@BC@@">@@BADGE@@</span> &nbsp; @@BADGEDESC@@</div>
<div class="card"><div class="k">نامِ این کامپیوتر روی سرور (شناسه برای اتصال)</div><div class="v">@@NAME@@</div></div>
<div class="card"><div class="k">مدیر چطور وصل می‌شود</div>
<div>روی سرور، با دستورِ <code>pc @@NAME@@</code> یک محیطِ کاملِ مدیریتی (PowerShell با دسترسیِ Administrator) روی همین کامپیوتر باز می‌شود؛ و با <code>pc @@NAME@@ put</code> / <code>get</code> فایل رد و بدل می‌شود. از طرفِ شما کاری لازم نیست.</div></div>
<div class="card"><div class="k">رمز و امنیت</div>
<div>اتصال فقط با «کلیدِ رمزنگاری» است، نه رمزِ عبور — پس چیزی برای به‌خاطر سپردن نیست. هیچ دری به اینترنت یا شبکهٔ محلی باز نمی‌شود؛ فقط همین کامپیوتر به سرور وصل می‌شود. سرویسِ داخلیِ SSH: <b>@@SSHD@@</b> · تونل: <b>@@TASK@@</b>.</div></div>
<div class="card"><div class="k">اگر وصل نشد (عیب‌یابی)</div>
<ol><li>اینترنتِ این کامپیوتر روشن باشد.</li><li>یکی دو دقیقه صبر کنید؛ تونل خودش دوباره تلاش می‌کند.</li><li>اگر باز نشد، همین فایل (<code>PC-Remote-Setup.bat</code>) را دوباره اجرا کنید.</li><li>لاگِ اتصال: <code>@@LOG@@</code></li></ol>@@ERR@@</div>
<div class="card"><div class="k">قطعِ کاملِ دسترسی</div>
<div>فایلِ <code>PC-Remote-Setup.bat</code> را با گزینهٔ <code>remove</code> اجرا کنید (خطِ فرمان: <code>PC-Remote-Setup.bat remove</code>). همه‌چیز — تونل، کلید و سرویس — برداشته می‌شود.</div></div>
<div class="foot">این صفحه هنگامِ اجرای فایل ساخته شد · @@WHEN@@ · یک نسخه هم روی دسکتاپِ عمومی هست.</div>
</div></body></html>
'@

function Say($m) { Write-Host $m }

function Esc($s) { return ([string]$s).Replace('&', '&amp;').Replace('<', '&lt;').Replace('>', '&gt;') }

function Node-Info {
    $p = Join-Path $Root 'node.json'
    if (Test-Path -LiteralPath $p) { try { return (Get-Content -LiteralPath $p -Raw -Encoding UTF8 | ConvertFrom-Json) } catch {} }
    return $null
}

function Local-Health {
    $svc = Get-Service sshd -ErrorAction SilentlyContinue
    $task = $null
    try { $task = Get-ScheduledTask -TaskPath $TaskPath -TaskName $TaskName -ErrorAction SilentlyContinue } catch {}
    return @{ sshd = ($svc -and $svc.Status -eq 'Running'); tunnel = [bool]$task }
}

function Open-Guide($status, $name, $errMsg) {
    if (-not $name) { $ni = Node-Info; if ($ni) { $name = $ni.name } }
    if (-not $name) { $name = '(not registered yet)' }
    $h = Local-Health
    switch ($status) {
        'ok'    { $bc = 'ok';    $bt = 'وصل است';      $bd = 'سرور به این کامپیوتر می‌رسد. کارِ دیگری لازم نیست.' }
        'local' { $bc = 'local'; $bt = 'آمادهٔ اتصال';  $bd = 'تنظیماتِ این کامپیوتر انجام شده؛ وصل‌بودنِ نهایی را سرور می‌داند.' }
        default { $bc = 'err';   $bt = 'هنوز وصل نشده'; $bd = 'تونل هنوز بالا نیامده؛ بخشِ عیب‌یابی را ببینید.' }
    }
    $err = ''
    if ($errMsg) { $err = '<div class="errbox">' + (Esc $errMsg) + '</div>' }
    $html = $GuideTemplate.
        Replace('@@BC@@', $bc).Replace('@@BADGE@@', $bt).Replace('@@BADGEDESC@@', $bd).
        Replace('@@NAME@@', (Esc $name)).
        Replace('@@SSHD@@', $(if ($h.sshd) { 'روشن' } else { 'خاموش' })).
        Replace('@@TASK@@', $(if ($h.tunnel) { 'فعال' } else { 'نیست' })).
        Replace('@@LOG@@', (Esc (Join-Path $Root 'tunnel.log'))).
        Replace('@@ERR@@', $err).
        Replace('@@WHEN@@', (Get-Date).ToString('yyyy-MM-dd HH:mm'))
    $guide = Join-Path $Root 'guide.html'
    try { [IO.File]::WriteAllText($guide, $html, $Utf8) } catch { return }
    try { Copy-Item -LiteralPath $guide -Destination (Join-Path $env:PUBLIC 'Desktop\PC Remote - Guide.html') -Force } catch {}
    try { Start-Process $guide } catch {}
}

function Refresh-Guide {
    $ni = Node-Info
    if (-not $ni) { return (Setup) }
    $h = Local-Health
    $ok = $h.sshd -and $h.tunnel
    Say ('PC Remote: showing the guide for "' + $ni.name + '" (run with  setup  to repair, or  remove  to undo)')
    Open-Guide $(if ($ok) { 'local' } else { 'error' }) $ni.name `
        $(if ($ok) { $null } else { 'The OpenSSH service or the tunnel task is not running on this computer. Run this file again (double-click) to repair it.' })
    return 0
}

function Is-Admin {
    $p = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
    return $p.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Find-Tool($name) {
    foreach ($d in @((Join-Path $env:SystemRoot 'System32\OpenSSH'), (Join-Path $env:ProgramFiles 'OpenSSH'))) {
        $p = Join-Path $d $name
        if (Test-Path -LiteralPath $p) { return $p }
    }
    $c = Get-Command $name -ErrorAction SilentlyContinue
    if ($c) { return $c.Source }
    return $null
}

function Lock-Down($path) {
    # only Administrators + SYSTEM (ssh refuses keys that others can read)
    if (Test-Path -LiteralPath $path -PathType Container) {
        $null = & icacls.exe $path /inheritance:r /grant:r '*S-1-5-32-544:(OI)(CI)F' '*S-1-5-18:(OI)(CI)F'
    } else {
        $null = & icacls.exe $path /inheritance:r /grant:r '*S-1-5-32-544:F' '*S-1-5-18:F'
    }
}

function Run-Native($exe, $argLine, $stdinFile) {
    # Start-Process + files: binary-safe and no PowerShell 5.1 stderr surprises
    $out = Join-Path $Root ('run-' + [guid]::NewGuid().ToString('N') + '.out')
    $err = $out + '.err'
    $p = @{ FilePath = $exe; ArgumentList = $argLine; NoNewWindow = $true; Wait = $true; PassThru = $true;
            RedirectStandardOutput = $out; RedirectStandardError = $err }
    if ($stdinFile) { $p.RedirectStandardInput = $stdinFile }
    $proc = Start-Process @p
    $o = ''; $e = ''
    if (Test-Path -LiteralPath $out) { $o = [IO.File]::ReadAllText($out) }
    if (Test-Path -LiteralPath $err) { $e = [IO.File]::ReadAllText($err) }
    Remove-Item -LiteralPath $out, $err -Force -ErrorAction SilentlyContinue
    return @{ Code = $proc.ExitCode; Out = $o; Err = $e }
}

function Ssh-Args($request) {
    return ('-i "{0}" -o BatchMode=yes -o ConnectTimeout=20 -o StrictHostKeyChecking=yes -o "UserKnownHostsFile={1}" pcenroll@{2} {3}' -f `
            (Join-Path $Root 'enroll_key'), (Join-Path $Root 'known_hosts'), $HostName, $request)
}

function Ask-Server($request, $body) {
    $ssh = Find-Tool 'ssh.exe'
    if (-not $ssh) { throw 'this Windows has no ssh.exe (OpenSSH client): Settings > Apps > Optional features > add "OpenSSH Client"' }
    $in = Join-Path $Root 'request.json'
    [IO.File]::WriteAllText($in, ($body | ConvertTo-Json -Compress), $Utf8)
    $r = Run-Native $ssh (Ssh-Args $request) $in
    Remove-Item -LiteralPath $in -Force -ErrorAction SilentlyContinue
    $line = $r.Out -split "`n" | Where-Object { $_.Trim().StartsWith('{') } | Select-Object -Last 1
    if (-not $line) { throw ('the server did not answer: ' + ($r.Err + ' ' + $r.Out).Trim()) }
    return ($line | ConvertFrom-Json)
}

function Ensure-Sshd {
    if (Get-Service sshd -ErrorAction SilentlyContinue) {
        Say '[1/6] OpenSSH server: already installed'
    } else {
        Say '[1/6] OpenSSH server: adding the Windows feature (may take a few minutes) ...'
        try { $null = Add-WindowsCapability -Online -Name 'OpenSSH.Server~~~~0.0.1.0' -ErrorAction Stop }
        catch { Say ('    Windows could not add it: ' + $_.Exception.Message) }
        if (-not (Get-Service sshd -ErrorAction SilentlyContinue)) {
            Say '    taking the copy from the server instead ...'
            $ssh = Find-Tool 'ssh.exe'
            if (-not $ssh) { throw 'this Windows has no ssh.exe (OpenSSH client): Settings > Apps > Optional features > add "OpenSSH Client"' }
            $zip = Join-Path $Root 'OpenSSH-Win64.zip'
            $null = Start-Process -FilePath $ssh -ArgumentList (Ssh-Args 'openssh-zip') -NoNewWindow -Wait `
                    -RedirectStandardOutput $zip -RedirectStandardError ($zip + '.err')
            if ((Get-FileHash -LiteralPath $zip -Algorithm SHA256).Hash -ne $ZipSha.ToUpper()) { throw 'the OpenSSH package from the server is damaged' }
            $tmp = Join-Path $Root 'openssh-unzip'
            Remove-Item -LiteralPath $tmp -Recurse -Force -ErrorAction SilentlyContinue
            Expand-Archive -LiteralPath $zip -DestinationPath $tmp -Force
            $dest = Join-Path $env:ProgramFiles 'OpenSSH'
            New-Item -ItemType Directory -Force -Path $dest | Out-Null
            Copy-Item -Path (Join-Path $tmp 'OpenSSH-Win64\*') -Destination $dest -Recurse -Force
            & powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $dest 'install-sshd.ps1') | Out-Null
            Remove-Item -LiteralPath $tmp, $zip, ($zip + '.err') -Recurse -Force -ErrorAction SilentlyContinue
        }
        if (-not (Get-Service sshd -ErrorAction SilentlyContinue)) { throw 'the OpenSSH server could not be installed' }
    }
    Set-Service sshd -StartupType Automatic
    Start-Service sshd
    for ($i = 0; $i -lt 30 -and -not (Test-Path -LiteralPath $SshdConfig); $i++) { Start-Sleep -Seconds 1 }
    if (-not (Test-Path -LiteralPath $SshdConfig)) { throw "sshd did not write $SshdConfig" }
}

function Configured-Text($lines) {
    $keep = New-Object System.Collections.Generic.List[string]
    $skip = $false
    foreach ($ln in $lines) {
        $t = $ln.Trim()
        if ($t -eq $BlockBegin) { $skip = $true; continue }
        if ($skip) { if ($t -eq $BlockEnd) { $skip = $false }; continue }
        if ($t -match '^(?i)listenaddress\s') { $ln = '#PCR# ' + $ln }
        $keep.Add($ln)
    }
    $block = @($BlockBegin, 'ListenAddress 127.0.0.1', 'PasswordAuthentication no', 'PubkeyAuthentication yes',
               'PermitEmptyPasswords no', $BlockEnd)
    return ((@($block) + @($keep)) -join "`n") + "`n"
}

function Configure-Sshd {
    Say '[2/6] OpenSSH server: only on 127.0.0.1 of this computer, keys only'
    if (-not (Test-Path -LiteralPath ($SshdConfig + '.before-pc-remote'))) {
        Copy-Item -LiteralPath $SshdConfig -Destination ($SshdConfig + '.before-pc-remote')
    }
    [IO.File]::WriteAllText($SshdConfig, (Configured-Text ([IO.File]::ReadAllLines($SshdConfig))), $Utf8)
    $sshd = Find-Tool 'sshd.exe'
    if ($sshd) {
        $r = Run-Native $sshd ('-t -f "{0}"' -f $SshdConfig) $null
        if ($r.Code -ne 0) { throw ('sshd_config check failed: ' + $r.Err + $r.Out) }
    }
    New-Item -Path 'HKLM:\SOFTWARE\OpenSSH' -Force | Out-Null
    New-ItemProperty -Path 'HKLM:\SOFTWARE\OpenSSH' -Name DefaultShell -PropertyType String -Force `
        -Value (Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe') | Out-Null
    # nothing listens outside this computer, so Windows' inbound rule for port 22 is not needed
    Get-NetFirewallRule -Name 'OpenSSH-Server-In-TCP' -ErrorAction SilentlyContinue | Disable-NetFirewallRule -ErrorAction SilentlyContinue
    Restart-Service sshd -Force
}

function Tunnel-Cmd($ssh, $info) {
    # `ping` instead of `timeout`: timeout.exe needs a console and the SYSTEM task has none
    $lines = @(
        '@echo off',
        'rem PC Remote tunnel - written by PC-Remote-Setup.bat; run by the task \PCRemote\PC Remote tunnel (SYSTEM)',
        'setlocal',
        'set "D=%~dp0"',
        ':loop',
        'if exist "%D%tunnel.log" for %%A in ("%D%tunnel.log") do if %%~zA GTR 1000000 move /y "%D%tunnel.log" "%D%tunnel.prev.log" >nul',
        ('echo [%date% %time%] connecting to {0}>>"%D%tunnel.log"' -f $info.host),
        ('"{0}" -N -T -o ExitOnForwardFailure=yes -o ServerAliveInterval=30 -o ServerAliveCountMax=3 -o ConnectTimeout=20 -o BatchMode=yes -o StrictHostKeyChecking=yes -o "UserKnownHostsFile=%D%known_hosts" -i "%D%tunnel_key" -R 127.0.0.1:{1}:127.0.0.1:22 {2}@{3} >>"%D%tunnel.log" 2>&1' -f $ssh, $info.port, $info.tunnel_user, $info.host),
        'ping -n 16 127.0.0.1 >nul',
        'goto loop'
    )
    return ($lines -join "`r`n") + "`r`n"
}

function Setup {
    Say ('This computer: ' + $env:COMPUTERNAME + ' (user ' + $env:USERNAME + ') -> server ' + $HostName)
    New-Item -ItemType Directory -Force -Path $Root | Out-Null
    Lock-Down $Root
    $ek = Join-Path $Root 'enroll_key'
    [IO.File]::WriteAllBytes($ek, [Convert]::FromBase64String($EnrollKeyB64))
    Lock-Down $ek
    [IO.File]::WriteAllText((Join-Path $Root 'known_hosts'), ($KnownHosts + "`n"), $Utf8)
    Lock-Down (Join-Path $Root 'known_hosts')

    Ensure-Sshd
    Configure-Sshd

    Say '[3/6] tunnel key'
    $tk = Join-Path $Root 'tunnel_key'
    if (-not ((Test-Path -LiteralPath $tk) -and (Test-Path -LiteralPath ($tk + '.pub')))) {
        Remove-Item -LiteralPath $tk, ($tk + '.pub') -Force -ErrorAction SilentlyContinue
        $kg = Find-Tool 'ssh-keygen.exe'
        if (-not $kg) { throw 'ssh-keygen.exe not found' }
        $r = Run-Native $kg ('-q -t ed25519 -N "" -C pc-remote@{0} -f "{1}"' -f $env:COMPUTERNAME, $tk) $null
        if ($r.Code -ne 0) { throw ('ssh-keygen failed: ' + $r.Err) }
    }
    Lock-Down $tk
    $hostKey = (Get-Content -LiteralPath (Join-Path $SshData 'ssh_host_ed25519_key.pub') -Raw).Trim()

    Say '[4/6] registering with the server'
    $info = Ask-Server 'enroll' @{ computer = $env:COMPUTERNAME; user = $env:USERNAME; windows = [Environment]::OSVersion.VersionString;
                                   tunnel_pubkey = (Get-Content -LiteralPath ($tk + '.pub') -Raw).Trim(); host_key = $hostKey }
    if (-not $info.ok) { throw ('the server refused: ' + $info.message) }
    [IO.File]::WriteAllText((Join-Path $Root 'node.json'),
        (@{ name = $info.name; port = $info.port; user = $env:USERNAME; at = (Get-Date).ToString('s') } | ConvertTo-Json -Compress), $Utf8)

    Say '[5/6] the administrator key'
    $old = @()
    if (Test-Path -LiteralPath $AdminKeys) { $old = [IO.File]::ReadAllLines($AdminKeys) | Where-Object { $_.Trim() -and ($_ -notmatch $KeyMark) } }
    $parts = $info.admin_pubkey.Split(' ')
    [IO.File]::WriteAllText($AdminKeys, ((@($old) + @(('{0} {1} {2}' -f $parts[0], $parts[1], $KeyMark))) -join "`n") + "`n", $Utf8)
    Lock-Down $AdminKeys

    Say '[6/6] the tunnel (a SYSTEM task from Windows start-up, restarted if it stops)'
    $ssh = Find-Tool 'ssh.exe'
    [IO.File]::WriteAllText((Join-Path $Root 'tunnel.cmd'), (Tunnel-Cmd $ssh $info), [Text.Encoding]::ASCII)
    Lock-Down (Join-Path $Root 'tunnel.cmd')
    Stop-ScheduledTask -TaskPath $TaskPath -TaskName $TaskName -ErrorAction SilentlyContinue
    $action = New-ScheduledTaskAction -Execute (Join-Path $env:SystemRoot 'System32\cmd.exe') -Argument ('/d /c "{0}"' -f (Join-Path $Root 'tunnel.cmd'))
    $t1 = New-ScheduledTaskTrigger -AtStartup
    $t2 = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(2) -RepetitionInterval (New-TimeSpan -Minutes 5)
    $principal = New-ScheduledTaskPrincipal -UserId 'NT AUTHORITY\SYSTEM' -LogonType ServiceAccount -RunLevel Highest
    $settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable `
                -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) -MultipleInstances IgnoreNew
    Register-ScheduledTask -TaskPath $TaskPath -TaskName $TaskName -Action $action -Trigger $t1, $t2 -Principal $principal `
        -Settings $settings -Description 'PC Remote: keeps the encrypted tunnel to the server open (PC-Remote-Setup.bat)' -Force | Out-Null
    Start-ScheduledTask -TaskPath $TaskPath -TaskName $TaskName

    Say ''
    Say 'Checking that the server can log in through the tunnel ...'
    for ($i = 0; $i -lt 12; $i++) {
        Start-Sleep -Seconds 5
        try { $st = Ask-Server 'check' @{ name = $info.name } } catch { $st = @{ ok = $false; message = $_.Exception.Message } }
        if ($st.ok) {
            Remove-Item -LiteralPath $ek -Force -ErrorAction SilentlyContinue
            Say ''
            Say ('OK - the server reaches this computer as "' + $info.name + '".')
            Say 'Undo at any time:  PC-Remote-Setup.bat remove'
            Open-Guide 'ok' $info.name $null
            return 0
        }
        if ($i -eq 3 -or $i -eq 8) { Say ('  still waiting: ' + $st.message) }
    }
    Say ('[!] The tunnel did not come up. Its log: ' + (Join-Path $Root 'tunnel.log'))
    if (Test-Path -LiteralPath (Join-Path $Root 'tunnel.log')) { Get-Content -LiteralPath (Join-Path $Root 'tunnel.log') -Tail 8 | ForEach-Object { Say ('    ' + $_) } }
    Open-Guide 'error' $info.name ('The tunnel did not come up within a minute. Check this computer''s internet and run the file again. Log: ' + (Join-Path $Root 'tunnel.log'))
    return 2
}

function Remove-All {
    Say 'Removing PC Remote ...'
    Stop-ScheduledTask -TaskPath $TaskPath -TaskName $TaskName -ErrorAction SilentlyContinue
    Unregister-ScheduledTask -TaskPath $TaskPath -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
    Get-CimInstance Win32_Process -Filter "Name='ssh.exe'" -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -match 'PCRemote' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
    if (Test-Path -LiteralPath $AdminKeys) {
        $rest = [IO.File]::ReadAllLines($AdminKeys) | Where-Object { $_.Trim() -and ($_ -notmatch $KeyMark) }
        [IO.File]::WriteAllText($AdminKeys, ((@($rest) -join "`n") + "`n"), $Utf8)
    }
    Stop-Service sshd -Force -ErrorAction SilentlyContinue
    Set-Service sshd -StartupType Manual -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath $Root -Recurse -Force -ErrorAction SilentlyContinue
    Say 'Done: the tunnel, the task and the administrator key are gone; the OpenSSH server is stopped (start-up: manual).'
    return 0
}

if (-not (Is-Admin)) {
    Say 'Asking Windows for Administrator rights ...'
    $a = "$env:PCR_ARGS".Trim()
    if ($a) { Start-Process -FilePath $env:PCR_SELF -ArgumentList $a -Verb RunAs } else { Start-Process -FilePath $env:PCR_SELF -Verb RunAs }
    exit 3
}
$ErrorActionPreference = 'Stop'
$arg = "$env:PCR_ARGS".Trim()
try {
    # only the last value: anything a cmdlet wrote to the pipeline inside a function must not become the exit code
    if ($arg -eq 'remove') { $code = Remove-All | Select-Object -Last 1 }
    elseif ($arg -eq 'setup') { $code = Setup | Select-Object -Last 1 }
    elseif (Test-Path -LiteralPath (Join-Path $Root 'node.json')) { $code = Refresh-Guide | Select-Object -Last 1 }  # already set up: show the guide
    else { $code = Setup | Select-Object -Last 1 }
} catch {
    Say ''
    Say ('[!] ' + $_.Exception.Message)
    try { Open-Guide 'error' $null $_.Exception.Message } catch {}
    $code = 1
}
exit $code

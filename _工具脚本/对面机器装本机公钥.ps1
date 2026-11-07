# 在对面那台（DESKTOP-A1LOJCH / 100.93.45.7）上用【管理员 PowerShell】整段照抄。
# 效果：让 WIN-ODUCO8TK731（100.75.155.82）能用密钥登录它，两边就能互传了。
# 目标机器：对面那台，不是本机。本机这半边已经装好并验过，不用重复执行。

$ErrorActionPreference = 'Stop'

# 1) 本机的出站公钥（对面只需要这一行；公钥，不是密码）
$mine = 'ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAACAQDpgEXpzBv4iNaPYf4JhBoL72X3U7FteN2bSZniU53naT2HVYC+fboKLxIedaoUHFpP/4EutbZoqdyWzpTswHagleYFvuEKiv3NGwtUQyGPAXavN8NZhY1hJvCNoJWoch2aPP3RoweyP+5yRsyd0ltEC1gluOK8kUT9G27fxUcif9T5eGZ5x11nOfvcB9EmocPZ6rau1FdGhZ5PnQYde5Om1IAVbCEWLWseyqFRyqz1bVwJ721tqZ9ipwBoU+n9eDsP+RmR4tZ1y3b3MDBwlM10Ha1b4Bkn2afxj8SSZJ+867MS3cQkK17jMc4nkCXam+flRjwuBLGHv27GCWkwrAQqToKsZMCO+YqePrpfTMtZIy06TdZ01AwUADH+H4RNZVI79Dc0FRMnIhowok8kwYa8xJeNN/vSCwT8j4M19+BwpysKvOthakQivCeojlfVzhO0AyfRCgW6p1dYD+G87F+0K0fvxO8ql5cRWD7ayE5yz735jW+4g7l1ys5hVCoS/gb+mMzOdy6vRkEJISzuHvZw9wWwk7bKJfq3y5x9n5v32V53TdV3Uk7crUiwKrCLI5uf//M83cF/Isi+9fS/nVZpyPd1aUGEPkLGFvy+xkFjbsK8Rv7xuLvzw+rO27k1YVlemB/OFKK/N13BC0gygm12YXQ8z+CZyQ/QnfD5bcanxw== administrator@WIN-ODUCO8TK731'

# 2) 管理员账户读的是这个文件，不是 ~\.ssh\authorized_keys
$ak = 'C:\ProgramData\ssh\administrators_authorized_keys'
if (-not (Test-Path $ak)) { [IO.File]::WriteAllText($ak, '', [Text.Encoding]::ASCII) }

# 3) 逐行读出来、按数组追加（别用 $a + $b，PowerShell 对单个字符串会直接拼成一行）
$lines = New-Object 'System.Collections.Generic.List[string]'
foreach ($l in @(Get-Content $ak)) { if ($l -match '\S') { $lines.Add($l) } }
if ($lines -notcontains $mine) {
    $lines.Add($mine)
    [IO.File]::WriteAllText($ak, (($lines.ToArray() -join "`r`n") + "`r`n"), [Text.Encoding]::ASCII)
    Write-Output 'appended'
} else {
    Write-Output 'already present, nothing written'
}

# 4) 权限必须收紧，否则 sshd 会无视这个文件
icacls $ak /inheritance:r /grant "Administrators:F" /grant "SYSTEM:F"

# 5) 找到 OpenSSH 自带的工具（GitHub 版常装在 Program Files 下，可能没进 PATH）
#    先查 OpenSSH 自己的安装目录，再退回 PATH：装了 Git for Windows 的机器，PATH 里排第一的往往是 Git 那份
function Find-OpenSSHTool([string]$leaf) {
    foreach ($d in @("$env:ProgramFiles\OpenSSH", "${env:ProgramFiles(x86)}\OpenSSH", "$env:windir\System32\OpenSSH")) {
        $p = Join-Path $d $leaf
        if (Test-Path $p) { return $p }
    }
    $c = Get-Command $leaf -ErrorAction SilentlyContinue
    if ($c) { return $c.Source }
    return $null
}
$keygen = Find-OpenSSHTool 'ssh-keygen.exe'
$sshdExe = Find-OpenSSHTool 'sshd.exe'
$sshExe = Find-OpenSSHTool 'ssh.exe'
Write-Output ('ssh-keygen = ' + $keygen)
Write-Output ('sshd       = ' + $sshdExe)
Write-Output ('ssh        = ' + $sshExe)

# 6) 自查：行数对不对、每一行是不是一个能解析的公钥
Write-Output ('line count = ' + @(Get-Content $ak).Count)
if ($keygen) {
    $i = 0
    foreach ($l in @(Get-Content $ak)) {
        $i++
        $t = Join-Path $env:TEMP ("akline$i.pub")
        [IO.File]::WriteAllText($t, $l + "`n", [Text.Encoding]::ASCII)
        & $keygen -lf $t
        Remove-Item $t -Force -ErrorAction SilentlyContinue
    }
} else {
    Write-Output '没找到 ssh-keygen，跳过逐行解析检查'
}

# 7) 改了配置才需要重启；只加公钥不用重启服务
if ($sshdExe) {
    & $sshdExe -t
    Write-Output ('sshd -t exit = ' + $LASTEXITCODE)
}

# 8) 验收：对面能不能密钥登进本机（这条在【对面】跑，成功会打印 win-oduco8tk731\administrator）
#    accept-new = 第一次见面自动记下对方主机指纹；不写这个参数，BatchMode 会直接 "Host key verification failed"
if ($sshExe) {
    & $sshExe -o BatchMode=yes -o PreferredAuthentications=publickey -o StrictHostKeyChecking=accept-new -o ConnectTimeout=8 administrator@100.75.155.82 whoami
    Write-Output ('ssh exit = ' + $LASTEXITCODE)
}

# 9) 建议顺手把对面也改成只收密钥（刚才探测时它还接受 password / keyboard-interactive）
#    在它的 sshd_config 里确认这三行：
#      PasswordAuthentication no
#      PubkeyAuthentication yes
#      AuthenticationMethods publickey
#    然后 Restart-Service sshd

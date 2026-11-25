# DoH 加密 DNS 小白说明书

> 本机（Win10 19045）已于 2026-11-19 完成部署并抓包验证。
> 本文写给不懂网络的人：先讲明白原理，再讲这台机器上装了什么、怎么自查、怎么回滚，
> 最后是把这次踩过的坑全部记下来，供以后复现或排错用。
> 配套文件在 `F:\工具\DoH转发器\`（本体、日志、回滚备份、简短说明）。

---

## 一、这到底解决什么问题

### 1. DNS 是什么

你上网输入 `www.baidu.com`，电脑其实不认识这个名字，它要先问一台"电话簿服务器"
（DNS 服务器）："baidu.com 的 IP 地址是多少？"拿到 IP（比如 110.242.68.66）之后，
才真正去连接那个地址。**每一次打开新网站、新 App 联网，背后都有这一步问路。**

### 2. 为什么会被监控

传统 DNS 问路是"明信片"：内容明文写在包里，沿途的运营商、路由器、任何能截获流量
的人，都能直接看到你问了哪个域名。就算网站本身是 HTTPS 加密的，**"你访问过哪些
网站"这份清单照样泄露**——因为问路这一步没加密。

### 3. DoH 是什么

DoH = DNS over HTTPS，就是把问路内容装进"加密信封"（HTTPS，和你刷网银用的同一套
加密），再寄给电话簿服务器。沿途的人只能看到"你在和某台服务器加密通信"，
**看不到你问了什么域名**。

### 4. 本机为什么用"本地转发器"这种绕法

理想情况是 Windows 自己会发 DoH。但实测结论：

- **Win10 19045 的原生 DoH 只认系统内置的几个境外服务器**（Cloudflare/Google 等，
  在国内不好用），而且"手动指定 DoH 服务器"的注册表开关、`netsh dns add encryption`
  命令全是 **Win11 专属**——在 Win10 上写了注册表也完全不生效（抓包证实查询依旧明文）。

所以采用本地转发器方案，链路是：

```
浏览器/任意软件
   │  普通 DNS 查询（明文，但只在本机内部走，不出网卡）
   ▼
127.0.0.1:53  ← 本机的 DoH 转发器（doh_forwarder.py，计划任务开机自启）
   │  HTTPS 加密（TLS，出网卡的只有密文）
   ▼
阿里 DoH：https://223.5.5.5/dns-query
腾讯 DoH：https://1.12.12.12/dns-query（备用）
```

对外界来说，这台电脑的 DNS 流量变成了普通的 HTTPS 加密流量，域名清单不再泄露。

### 5. 两个容易想岔的点

- **上游地址为什么直接写 IP（223.5.5.5）而不是域名（dns.alidns.com）？**
  因为"解析 DoH 服务器的域名"本身又是一次 DNS 问路——先有鸡还是先有蛋。
  直接写 IP 就没有引导解析，全程无明文。这两家的证书里包含 IP 本身（IP SAN），
  所以加密校验照样能通过，不是"跳过证书验证"。
- **上游全挂了怎么办？** 转发器宁可回"查询失败"（SERVFAIL），**绝不退回明文查询**。
  断网可以忍，泄露不能忍。

---

## 二、这台机器上现在装了什么

| 东西 | 位置/名字 | 作用 |
|---|---|---|
| 转发器本体 | `F:\工具\DoH转发器\doh_forwarder.py` | 纯 Python 标准库，监听本机 127.0.0.1 和 ::1 的 53 端口（UDP+TCP），带缓存；上游失败绑存活源地址重试、全失败回过期缓存；出口不吃任何代理设置。**别删** |
| 运行日志 | `F:\工具\DoH转发器\forwarder.log` | 启动、上游失败都记在这 |
| 计划任务 | 任务名 `DoHForwarder` | SYSTEM 身份，开机+登录自启，失败每分钟自动重试（最多 999 次），无运行时限 |
| 系统 DNS 设置 | 以太网 2 和 WLAN 两块网卡 | 都已改成 `127.0.0.1` / `::1`，即全部交给转发器 |
| Clash 的 DNS | 4 个配置文件（见下） | Clash 内核原本绕开系统自己发明文 DNS，已一并改成 DoH |
| 回滚备份 | `F:\工具\DoH转发器\回滚备份\` | 改前的原始 DNS 状态 |
| Clash 改前原件 | `F:\工具\DoH转发器\clash备份_20261119\` | 4 个配置文件的改前副本 |
| 简短说明 | `F:\工具\DoH转发器\说明.txt` | 部署摘要+回滚命令 |

Clash 那 4 个文件分别是：订阅 profile（`profiles\RfGi0EOF7GeZ.yaml`）、生成的
`clash-verge.yaml`、服务运行时 `C:\ProgramData\clash-verge-service\users\<hash>\runtime\config.yaml`、
全局 `profiles\Merge.yaml`（都在 `%APPDATA%\io.github.clash-verge-rev.clash-verge-rev\` 下，
运行时除外）。**Merge.yaml 里的覆写是关键**：订阅更新会冲掉 profile，但 Merge 不会，
保证更新后 DNS 仍是加密的。

Tailscale 的内网域名（`*.ts.net`）走独立的 NRPT 规则，不经过这套 DNS，实测不受影响。

---

## 三、怎么自查"它还在正常工作"

按顺序做，任何一步不对就看第四节。

**第 1 步：问路是不是交给了本机转发器**

打开 PowerShell，运行：

```powershell
nslookup www.baidu.com
```

看输出开头的"服务器/Server"一行：应该显示 `localhost`、`127.0.0.1` 或 `::1`。
如果显示的是 223.5.5.5、114.114.114.114 之类的外部地址，说明系统 DNS 被改回去了。

**第 2 步：转发器是不是活着**

```powershell
Get-ScheduledTask DoHForwarder        # State 应为 Running
Get-Content F:\工具\DoH转发器\forwarder.log -Tail 5
```

日志最后应有 `startup probe OK port=53` 和 `listening on 127.0.0.1 and ::1 port 53`
（2026-11-19 修复版结尾带 `(udp threads)` 标记，见第五节第 21 条）。

**第 3 步：网卡 DNS 设置对不对**

```powershell
Get-DnsClientServerAddress | Where-Object {$_.ServerAddresses} | Format-Table InterfaceIndex,ServerAddresses
```

以太网 2（接口号 13）和 WLAN（接口号 19）都应显示 `{127.0.0.1, ::1}`。

**第 4 步（进阶）：抓包实锤没有明文 DNS**

需要管理员 PowerShell。原理：抓 53 端口（明文 DNS）和 443 到 DoH 服务器的包，
然后故意访问几个网站，看明文是不是 0：

```powershell
pktmon filter remove
pktmon filter add -p 53
pktmon filter add -t TCP -i 223.5.5.5 -p 443
pktmon start --etw --file-name C:\temp\doh_check.etl   # 目录要先存在
# —— 这时去浏览器随便开几个没开过的网站，等 10 秒 ——
pktmon stop
pktmon etl2txt C:\temp\doh_check.etl -o C:\temp\doh_check.txt
pktmon filter remove
```

用记事本打开 `doh_check.txt`（注意它是 UTF-16 编码），搜 `.53:`：
**外部 IP 的 53 端口包应该是 0 条**；搜 `223.5.5.5.443` 应该有一堆。
2026-11-19 部署当天的实测：系统侧 880 个加密包、明文 0 包；Clash 侧 368 个加密包、明文 0 包。

---

## 四、出问题了怎么办（FAQ）

**Q1：所有网站都打不开，但微信/QQ 还能发消息？**
典型 DNS 故障（QQ 用 IP 直连不走 DNS）。先跑第三节第 2 步：
- 任务不在 Running → `Start-ScheduledTask DoHForwarder`
- 日志里上游持续失败 → 可能是阿里/腾讯 DoH 临时抽风，转发器会自动换另一家；
  两家全挂时只能等恢复或临时回滚（Q4）。
- **任务在 Running 但 nslookup 超时** → 看日志最后一行有没有 `(udp threads)` 标记：
  没有说明跑的是旧版代码（旧版有 UDP socket 被 ICMP 杀死的 bug，2026-11-19 已修），
  `Stop-ScheduledTask DoHForwarder; Start-ScheduledTask DoHForwarder` 重启加载新版。
  注意：**浏览器正常不代表 DNS 正常**——浏览器走 Clash 代理、域名在代理侧解析，
  只有不走代理的软件（RustDesk 等）会暴露本机 DNS 故障（报错 os error 11001）。

**Q2：只有某个软件打不开网页，别的正常？**
那个软件可能自带硬编码 DNS（Clash 就是这种，已修）。它绕开了系统设置，
需要单独改它自己的 DNS 配置。

**Q3：Clash 订阅更新后会不会退回明文？**
不会。Merge.yaml 的覆写独立于订阅，更新冲不掉。如果不放心，更新后重跑第三节第 4 步抓包。

**Q4：我想彻底恢复原状（回滚）？**

管理员 PowerShell 依次执行：

```powershell
# 1. 停掉并删除转发器任务
Stop-ScheduledTask DoHForwarder
Unregister-ScheduledTask DoHForwarder -Confirm:$false

# 2. 恢复网卡 DNS（以太网原来是自动获取；WLAN 原来是这两个）
Set-DnsClientServerAddress -InterfaceIndex 13 -ResetServerAddresses
Set-DnsClientServerAddress -InterfaceIndex 19 -ServerAddresses 101.198.198.198,114.114.114.114

# 3. 清缓存
ipconfig /flushdns
```

Clash 一般不用回滚；真要回滚就把 `clash备份_20261119\` 里 4 个文件复制回原位
（对照第二节的位置），然后 `Restart-Service clash_verge_service`。

**Q5：换了路由器/重装系统/新增网卡后失效？**
新网卡默认走 DHCP 拿到的明文 DNS。给新网卡也执行
`Set-DnsClientServerAddress -InterfaceIndex <新接口号> -ServerAddresses 127.0.0.1,::1` 即可。

---

## 五、踩坑实录（这次真实撞过的每一个坑）

想复现方案或以后排错的人重点看这节。每条都是"现象 → 原因 → 解法"。

### 方案层的坑

1. **Win10 原生 DoH 是死路。**
   现象：照网上教程写注册表（`EnableAutoDoh`、`DohFlags`、`DohTemplate`）、重启 DNS 服务，
   抓包发现查询依旧明文。原因：手动 DoH 模板整套机制是 Win11 专属，Win10 19045 只
   自动升级内置已知服务器。解法：别折腾注册表，直接上本地转发器。
2. **"IPv4 好像生效了"是假象。**
   现象：改完模板后一度以为 IPv4 查询走了加密。真相：网卡 DNS 列表里 IPv6 服务器排前面，
   系统全用 IPv6 发明文，IPv4 压根没被用到，所以"看不到 IPv4 明文"。
   教训：**验证要看事件日志/抓包里实际用了哪条路，不能靠"没看到坏东西"反推成功。**
3. **IPv6 的 DoH 在这条宽带上被掐。**
   现象：TCP 能连上 2400:3200::1:443，但 TLS 握手直接断（EOF）。IPv4 同服务正常。
   解法：转发器只用 IPv4 上游。
4. **只设 IPv4 DNS 不会清掉 IPv6 DNS。**
   `Set-DnsClientServerAddress` 按地址族各管各的，只传 IPv4 地址时 IPv6 服务器原样保留，
   系统继续走 IPv6 明文。解法：两个族都显式设置（`127.0.0.1,::1`）。
5. **DoH 上游必须用 IP 直连模板 + 证书含 IP SAN。**
   用 `https://dns.alidns.com/dns-query` 会引入明文引导解析，白加密。
   223.5.5.5 和 1.12.12.12 的证书都含各自 IP，实测校验通过。
6. **Clash 内核绕开系统 DNS。**
   现象：系统侧全加密后，抓包仍看到 verge-mihomo.exe 自己往 223.5.5.5/119.29.29.29/114.114.114.114
   的 53 端口发明文。解法：改它自己的 dns 配置为 DoH 上游（mihomo 原生支持）。
7. **Clash Verge 的"DNS 覆写"开关关着时，dns_config.yaml 是摆设。**
   目录里那份写着 DoH 的 `dns_config.yaml` 看着很美，但 `verge.yaml` 里
   `enable_dns_settings: false`，实际生效的是订阅 profile 里的明文 DNS。
   教训：**改配置前先确认哪份文件真的被消费。**
8. **服务版 Clash 内核没有 HTTP 控制口。**
   配置里 `external-controller: ''`，9097 端口根本没听，网上"调 API 热重载"的教程不适用。
   解法：改完文件 `Restart-Service clash_verge_service`（代理会断几秒）。
9. **订阅更新会冲掉 profile 改动。**
   只改订阅 profile 的话，下次更新订阅就退回明文。解法：把 DNS 覆写写进全局 Merge.yaml
   （订阅更新不碰它），profile 也同步改一份做双保险。

### 工具层的坑（本机环境特色）

10. **Git Bash 里 `powershell -Command` 会吃掉 `$_`、`$var`。**
    现象：脚本报"extglob.DisplayName 无法识别"。原因：bash 先把 `$_` 展开掉了。
    解法：凡带变量的 PowerShell，一律写成 `.ps1` 文件用 `-File` 跑。
11. **PowerShell 5.1 把无 BOM 的 .ps1 当 ANSI 读。**
    脚本里的中文路径（`F:\工具\...`）变乱码、找不到文件。解法：存成 **UTF-8 带 BOM**。
12. **Git Bash 把 `/svc`、`/groups` 当路径转换。**
    `tasklist /svc` 报"找不到 D:/Git/svc"。解法：写 `//svc`（双斜杠）或改走 PowerShell。
13. **curl 默认吃系统代理环境变量。**
    测"DoH 服务器直连通不通"时 curl 走了 Clash 的 CONNECT 隧道，结果完全失真。
    解法：直连测试加 `--noproxy '*'`。
14. **pktmon 实时模式会卡死前台。**
    `pktmon start --etw -m real-time` 一直刷屏不返回。解法：用文件模式
    （`--file-name xxx.etl`），抓完 `pktmon stop` 再 `etl2txt`。
15. **pktmon 的 etl2txt 输出是 UTF-16。**
    按 UTF-8 读会解析出 0 条匹配，误以为"没流量"。解法：按 UTF-16 读（记事本能直接开）。
16. **Win10 的 pktmon 抓不到 loopback。**
    本机到 127.0.0.1 的包不出现——这反而方便：抓到的 53 端口包必然出过网卡，都是真泄露。
17. **pktmon 报文头里的 PID 是十六进制。**
    `[00]BC3C.0648::` 里的 BC3C 要按 16 进制换算成十进制再去 tasklist 对进程名。
18. **Dnscache 服务正常手段停不掉。**
    `Restart-Service Dnscache` 报错。解法：`tasklist /svc` 找到它的 svchost PID，
    `taskkill /PID <pid> /F`，服务管理器会自动拉起新的（等于重启）。
19. **手搓 DoH GET 请求极易错。**
    DNS 报文里域名按"长度字节+标签"编码，`baidu` 是 5 不是 6，错一个字节服务器回 400/502。
    解法：别手搓，用程序构造标准 wire-format，POST `application/dns-message` 最稳。
20. **转发器自己写响应时别弄丢标志位。**
    上游全挂回 SERVFAIL 时，第一版把请求里的 RD（期望递归）位清掉了，严格客户端会拒收。
    解法：保留原 flags 的 RD 位再叠加响应码：`(flags & 0x0100) | 0x8002`。

### 上线后第二天炸出来的坑（2026-11-19 凌晨，RustDesk 报 11001 事件）

21. **Windows 上 asyncio 的 UDP transport 会被 ICMP 杀死。**
    现象：部署当晚一切正常，几小时后系统 DNS 全超时；netstat 里转发器的 IPv4 UDP
    socket 消失、IPv6 UDP socket 还在但不收包，TCP 却正常。原因：某个客户端查询后
    超时消失，转发器的回包引来 ICMP port-unreachable，Windows 上 recvfrom 随之抛
    10054，asyncio 把 UDP transport 关闭/挂死——**socket 一死不会自愈**。
    解法：UDP 改用独立线程 + 阻塞 socket，`recvfrom` 抛 OSError 就 continue；
    回归测试＝发查询后立刻关socket（制造 ICMP），连做 6 次，服务器必须仍应答。
    修复版日志带 `(udp threads)` 标记。改前原件在 `回滚备份\doh_forwarder_改前_20261119.py`。
22. **阻塞调用放进事件循环＝全体排队。**
    旧版 `datagram_received` 里同步做 HTTPS 转发（缓存未命中时最长 8 秒），
    整个 asyncio 循环被冻住，期间所有 UDP/TCP 查询一起超时。
    解法：转发一律丢线程池（ThreadPoolExecutor），事件循环只做收发包。
23. **ICS（SharedAccess 服务）占着通配 UDP 0.0.0.0:53。**
    它不挡回环特定地址绑定（Windows 特定地址优先于通配），但转发器 UDP socket 一死，
    查询就落进 ICS 自带 DNS 代理，被 reset 或自环，故障被放大。
    排错第一步：`netstat -ano | findstr ":53 "` 看 UDP 53 到底在谁手里。
24. **"浏览器正常"不能证明 DNS 正常。**
    开着系统代理时浏览器域名在 Clash 侧解析，本机 DNS 全断也照样上网；
    只有不走代理的软件（RustDesk、nslookup）会暴露。os error 11001 =
    WSAHOST_NOT_FOUND，即系统解析器查无此主机。本次就是 RustDesk 先炸才发现。
25. **双网卡垂死黑洞会埋掉转发器出口（第二波 11001 的真凶）。**
    现象：UDP bug 修好后 RustDesk 仍报 11001；转发器日志出现 TLS handshake
    timeout / 10054。原因：WLAN 网卡链路已断但 IP 和默认路由还残留（黑洞），
    转发器出网跟着默认路由走进黑洞；Clash 自己绑存活网卡所以走它一直绿。
    WLAN 彻底掉线、默认路由落回以太网后自愈。解法（已进代码）：上游失败后
    绑本机各存活源地址重试；全失败时**serve 过期缓存**（查过的域名先给旧结果，
    软件不会瞬断）。排错命令：`Get-NetAdapter` 看 MediaConnectionState、
    `Get-NetRoute -DestinationPrefix '0.0.0.0/0'` 看默认路由落在哪块卡。
26. **urllib 会偷偷走系统代理。**
    urllib.request 默认读环境变量的 HTTP(S)_PROXY 和 WinINET 注册表代理。
    DoH 出口若走 Clash 就形成循环依赖（Clash 自己也要 DNS）。解法：改用
    http.client 直连（不吃任何代理设置）。注意本机代理变量是**用户级**的：
    交互 shell 里的测试走代理、SYSTEM 计划任务里的转发器走直连——
    两条路径要分开测，别拿 shell 的绿灯当转发器的绿灯。
27. **重启计划任务可能撞端口（10048）。**
    Stop 后旧进程释放 socket 与新进程绑定之间有竞态，新进程可能 fatal 10048
    退出。任务自带每分钟重试会自愈；手动再 `Start-ScheduledTask DoHForwarder`
    一次即可。看到日志 fatal 10048 不用慌，确认 netstat 里 53 端口有人听就行。

---

## 六、DoH 保护不了什么（别期望过头）

- **只藏"问路"，不藏"上门"。** 拿到 IP 后你去连接哪个服务器、TLS 握手里的站点名
  （SNI），链路上仍然可见。要连这些也藏，得靠代理/VPN（本机的 Clash 就是干这个的）。
- **DoH 服务商看得到查询。** 阿里和腾讯扮演电话簿，它们知道你在查什么。
  这是"防沿途偷看"，不是"对所有人隐身"。
- **自带硬编码 DNS 的软件会绕开。** 系统设置只管走系统解析器的软件；
  本机已知的绕开者 Clash 已修，以后装新软件若发现明文，参照第五节第 6 条处理。
- **本机内部不加密。** 软件到 127.0.0.1 转发器这一段是明文，但它不出网卡，
  外部观察者截不到；只有本机上的恶意软件才看得到——那是另一个层面的问题。

---

*部署与验证：2026-11-19。验证手段为 pktmon 抓包 + 真实域名解析测试，非纸面推断。*
# Android 在线缩容等待与回归

报告：U30 Air，MU300 6.18 包，在线缩容阶段报
`ConnectionError: Reading from ... timed out (60 seconds)`。
提供的 debug 片段只包含计划阶段，没有失败前最后一条命令，因此尚不能
将该次现场确定归因于上传、探测或校验。

已确认的源码缺口：`OnlineShrink.stage()` 向 Android 上传静态工具及四份
GPT 恢复文件时，固定传入 60 秒；嵌入式 ADB 将它继续传给 FileSync 的
transport/read timeout。上传后 `cp/chmod/sync` 则继承普通查询的 20 秒预算。
设备忙于存储同步时，这两个预算与已有的长任务等待不一致。

将准备文件上传、复制后同步及在线能力探测统一为此前约定的 888 秒预算。
普通身份/状态查询保持原预算；不去掉校验，不绕过设备身份、分区边界及
文件系统检查，不自动重放缩容、GPT 或分区写入，不自动转清空数据。
长 shell 继续使用已有心跳和最终退出状态，二进制 FileSync 不插入文本。

新增回归覆盖 eMMC/MU300 与 4Kn UFS/E5 的准备上传与同步预算、上传失败
后禁止启动/清空后备、文件校验失败停止，以及真实公共 Adb 包装层到
Android Driver 的 FileSync 参数传递、失败关闭连接且不重试。

检查范围包括 Android ADB/SSH 连接与授权、二进制备份、在线缩容、安装、
卸载/扩容、OTA 检查/应用/撤销和记录导入导出；通过现有全套 Python
回归及生产前端浏览器用例验证。每轮数量及跳过项以 out/build-logs 为准。
本轮没有连接实机执行安装、缩容或 NV 写入，离线通过不代表本例实机复现已消失。

## 本轮结果

- Windows 全套后端：570 通过，100 跳过（主要为 POSIX 文件系统用例）。
- WSL 全套后端：666 通过，4 跳过；跳过 Rust 解析器、两个要求带 pgrep
  的宿主 BusyBox 用例，以及需要新版原生 F2FS 工具的实际扩容用例。
  Windows 本轮已运行原生 Rust 解析器用例。
- 生产前端浏览器：17 组全部通过，含 Android 手机布局与弹窗。
- Android 文件导入/导出原生组件：5 项通过；前端单元测试 22 项通过。
- 已重编 ARM64 release APK，沿用原签名/证书轮换，签名校验、源码指纹、
  ABI/16 KiB ELF 校验通过。用 CPython 3.13 直接解码 APK 的
  `assets/chaquopy/app.imy` 内字节码，确认准备上传/同步和探测使用 888 秒预算。

日志分别在 `out/build-logs/` 下：
`20261106-122439-android-all-backend-regression-24927`、
`20261106-122539-android-posix-all-regression-24970`、
`20261106-122726-android-full-ui-regression-27711`、
`20261106-123325-android-shrink-fixed-release-27740` 和
`20261106-123439-android-native-and-ui-units-27757`。

本轮只交付独立 APK，之前的固件 ZIP 没有自动替换其中的 APK。

## 补充完整日志后的定位

随后提供的 `OpenWrt-Installer.log (1)` 是另一台 F50：20:45:13
停在首次上传 555064 字节的 `f2fs-online-arm64`。此前的 GPT 小文件及
64 MiB metadata 备份均很快完成；现有 worker 查询为 `busy=0`，没有
执行本轮 `start`。因此该日志中的长等待发生在准备工具上传，不是 F2FS
搬移或 GPT 写入。仅延长上传预算不能消除异常等待。

确认底层缺陷：vendored adb-shell 0.4.4 的 TCP `bulk_write()` 调用一次
非阻塞 `socket.send()` 就返回，而上层 `_AdbIOManager._send()` 不处理
返回的字节数。遇到合法的 TCP 短写，会丢失 ADB 帧剩余部分，设备等待
剩余字节、控制端等待确认，最终超时。日志没有每次 send 返回值或 TCP
抓包；不能把离线复现等同于已抓到该用户现场的每个网络包。

Android LAN transport 现覆盖 bulk_write，按实际已发送偏移补齐整帧，
处理临时反压，使用同一帧总期限；不会重复已发送的前缀或重放上传。
USB 传输、AT、分区/缩容操作和桌面原生 adb 不改变。

`tests/test_mobile_adb_upload.py` 使用同款真实 ADB 库、真实本地 TCP
和 FileSync 协议，强制 socket 每次最多发送 8192 字节。旧代码在约
542 KiB 文件上复现相同读取超时；修正后完整上传并逐字节校验通过，
只打开一次 sync 会话。另覆盖短写/反压不重复、进度不延长期限、关闭
或不可写 socket 失败。复现与首次修复记录位于
`20261106-125307-android-short-write-reproduce-27779` 和
`20261106-125322-android-short-write-fixed-27792`。

短写修正后的全套 WSL 回归为 670 通过、4 跳过（共 674），Windows
为 574 通过、100 跳过（共 674）。日志分别为
`20261106-125425-android-short-write-all-posix-27856` 和
`20261106-125623-android-short-write-windows-and-apk-30598`。
本次没有改前端或原生文件组件，沿用上轮 17 组浏览器、5 项 Android
原生组件和 22 项前端单元的通过结果；APK 重新构建，不沿用前一次仅有
预算修正的二进制。

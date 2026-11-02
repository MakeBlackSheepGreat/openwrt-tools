# 在线缩容：原厂 F2FS 的不完整尾部 section

2026-11-02，以 U30 Pro / MU5358 原厂 Android 15 实机只读复现。
原厂版本为 `ZTE/MU5358/MU5358:15/AP3A.240905.015.A2/20260203.005521:user/release-keys`，
内核为 `6.6.98-android15-8-g9a8b79fdfb2e-ab14559829-4k`。

实机主备超级块相同，block_size=4096，blocks_per_segment=512，segs_per_sec=1，
block_count=13411584，尾数为 256 块。文件系统和 dm-default-key 映射大小均为
54933848064 字节。文件加密并不阻止通过 Android 已解密的挂载点在线缩容。

旧主机解析器和静态 helper 把 `block_count % section_blocks != 0` 当作无效几何，
错误排除合法原厂文件系统。另有两个关联缺口：

1. 此原厂内核先校验 ioctl 目标绝对对齐，再判断目标是否等于原容量，因此对
   有尾数的原容量执行 same-size ioctl 会返回 EINVAL。不能将目标向下取整后
   当作无操作探测，那会真正缩容。此情况明确延后能力确认到用户授权的 worker。
2. 内核按完整 section 更新超级块，实际 block_count 保留原尾数。不能把传入
   ioctl 的向下对齐值当作最终容量，更不能据此缩小 GPT。

修正采用以下约定，原先没有尾数的设备计算结果不变：

```
S = section_blocks
B = 原始 block_count
budget = 新 userdata GPT 分区可容纳的 4K 块数
F = B - ceil((B - budget) / S) * S
ioctl_target = F - (B % S)
```

主机记录、worker 重入以及读回检查使用 F。F 始终不超过新分区容量，且
`(B - F) % S == 0`。设备 worker 验证 UUID、挂载设备、原始容量、双份 GPT，
实际文件系统读回等于 F 后才提交 GPT。拒绝或中断仍按原事务状态恢复，
不自动清空 Android。

原厂实现证据来自本机正在使用的 boot 内核与本地已捕获原件的 SHA-256 一致：
`fc9bd8f2c77ec889cacb100a8723bb5714027fe5d97e03bbf44df117bb601435`。
离线符号/指令核对包含 f2fs_resize_fs 的绝对对齐检查、section 取整以及
update_sb_metadata 的按完整 section 更新。此哈希仅为研究证据，不作为功能白名单。

回归覆盖 eMMC/UFS、512/4096 GPT、原厂 256 块尾数、MiB 边界、保数据优先、
错误 ioctl、ADB 中断、重启续接及取消。静态 helper 同时检查合法尾数和错误
目标；主备超级块不一致、零容量、容量溢出等仍被拒绝。

本次实机只读采集，没有执行 probe/shrink ioctl、写 GPT、格式化或修改 NV。
实际保数据缩容仍需用户在新安装计划里明确确认后执行，离线通过不代表实机完成。

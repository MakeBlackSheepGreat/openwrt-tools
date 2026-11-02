# 在线缩容的 F2FS 内核版本差异

来源：Snrat 的 [PR #2](https://github.com/kanoqwq/openwrt-tools/pull/2)，
提交 `7971a23b7786dd1885dd6f866a215851fd1d7506`。

部分 Android 固件更新后，两份超级块只在 `version[256]` 内核版本字符串上不同。
把完整 3072 字节逐字节比较会误拒绝这种保数据在线缩容。主机 Python 与 Android
ARM64 helper 现在仅允许 `version` 和末尾 CRC 的差异；几何、UUID、初始版本、
feature、设备列表及其他字节仍须一致。检查不修改超级块。

审查时补齐了原 PR 尚未处理的校验：如果启用 `F2FS_FEATURE_SB_CHKSUM`，
两份超级块必须各自通过 F2FS CRC32（magic 初值、无末尾异或），并且
`checksum_offset` 必须是 3068。不能因为允许版本不同就接受损坏或过期的 CRC。
依据 Linux `include/linux/f2fs_fs.h` 的布局及 `fs/f2fs/super.c` 中
`sanity_check_raw_super()` 的 checksum 校验。

共享后端覆盖 Windows、macOS 与 Android；E5/MU300 的存储、NV、槽位及确认边界
保持各自现有实现。没有放宽容量、映射或数据擦除确认，也没有修改设备分区。

构建仍通过 `tools/build-release.py run ... -- python3 build-online-helper.py`，
重新生成 `device/f2fs-online-arm64` 与源码/二进制摘要 `device/build.json`。
桌面、Android 冻结资源继续使用这份带指纹校验的工具，不能只更新 Python 源码。

离线回归包括逐字节差异、checksum 开关、主/备 CRC 损坏、版本变化但 CRC 未更新、
初始版本/几何不同、错误 checksum_offset、Python/C 结果对照，以及 ARM64
原生单元测试。所有输入是测试字节或临时普通文件，不调用实机缩容 ioctl。

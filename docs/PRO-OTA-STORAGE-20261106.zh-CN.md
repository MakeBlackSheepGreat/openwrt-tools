# Pro 系列差异更新后的早期启动缺失

## 已确认的缺陷

Pro 系列安装器把存储挂载适配、设备身份、槽位记录和离线 ext4 修复工具追加到
本机启动 ramdisk。分发包的 canonical boot 不包含安装绑定的存储适配。
Pro 的新 init 却会在挂载 root 前执行：

```sh
. /etc/mu300-desktop-storage.sh
desktop_storage_start
desktop_mount_root
```

旧 OTA `Binder` 只保留槽位和存储模式等标记，没有保留这个脚本，以及它依赖的
`mu300-internal-ext4.sh` 和 `/repair` 工具。因此包含 boot 的补丁可以成功写入、
回读校验并生成 ramdisk 一致的三镜像，仍然在下一次启动挂载 root 前失败。
旧测试的简化 init 直接 switch_root，没有实际的存储脚本依赖，未覆盖该缺陷。

已用当前安装好的 U30 Pro 启动镜像和真实分发 canonical boot 离线复现：
旧绑定结果仍有 `root-mode=part` 和正确 Android 槽，但挂载脚本消失。
修复后绑定结果保留原来的 31 个存储／修复条目。此结论不依赖群友提供版本或日志；
没有原始故障日志，不能说所有“卡第一屏”反馈都由这一原因造成。

## 修复边界

- 仅当 MU300 family 的现有 init 明确为 Pro 原生启动时，绑定已安装的存储
  适配脚本、所需离线安装脚本、GPT 工具、`repair/` 工具及其实际存在的运行别名。
- 不复制旧 ramdisk 的内核、模块树或无关用户程序；继续使用新版 init、内核、
  存储发现库，保留本机槽位／身份和既有存储布局。
- 原 boot 的恢复 guard 本来就包含工具，不再次追加整套副本。
  连续更新从新的 canonical boot 绑定，不随更新次数累积工具副本。
- 已安装的关键存储适配缺失时，在允许写入任何 root／启动分区之前明确报错，
  不把一份校验正确但无法挂载 root 的镜像写入设备。
- 原有三镜像备份、guard/final 写入顺序、失败恢复和回滚保留；Android 槽和
  NV 不写。普通 MU300、E5 的绑定策略不变。

## 验证与交付

`tests/test_u30pro_boot.py` 增加缺失依赖重现、脚本／ELF／符号链接保留、
旧模块排除、三次连续更新尺寸不增长、guard 不重复工具、写入前拒绝损坏适配，
以及 U30 Pro／F50 Pro 双向槽位的三镜像更新与撤销完整事务。
均使用普通临时文件代替分区，不访问设备。

Diff Studio 将生成工具自身的 `boot.py` 打入补丁的隔离更新环境。
因此旧工具已经生成的 `.ota` 不会因为更新目标固件源码而自动修复，需要用
收录本修复的 Diff Studio 重新生成。Windows／Android／macOS 共享该运行时源码；
源码回归不等于这些平台的交付二进制已经重编，也不等于真实刷写验收。

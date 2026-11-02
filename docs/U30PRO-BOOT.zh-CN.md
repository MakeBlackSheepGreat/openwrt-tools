# U30 Pro 启动适配契约

完整包以 desktop/manifest.json 的 platform=u30pro 选择 MU300 存储适配器下的
原生启动容器支持。profile 为 u30pro，不与 mu300-family 混淆；型号差异仍由 typed yes
确认，不会绕过容器完整性、设备身份、槽位和分区校验。

父固件必须随包提供并校验 desktop/native_u30pro.py 与 desktop/boot-runtime.py。
boot-runtime.py 必须来自本仓库 runtime/luci-app-unisoc-ota/root/usr/lib/unisoc-ota/boot.py，
与设备 OTA 使用同一编码器，不依赖另一固件工作目录或额外 boot 副本。

原生 writer 接口支持 flash(android, canonical, control, root, gui, *, dry_run=False,
before_write='', before_misc='', preserve_bcb=False)。before_write 为事务 GPT/身份守卫，
before_misc 为已确认的 BCB 交接；写入失败须恢复整个启动组合，misc 最后提交。
backup/native-before.json 包含 serial/android_slot、原件 SHA、canonical_sha256、
planned、worker、write_started/committed。中断恢复从原件和 canonical 重算计划，
不得把未知目标覆盖成成功，仍运行的同一 worker 必须等其结束。

shared backend/native_boot.py 负责 SSH 的二进制模板传输，以及公共修复/卸载调用。
实际容量、模板 DTB、bootconfig、A/B 关系均来自目标设备；不硬编码镜像文件哈希。
三容器的格式检查与恢复函数在 runtime boot.py。OTA journal 的 boot_companions 为
可选字段，普通 E5/MU300 无此字段或为空，继续沿用原路径。

U30 Pro 的 Android v4 将通用 ramdisk 放在 init_boot。挂载前 F2FS 扩容仅临时编辑
实际 Android 槽 init_boot，并用该事务备份精确恢复；普通机型仍编辑 boot。
维护镜像必须将相同的 Linux ramdisk 放进 boot/vendor_boot，init_boot 不带 Android
启动内容；卸载完成时恢复另一槽 Android 的配套容器。

离线覆盖在 tests/test_u30pro_boot.py、tests/test_android_growth_boot.py。父固件还须
执行自身 native writer 的普通文件故障注入测试；不能用这些结果替代实机验收。
构建旧 EXE/APK 后修改本仓库会触发源码指纹失配，必须重编对应交付件。

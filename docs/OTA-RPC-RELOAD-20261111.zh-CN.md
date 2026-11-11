# 系统补丁完成后的 RPC 不可用与页面误报

## 现场和结论边界

2026-11-11 对用户保留的 U30 Pro 现场仅作只读检查：更新 journal、job
均为 complete，activation=ready，reboot_required=true；目标版本为
`r20261111.104953-ga03a43a7-sf753e650`。当时 unisoc-ota 已注册，status
可调用，没有发现 OOM 或存储 I/O 错误。本轮没有重载服务、写设备或重启。

这证明本次文件更新已成功，不能把网页 Object not found 当作文件写入失败。
用户另有“页面一直不可用，重启恢复”的报告；没有抓到该次持续缺失的后端
对象，不能声称已经证实那次的唯一原因。

## 已确认的公共缺口

- 完成后调用 rpcd reload，网页仍在查询 status；其 Object not found
  没有进入已有的重连分支，会留下错误通知。
- 页面首次 load 只请求一次。恰逢对象重新注册时打开页面，会一直停留在
  加载失败结果，即使后端之后已恢复，也不会自动出现完成状态和重启按钮。
- 插件 list 入口要执行 Python 并导入整个引擎；注册阶段不需要这些依赖。
  隔离测试证实：注册解释器不可用时，旧入口无法向 rpcd 提供签名。
- reload 的信号确认是异步的，随后立即成功的 status 可能仍来自旧对象。
  原检查没有确认对象 ID 已更换，因此可能过早返回 ready。

[rpcd main.c](https://github.com/openwrt/rpcd/blob/master/main.c) 的 SIGHUP
流程保存会话后重新执行守护进程；
[plugin.c](https://github.com/openwrt/rpcd/blob/master/plugin.c) 在启动时
执行插件 list，缺少有效方法声明的入口不会注册。

## 修正

1. proxy.sh 通过 shell 内建 printf 返回固定方法声明，不为 list 启动
   Python。回归校验声明与 rpc.py METHODS 完全一致，不变更方法、参数或 ACL。
2. 收尾检查记录重载前对象 ID，等待不同的新对象；status 健康检查后再核对
   同一个新 ID，不能把即将消失的旧对象或另一次重载当成恢复完成。
   检查失败仍是已提交文件之后的 activation warning，不触发文件回滚。
3. 仅在已知更新／恢复操作期间，把本 OTA 对象的临时缺失作为状态重连。
   丢失启动响应时继续核对原操作及补丁 ID，只查询，不重复发起写入。
4. 首次加载遇到临时缺失时，复用现有 2 秒轮询，最多重试 15 次；恢复后
   展示真实完成状态和重启按钮。持续缺失则明确报错并停止重试；权限拒绝、
   协议错误和真实后台写入失败不会被当作成功。

没有修改补丁适用性、散列、分区、槽位、NV 或配置保留校验；没有新常驻
任务，也没有使用普通重启命令绕过 OTA 自己的启动槽位选择。

## 离线验证

```sh
node tests/ota_luci.js
python3 tests/ota_reconnect_browser.py
python3 -m unittest discover -s tests -p test_ota_rpc.py -v
python3 -m unittest discover -s tests -p test_ota.py -v
OPENWRT_OTA_RPCD_TEST_IMAGE=<已有的OpenWrt测试镜像> python3 tests/ota_rpcd_registration.py
```

最后一项只在明确选择的既有 Docker 镜像中运行，使用私有 ubus socket、
一次性插件目录和模拟 status；不访问设备或宿主 ubus。先重现旧入口在
注册解释器不可用时不注册，再验证轻量入口和真实 SIGHUP 的新对象／调用。
镜像需要原有 rpcd、ubusd 和 ubus；没有指定镜像会明确跳过。

网页回归执行实际交付 JS：覆盖首次加载恢复、持续缺失、更新过程短暂缺失、
丢失启动响应、匹配及不匹配的事务、真实权限错误、真实写入失败与页面退出。
该项已加入 Windows/Linux CI。以上是离线软件验证，不是实机 OTA 验收。

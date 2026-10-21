## Nikki 机身控制页

适用当前 E5 infoscreen API2、Nikki1.26.2和Mihomo1.19.32。使用原 infoscreen 插件安装器，入口是机身“应用 → Nikki代理”。上下选项、确认执行、返回上一级；停止/重启/更新会先进入确认页。

支持状态总览、启动/停止/重启、订阅更新并应用、节点组选择。默认代理节点按核心选择链解析；分流规则可能使用其他节点组。延迟是核心最近探测，速率由当前上联网卡计数器计算。没有默认路由时显示无上联，不把连接Wi-Fi等同于已经验证互联网。

屏幕显示去除组名开头的装饰符，所有API请求仍保留原始名称。API密钥只由设备Python后端读取，不返回前端；接口只依赖原先仅监听loopback的infoscreen服务，不增加设备对外端口。控制API地址改变时会拒绝操作，需核验control.py中的允许列表。

耗时操作为后台任务，flock串行化，任务JSON原子写入；节点选择校验候选并回读。业务错误同时检查JSON的ok字段，兼容当前固件将HTTP状态保留为200的行为。停止后控制页继续工作；启动会设置Nikki开机启用。更新失败保留官方脚本原有缓存行为。

安装：将发布tar.gz复制到设备临时目录，校验SHA256，再执行：

```sh
/usr/libexec/e5-infoscreen/plugin install /tmp/e5-nikki-control.tar.gz
```

当前原安装器的do_link使用全局id变量，成功日志可能打印其他已安装应用名。以目标manifest、文件SHA256和/api/plugins中的ID为验收依据，不修改原安装器。

卸载：`/usr/libexec/e5-infoscreen/plugin remove nikki-control`，只移除机身入口，Nikki本身和订阅保留。不要删除其他应用或恢复整包固件。

测试：设备上运行tests/test_nikki_control.py；tests/e2e_nikki_control.py通过实际infoscreenHTTP接口验证切换/回读、重启保留、停用/启用、订阅更新和并发拦截，并恢复原节点组。E2E会短暂重启代理，需在维护窗口执行。Windows无法直接运行依赖Linux flock的测试。tools/preview-infoscreen.py仅用于临时localhost预览，测试完结束进程，不作常驻服务。

## E5 Wi-Fi机身管理

入口：机身“应用 → Wi-Fi管理”。支持已保存网络、扫描、手动添加、2.4/5GHz个人网络、热点切换、忘记网络、恢复上次配置。当前只在E5原radio0/uplink/default_radio0结构上验证；不安装额外驱动或开放Wi-Fi管理端口。

方向键选择、确认执行、返回上级。名称/密码使用六列字符盘：方向键选字符，确认输入，数字键直接输入数字，#删除，*切换小写/大写/数字/符号；选择“完成”回到连接设置。密码只显示星号。扫描得到的中文SSID无需手输；手动字符盘提供ASCII，隐藏中文SSID需要通过LuCI配置。

仅支持WPA2/WPA3个人认证和开放网络，不支持企业认证。扫描由现有iwinfo提供，结果不保证包括所有频段和隐藏网络；手动连接可选择频段。热点与上联按互斥方式切换；无SIM时，开启热点会使设备没有互联网来源。USB管理不动。

后台串行事务：对当前已提交的wireless/network/firewall做root-only持久快照，拒绝覆盖未应用的UCI改动；UCI batch通过stdin接收带引用的参数，密码不进入argv；连接45秒未关联/取得DHCP地址则原子恢复配置并重新加载网络。上一次配置保留在/etc/e5-infoscreen/wifi-control，断电后仍可在机身选择恢复。不要在其他会话同时修改这三份网络配置。

密码存在设备root-only的profiles.json及实际UCI无线配置。请求通过mkdtemp的700目录/600文件传给Python，完成后删除；后台任务payload也只在700运行目录，完成后清除。状态接口只返回SSID/频段，不返回密码或私有payload。网络控制接口继续只由原loopback infoscreen服务提供。

原插件安装器安装发布tar.gz；卸载`/usr/libexec/e5-infoscreen/plugin remove wifi-control`只移除界面，不主动改动网络或删除私有已保存网络。不要删除其他插件或运行整包恢复。

tests/test_wifi_control.py验证密码脱敏、输入校验、配置快照/恢复、失败回滚和stdin传参。tests/e2e_wifi_control.py在设备上实际测试扫描、重连、AP/STA切换、失败回滚和恢复，需始终保留USB维护连接。操作会短暂断开设备上联，测试后恢复原SSID。

## 重启无线

首页「重启无线」调用 POST /restart：只执行 wifi down / wifi up，不改任何配置。
重启后最多等 20 秒确认 wlan0 的默认网关可达，把地址、网关和结论一起返回。
用于「显示已连接、IP 和路由都在，但一个包也发不出去」这类驱动假死（SC2355 hif 通道退出）。

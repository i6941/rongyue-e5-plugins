# ZeroTier（E5 插件）

在信息屏上看节点状态、加入/离开 ZeroTier 网络。

- 只改 `/etc/config/zerotier`，不动路由、防火墙和 Nikki。
- 网络 ID 严格校验 16 位十六进制。
- 不返回任何密钥；身份文件在 `/var/lib/zerotier-one`（root-only）。
- 依赖系统包：`zerotier`、`kmod-tun`、`libstdcpp6`（OpenWrt 25.x 用 apk）。

接口：

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/status` | 节点 ID、在线状态、已加入网络 |
| POST | `/join` | `{"id":"16位ID"}` |
| POST | `/leave` | `{"id":"16位ID"}` |
| POST | `/toggle` | `{"enabled":true/false}`，停服务不删配置 |

安装后需要在 `/usr/share/e5-infoscreen/www/plugins/` 建一个指向本目录的软链，
宿主才会把它列进应用。

# 复古游戏机 · 荣月 E5 插件

在荣月 E5（`Rongyue E5`，展锐 UMS9621，OpenWrt 25.12.5，320×480 屏）上玩 FC / MD / GBA / GB。

游戏不是跑在网页里，而是跑在设备上的**原生核心**里：后端拉起一个静态编译的
libretro 核心，核心把画面通过本机回环的 WebSocket 推给页面，页面只负责显示
和把手柄按键发回去。真机实测 **FC 59.5 FPS / MD 59 FPS**，画面是核心的原生
分辨率（如 FC 256×240），按整数比例放大到屏幕上。

---

## 一、安装（一条命令）

手机用 USB 连电脑，设备地址是 `192.168.9.1`。在电脑上执行：

```sh
ssh root@192.168.9.1 'wget -O- https://raw.githubusercontent.com/i6941/rongyue-e5-plugins/main/install.sh | sh'
```

装完在信息屏里打开「复古游戏机」就能玩。想连自制游戏一起装：

```sh
ssh root@192.168.9.1 'wget -O- https://raw.githubusercontent.com/i6941/rongyue-e5-plugins/main/install.sh | sh -s -- --roms'
```

卸载：

```sh
ssh root@192.168.9.1 'wget -O- https://raw.githubusercontent.com/i6941/rongyue-e5-plugins/main/install.sh | sh -s -- --remove'
```

安装脚本做的事：下载三个核心二进制和插件包 → 校验 sha256 → 装到
`/usr/bin` 和 `/etc/e5-infoscreen/plugins/e5-emulator/` → 清 WebKit 页面缓存
→ 重启信息屏 → 自检并打印结果。

> 设备密码就是你自己设的那个。脚本用 `wget` 或 `curl` 下载，两种都支持。

## 二、按键

| 机身按键 | 游戏里 |
|---|---|
| 方向键 | 十字键 |
| OK | A |
| 返回（短按） | B |
| 返回（长按 1.2 秒以上） | 退出游戏 |
| `0` | START |
| `1` | SELECT |
| `2` | L |
| `3` | R |
| `#`（列表里也可以按 `9`） | 打开按键设置 |

按键设置里每一项都能点开重新绑定，也可以一键恢复默认或切到数字键方案。
面板里还有两个画面选项：**滤镜**（关 / 扫描线 / LCD 网格）和 **比例**
（宽铺 / 拉伸 / 1:1）。滤镜只是叠一层 CSS，不改核心，也不占每帧开销。

在游戏列表里按返回会交还给宿主（信息屏主界面），不会退出插件。游戏里长按返回
只退到游戏列表，不会一路退到宿主主界面——退出后继续按返回才会离开插件。

游戏内顶部显示游戏名、分辨率和实时帧率（分辨率取核心的实时值，所以同一个
ROM 切换显示模式时也不会被拉伸），底部一行是存档和按键提示。

## 三、玩自己的 ROM

把 ROM 传到设备的 `/etc/e5-infoscreen/roms/` 就行，**扩展名决定用哪个核心**：

| 扩展名 | 核心 | 对应机种 |
|---|---|---|
| `.nes` | `e5emu` | FC / NES |
| `.md` | `e5emu-genesis` | MD / 世嘉 |
| `.gba` `.gb` | `e5emu-gba` | GBA / GB |

```sh
scp mygame.nes root@192.168.9.1:/etc/e5-infoscreen/roms/
```

文件名前只能用字母、数字、`.`、`_`、`-`，别的字符会被过滤掉。

**商业 ROM 请自己保管，不要转发给别人。** 仓库里带的是 19 个许可允许再分发的
自制游戏，清单见 [`roms/manifest.json`](roms/manifest.json) 和
[`docs/ROMS-LICENSES.md`](docs/ROMS-LICENSES.md)。

存档：核心会把带电池的存档（`.srm`）在游戏退出时写回 ROM 旁边；游戏内底部
还有快速存/读档（`.st0`），退出后下次进游戏会提示继续。

## 四、常见问题

**装完还是旧的界面 / 改了没反应**
信息屏的浏览器缓存很顽固，脚本已经清了
`/tmp/run/e5-infoscreen/.cache/wpe/WebKitCache`。还是不行就重启信息屏：
`/etc/init.d/e5-infoscreen restart`。

**进游戏后黑屏、一直"启动中"**
先确认核心装了：`ls -l /usr/bin/e5emu*`。再手动看日志：
`cat /tmp/e5emu.log`。

**没声音**
这台机器的信息屏默认没有音频输出。核心的音频走 ALSA（`paplay`），
如果设备上没装 alsa-utils 就没有声音。先在信息屏里试其它应用的音量，
确认设备本身能出声。

**帧率上不去**
核心是按屏幕刷新率跑的，60 是这台机器的刷新上限，看起来 59.x 属于正常。

## 五、其它插件

| 插件 | 作用 |
|---|---|
| `e5-keepalive` | 定时保活 giffgaff SIM，并通过 PushPlus 推通知 |
| `nikki-control` | Nikki 代理服务的本地控制面板（不返回任何凭据） |
| `wifi-control` | 扫描 Wi-Fi 并切换 USB 上行，失败自动回滚 |
| `wpe-capability` | 报告这台设备的 WPE 运行时到底支持什么 |
| `bili` | 哔哩哔哩：排行榜/搜索、720P 播放、声音、自动跳广告、扫码登录 |

## 六、给开发者

### 仓库结构

```
plugins/<id>/          每个插件一个目录：index.html + backend.uc + manifest.json
native/                原生核心前端 e5emu.c（libretro 前端 + WebSocket 帧服务）
roms/                  自制游戏与清单
tools/                 打包、测试、调试用的小工具
docs/                  设备特性、许可、ucode 限制等说明
```

### 原生核心怎么工作

`e5emu` 是个单文件的 libretro 前端：它加载一个 ROM，把核心渲染出的 RGB565
帧按「宽 u16le + 高 u16le + 像素」的格式，通过本机 `127.0.0.1:9510` 的
WebSocket 推给插件页面；页面把按键位图发回来，核心转成 libretro 的输入位。
连接协议细节见 [`native/README.md`](native/README.md)。

之所以不用浏览器里的 WebAssembly 核心：这台机器的 WPE WebKit 跑 wasm 核心会
在进游戏两三秒后停摆（灰屏、0 FPS、按键无反应），反复开关还会耗尽 WebGL2
上下文。所以默认走原生核心，网页里的 EmulatorJS 路径只作为回退保留。

### 编译

需要 [Zig](https://ziglang.org/)（0.17 验证过）和对应 libretro 核心的源码：

```sh
zig cc -target aarch64-linux-musl -O2 -static \
  -D__LIBRETRO__ -DPATH_MAX=1024 -DFCEU_VERSION_NUMERIC=9900 \
  -DFRONTEND_SUPPORTS_RGB565 \
  -Icore/src/drivers/libretro -Icore/src/drivers/libretro/libretro-common/include \
  -Icore/src -Icore/src/input -Icore/src/boards \
  e5emu.c <核心源码> -o e5emu
```

### 测试

```sh
python -m unittest discover -s tests -p 'test_*.py'
```

### 其它工具

| 工具 | 用途 |
|---|---|
| `tools/build-rom-manifest.py` | 重新生成 `roms/manifest.json`（含每个 ROM 的 sha256） |
| `tools/build-rom-docs.py` | 重新生成 `docs/ROMS-LICENSES.md` 与 `docs/THIRD-PARTY.md` |
| `tools/enable-game-audio.sh` | 安装 GStreamer 音频包，给信息屏补上音频输出 |
| `tools/device-proxy.py` | 把设备回环上的面板端口转发到电脑，方便调试 |
| `tools/preview-infoscreen.py` | 用 SSH 隧道在电脑浏览器里预览真机界面 |
| `tools/shot-frame.py` | 从帧服务抓一帧存成 PNG（取真实分辨率画面用） |
| `tools/native-preview.py` | 在电脑上预览插件页面（可接真核心，也可造假帧） |
| `tools/sync-to-publish.py` | 把工作目录同步到公开仓库（游戏表会被换回自制版） |

`device-proxy.py` 有三种用法，设备地址用 `E5_HOST` 环境变量给（它按 MAC 派生，
不能写进仓库）：

```sh
E5_HOST=<设备地址> python tools/device-proxy.py 18088            # 面板的 HTTP
E5_HOST=<设备地址> python tools/device-proxy.py 9510 --tcp 9510  # 核心端口的裸隧道
E5_HOST=<设备地址> python tools/device-proxy.py 18099 --rewrite 8089
```

最后一种把页面里写死的 `http://127.0.0.1:8089` 改成电脑上的端口，并给本地
脚本加随机尾巴（浏览器会缓存改写前的版本）。配合 `--tcp` 隧道，就能在电脑
浏览器里打开**真机上的**宿主页面，点开应用磁贴，让真机的那份插件页跑在
iframe 里——不用有人去点设备屏幕。

三个 SSH 工具会在运行时从 `.secrets/openwrt-access.json` 读设备密码，从
`.secrets/openwrt-known-hosts` 读主机指纹。这两个文件不在仓库里，自己建一个：

```json
{ "adminPassword": "the-password-you-set-on-the-device" }
```

设备地址默认 `192.168.9.1`（USB 网卡），可以用环境变量 `E5_HOST` 覆盖。
链路本地 IPv6 地址由 MAC 推导，所以没有写死在代码里。

---

## English summary

Plugins for the **Rongyue E5** phone (Unisoc UMS9621, OpenWrt 25.12.5, 320×480).
The retro game console runs **native libretro cores** (NES, Mega Drive, GBA/GB)
instead of WebAssembly: the backend starts a static core binary that streams
RGB565 frames to the plugin page over a loopback WebSocket, and the page sends
the gamepad bitmask back. Measured on the device: 59.5 FPS (NES), 59 FPS (MD).

Install in one command over SSH (device at `192.168.9.1`):

```sh
ssh root@192.168.9.1 'wget -O- https://raw.githubusercontent.com/i6941/rongyue-e5-plugins/main/install.sh | sh'
```

Drop your own ROMs into `/etc/e5-infoscreen/roms/` — `.nes`, `.md`, `.gba`/`.gb`
pick the matching core. The bundled games are homebrew titles whose licences
allow redistribution; no commercial ROMs are included.

## Licence

GPL-3.0-or-later — required because the bundled EmulatorJS runtime and several
of its cores are GPL. See [`LICENSE`](LICENSE) and
[`docs/THIRD-PARTY.md`](docs/THIRD-PARTY.md) for the full attribution list.

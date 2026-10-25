# DOS 游戏

本插件由 `tools/split-emulator-plugins.py` 从 `plugins/e5-emulator` 派生，不要手工修改——改源插件后重新生成。

- 机种范围：`DOS`
- 原生核心：`/usr/bin/e5emu-dos（DOSBox-Pure）`
- 只走原生：这个机种没有网页运行库版本可退回，缺少核心时会直接提示路径

安装：

```sh
python tools/split-emulator-plugins.py --apply
python tools/install-plugin.py e5-dos
```

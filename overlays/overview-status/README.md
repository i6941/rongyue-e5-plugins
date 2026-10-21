机身主页概览扩展：在流量卡下增加上游 Wi-Fi、Nikki 两行只读状态。

通过现有 loopback infoscreen plugin API 读取状态，不新增端口，不返回密钥。仅概览可见且没有打开应用时每10秒刷新；7秒超时、两个来源分别降级。长节点名省略，完整信息在 Nikki 应用内查看。运行状态不等于已证明 Internet 可用。

安装：将两个文件复制到 `/usr/share/e5-infoscreen/www/`，在该目录 `index.html` 的 `</head>` 前加入 `<link rel="stylesheet" href="overview-status.css">`，在 `</body>` 前加入 `<script src="overview-status.js"></script>`。先保存原始 index.html；不修改 app.js。固件更新可能覆盖入口，需要比对新版入口再重装。

恢复：移除 index.html 的上述两行，再删除这两个扩展文件。原始入口备份位于 `/etc/e5-infoscreen/overrides/overview-index.original.html`。

'use strict';
/* 浏览器插件后端：只做转发。
   抓取和解析都交给 /usr/libexec/e5-browse（python3），
   因为 ucode 不能写正则字面量，也不适合解析 HTML。 */
import { open } from 'fs';

return function (ctx) {
    /* URL 白名单：只允许 http(s)，且字符集里不含单引号、空格、$ 和反引号，
       这样拼进 shell 的单引号参数里不会被注入。 */
    function clean_url(raw) {
        if (type(raw) != 'string') return null;
        let u = raw;
        if (length(u) < 8 || length(u) > 2048) return null;
        let s = lc(u);
        if (substr(s, 0, 7) != 'http://' && substr(s, 0, 8) != 'https://') return null;
        let allowed = 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789:/?&=._~%+@#-,;!()[]*';
        for (let i = 0; i < length(u); i++)
            if (index(allowed, substr(u, i, 1)) === null) return null;
        return u;
    }

    return {
        /* 记录原文模式（iframe）在设备上到底加载成功没有，排查用 */
        'POST /probe': function (req) {
            let b = req.body ?? {};
            let line = sprintf('%J\n', { t: time(), mode: `${b.mode ?? ''}`, status: `${b.status ?? ''}`, url: `${b.url ?? ''}` });
            try {
                let f = open('/tmp/e5-browser-probe.log', 'a', 0o644);
                if (!f) return { ok: false };
                f.write(line);
                f.close();
                return { ok: true };
            } catch (e) { return { ok: false, error: `${e}` }; }
        },
        /* 同源代理：把外站 HTML 取回来、链接改写成 /proxy?url=…，
           页面就和插件同源了，界面才能读标题、地址并接管点击。 */
        'GET /proxy': function (req) {
            let url = clean_url(req.query?.url ?? '');
            if (url === null)
                return { status: 400, type: 'text/html; charset=utf-8',
                         body: '<p style="font:13px sans-serif;color:#c00">网址不合法</p>' };
            let out = ctx.sh("python3 /etc/e5-infoscreen/plugins/browser/e5-proxy '" + url + "'");
            if (type(out) != 'string' || length(out) == 0)
                return { status: 502, type: 'text/html; charset=utf-8',
                         body: '<p style="font:13px sans-serif;color:#c00">代理抓取失败</p>' };
            return { status: 200, type: 'text/html; charset=utf-8', body: out };
        },
        'GET /browse': function (req) {
            let url = clean_url(req.query?.url ?? '');
            if (url === null) return { ok: false, error: 'bad url' };
            let via = `${req.query?.via ?? ''}` === 'jina' ? ' jina' : '';
            let out = ctx.sh("python3 /usr/share/e5-infoscreen/www/plugins/browser/e5-browse '" + url + "'" + via);
            if (type(out) != 'string' || length(out) == 0)
                return { ok: false, error: 'browse failed' };
            return { status: 200, type: 'application/json', body: out };
        }
    };
};

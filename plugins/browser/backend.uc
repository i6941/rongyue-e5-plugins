'use strict';
/* 浏览器插件后端：只做转发。
   抓取和解析都交给 /usr/libexec/e5-browse（python3），
   因为 ucode 不能写正则字面量，也不适合解析 HTML。 */
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
        'GET /browse': function (req) {
            let url = clean_url(req.query?.url ?? '');
            if (url === null) return { ok: false, error: 'bad url' };
            let out = ctx.sh("python3 /usr/share/e5-infoscreen/www/plugins/browser/e5-browse '" + url + "'");
            if (type(out) != 'string' || length(out) == 0)
                return { ok: false, error: 'browse failed' };
            return { status: 200, type: 'application/json', body: out };
        }
    };
};

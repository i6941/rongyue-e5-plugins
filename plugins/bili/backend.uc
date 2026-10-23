'use strict';
import { open, readfile } from 'fs';
/* 精简版 B站 客户端后端：只封装官方 API，不破解。
   取流走 platform=html5 + fnval=0，官方会直接给 progressive MP4（durl），
   这是 <video> 能直接吃的格式；DASH 的分离音轨这条路在 WPE 上不好走。
   视频和封面都要带 Referer，所以统一由后端代理。 */
return function (ctx) {
    const UA = 'Mozilla/5.0 (X11; Linux aarch64) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15';
    const REFERER = 'https://www.bilibili.com/';
    const API = 'https://api.bilibili.com';
    const IMG_DOMAINS = ['hdslb.com'];
    const VID_DOMAINS = ['bilivideo.com', 'bilivideo.cn', 'akamaized.net', 'bilibili.com'];

    /* B站接口有时给 http:// 的封面地址，而 host_ok 只放行 https，统一升一下级 */
    function httpsify(u) {
        if (substr(u, 0, 2) === '//') return 'https:' + u;
        if (substr(u, 0, 7) === 'http://') return 'https://' + substr(u, 7);
        return u;
    }
    function ends_with(s, suf) {
        if (length(s) < length(suf)) return false;
        return substr(s, length(s) - length(suf), length(suf)) === suf;
    }
    function host_of(url) {
        let i = index(url, '://');
        if (i < 0) return '';
        let rest = substr(url, i + 3);
        let j = index(rest, '/');
        return j < 0 ? rest : substr(rest, 0, j);
    }
    function host_ok(url, domains) {
        if (substr(url, 0, 8) !== 'https://') return false;
        let h = lc(host_of(url));
        for (let d in domains)
            if (h === d || ends_with(h, '.' + d)) return true;
        return false;
    }
    /* B站的风控要 buvid3 指纹 cookie，否则排行榜返回 -352。
       通过公开的 finger/spi 取一次，缓存在 /tmp，避免每个请求都取。 */
    function buvid3() {
        let cached = '';
        try { cached = trim(readfile('/tmp/bili-buvid3') ?? ''); } catch (e) { }
        if (length(cached) > 20) return cached;
        let r = ctx.sh("curl -s --max-time 12 -A '" + UA + "' '" + API + "/x/frontend/finger/spi'");
        let j = null;
        try { j = json(r); } catch (e) { return ''; }
        let b = `${j?.data?.b_3 ?? ''}`;
        if (length(b) > 20) {
            try {
                let f = open('/tmp/bili-buvid3', 'w', 0o600);
                if (f) { f.write(b); f.close(); }
            } catch (e) { }
            return b;
        }
        return '';
    }
    /* 登录态 Cookie：SESSDATA/bili_jct/DedeUserID，存在插件目录里（600）。
       只用于向 B 站官方接口证明身份，不上传、不进仓库。 */
    const COOKIE_FILE = '/etc/e5-infoscreen/plugins/bili/cookies.txt';
    function user_cookie() {
        let c = '';
        try { c = trim(`${ctx.sh('cat ' + COOKIE_FILE + ' 2>/dev/null') ?? ''}`); } catch (e) { }
        if (index(c, '\n') >= 0) c = substr(c, 0, index(c, '\n'));
        return c;
    }
    function cookie_hdr() {
        let parts = '';
        let b = buvid3();
        if (b !== '') parts = 'buvid3=' + b;
        let u = user_cookie();
        if (u !== '') parts = parts === '' ? u : parts + '; ' + u;
        return parts === '' ? '' : " -H 'Cookie: " + parts + "'";
    }
    function api_get(path) {
        return ctx.sh("curl -s --max-time 15 -A '" + UA + "'" + cookie_hdr() +
                      " -H 'Referer: " + REFERER + "' '" + API + path + "'");
    }
    function num(v) { let n = +v; return n == n ? n : 0; }
    function strip_tags(s) {
        let out = '', inTag = false;
        for (let i = 0; i < length(s); i++) {
            let c = substr(s, i, 1);
            if (c === '<') { inTag = true; continue; }
            if (c === '>') { inTag = false; continue; }
            if (!inTag) out += c;
        }
        return out;
    }
    /* 搜索词要允许中文（UTF-8 多字节），只挡 shell 里有特殊含义的字符 */
    function clean_text(s) {
        let danger = "'\"`$;&|<>(){}[]*?\\\n\r\t";
        let out = '';
        for (let i = 0; i < length(s); i++) {
            let c = substr(s, i, 1);
            if (index(danger, c) < 0) out += c;
        }
        return substr(out, 0, 40);
    }
    /* BVID 严格校验：BV + 10 位字母数字，长度 12 */
    function bad_bvid(s) {
        if (length(s) !== 12 || substr(s, 0, 2) !== 'BV') return true;
        let alnum = 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789';
        for (let i = 2; i < 12; i++) if (index(alnum, substr(s, i, 1)) < 0) return true;
    return false;
    }

    /* 停播放器要确认进程真的没了：只发信号就走，下一次播放会和旧实例抢端口 */
    function stop_player() {
        let pid = trim(`${ctx.sh('cat /var/run/e5play.pid 2>/dev/null') ?? ''}`);
        if (length(pid) > 0) {
            let cmd = `${ctx.sh('tr "\\0" " " < /proc/' + pid + '/cmdline 2>/dev/null') ?? ''}`;
            if (index(cmd, 'e5play') !== null) {
                ctx.sh('kill -TERM ' + pid + ' 2>/dev/null');
                let i = 0;
                while (i < 20) {
                    if (trim(`${ctx.sh('kill -0 ' + pid + ' 2>/dev/null && echo yes') ?? ''}`) !== 'yes')
                        break;
                    ctx.sh('/opt/e5/bin/busybox sleep 0.1');
                    i++;
                }
                if (trim(`${ctx.sh('kill -0 ' + pid + ' 2>/dev/null && echo yes') ?? ''}`) === 'yes') {
                    ctx.sh('kill -KILL ' + pid + ' 2>/dev/null');
                    ctx.sh('/opt/e5/bin/busybox sleep 0.2');
                }
            }
        }
        ctx.sh('rm -f /var/run/e5play.pid 2>/dev/null');
        return length(trim(`${ctx.sh('pidof e5play 2>/dev/null') ?? ''}`)) == 0;
    }

    return {
        /* 排行榜：取前 40 个，字段裁剪到面板需要的几个 */
        'GET /rank': function () {
            let raw = api_get('/x/web-interface/ranking/v2?rid=0&type=all');
            let j = null;
            try { j = json(raw); } catch (e) { return { ok: false, error: 'bad json' }; }
            if (!j || num(j.code) !== 0) return { ok: false, error: 'api ' + (j ? j.code : '?') };
            let out = [];
            for (let it in (j.data?.list ?? [])) {
                push(out, {
                    bvid: `${it.bvid ?? ''}`,
                    title: `${it.title ?? ''}`,
                    author: `${it.owner?.name ?? ''}`,
                    pic: httpsify(`${it.pic ?? ''}`),
                    dur: num(it.duration),
                    play: num(it.stat?.view),
                    cid: 0
                });
                if (length(out) >= 40) break;
            }
            return { ok: true, list: out };
        },
        /* 搜索：这个接口不带签名也能用（设备上实测 code=0） */
        'GET /search': function (req) {
            let q = clean_text(`${req.query?.q ?? ''}`);
            if (length(q) < 1) return { ok: false, error: 'empty' };
            let raw = ctx.sh("curl -s -G --max-time 15 -A '" + UA + "'" + cookie_hdr() +
                             " -H 'Referer: " + REFERER +
                             "' --data 'search_type=video' --data-urlencode 'keyword=" + q +
                             "' '" + API + "/x/web-interface/search/type'");
            let j = null;
            try { j = json(raw); } catch (e) { return { ok: false, error: 'bad json' }; }
            if (!j || num(j.code) !== 0) return { ok: false, error: 'api ' + (j ? j.code : '?') };
            let out = [];
            for (let it in (j.data?.result ?? [])) {
                if (`${it.type ?? ''}` !== 'video') continue;
                let pic = httpsify(`${it.pic ?? ''}`);
                push(out, {
                    bvid: `${it.bvid ?? ''}`,
                    title: strip_tags(`${it.title ?? ''}`),
                    author: `${it.author ?? ''}`,
                    pic: pic,
                    dur: 0,
                    durtxt: `${it.duration ?? ''}`,
                    play: num(it.play),
                    cid: 0
                });
                if (length(out) >= 30) break;
            }
            return { ok: true, list: out };
        },
        /* 取一个视频的可播地址（html5 progressive mp4） */
        'GET /play': function (req) {
            let bvid = `${req.query?.bvid ?? ''}`;
            let cid = num(req.query?.cid);
            if (bad_bvid(bvid)) return { ok: false, error: 'bad bvid' };
            if (!cid) {
                let pg = api_get('/x/player/pagelist?bvid=' + bvid);
                let pj = null;
                try { pj = json(pg); } catch (e) { return { ok: false, error: 'pagelist json' }; }
                if (!pj || num(pj.code) !== 0 || !pj.data || !pj.data[0]) return { ok: false, error: 'pagelist' };
                cid = num(pj.data[0].cid);
            }
            let qn = num(req.query?.qn);
            if (qn !== 16 && qn !== 32 && qn !== 64 && qn !== 80 && qn !== 112) qn = 80;
            let q = api_get('/x/player/playurl?bvid=' + bvid + '&cid=' + cid + '&qn=' + qn +
                            '&fnval=0&platform=pc&fourk=1');
            let j = null;
            try { j = json(q); } catch (e) { return { ok: false, error: 'playurl json' }; }
            if (!j || num(j.code) !== 0) return { ok: false, error: 'playurl ' + (j ? j.code : '?') };
            let d = j.data?.durl?.[0];
            if (!d || !d.url) return { ok: false, error: 'no durl' };
            return { ok: true, cid: cid, url: `${d.url}`, size: num(d.size), quality: num(j.data.quality) };
        },
        /* 取流后让 curl 在后台下载，前端轮询 /ready。
           不能在 CGI 里同步下几十 MB：uhttpd 30 秒左右就掐断请求，
           页面收到的是 HTML 错误页，JSON 解析直接失败。 */
        'GET /prepare': function (req) {
            let bvid = `${req.query?.bvid ?? ''}`;
            let cid = num(req.query?.cid);
            if (bad_bvid(bvid)) return { ok: false, error: 'bad bvid' };
            if (!cid) {
                let pg = api_get('/x/player/pagelist?bvid=' + bvid);
                let pj = null;
                try { pj = json(pg); } catch (e) { }
                if (!pj || num(pj.code) !== 0 || !pj.data || !pj.data[0])
                    return { ok: false, error: 'pagelist' };
                cid = num(pj.data[0].cid);
            }
            let q = api_get('/x/player/playurl?bvid=' + bvid + '&cid=' + cid + '&qn=80&fnval=0&platform=pc&fourk=1');
            let j = null;
            try { j = json(q); } catch (e) { }
            if (!j || num(j.code) !== 0) return { ok: false, error: 'playurl' };
            let d = j.data?.durl?.[0];
            if (!d || !d.url) return { ok: false, error: 'no durl' };
            let u = `${d.url}`;
            if (!host_ok(u, VID_DOMAINS) || index(u, "'") >= 0) return { ok: false, error: 'bad url' };

            let dir = '/etc/e5-infoscreen/plugins/bili';
            let out = dir + '/cache.mp4';
            let tmp = '/tmp/bili-dl.mp4';
            let res = '/tmp/bili-dl.res';
            /* 同一个视频已经缓存过就直接用，别每次重下几十上百 MB */
            let id = bvid + ' ' + cid;
            let cached = trim(`${ctx.sh('cat /tmp/bili-cache-id 2>/dev/null') ?? ''}`);
            let have = num(`${ctx.sh('wc -c < ' + out + ' 2>/dev/null') ?? '0'}`);
            ctx.sh("echo '" + id + "' > /tmp/bili-req");
            if (cached === id && have > 1048576)
                return { ok: true, state: 'cached', size: have, cid: cid };
            ctx.sh('start-stop-daemon -K -q -p /var/run/bili-dl.pid; rm -f /var/run/bili-dl.pid ' +
                   res + ' ' + tmp);
            let script = "curl -s --max-time 1800 --retry 3 --retry-delay 2 --max-filesize 300000000 -A '" + UA +
                         "' -H 'Referer: " + REFERER + "'" + cookie_hdr() + " -o " + tmp +
                         " -w '%{http_code} %{size_download}' '" + u + "' > " + res;
            ctx.sh('start-stop-daemon -S -q -b -m -p /var/run/bili-dl.pid -x /bin/sh -- -c "' +
                   script + '"');
            return { ok: true, state: 'downloading', quality: num(j.data.quality), cid: cid };
        },
        /* 前端每秒问一次：下载完了没有 */
        'GET /ready': function () {
            let out = '/etc/e5-infoscreen/plugins/bili/cache.mp4';
            let r = trim(`${ctx.sh('cat /tmp/bili-dl.res 2>/dev/null') ?? ''}`);
            if (r === '') {
                /* 缓存命中时不会有下载结果文件，直接按标记回答 */
                let req = trim(`${ctx.sh('cat /tmp/bili-req 2>/dev/null') ?? ''}`);
                let cached = trim(`${ctx.sh('cat /tmp/bili-cache-id 2>/dev/null') ?? ''}`);
                if (req !== '' && req === cached) {
                    let have = num(`${ctx.sh('wc -c < ' + out + ' 2>/dev/null') ?? '0'}`);
                    if (have > 1048576)
                        return { ok: true, ready: true, cached: true, size: have };
                }
                /* 下载进程没了、结果文件又是空的，说明 curl 被中断（超时或被换片杀掉）。
                   以前这里一律回「下载中」，页面就永远等下去——现在改成明确失败，
                   并带上已经下了多少字节，界面能显示进度。 */
                let pidf = trim(`${ctx.sh('cat /var/run/bili-dl.pid 2>/dev/null') ?? ''}`);
                let alive = 'no';
                if (length(pidf) > 0)
                    alive = trim(`${ctx.sh('kill -0 ' + pidf + ' 2>/dev/null && echo yes') ?? ''}`);
                let bytes = num(`${ctx.sh('wc -c < /tmp/bili-dl.mp4 2>/dev/null') ?? '0'}`);
                if (alive !== 'yes')
                    return { ok: true, ready: false, state: 'failed', code: 'interrupted', bytes: bytes };
                return { ok: true, ready: false, state: 'downloading', bytes: bytes };
            }
            let parts = split(r, ' ');
            let code = `${parts[0] ?? '0'}`;
            let size = num(parts[1]);
            if (code !== '200' || size < 1024)
                return { ok: true, ready: false, state: 'failed', code: code };
            ctx.sh('mv -f /tmp/bili-dl.mp4 ' + out + '; rm -f /tmp/bili-dl.res; ' +
                   'cat /tmp/bili-req 2>/dev/null > /tmp/bili-cache-id');
            return { ok: true, ready: true, file: '/plugins/bili/cache.mp4?v=' + time(), size: size };
        },
        /* 视频流代理：upos 要求 Referer，前端 <video> 没法自己加 */
        'GET /stream': function (req) {
            let u = `${req.query?.u ?? ''}`;
            if (!host_ok(u, VID_DOMAINS)) return { status: 403, type: 'text/plain', body: 'host not allowed' };
            let tmp = '/tmp/bili-stream.mp4';
            ctx.sh('rm -f ' + tmp);
            let r = ctx.sh("curl -s --max-time 120 --max-filesize 120000000 -A '" + UA +
                           "' -H 'Referer: " + REFERER + "' -o " + tmp +
                           " -w '%{http_code} %{size_download}' '" + u + "'");
            let parts = split(`${r ?? ''}`, ' ');
            let code = `${parts[0] ?? '0'}`;
            let size = num(parts[1]);
            if (code !== '200' || size < 1024) return { status: 502, type: 'text/plain', body: 'upstream ' + code };
            let data = readfile(tmp);
            ctx.sh('rm -f ' + tmp);
            if (!data) return { status: 500, type: 'text/plain', body: 'read fail' };
            return { status: 200, type: 'video/mp4', body: data };
        },
        /* 启动原生播放器：设备上没有 H.264 解码器（只有跑不起来的
           h264_v4l2m2m），所以视频由插件自带的 e5play（openh264 软解）
           解码，再用和模拟器相同的 WebSocket 协议把 RGB565 帧推给页面。 */
        'GET /player-start': function () {
            let dir = '/etc/e5-infoscreen/plugins/bili';
            let bin = dir + '/e5play';
            let mp4 = dir + '/cache.mp4';
            if (trim(`${ctx.sh('test -x ' + bin + ' && echo yes') ?? ''}`) !== 'yes')
                return { ok: false, error: 'no player binary' };
            if (trim(`${ctx.sh('test -s ' + mp4 + ' && echo yes') ?? ''}`) !== 'yes')
                return { ok: false, error: 'no cached video' };
            if (!stop_player()) return { ok: false, error: '旧播放器没退出' };
            ctx.sh('start-stop-daemon -S -q -b -m -p /var/run/e5play.pid -x ' + bin +
                   ' -- --serve ' + mp4 + ' 9511');
            return { ok: true, port: 9511 };
        },
        /* 退出播放时一定要停掉：一个插件目录里只常驻一个解码进程 */
        'GET /player-stop': function () {
            return { ok: true, stopped: stop_player() };
        },
        /* 封面代理：同样的 Referer 问题 */
        'GET /img': function (req) {
            let u = `${req.query?.u ?? ''}`;
            if (!host_ok(u, IMG_DOMAINS)) return { status: 403, type: 'text/plain', body: 'host not allowed' };
            /* 每次请求各用一个临时文件：列表会同时拉多张封面，
               共用一个文件会互相覆盖，表现就是黑框。 */
            let tmp = trim(`${ctx.sh('mktemp /tmp/bili-img-XXXXXX') ?? ''}`);
            if (length(tmp) < 5) return { status: 500, type: 'text/plain', body: 'tmp' };
            ctx.sh('rm -f ' + tmp);
            let r = ctx.sh("curl -sL --max-time 20 -A '" + UA + "' -H 'Referer: " + REFERER + "' -o " + tmp +
                           " -w '%{http_code}' '" + u + "'");
            if (`${r ?? ''}` !== '200') return { status: 502, type: 'text/plain', body: 'upstream' };
            let data = readfile(tmp);
            ctx.sh('rm -f ' + tmp);
            if (!data) return { status: 500, type: 'text/plain', body: 'read fail' };
            return { status: 200, type: 'image/jpeg', body: data };
        },
        /* 真机截图：页面把画布按 RGB565 分块传上来（宿主 read_body 超过
           4096 字节会整块丢弃，所以每块只有 3000 字符）。 */
        'POST /shot': function (req) {
            let body = req.body ?? {};
            let part = +(`${body.part ?? ''}`);
            part = part - (part % 1);
            if (part !== part || part < 0 || part > 400) return { ok: false, error: 'bad part' };
            let s = `${body.b64 ?? ''}`;
            if (length(s) > 4000) return { ok: false, error: 'too long' };
            try {
                let f = open('/tmp/bili-shot-' + part + '.b64', 'w', 0o644);
                if (!f) return { ok: false };
                f.write(s);
                f.close();
                return { ok: true };
            } catch (e) { return { ok: false, error: `${e}` }; }
        },
        /* 弹幕：官方 XML 接口（list.so）返回整段的 deflate 压缩 XML，
           这里解压后按 <d p="...">文本</d> 拆开，只留下前端画弹幕要用的字段。 */
        'GET /danmaku': function (req) {
            let cid = num(req.query?.cid);
            if (!cid || cid < 1 || cid > 99999999999999) return { ok: false, error: 'bad cid' };
            ctx.sh("curl -s --compressed --max-time 25 -A '" + UA +
                   "' -H 'Referer: " + REFERER + "' -o /tmp/bili-dm.xml" +
                   " 'https://api.bilibili.com/x/v1/dm/list.so?oid=" + cid + "'");
            let s = `${ctx.sh('cat /tmp/bili-dm.xml 2>/dev/null') ?? ''}`;
            if (length(s) < 100) return { ok: false, error: 'no xml' };
            let chunks = split(s, '<d p="');
            let out = [];
            for (let i = 1; i < length(chunks); i++) {
                let chunk = chunks[i];
                let gt = index(chunk, '">');
                if (gt < 0) continue;
                let p = substr(chunk, 0, gt);
                let body = substr(chunk, gt + 2);
                let end = index(body, '</d>');
                if (end < 0) continue;
                let text = substr(body, 0, end);
                if (length(text) < 1 || length(text) > 60) continue;
                let f = split(p, ',');
                if (length(f) < 4) continue;
                let t = num(f[0]);
                let mode = num(f[1]);
                let size = num(f[2]);
                let color = num(f[3]);
                if (t < 0 || t > 86400) continue;
                if (mode < 1 || mode > 5) continue;
                push(out, { t: t, m: mode, s: size, c: color, x: text });
                if (length(out) >= 3000) break;
            }
            return { ok: true, cid: cid, list: out };
        },
        /* 设置面板里的"清空缓存" */
        'GET /clear-cache': function () {
            ctx.sh('rm -f /etc/e5-infoscreen/plugins/bili/cache.mp4 /tmp/bili-cache-id /tmp/bili-req /tmp/bili-dl.mp4 /tmp/bili-dl.res');
            return { ok: true };
        },
        /* ---------- 扫码登录 ---------- */
        /* 生成二维码：拿到 url 和 qrcode_key，二维码由设备上的 qrencode 画成 PNG，
           再把 base64 交给页面显示（插件路由返回二进制不方便）。 */
        'GET /login-qr': function () {
            let raw = ctx.sh("curl -s --max-time 15 -A '" + UA +
                             "' -H 'Referer: " + REFERER +
                             "' 'https://passport.bilibili.com/x/passport-login/web/qrcode/generate'");
            let j = null;
            try { j = json(raw); } catch (e) { return { ok: false, error: 'json' }; }
            if (!j || num(j.code) !== 0) return { ok: false, error: 'api ' + (j ? j.code : '?') };
            let url = `${j.data?.url ?? ''}`;
            let key = `${j.data?.qrcode_key ?? ''}`;
            if (length(url) < 10 || length(url) > 400 || length(key) < 10) return { ok: false, error: 'bad data' };
            let hex = '0123456789abcdefABCDEF';
            for (let i = 0; i < length(key); i++)
                if (index(hex, substr(key, i, 1)) < 0) return { ok: false, error: 'bad key' };
            if (index(url, "'") >= 0 || substr(url, 0, 5) !== 'https') return { ok: false, error: 'bad url' };
            ctx.sh("printf %s '" + key + "' > /tmp/bili-qr-key");
            /* 设备上的 qrencode 没编 PNG 输出，二维码改由页面用 JS 画，
               这里只把登录地址和 key 交给前端。 */
            return { ok: true, url: url };
        },
        /* 轮询扫码结果。data.code：86101 未扫、86090 已扫待确认、0 成功、86038 过期。
           成功时从响应头里取 Set-Cookie，落到 600 权限的本地文件。 */
        'GET /login-poll': function (req) {
            let key = trim(`${ctx.sh('cat /tmp/bili-qr-key 2>/dev/null') ?? ''}`);
            /* 允许显式指定 key：页面用默认的，诊断脚本可以指定 */
            let qk = `${req.query?.key ?? ''}`;
            if (length(qk) === 32) {
                let okhex = true;
                for (let i = 0; i < 32; i++) {
                    if (index('0123456789abcdef', substr(qk, i, 1)) < 0) { okhex = false; break; }
                }
                if (okhex) key = qk;
            }
            if (length(key) < 10) return { ok: false, error: 'no qr' };

            /* 每次都用自己的临时文件。以前用固定文件名，两个轮询（页面 + 诊断脚本）
               会互相覆盖，先拿到成功响应的那个读到的却是"已失效"，cookie 就丢了。 */
            let tmp = trim(`${ctx.sh('umask 077; mktemp /tmp/bili-poll.XXXXXX') ?? ''}`);
            if (length(tmp) < 8) return { ok: false, error: 'tmp' };
            let hdr = tmp + '.h', body = tmp + '.b', jar = tmp + '.jar';
            ctx.sh("curl -s --max-time 15 -c " + jar + " -D " + hdr + " -o " + body +
                   " -A '" + UA + "' -H 'Referer: " + REFERER +
                   "' 'https://passport.bilibili.com/x/passport-login/web/qrcode/poll?qrcode_key=" + key + "'");
            let raw = `${ctx.sh('cat ' + body + ' 2>/dev/null') ?? ''}`;
            let h = `${ctx.sh('cat ' + hdr + ' 2>/dev/null') ?? ''}`;
            let jarS = `${ctx.sh('cat ' + jar + ' 2>/dev/null') ?? ''}`;
            ctx.sh('rm -f ' + hdr + ' ' + body + ' ' + jar);

            let j = null;
            try { j = json(raw); } catch (e) { return { ok: false, error: 'json' }; }
            if (!j || num(j.code) !== 0) return { ok: false, error: 'api ' + (j ? j.code : '?') };
            let code = num(j.data?.code);
            /* up_* 是 B 站原始状态码，方便判断卡在哪一步（不含凭据） */
            let up = { up_code: code, up_msg: `${j.data?.message ?? ''}`, key: substr(key, 0, 6) };
            if (code === 86101) return { ok: true, state: 'waiting', up: up };
            if (code === 86090) return { ok: true, state: 'scanned', up: up };
            if (code === 86038) return { ok: true, state: 'expired', up: up };
            if (code !== 0) return { ok: true, state: 'pending', up: up };

            /* cookie 的来源有三处，命中即用：
               1) 响应头的 Set-Cookie（实测走这条）；
               2) 响应 JSON 的 data.url 查询串；
               3) curl -c 落的 cookie jar。 */
            let u = `${j.data?.url ?? ''}`;
            let names = ['SESSDATA', 'bili_jct', 'DedeUserID'];
            let vals = [];
            for (let n in names) {
                let k = names[n] + '=';
                let v = '';
                let at = index(h, k);
                if (at >= 0) {
                    let rest = substr(h, at + length(k));
                    let cut = index(rest, ';');
                    v = cut < 0 ? rest : substr(rest, 0, cut);
                } else {
                    at = index(u, k);
                    if (at >= 0) {
                        let rest = substr(u, at + length(k));
                        let cut = index(rest, '&');
                        v = cut < 0 ? rest : substr(rest, 0, cut);
                    } else {
                        let tab = index(jarS, '\t' + names[n] + '\t');
                        if (tab >= 0)
                            v = substr(jarS, tab + length(names[n]) + 2);
                    }
                }
                let nl = index(v, '\n');
                if (nl >= 0) v = substr(v, 0, nl);
                let cr = index(v, '\r');
                if (cr >= 0) v = substr(v, 0, cr);
                let qt = index(v, '"');
                if (qt >= 0) v = substr(v, 0, qt);
                push(vals, trim(v));
            }

            if (length(vals[0]) < 10 && length(u) > 20 && index(u, 'http') === 0 && index(u, "'") < 0) {
                /* 有些场景 cookie 只在跨域地址上才下发，照浏览器再走一次 */
                let t2 = trim(`${ctx.sh('umask 077; mktemp /tmp/bili-poll.XXXXXX') ?? ''}`);
                if (length(t2) > 8) {
                    ctx.sh("curl -s --max-time 15 -c " + t2 + " -o /dev/null -A '" + UA +
                           "' -H 'Referer: " + REFERER + "' '" + u + "'");
                    let j2 = `${ctx.sh('cat ' + t2 + ' 2>/dev/null') ?? ''}`;
                    ctx.sh('rm -f ' + t2);
                    for (let n2 in names) {
                        if (length(vals[n2]) >= 10) continue;
                        let tab2 = index(j2, '\t' + names[n2] + '\t');
                        if (tab2 < 0) continue;
                        let v2 = substr(j2, tab2 + length(names[n2]) + 2);
                        let nl2 = index(v2, '\n');
                        if (nl2 >= 0) v2 = substr(v2, 0, nl2);
                        let cr2 = index(v2, '\r');
                        if (cr2 >= 0) v2 = substr(v2, 0, cr2);
                        vals[n2] = trim(v2);
                    }
                }
            }

            if (length(vals[0]) < 10 || length(vals[1]) < 10)
                return { ok: true, state: 'nocookie',
                         dbg: { hdr: length(h), url: length(u), jar: length(jarS),
                                sess: length(vals[0]), jct: length(vals[1]) } };
            let cookie = 'SESSDATA=' + vals[0] + '; bili_jct=' + vals[1] + '; DedeUserID=' + vals[2];
            if (index(cookie, "'") >= 0) return { ok: false, error: 'bad cookie' };
            ctx.sh("umask 077; printf %s '" + cookie + "' > " + COOKIE_FILE +
                   "; chmod 600 " + COOKIE_FILE);
            ctx.sh('rm -f /tmp/bili-qr-key');
            let nav = api_get('/x/web-interface/nav');
            let nj = null;
            try { nj = json(nav); } catch (e) { }
            let uname = `${nj?.data?.uname ?? ''}`;
            return { ok: true, state: 'ok', uname: uname, vip: num(nj?.data?.vipStatus) };
        },
        /* 页面进来时问一次：现在是不是已登录、叫什么名字 */
        'GET /login-state': function () {
            if (user_cookie() === '') return { ok: true, logged: false };
            let raw = api_get('/x/web-interface/nav');
            let j = null;
            try { j = json(raw); } catch (e) { return { ok: true, logged: false }; }
            if (num(j?.code) !== 0 || num(j?.data?.isLogin) !== 1) return { ok: true, logged: false };
            return { ok: true, logged: true, uname: `${j.data.uname ?? ''}`,
                     vip: num(j.data.vipStatus), level: num(j.data.level_info?.current_level) };
        },
        'GET /logout': function () {
            ctx.sh('rm -f ' + COOKIE_FILE);
            return { ok: true };
        },
        /* 跳过广告：用 BilibiliSponsorBlock 社区库（PiliPlus 用的也是这套）。
           返回 [{cat,a,b}]，单位秒；没有数据时返回空数组，前端就不用管。 */
        'GET /segments': function (req) {
            let bvid = `${req.query?.bvid ?? ''}`;
            if (bad_bvid(bvid)) return { ok: false, error: 'bad bvid' };
            let r = ctx.sh("curl -s --max-time 12 'https://bsbsb.top/api/skipSegments?service=bilibili&categories=%5B%22sponsor%22%2C%22selfpromo%22%2C%22intro%22%2C%22outro%22%2C%22interaction%22%5D&videoID=" + bvid + "'");
            let j = null;
            try { j = json(r); } catch (e) { return { ok: true, list: [] }; }
            if (type(j) !== 'array') return { ok: true, list: [] };
            let out = [];
            for (let s in j) {
                let seg = s.segment ?? [];
                if (length(seg) < 2) continue;
                push(out, { cat: `${s.category ?? ''}`, a: num(seg[0]), b: num(seg[1]) });
            }
            return { ok: true, list: out };
        },
        /* 播放状态探针，方便在没有截图的情况下确认视频真的在播 */
        'POST /probe': function (req) {
            let b = req.body ?? {};
            let line = sprintf('%J\n', { t: time(), status: `${b.status ?? ''}`, info: `${b.info ?? ''}` });
            try {
                let f = open('/tmp/bili-probe.log', 'a', 0o644);
                if (!f) return { ok: false };
                f.write(line);
                f.close();
                return { ok: true };
            } catch (e) { return { ok: false, error: `${e}` }; }
        }
    };
};

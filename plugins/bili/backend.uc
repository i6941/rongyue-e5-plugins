'use strict';
import { open } from 'fs';
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
    function cookie_hdr() {
        let b = buvid3();
        return b === '' ? '' : " -H 'Cookie: buvid3=" + b + "'";
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
                    pic: `${it.pic ?? ''}`,
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
                let pic = `${it.pic ?? ''}`;
                if (substr(pic, 0, 2) === '//') pic = 'https:' + pic;
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
            let q = api_get('/x/player/playurl?bvid=' + bvid + '&cid=' + cid + '&qn=32&fnval=0&platform=html5');
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
            let q = api_get('/x/player/playurl?bvid=' + bvid + '&cid=' + cid + '&qn=32&fnval=0&platform=html5');
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
            ctx.sh('start-stop-daemon -K -q -p /var/run/bili-dl.pid; rm -f /var/run/bili-dl.pid ' +
                   res + ' ' + tmp);
            let script = "curl -s --max-time 180 --max-filesize 200000000 -A '" + UA +
                         "' -H 'Referer: " + REFERER + "' -o " + tmp +
                         " -w '%{http_code} %{size_download}' '" + u + "' > " + res;
            ctx.sh('start-stop-daemon -S -q -b -m -p /var/run/bili-dl.pid -x /bin/sh -- -c "' +
                   script + '"');
            return { ok: true, state: 'downloading', quality: num(j.data.quality) };
        },
        /* 前端每秒问一次：下载完了没有 */
        'GET /ready': function () {
            let out = '/etc/e5-infoscreen/plugins/bili/cache.mp4';
            let r = trim(`${ctx.sh('cat /tmp/bili-dl.res 2>/dev/null') ?? ''}`);
            if (r === '') return { ok: true, ready: false, state: 'downloading' };
            let parts = split(r, ' ');
            let code = `${parts[0] ?? '0'}`;
            let size = num(parts[1]);
            if (code !== '200' || size < 1024)
                return { ok: true, ready: false, state: 'failed', code: code };
            ctx.sh('mv -f /tmp/bili-dl.mp4 ' + out + '; rm -f /tmp/bili-dl.res');
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
            ctx.sh('start-stop-daemon -K -q -p /var/run/e5play.pid; rm -f /var/run/e5play.pid');
            ctx.sh('start-stop-daemon -S -q -b -m -p /var/run/e5play.pid -x ' + bin +
                   ' -- --serve ' + mp4 + ' 9511');
            return { ok: true, port: 9511 };
        },
        /* 退出播放时一定要停掉：一个插件目录里只常驻一个解码进程 */
        'GET /player-stop': function () {
            ctx.sh('start-stop-daemon -K -q -p /var/run/e5play.pid; rm -f /var/run/e5play.pid');
            return { ok: true };
        },
        /* 封面代理：同样的 Referer 问题 */
        'GET /img': function (req) {
            let u = `${req.query?.u ?? ''}`;
            if (!host_ok(u, IMG_DOMAINS)) return { status: 403, type: 'text/plain', body: 'host not allowed' };
            let tmp = '/tmp/bili-img.jpg';
            ctx.sh('rm -f ' + tmp);
            let r = ctx.sh("curl -s --max-time 20 -A '" + UA + "' -H 'Referer: " + REFERER + "' -o " + tmp +
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

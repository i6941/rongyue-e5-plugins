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
    function user_csrf() {
        let u = user_cookie();
        let i = index(u, 'bili_jct=');
        if (i < 0) return '';
        let rest = substr(u, i + 9);
        let j = index(rest, ';');
        return j >= 0 ? substr(rest, 0, j) : rest;
    }
    function user_mid() {
        let u = user_cookie();
        let i = index(u, 'DedeUserID=');
        if (i < 0) return '';
        let rest = substr(u, i + 11);
        let j = index(rest, ';');
        return j >= 0 ? substr(rest, 0, j) : rest;
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

    /* ---- 首页推荐：B站新版接口要求 wbi 签名（wts + w_rid） ---- */
    const WBI_TAB = [46,47,18,2,53,8,23,32,15,50,10,31,58,3,45,35,27,43,5,49,33,9,42,19,
                     29,28,14,39,12,38,41,13,37,48,7,16,24,55,40,61,26,17,0,1,60,51,30,4,
                     22,25,54,21,56,59,6,63,57,62,11,36,20,34,44,52];

    /* 从 https://i0.hdslb.com/bfs/wbi/7cd084941338484aae1ad9425b84077c.png 取 key */
    function wbi_base(u) {
        let parts = split(`${u ?? ''}`, '/');
        if (!length(parts)) return '';
        let last = `${parts[length(parts) - 1] ?? ''}`;
        let seg = split(last, '.');
        return `${seg[0] ?? ''}`;
    }

    function wbi_keys() {
        let cached = trim(`${ctx.sh('cat /tmp/bili-wbi 2>/dev/null') ?? ''}`);
        let parts = split(cached, ' ');
        if (length(parts) >= 2 && length(`${parts[0]}`) == 32 && length(`${parts[1]}`) == 32)
            return [ `${parts[0]}`, `${parts[1]}` ];
        let j = null;
        try { j = json(api_get('/x/web-interface/nav')); } catch (e) { }
        let img = wbi_base(j?.data?.wbi_img?.img_url);
        let sub = wbi_base(j?.data?.wbi_img?.sub_url);
        if (length(img) < 16 || length(sub) < 16) return [];
        ctx.sh("printf '%s %s' '" + img + "' '" + sub + "' > /tmp/bili-wbi");
        return [ img, sub ];
    }

    function wbi_sign(params) {
        let ks = wbi_keys();
        if (length(ks) < 2) return '';
        let raw = `${ks[0]}${ks[1]}`;
        let mix = '';
        for (let i = 0; i < 64; i++) mix += substr(raw, WBI_TAB[i], 1);
        mix = substr(mix, 0, 32);
        let names = keys(params);
        sort(names);
        let q = '';
        for (let n in names) {
            if (length(q)) q += '&';
            q += `${n}=${params[n]}`;
        }
        /* 签的是 query + mixinKey，两段一起哈希 */
        let tmp = trim(`${ctx.sh('mktemp /tmp/bili-wbiq.XXXXXX 2>/dev/null') ?? ''}`);
        if (!length(tmp) || index(tmp, '/tmp/bili-wbiq.') < 0) return '';
        ctx.sh("printf '%s' '" + q + mix + "' > " + tmp);
        let rid = trim(`${ctx.sh('md5sum ' + tmp + ' | cut -c1-32') ?? ''}`);
        ctx.sh('rm -f ' + tmp);
        if (length(rid) != 32) return '';
        return q + '&w_rid=' + rid;
    }

    /* 列表项统一成页面要的形状；推荐流里混着番剧，没 bvid 的直接跳过 */
    function feed_item(it, out) {
        let bvid = `${it?.bvid ?? ''}`;
        if (substr(bvid, 0, 2) !== 'BV') return;
        push(out, {
            bvid: bvid,
            title: `${it?.title ?? ''}`,
            author: `${it?.owner?.name ?? ''}`,
            pic: httpsify(`${it?.pic ?? ''}`),
            dur: num(it?.duration),
            play: num(it?.stat?.view),
            cid: 0
        });
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

        /* 个性化推荐：登录后是千人千面，未登录时是通用推荐 */
        'GET /recommend': function (req) {
            let ps = num(req.query?.ps);
            if (ps < 6 || ps > 30) ps = 20;
            let params = {
                web_location: '1430650', y_num: '5', fresh_type: '4', feed_version: 'V8',
                fresh_idx: `${num(req.query?.idx) > 0 ? num(req.query.idx) : 1}`,
                fresh_idx_1h: '1', brush: '0', homepage_ver: '1',
                ps: `${ps}`, last_y_num: '5', screen: '320x480', seo_info: '', fetch_row: '1',
                wts: `${time()}`
            };
            let q = wbi_sign(params);
            if (length(q) < 10) return { ok: false, error: 'wbi' };
            let raw = api_get('/x/web-interface/wbi/index/top/feed/rcmd?' + q);
            let j = null;
            try { j = json(raw); } catch (e) { return { ok: false, error: 'bad json' }; }
            if (!j || num(j.code) !== 0) return { ok: false, error: 'api ' + (j ? j.code : '?') };
            let out = [];
            for (let it in (j.data?.item ?? [])) feed_item(it, out);
            return { ok: true, list: out };
        },
        /* 热门 */
        'GET /popular': function (req) {
            let pn = num(req.query?.pn);
            if (pn < 1) pn = 1;
            let raw = api_get('/x/web-interface/popular?ps=20&pn=' + pn);
            let j = null;
            try { j = json(raw); } catch (e) { return { ok: false, error: 'bad json' }; }
            if (!j || num(j.code) !== 0) return { ok: false, error: 'api ' + (j ? j.code : '?') };
            let out = [];
            for (let it in (j.data?.list ?? [])) feed_item(it, out);
            return { ok: true, list: out };
        },

        /* 字幕：B站把字幕放在 player/v2 里，且需要登录（未登录 need_login_subtitle=true） */
        'GET /subtitle': function (req) {
            let bvid = `${req.query?.bvid ?? ''}`;
            let cid = num(req.query?.cid);
            if (bad_bvid(bvid)) return { ok: false, error: 'bad bvid' };
            if (!cid) return { ok: false, error: 'no cid' };
            /* 必须走签名接口：未签名的 /x/player/v2 在登录态下会随机返回别的视频的字幕 */
            let q = wbi_sign({ bvid: bvid, cid: `${cid}`, wts: `${time()}` });
            /* 不回退到未签名接口：那条路实测会返回别的视频的字幕，宁可不显示 */
            if (length(q) < 10) return { ok: false, error: 'wbi' };
            let j = null;
            try { j = json(api_get('/x/player/wbi/v2?' + q)); } catch (e) { }
            if (!j || num(j.code) !== 0) return { ok: false, error: 'api' };
            /* 这个接口会把实际返回的 bvid/cid 一起带上；对不上就说明拿的不是这部片子的字幕 */
            let gotCid = num(j.data?.cid);
            let gotBvid = `${j.data?.bvid ?? ''}`;
            if (gotCid && gotCid !== cid) return { ok: false, error: 'cid mismatch' };
            if (length(gotBvid) > 2 && gotBvid !== bvid) return { ok: false, error: 'bvid mismatch' };
            let need_login = j.data?.need_login_subtitle === true;
            let tracks = j.data?.subtitle?.subtitles ?? [];
            /* 多轨时优先人工中文，其次 AI 中文，最后才是第一条 */
            let manual = null, zh = null, any = null;
            for (let t in tracks) {
                if (!t?.subtitle_url) continue;
                let lan = `${t?.lan ?? ''}`;
                if (!any) any = t;
                if (!zh && index(lan, 'zh') >= 0) zh = t;
                if (!manual && index(lan, 'ai') < 0 && index(lan, 'zh') >= 0) manual = t;
            }
            let first = manual ? manual : (zh ? zh : any);
            if (!first) return { ok: true, need_login: need_login, lan: '', list: [] };
            let u = `${first.subtitle_url ?? ''}`;
            if (substr(u, 0, 2) === '//') u = 'https:' + u;
            if (!host_ok(u, IMG_DOMAINS) || index(u, "'") >= 0) return { ok: false, error: 'bad url' };
            /* 每次请求单独一个临时文件：共用一个文件时，curl 失败会把上一个视频的字幕留下来 */
            let tmp = trim(`${ctx.sh('mktemp /tmp/bili-sub.XXXXXX 2>/dev/null') ?? ''}`);
            if (!length(tmp) || index(tmp, '/tmp/bili-sub.') < 0) return { ok: false, error: 'tmp' };
            let code = trim(`${ctx.sh("curl -s -o " + tmp + " -w '%{http_code}' --max-time 20 -A '" + UA + "' '" + u + "'") ?? ''}`);
            if (code !== '200') { ctx.sh('rm -f ' + tmp); return { ok: false, error: 'sub http ' + code }; }
            let raw = '';
            try { raw = readfile(tmp) ?? ''; } catch (e) { }
            ctx.sh('rm -f ' + tmp);
            if (length(raw) < 20) return { ok: false, error: 'sub empty' };
            let sj = null;
            try { sj = json(raw); } catch (e) { }
            if (!sj || type(sj.body) !== 'array') return { ok: false, error: 'sub json' };
            let out = [];
            for (let line in (sj.body ?? [])) {
                let t = `${line?.content ?? ''}`;
                if (length(t) < 1) continue;
                push(out, { a: num(line?.from) * 1000, b: num(line?.to) * 1000, t: t });
                if (length(out) >= 4000) break;
            }
            return { ok: true, need_login: false, lan: `${first.lan ?? ''}`, list: out };
        },
        /* 视频互动关系：点赞、收藏状态 */
        'GET /relation': function (req) {
            let bvid = `${req.query?.bvid ?? ''}`;
            if (bad_bvid(bvid)) return { ok: false, error: 'bad bvid' };
            let raw = api_get('/x/web-interface/archive/relation?bvid=' + bvid);
            let j = null;
            try { j = json(raw); } catch (e) { return { ok: false, error: 'bad json' }; }
            if (!j || num(j.code) !== 0) return { ok: false, error: 'api' };
            let d = j.data ?? {};
            return { ok: true, like: d.like === true, favorite: d.favorite === true };
        },
        /* 点赞 / 取消点赞 */
        'POST /like': function (req) {
            let b = req.body ?? {};
            let bvid = `${b.bvid ?? ''}`;
            let like = num(b.like);
            if (bad_bvid(bvid)) return { ok: false, error: 'bad bvid' };
            let csrf = user_csrf();
            if (!length(csrf)) return { ok: false, login: true, error: '未登录' };
            let raw = ctx.sh("curl -s -m 15 -X POST -A '" + UA + "'" + cookie_hdr() +
                             " -H 'Referer: " + REFERER + "' " +
                             "--data 'bvid=" + bvid + "&like=" + (like == 2 ? 2 : 1) + "&csrf=" + csrf + "' " +
                             "'https://api.bilibili.com/x/web-interface/archive/like'");
            let j = null;
            try { j = json(raw); } catch (e) { return { ok: false, error: 'bad json' }; }
            if (!j || num(j.code) !== 0) return { ok: false, error: j?.message ?? 'api' };
            return { ok: true, like: like !== 2 };
        },
        /* 收藏 / 取消收藏到默认收藏夹 */
        'POST /favorite': function (req) {
            let b = req.body ?? {};
            let bvid = `${b.bvid ?? ''}`;
            let fav = b.fav === true || b.fav === 1;
            if (bad_bvid(bvid)) return { ok: false, error: 'bad bvid' };
            let csrf = user_csrf();
            let mid = user_mid();
            if (!length(csrf) || !length(mid)) return { ok: false, login: true, error: '未登录' };

            let rawV = api_get('/x/web-interface/view?bvid=' + bvid);
            let jv = null;
            try { jv = json(rawV); } catch (e) { return { ok: false, error: 'view json' }; }
            let aid = num(jv?.data?.aid);
            if (!aid) return { ok: false, error: 'no aid' };

            let rawF = api_get('/x/v3/fav/folder/created/list-all?up_mid=' + mid);
            let jf = null;
            try { jf = json(rawF); } catch (e) { return { ok: false, error: 'folder json' }; }
            let fid = num(jf?.data?.list?.[0]?.id);
            if (!fid) return { ok: false, error: 'no folder' };

            let postData = 'rid=' + aid + '&type=2&csrf=' + csrf + (fav ? ('&add_media_ids=' + fid) : ('&del_media_ids=' + fid));
            let rawD = ctx.sh("curl -s -m 15 -X POST -A '" + UA + "'" + cookie_hdr() +
                              " -H 'Referer: " + REFERER + "' " +
                              "--data '" + postData + "' " +
                              "'https://api.bilibili.com/x/v3/fav/resource/deal'");
            let jd = null;
            try { jd = json(rawD); } catch (e) { return { ok: false, error: 'deal json' }; }
            if (!jd || num(jd.code) !== 0) return { ok: false, error: jd?.message ?? 'api' };
            return { ok: true, favorite: fav };
        },
        /* 相关视频推荐：基于当前视频的关联推荐流 */
        'GET /related': function (req) {
            let bvid = `${req.query?.bvid ?? ''}`;
            if (bad_bvid(bvid)) return { ok: false, error: 'bad bvid' };
            let raw = api_get('/x/web-interface/archive/related?bvid=' + bvid);
            let j = null;
            try { j = json(raw); } catch (e) { return { ok: false, error: 'bad json' }; }
            if (!j || num(j.code) !== 0) return { ok: false, error: 'api ' + (j ? j.code : '?') };
            let out = [];
            for (let it in (j.data ?? [])) {
                let v = it?.videos;
                push(out, {
                    bvid: `${it?.bvid ?? ''}`,
                    title: `${it?.title ?? ''}`,
                    author: `${it?.owner?.name ?? ''}`,
                    pic: httpsify(`${it?.pic ?? ''}`),
                    dur: num(it?.duration),
                    play: num(it?.stat?.view),
                    cid: 0
                });
                if (length(out) >= 30) break;
            }
            return { ok: true, list: out };
        },
        /* 视频评论区：获取主楼热门/排序评论 */
        'GET /comments': function (req) {
            let bvid = `${req.query?.bvid ?? ''}`;
            let pn = num(req.query?.pn);
            if (pn < 1) pn = 1;
            let aid = num(req.query?.aid);
            if (!aid) {
                if (bad_bvid(bvid)) return { ok: false, error: 'bad bvid' };
                let rv = api_get('/x/web-interface/view?bvid=' + bvid);
                let jv = null;
                try { jv = json(rv); } catch (e) { return { ok: false, error: 'view' }; }
                aid = num(jv?.data?.aid);
            }
            if (!aid) return { ok: false, error: 'no aid' };
            let raw = api_get('/x/v2/reply?type=1&oid=' + aid + '&sort=1&pn=' + pn + '&ps=20');
            let j = null;
            try { j = json(raw); } catch (e) { return { ok: false, error: 'bad json' }; }
            if (!j || num(j.code) !== 0) return { ok: false, error: 'api ' + (j ? j.code : '?') };
            let d = j.data ?? {};
            let out = [];
            for (let r in (d.replies ?? [])) {
                let m = r?.member ?? {};
                let c = r?.content ?? {};
                push(out, {
                    rpid: `${r?.rpid ?? ''}`,
                    uname: `${m?.uname ?? ''}`,
                    avatar: httpsify(`${m?.avatar ?? ''}`),
                    message: `${c?.message ?? ''}`,
                    like: num(r?.like),
                    ctime: num(r?.ctime),
                    rcount: num(r?.rcount)
                });
            }
            return {
                ok: true,
                count: num(d.page?.count),
                list: out
            };
        },
        /* 分区入口列表（去掉了无内容的直播） */
        'GET /regions': function () {
            return { ok: true, list: [
                { key: 'anime', name: '番剧', season_type: 1 },
                { key: 'guochuang', name: '国创', season_type: 4 },
                { key: 'movie', name: '电影', season_type: 2 },
                { key: 'tv', name: '电视剧', season_type: 5 },
                { key: 'doc', name: '纪录片', season_type: 3 },
                { key: 'douga', name: '动画', rid: 1 },
                { key: 'game', name: '游戏', rid: 4 },
                { key: 'music', name: '音乐', rid: 3 },
                { key: 'dance', name: '舞蹈', rid: 129 },
                { key: 'tech', name: '科技', rid: 188 },
                { key: 'life', name: '生活', rid: 160 },
                { key: 'cinephile', name: '影视', rid: 181 }
            ] };
        },
        /* PGC 剧集列表（番剧/国创/电影/电视剧/纪录片）：走 /pgc/season/index/result */
        'GET /pgc': function (req) {
            let st = num(req.query?.season_type);
            if (st < 1 || st > 10) st = 1;
            let raw = api_get('/pgc/season/index/result?type=1&season_type=' + st + '&page=1&pagesize=20');
            let j = null;
            try { j = json(raw); } catch (e) { return { ok: false, error: 'bad json' }; }
            if (!j || num(j.code) !== 0) return { ok: false, error: 'api ' + (j ? j.code : '?') };
            let out = [];
            for (let it in (j.data?.list ?? [])) {
                let badge = `${it.badge_info?.text ?? it.badge ?? ''}`;
                let show = `${it.index_show ?? ''}`;
                let sub = `${it.subTitle ?? it.order ?? ''}`;
                let author = length(badge) ? (badge + (length(show) ? ' · ' + show : '')) : show;
                push(out, {
                    ssid: num(it.season_id),
                    bvid: '',
                    title: `${it.title ?? ''}`,
                    author: author,
                    pic: httpsify(`${it.cover ?? ''}`),
                    dur: 0,
                    durtxt: sub,
                    play: 0,
                    cid: 0,
                    is_pgc: true
                });
                if (length(out) >= 20) break;
            }
            return { ok: true, list: out };
        },
        /* PGC 剧集分集详情：按 season_id 取每一集的 bvid 和 cid */
        'GET /season': function (req) {
            let ssid = num(req.query?.ssid);
            if (!ssid) return { ok: false, error: 'no ssid' };
            let raw = api_get('/pgc/view/web/season?season_id=' + ssid);
            let j = null;
            try { j = json(raw); } catch (e) { return { ok: false, error: 'bad json' }; }
            if (!j || num(j.code) !== 0) return { ok: false, error: 'api ' + (j ? j.code : '?') };
            let res = j.result ?? {};
            let sTitle = `${res.title ?? ''}`;
            let out = [];
            for (let ep in (res.episodes ?? [])) {
                let epTitle = `${ep.title ?? ''}`;
                let longTitle = `${ep.long_title ?? ''}`;
                let fullTitle = epTitle + (length(longTitle) ? (' ' + longTitle) : '');
                push(out, {
                    bvid: `${ep.bvid ?? ''}`,
                    cid: num(ep.cid),
                    title: fullTitle,
                    author: sTitle,
                    pic: httpsify(`${ep.cover ?? ''}`),
                    dur: num(ep.duration) > 0 ? num(ep.duration) / 1000 : 0,
                    play: 0
                });
            }
            return { ok: true, season_title: sTitle, list: out };
        },
        /* 某个分区的视频（走排行榜的 rid 过滤，不需要额外签名） */
        'GET /region': function (req) {
            let rid = num(req.query?.rid);
            if (rid < 0) rid = 0;
            let raw = api_get('/x/web-interface/ranking/v2?rid=' + rid + '&type=all');
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
        /* 直播分区推荐：用直播专区接口，不靠推荐流过滤 */
        'GET /live': function () {
            let raw = api_get('/x/web-interface/wbi/index/top/feed/rcmd?ps=20&fresh_type=4&feed_version=V8');
            let j = null;
            try { j = json(raw); } catch (e) { }
            let out = [];
            /* 推荐流里 goto=live 的项就是直播间；没有就返回空，页面显示提示 */
            for (let it in (j?.data?.item ?? [])) {
                let g = `${it?.goto ?? ''}`;
                if (g !== 'live') continue;
                push(out, {
                    bvid: '', title: `${it?.title ?? ''}`, author: `${it?.uname ?? ''}`,
                    pic: httpsify(`${it?.cover ?? ''}`), dur: 0, play: num(it?.online),
                    cid: 0, live: true
                });
                if (length(out) >= 20) break;
            }
            return { ok: true, list: out };
        },
        /* 观看历史：必须登录，未登录时返回 login:true 让页面提示去扫码 */
        'GET /history': function (req) {
            let pn = num(req.query?.pn);
            if (pn < 1) pn = 1;
            let raw = api_get('/x/web-interface/history/cursor?ps=20&pn=' + pn + '&type=archive');
            let j = null;
            try { j = json(raw); } catch (e) { return { ok: false, error: 'bad json' }; }
            if (!j) return { ok: false, error: 'api' };
            if (num(j.code) === -101 || num(j.code) === -400) return { ok: false, login: true, error: '需要登录' };
            if (num(j.code) !== 0) return { ok: false, error: 'api ' + `${j.code ?? '?'}` };
            let out = [];
            for (let it in (j.data?.list ?? [])) {
                let h = it?.history ?? {};
                let bvid = `${h.bvid ?? ''}`;
                if (substr(bvid, 0, 2) !== 'BV') continue;
                push(out, {
                    bvid: bvid,
                    title: `${it?.title ?? ''}`,
                    author: `${it?.author_name ?? ''}`,
                    pic: httpsify(`${it?.cover ?? ''}`),
                    dur: num(it?.duration),
                    play: 0,
                    cid: num(it?.videos) > 0 ? 0 : 0,
                    progress: num(h.view_at) > 0 ? num(h.progress) : -1,
                    viewed: num(it?.view_at)
                });
                if (length(out) >= 20) break;
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
            /* 画质用页面传来的值（16/32/64/80/112） */
            let qn = num(req.query?.qn);
            if (qn !== 16 && qn !== 32 && qn !== 64 && qn !== 80 && qn !== 112) qn = 80;
            let q = api_get('/x/player/playurl?bvid=' + bvid + '&cid=' + cid + '&qn=' + qn +
                            '&fnval=0&platform=pc&fourk=1');
            let j = null;
            try { j = json(q); } catch (e) { }
            let d = j?.data?.durl?.[0];
            /* 电影、番剧、电视剧等版权内容（PGC）在普通接口会报 -404 啥都木有，
               必须走 /pgc/player/web/playurl 才能拿到流 */
            if (!d || !d.url) {
                let q_pgc = api_get('/pgc/player/web/playurl?bvid=' + bvid + '&cid=' + cid + '&qn=' + qn + '&fnval=0');
                let j_pgc = null;
                try { j_pgc = json(q_pgc); } catch (e) { }
                d = j_pgc?.result?.durl?.[0] ?? j_pgc?.data?.durl?.[0];
                if (!d || !d.url) {
                    let err = j_pgc?.message ?? j?.message ?? (j ? 'playurl ' + j.code : 'no durl');
                    return { ok: false, error: err };
                }
            }
            let u = `${d.url}`;
            if (!host_ok(u, VID_DOMAINS) || index(u, "'") >= 0) return { ok: false, error: 'bad url' };

            let dir = '/etc/e5-infoscreen/plugins/bili';
            let out = dir + '/cache.mp4';
            let res = '/tmp/bili-dl.res';
            /* 同一个视频已经缓存过就直接用，别每次重下几十上百 MB */
            let id = bvid + ' ' + cid;
            let cached = trim(`${ctx.sh('cat /tmp/bili-cache-id 2>/dev/null') ?? ''}`);
            let have = num(`${ctx.sh('wc -c < ' + out + ' 2>/dev/null') ?? '0'}`);
            /* 快进续传过的缓存中间有空洞：文件大小够了但内容不全，
               当缓存用会播到缺口就停，所以有空洞一律重下 */
            let hole = num(`${ctx.sh('cat /tmp/bili-hole 2>/dev/null') ?? '0'}`);
            ctx.sh("echo '" + id + "' > /tmp/bili-req");
            let v2_raw = api_get('/x/player/v2?bvid=' + bvid + '&cid=' + cid);
            let v2_j = null;
            try { v2_j = json(v2_raw); } catch (e) { }
            let cloud_ms = num(v2_j?.data?.last_play_time);

            if (cached === id && have > 1048576 && !(hole > 0))
                return { ok: true, state: 'cached', size: have, cid: cid, cloud_ms: cloud_ms };
            /* 边下边播：直接写 cache.mp4，播放器读这个正在增长的文件 */
            ctx.sh('start-stop-daemon -K -q -p /var/run/bili-dl.pid; rm -f /var/run/bili-dl.pid ' + res);
            ctx.sh('rm -f ' + out);
            let script = "curl -s --max-time 1800 --retry 3 --retry-delay 2 --max-filesize 900000000 -A '" + UA +
                         "' -H 'Referer: " + REFERER + "'" + cookie_hdr() + " -o " + out +
                         " -w '%{http_code} %{size_download}' '" + u + "' > " + res;
            ctx.sh('start-stop-daemon -S -q -b -m -p /var/run/bili-dl.pid -x /bin/sh -- -c "' +
                   script + '"');
            /* 记下直链和总大小：快进时要按字节位置续传 */
            ctx.sh("printf '%s' '" + u + "' > /tmp/bili-url");
            ctx.sh('rm -f /tmp/bili-total /tmp/bili-hole');
            return { ok: true, state: 'downloading', quality: num(j.data.quality), cid: cid, cloud_ms: cloud_ms };
        },

        /* 云端播放进度上报（心跳）：同步到 B 站账号个人观看历史 */
        'POST /heartbeat': function (req) {
            let b = req.body ?? {};
            let bvid = `${b.bvid ?? ''}`;
            let cid = num(b.cid);
            let played = num(b.played_time);
            if (bad_bvid(bvid) || !cid) return { ok: false, error: 'bad args' };
            let csrf = user_csrf();
            if (!length(csrf)) return { ok: false, login: true, error: '未登录' };
            let postData = 'bvid=' + bvid + '&cid=' + cid + '&played_time=' + played +
                           '&realtime=' + played + '&start_ts=' + time() + '&csrf=' + csrf;
            let raw = ctx.sh("curl -s -m 10 -X POST -A '" + UA + "'" + cookie_hdr() +
                             " -H 'Referer: " + REFERER + "' --data '" + postData +
                             "' 'https://api.bilibili.com/x/click-interface/web/heartbeat'");
            let j = null;
            try { j = json(raw); } catch (e) { }
            return { ok: true, synced: j?.code === 0 };
        },
        /* 快进到还没下载的位置：按时间估算字节位置，从那里续传。
           跳过的部分不需要下载——原来顺序下载必须把中间几十兆等完。 */
        'GET /seek': function (req) {
            let ms = num(req.query?.ms);
            let dur = num(req.query?.dur);
            if (!(ms > 0) || !(dur > 0)) return { ok: false, error: 'bad args' };
            let dir = '/etc/e5-infoscreen/plugins/bili';
            let out = dir + '/cache.mp4';
            let url = trim(`${ctx.sh('cat /tmp/bili-url 2>/dev/null') ?? ''}`);
            if (length(url) < 10) return { ok: false, error: 'no url' };
            let have = num(`${ctx.sh('wc -c < ' + out + ' 2>/dev/null') ?? '0'}`);
            let total = num(`${ctx.sh('cat /tmp/bili-total 2>/dev/null') ?? '0'}`);
            if (!(total > 0)) {
                ctx.sh("curl -s -D - -o /dev/null -r 0-0 -A '" + UA + "' -H 'Referer: " + REFERER + "'" + cookie_hdr() +
                       " '" + url + "' > /tmp/bili-head");
                /* upos 返回的响应头是小写 content-range，awk 的模式匹配区分大小写，
                   原来写 /Content-Range/ 永远匹配不到，total 一直是 0，
                   续传因此一直被 "no size" 拒绝。 */
                total = num(`${ctx.sh("tr -d '\\r' < /tmp/bili-head | awk -F/ 'tolower($0) ~ /content-range/ {print $2}'") ?? '0'}`);
                if (total > 0) ctx.sh("echo '" + total + "' > /tmp/bili-total");
            }
            if (!(total > 0)) return { ok: false, error: 'no size' };
            /* 留 2MB 余量：估出来的位置可能落在关键帧之后 */
            let off = (total * ms) / dur - 2097152;
            if (off < 0) off = 0;
            off = off - (off % 65536);
            let hole = num(`${ctx.sh('cat /tmp/bili-hole 2>/dev/null') ?? '0'}`);
            let covered = off <= have;
            if (hole > 0 && off < hole) covered = false;
            if (covered) return { ok: true, need: false, off: off };
            /* 关键：MP4 的索引（moov）在文件头，通常 6MB 左右。
               以前这里直接杀掉顺序下载再跳到目标位置续传，结果索引只下到
               不到 1MB 就被掐断，文件头变成大片空洞（0 字节）。
               播放器读到的 moov 是空的，解析出 frames=0，连上后一帧都发不
               出来就断开——这才是"正在索引/播放中"来回跳的真正原因。
               所以：先让文件头落盘（16MB 足够放下 6MB 的 moov），
               再切到目标位置续传。 */
            let sh = '/tmp/bili-range.sh';
            let f = open(sh, 'w', 0o755);
            if (!f) return { ok: false, error: 'script' };
            f.write("#!/bin/sh\n" +
                    "OUT=" + out + "\n" +
                    "BUSY=/opt/e5/bin/busybox\n" +
                    "# 判断文件头是否真的有效：moov 里不该有大段空白。\n" +
                    "# 只比文件大小是不够的——dd seek= 会在截断过的文件上造出稀疏空洞，\n" +
                    "# 大小看着很大，索引区却全是 0，播放器照样解析出 frames=0。\n" +
                    "head_ok() {\n" +
                    "  [ -f $OUT ] || return 1\n" +
                    "  N=$(dd if=$OUT bs=1024 skip=1024 count=4 2>/dev/null | tr -d '\\000' | wc -c)\n" +
                    "  [ \"$N\" -gt 512 ] || return 1\n" +
                    "  N2=$(dd if=$OUT bs=1024 skip=4096 count=4 2>/dev/null | tr -d '\\000' | wc -c)\n" +
                    "  [ \"$N2\" -gt 512 ] || return 1\n" +
                    "  return 0\n" +
                    "}\n" +
                    "# 1. 等顺序下载把文件头写好，最多 30 秒\n" +
                    "i=0\n" +
                    "while [ $i -lt 150 ]; do\n" +
                    "  head_ok && break\n" +
                    "  $BUSY sleep 0.2\n" +
                    "  i=$((i+1))\n" +
                    "done\n" +
                    "# 2. 头还是坏的：停掉顺序下载，自己把 0-16MB 补回来\n" +
                    "if ! head_ok; then\n" +
                    "  start-stop-daemon -K -q -p /var/run/bili-dl.pid 2>/dev/null\n" +
                    "  rm -f /var/run/bili-dl.pid\n" +
                    "  $BUSY sleep 1\n" +
                    "  curl -s --max-time 400 -A '" + UA + "' -H 'Referer: " + REFERER + "'" +
                    cookie_hdr() + " -r 0-16777215 '" + url + "' | dd of=$OUT bs=65536 seek=0 conv=notrunc 2>/dev/null\n" +
                    "fi\n" +
                    "# 3. 停掉顺序下载，从目标位置续传（两个进程同时写会互相踩）\n" +
                    "start-stop-daemon -K -q -p /var/run/bili-dl.pid 2>/dev/null\n" +
                    "rm -f /var/run/bili-dl.pid\n" +
                    "curl -s --max-time 1800 -A '" + UA + "' -H 'Referer: " + REFERER + "'" +
                    cookie_hdr() + " -r " + off + "- '" + url + "' | dd of=$OUT" +
                    " bs=65536 seek=" + sprintf('%d', off / 65536) + " conv=notrunc 2>/dev/null\n");
            f.close();
            ctx.sh("echo '" + off + "' > /tmp/bili-hole");
            /* 用独立的 pid 文件：脚本要杀的是 bili-dl，不能把自己的 pid 写进去 */
            ctx.sh('start-stop-daemon -S -q -b -m -p /var/run/bili-range.pid -x /bin/sh -- ' + sh);
            return { ok: true, need: true, off: off, have: have };
        },
        /* 前端每秒问一次：够不够开播／下完没有。
           边下边播：下载直接写 cache.mp4，够 12MB 就先让播放器读，
           剩下的在播放过程中继续写。 */
        'GET /ready': function (req) {
            /* 起播门槛：页面传 wk（KB），默认 512KB。实测下载约 3MB/s，
               512KB 半秒内就到；e5play 读的是增长中的文件，不用等整段。 */
            let wk = num(req.query?.wk);
            if (wk < 256 || wk > 65536) wk = 512;
            let need = wk * 1024;
            let out = '/etc/e5-infoscreen/plugins/bili/cache.mp4';
            let cur = trim(`${ctx.sh('cat /tmp/bili-req 2>/dev/null') ?? ''}`);
            let cached = trim(`${ctx.sh('cat /tmp/bili-cache-id 2>/dev/null') ?? ''}`);
            let bytes = num(`${ctx.sh('wc -c < ' + out + ' 2>/dev/null') ?? '0'}`);
            let r = trim(`${ctx.sh('cat /tmp/bili-dl.res 2>/dev/null') ?? ''}`);
            if (r !== '') {
                let parts = split(r, ' ');
                let code = `${parts[0] ?? '0'}`;
                let size = num(parts[1]);
                if (code === '200' && size >= 1024) {
                    ctx.sh('rm -f /tmp/bili-dl.res; cat /tmp/bili-req 2>/dev/null > /tmp/bili-cache-id');
                    return { ok: true, ready: true, size: size };
                }
                return { ok: true, ready: false, state: 'failed', code: code, bytes: bytes };
            }
            if (cur !== '' && cur === cached && bytes > 1048576)
                return { ok: true, ready: true, cached: true, size: bytes };
            let pidf = trim(`${ctx.sh('cat /var/run/bili-dl.pid 2>/dev/null') ?? ''}`);
            let alive = 'no';
            if (length(pidf) > 0)
                alive = trim(`${ctx.sh('kill -0 ' + pidf + ' 2>/dev/null && echo yes') ?? ''}`);
            /* 12MB 大约够几十秒，下载速度远高于码率，够撑到后面写完 */
            if (bytes >= need)
                return { ok: true, ready: true, partial: alive === 'yes', size: bytes };
            if (alive === 'yes')
                return { ok: true, ready: false, state: 'downloading', bytes: bytes };
            return { ok: true, ready: false, state: 'failed', code: 'interrupted', bytes: bytes };
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
        'GET /player-start': function (req) {
            /* 输出尺寸跟着页面当前的横竖屏走：画布多大就输出多大，页面不再缩放 */
            let max = num(req.query?.max);
            if (max < 64 || max > 1920) max = 480;
            /* 声音起进程到出声的延迟（毫秒）：e5play 用它把视频时钟往后压，
               让快进/恢复后音画仍然对齐 */
            let lead = num(req.query?.lead);
            if (lead < 0 || lead > 1000) lead = 120;
            let dir = '/etc/e5-infoscreen/plugins/bili';
            let bin = dir + '/e5play';
            let mp4 = dir + '/cache.mp4';
            if (trim(`${ctx.sh('test -x ' + bin + ' && echo yes') ?? ''}`) !== 'yes')
                return { ok: false, error: 'no player binary' };
            if (trim(`${ctx.sh('test -s ' + mp4 + ' && echo yes') ?? ''}`) !== 'yes')
                return { ok: false, error: 'no cached video' };
            /* 文件头校验：索引区如果是空的（上一次续传在索引写完前就把
               顺序下载砍掉了，留下大片零），播放器会解析出 0 帧，连上之后
               一帧都发不出来。这里提前判定并报错，让页面重新准备文件，
               而不是让前端反复重连空转。 */
            let h1 = num(`${ctx.sh("dd if=" + mp4 + " bs=1024 skip=1024 count=4 2>/dev/null | tr -d '\\\\000' | wc -c") ?? '0'}`);
            let h2 = num(`${ctx.sh("dd if=" + mp4 + " bs=1024 skip=4096 count=4 2>/dev/null | tr -d '\\\\000' | wc -c") ?? '0'}`);
            if (h1 < 512 || h2 < 512)
                return { ok: false, error: 'index-broken' };
            if (!stop_player()) return { ok: false, error: '旧播放器没退出' };
            ctx.sh('start-stop-daemon -S -q -b -m -p /var/run/e5play.pid -x ' + bin +
                   ' -- --serve ' + mp4 + ' 9511 --max ' + max + ' --audio-lead ' + lead);
            return { ok: true, port: 9511 };
        },
        /* 退出播放时一定要停掉：一个插件目录里只常驻一个解码进程 */
        'GET /player-stop': function () {
            return { ok: true, stopped: stop_player() };
        },
        /* 丢弃缓存（索引损坏时用）：删文件 + 清掉所有"缓存有效"的标记，
           否则下一次 prepare 会以为还有可用缓存而直接返回 cached。 */
        'GET /drop': function () {
            ctx.sh('start-stop-daemon -K -q -p /var/run/bili-dl.pid 2>/dev/null; rm -f /var/run/bili-dl.pid');
            ctx.sh('start-stop-daemon -K -q -p /var/run/bili-range.pid 2>/dev/null; rm -f /var/run/bili-range.pid');
            ctx.sh('rm -f /etc/e5-infoscreen/plugins/bili/cache.mp4 /tmp/bili-cache-id ' +
                   '/tmp/bili-hole /tmp/bili-total /tmp/bili-dl.res');
            return { ok: true };
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

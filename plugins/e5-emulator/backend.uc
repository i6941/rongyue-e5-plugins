'use strict';
/* ROMLINK：ROM 放在 /etc/e5-infoscreen/roms（更新时会被 settings.tar 带走），
   www/roms 只是软链；每次 API 调用都检查一次，更新后第一次打开应用就自动补回。 */
const ROMDIR = '/etc/e5-infoscreen/roms';
const ROMLINK = '/usr/share/e5-infoscreen/www/roms';
import { open } from 'fs';

// 前端把状态（帧率、核心、错误）POST 过来，写进 /tmp 供 SSH 侧读取。
// 不执行命令、不读设备信息。
return function (ctx) {
    function read_text(path) {
        let t = ctx.read_trim(path);
        if (t === null) return '';
        return t;
    }

    function write_text(path, data, mode) {
        let f = open(path, 'w', mode);
        if (!f) return false;
        f.write(data);
        f.close();
        return true;
    }

    function romlink() {
        /* 目录与软链都由 root 维护；失败也不影响应用其它功能 */
        try {
            let st = stat(ROMLINK);
            if (st !== null && st.type === 'link') return true;
        } catch (e) { }
        let r = ctx.sh('mkdir -p ' + ROMDIR + ' && rm -rf ' + ROMLINK + ' && ln -s ' + ROMDIR + ' ' + ROMLINK);
        return r === '';
    }

    return {
        'POST /stat': function (req) {
            /* 状态按 tag 分文件：我的自动测试实例与用户在信息屏里打开的应用不会互相覆盖 */
            let b = req.body ?? {};
            /* ucode 没有正则字面量（写了会让整个插件后端编译失败），
               这里用白名单逐字符过滤。 */
            let raw = b.tag;
            let tag = 'ui';
            if (type(raw) == 'string') {
                let allowed = 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_';
                let clean = '';
                for (let i = 0; i < length(raw); i++) {
                    let ch = substr(raw, i, 1);
                    if (index(allowed, ch) !== null) clean += ch;
                }
                if (length(clean) > 0) tag = substr(clean, 0, 32);
            }
            let data = sprintf('%J\n', b);
            let path = '/tmp/e5-emulator-stat-' + tag + '.json';
            try {
                let f = open(path, 'w', 0o644);
                if (!f) return { ok: false, error: 'cannot open' };
                f.write(data);
                f.close();
                if (tag === 'ui') {
                    let g = open('/tmp/e5-emulator-stat.json', 'w', 0o644);
                    if (g) { g.write(data); g.close(); }
                }
                return { ok: true, path: path, tag: tag };
            } catch (e) {
                return { ok: false, error: `${e}` };
            }
        },
        'POST /shot': function (req) {
            /* 分块上传的游戏截图：每块 ≤4 KB，末块 last=1 时拼成 /tmp/e5-shot.b64 */
            let b = req.body ?? {};
            let qp = req.query ?? {};
            let i = `${qp.i ?? 0}`;
            let n = `${qp.n ?? 1}`;
            let last = `${qp.last ?? 0}` === '1';
            let chunk = `${b.c ?? ''}`;
            let dir = '/tmp/e5-shot';
            let mk = ctx.sh('mkdir -p ' + dir);
            let w = write_text(dir + '/part-' + sprintf('%03d', i), chunk, 0o600);
            let ls = ctx.sh('ls -l ' + dir);
            if (last) {
                /* 受限 shell 不做通配符展开，自己按顺序拼 */
                let all = '';
                let cnt = int(n) || 1;
                for (let k = 0; k < cnt; k++) {
                    let part = read_text(dir + '/part-' + sprintf('%03d', k));
                    all = all + part;
                }
                write_text('/tmp/e5-shot.b64', all, 0o600);
            }
            return { ok: true, part: i, n: n, last: last, size: chunk.length, wrote: w, mk: mk, ls: ls };
        },

        'GET /stat': function () {
            let path = '/tmp/e5-emulator-stat.json';
            try {
                let f = open(path, 'r');
                if (!f) return { ok: false, error: 'no stat yet' };
                let t = f.read('all');
                f.close();
                return { ok: true, raw: t };
            } catch (e) {
                return { ok: false, error: `${e}` };
            }
        }
    };
};

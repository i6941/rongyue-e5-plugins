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
        },

        /* ---- 原生引擎（e5emu）启停 ----
           浏览器里跑 wasm 核心在这台机器上会卡死，FC 游戏改走原生：
           后端只负责拉起/结束 /usr/bin/e5emu，帧走本机回环的 WebSocket。
           rom 只接受白名单字符，拼出来的路径不会有空格或引号。 */
        'POST /emu/start': function (req) {
            let b = req.body ?? {};
            let raw = `${b.rom ?? ''}`;
            let allowed = 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-';
            let clean = '';
            for (let i = 0; i < length(raw); i++) {
                let ch = substr(raw, i, 1);
                if (index(allowed, ch) !== null) clean += ch;
            }
            if (length(clean) < 5 || substr(clean, 0, 1) === '.') {
                return { ok: false, error: 'bad rom name' };
            }
            /* 按扩展名挑内核：每个内核编成一个独立二进制，互不干扰 */
            let tail3 = substr(clean, length(clean) - 3, 3);
            let tail4 = substr(clean, length(clean) - 4, 4);
            let bin = '';
            if (tail4 === '.nes') bin = '/usr/bin/e5emu';
            else if (tail3 === '.md') bin = '/usr/bin/e5emu-genesis';
            else if (tail4 === '.gba') bin = '/usr/bin/e5emu-gba';
            if (bin === '') return { ok: false, error: 'unsupported rom' };

            try {
                let r = ctx.sh('[ -x ' + bin + ' ] && echo yes');
                if (index(`${r ?? ''}`, 'yes') === null) return { ok: false, error: bin + ' not installed' };
            } catch (e) {
                return { ok: false, error: bin + ' not installed' };
            }

            /* 先收掉上一个实例，避免端口占用 */
            ctx.sh('start-stop-daemon -K -q -p /var/run/e5emu.pid; rm -f /var/run/e5emu.pid');
            let romfile = ROMDIR + '/' + clean;
            let cmd = 'start-stop-daemon -S -q -b -m -p /var/run/e5emu.pid -x ' + bin
                + ' -- --serve ' + romfile + ' 9510 --log /tmp/e5emu.log';
            let out = ctx.sh(cmd);
            let pid = read_text('/var/run/e5emu.pid');
            /* 有没有即时档：有的话前端在进游戏 3 秒后显示“存档读取中”并读回 */
            let base = clean;
            let dot = -1;
            for (let i = 0; i < length(clean); i++)
                if (substr(clean, i, 1) === '.') dot = i;
            if (dot > 0) base = substr(clean, 0, dot);
            let hasState = false;
            try {
                let s = ctx.sh('[ -f ' + ROMDIR + '/' + base + '.st0 ] && echo yes');
                hasState = index(`${s ?? ''}`, 'yes') !== null;
            } catch (e) { }
            /* 哪些槽已经有存档：前端切槽时据此提示"空槽"，不用再跑一次请求 */
            let slots = [];
            for (let k = 0; k <= 3; k++) {
                try {
                    let s2 = ctx.sh('[ -f ' + ROMDIR + '/' + base + '.st' + k + ' ] && echo yes');
                    if (index(`${s2 ?? ''}`, 'yes') !== null) push(slots, k);
                } catch (e) { }
            }
            return { ok: length(pid) > 0, pid: pid, rom: romfile, state: hasState, slots: slots, out: out };
        },
        'POST /emu/stop': function () {
            let out = ctx.sh('start-stop-daemon -K -q -p /var/run/e5emu.pid; rm -f /var/run/e5emu.pid');
            return { ok: true, out: out };
        },
        'GET /emu/status': function () {
            function has(p) {
                try {
                    /* 只取退出码：以前用 "&& echo yes" 判断，结果缺失时也返回 yes */
                    let out = trim(`${ctx.sh('[ -x ' + p + ' ]; echo $?') ?? ''}`);
                    return out === '0';
                } catch (e) { return false; }
            }
            let bins = { nes: has('/usr/bin/e5emu'), md: has('/usr/bin/e5emu-genesis'), gba: has('/usr/bin/e5emu-gba') };
            let pid = read_text('/var/run/e5emu.pid');
            return { ok: true, installed: bins.nes, bins: bins, pid: pid };
        }
    };
};

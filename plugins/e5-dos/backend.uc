'use strict';
/* plugins/e5-dos/backend.uc — 独立 DOS 游戏专用后端
 * 专用 DOSBox-Pure 核心，启动前彻底清理占用，确保各游戏独立稳定运行。
 */
const ROMDIR = '/etc/e5-infoscreen/roms';
const ROMLINK = '/usr/share/e5-infoscreen/www/roms';
const BIN = '/usr/bin/e5emu-dos';
const PIDFILE = '/var/run/e5emu.pid';

import { open } from 'fs';

return function (ctx) {
    function trim(s) {
        if (!s) return '';
        let i = 0, j = length(s) - 1;
        while (i <= j && (substr(s, i, 1) === ' ' || substr(s, i, 1) === '\n' || substr(s, i, 1) === '\r' || substr(s, i, 1) === '\t')) i++;
        while (j >= i && (substr(s, j, 1) === ' ' || substr(s, j, 1) === '\n' || substr(s, j, 1) === '\r' || substr(s, j, 1) === '\t')) j--;
        return (i <= j) ? substr(s, i, j - i + 1) : '';
    }

    function clean_all_cores() {
        ctx.sh('killall -9 e5emu-pal e5emu-dos e5emu e5emu-arcade e5emu-gba e5emu-genesis paplay 2>/dev/null; rm -f /var/run/e5emu.pid /var/run/e5pal.pid');
        for (let i = 0; i < 30; i++) {
            let busy = '';
            try { busy = trim(`${ctx.sh('netstat -ltn 2>/dev/null | grep -c ":9510 "') ?? '0'}`); } catch (e) { busy = '0'; }
            if (busy === '0' || busy === '') break;
            ctx.sh('sleep 0.1');
        }
    }

    return {
        'POST /stat': function (req) {
            let b = req.body ?? {};
            let data = sprintf('%J\n', b);
            try {
                let f = open('/tmp/e5-emulator-stat-ui.json', 'w', 0o644);
                if (f) { f.write(data); f.close(); }
            } catch (e) {}
            return { ok: true };
        },

        'GET /stat': function () {
            let path = '/tmp/e5-emulator-stat-ui.json';
            try {
                let f = open(path, 'r');
                if (!f) return { ok: false, error: 'no stat' };
                let txt = f.read('all');
                f.close();
                return { ok: true, data: txt };
            } catch (e) {
                return { ok: false, error: `${e}` };
            }
        },

        'POST /emu/start': function (req) {
            let b = req.body ?? {};
            let raw = b.rom ?? '';
            let allowed = 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_./';
            let clean = '';
            for (let i = 0; i < length(raw); i++) {
                let ch = substr(raw, i, 1);
                if (index(allowed, ch) >= 0) clean += ch;
            }
            if (length(clean) < 3 || index(clean, '..') >= 0) {
                return { ok: false, error: 'bad rom name' };
            }

            clean_all_cores();

            try {
                let r = ctx.sh('[ -x ' + BIN + ' ] && echo yes');
                if (index(`${r ?? ''}`, 'yes') < 0) return { ok: false, error: 'e5emu-dos not installed' };
            } catch (e) {
                return { ok: false, error: 'check failed' };
            }

            let romfile = ROMDIR + '/' + clean;
            try {
                let exist = trim(`${ctx.sh('[ -e ' + romfile + ' ] && echo yes') ?? ''}`);
                if (exist !== 'yes') return { ok: false, error: 'rom not found: ' + clean };
            } catch (e) {
                return { ok: false, error: 'cannot check rom' };
            }

            let cmd = 'start-stop-daemon -S -q -b -m -p ' + PIDFILE + ' -x ' + BIN
                    + ' -- --serve ' + romfile + ' 9510 --log /tmp/e5emu.log';
            ctx.sh(cmd);

            /* 等待 9510 就绪 */
            for (let i = 0; i < 40; i++) {
                let listening = '';
                try { listening = trim(`${ctx.sh('netstat -ltn 2>/dev/null | grep -c ":9510 "') ?? '0'}`); } catch (e) { listening = '0'; }
                if (listening !== '0' && listening !== '') break;
                ctx.sh('sleep 0.1');
            }

            let pid = '';
            try {
                let f = open(PIDFILE, 'r');
                if (f) { pid = trim(f.read('all') ?? ''); f.close(); }
            } catch (e) {}

            return { ok: length(pid) > 0, pid: pid, rom: romfile };
        },

        'POST /emu/stop': function (req) {
            clean_all_cores();
            return { ok: true };
        },

        'GET /emu/status': function (req) {
            let running = false;
            try {
                let count = trim(`${ctx.sh('pgrep -f e5emu-dos 2>/dev/null | wc -l') ?? '0'}`);
                running = (+count > 0);
            } catch (e) {}
            return { running: running, installed: { dos: true } };
        }
    };
};

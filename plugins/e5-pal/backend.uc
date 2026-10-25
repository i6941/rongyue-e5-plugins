'use strict';
/* plugins/e5-pal/backend.uc — 独立仙剑奇侠传专属极简后端
 * 仅负责 /usr/bin/e5emu-pal 核心的拉起与终止，彻底杜绝多机种干扰与僵尸进程。
 */
import { open } from 'fs';

const ROMDIR = '/etc/e5-infoscreen/roms/pal';
const BIN = '/usr/bin/e5emu-pal';
const PIDFILE = '/var/run/e5pal.pid';

return function (ctx) {
    function trim(s) {
        if (!s) return '';
        let i = 0, j = length(s) - 1;
        while (i <= j && (substr(s, i, 1) === ' ' || substr(s, i, 1) === '\n' || substr(s, i, 1) === '\r' || substr(s, i, 1) === '\t')) i++;
        while (j >= i && (substr(s, j, 1) === ' ' || substr(s, j, 1) === '\n' || substr(s, j, 1) === '\r' || substr(s, j, 1) === '\t')) j--;
        return (i <= j) ? substr(s, i, j - i + 1) : '';
    }

    function clean_all_cores() {
        /* 彻底清场：终止所有可能占着端口的进程 */
        ctx.sh('killall -9 e5emu-pal e5emu-dos e5emu e5emu-arcade e5emu-gba e5emu-genesis paplay 2>/dev/null; rm -f /var/run/e5emu.pid /var/run/e5pal.pid');
        for (let i = 0; i < 30; i++) {
            let busy = '';
            try { busy = trim(`${ctx.sh('netstat -ltn 2>/dev/null | grep -c ":9510 "') ?? '0'}`); } catch (e) { busy = '0'; }
            if (busy === '0' || busy === '') break;
            ctx.sh('sleep 0.1');
        }
    }

    return {
        'POST /emu/start': function (req) {
            clean_all_cores();

            try {
                let exist = trim(`${ctx.sh('[ -x ' + BIN + ' ] && echo yes') ?? ''}`);
                if (exist !== 'yes') return { ok: false, error: 'e5emu-pal not found' };
            } catch (e) {
                return { ok: false, error: 'check failed' };
            }

            let cmd = 'start-stop-daemon -S -q -b -m -p ' + PIDFILE + ' -d ' + ROMDIR + ' -x /usr/bin/env -- '
                    + 'SDL_VIDEODRIVER=offscreen SDL_AUDIODRIVER=disk ' + BIN + ' 9510 >/tmp/pal.log 2>&1';
            ctx.sh(cmd);

            /* 等待 9510 端口就绪 */
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

            return { ok: length(pid) > 0, pid: pid };
        },

        'POST /emu/stop': function (req) {
            clean_all_cores();
            return { ok: true };
        },

        'GET /emu/status': function (req) {
            let running = false;
            try {
                let count = trim(`${ctx.sh('pgrep -f e5emu-pal 2>/dev/null | wc -l') ?? '0'}`);
                running = (+count > 0);
            } catch (e) {}
            return { running: running };
        }
    };
};

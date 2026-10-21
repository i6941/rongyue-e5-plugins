'use strict';
import { open } from 'fs';

/*
 * 「保号 · 推送」的后端。
 *
 * 只做 LuCI 里没有的两件事，底层全部交给设备已有的机制：
 *   - giffgaff 保号：按间隔发一条短信（/usr/libexec/e5-sms send），可选由 crontab 周期执行
 *   - PushPlus 推送：复用 e5-notify 的 forward（收到新短信就 curl 出去），只是把目标填成 pushplus
 *
 * 短信收发、号码转发、APN、SIM 管理都在 LuCI 里，这里不重复实现。
 * 写到设备上的地方只有三处：/etc/config/e5-keepalive（本应用的设置）、
 * /etc/e5-keepalive/pushplus.token（token，0600）、/etc/crontabs/root（一行计划任务）。
 *
 * 插件沙箱里 ctx.sh(cmd) 返回的是**输出字符串**（不是 api.uc 内部的 {rc,out}），
 * ctx.sh_json 返回解析后的 JSON；ucode 没有 undefined/popopen/typeof，字符串也没有方法。
 */

const CFG = 'e5-keepalive';
const DIR = '/etc/e5-infoscreen/keepalive';   /* 放在会被更新保留的目录里 */
const TOKEN = DIR + '/pushplus.token';
const LASTSEND = DIR + '/last-send-time';
const CRONFILE = '/etc/crontabs/root';
const CRON_MARK = 'e5-keepalive-send';
const SENDHELPER = '/usr/libexec/e5-keepalive-send';
const FORWARD_LOG = '/tmp/run/e5-sms/forward.log';
const UNREAD = '/tmp/run/e5-sms/unread';
const LASTSEND_JSON = '/tmp/e5-keepalive/last-send.json';
const CONF = DIR + '/keepalive.conf';

const HELPER = '#!/bin/sh\n' +
'# 定时保号：由 crontab 调用，也可以手动执行。\n' +
'# 设置读 /etc/e5-keepalive/keepalive.conf（自己的 key=value 文件）。\n' +
'# 按间隔判断是否该发，然后走 e5-sms send；只有发送成功才记时间戳。\n' +
'STATE=/etc/e5-keepalive\n' +
'CONF=$STATE/keepalive.conf\n' +
'mkdir -p $STATE /tmp/e5-keepalive\n' +
'get() { sed -n "s/^$1=//p" "$CONF" 2>/dev/null | head -1; }\n' +
'num=$(get number)\n' +
'[ -z "$num" ] && exit 0\n' +
'days=$(get days); [ -z "$days" ] && days=30\n' +
'card=$(get card); [ -z "$card" ] && card=0\n' +
'txt=$(get text); [ -z "$txt" ] && txt=keepalive\n' +
'now=$(date +%s)\n' +
'last=$(cat $STATE/last-send-time 2>/dev/null || echo 0)\n' +
'if [ $(( now - last )) -lt $(( days * 86400 )) ]; then exit 0; fi\n' +
'f=$(mktemp) || exit 1\n' +
"printf '%s' \"$txt\" > \"$f\"\n" +
'/usr/libexec/e5-sms send "$num" "$f" "$card" > /tmp/e5-keepalive/last-send.json 2>&1\n' +
'# e5-sms 失败时也会返回 0，要看返回的 JSON 里的 ok\n' +
'if grep -q \'"ok": true\' /tmp/e5-keepalive/last-send.json 2>/dev/null; then\n' +
'\techo $now > $STATE/last-send-time\n' +
'fi\n' +
'rm -f "$f"\n';

return function (ctx) {
    function sh(cmd) {
        let r = ctx.sh(cmd);
        if (type(r) === 'string') return r;
        return '';
    }

    function sh_json(cmd) {
        let r = ctx.sh_json(cmd);
        if (r === null) return null;
        return r;
    }

    /* ucode 里不存在的键给的是字符串 "null"（不是 null），用它来分辨“没传” */
    function pick(qp, k, cur) {
        let v = qp[k];
        if (v === null) return cur;
        return `${v}`;
    }

    function q(s) {
        return "'" + replace(`${s}`, "'", "'\\''") + "'";
    }

    function uci_get(cfg, section, option, def) {
        let v = trim(sh('uci -q get ' + q(cfg + '.' + section + '.' + option)));
        if (v === '') return def;
        return v;
    }

    function uci_set_raw(cfg, section, option, value) {
        /* 只对已经存在的配置文件用（uci 不能凭空建文件）：键不加引号，值加引号 */
        let key = cfg + '.' + section + '.' + option;
        sh('uci -q set ' + key + '=' + q(`${value}`));
        sh('uci -q commit ' + q(cfg));
    }

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

    /* 自己的设置写自己的 key=value 文件：uci 建不了新配置文件 */
    function conf_read() {
        let out = { number: '', text: 'keepalive', days: '30', card: '0', enabled: '0' };
        let lines = split(read_text(CONF), '\n');
        for (let i = 0; i < length(lines); i++) {
            let l = trim(lines[i]);
            if (l === '' || substr(l, 0, 1) === '#') continue;
            let p = index(l, '=');
            if (p < 0) continue;
            let k = trim(substr(l, 0, p));
            let v = trim(substr(l, p + 1));
            if (k === 'number' || k === 'text' || k === 'days' || k === 'card' || k === 'enabled') out[k] = v;
        }
        return out;
    }

    function conf_write(c) {
        let body = '# 保号 · 推送 的设置（由 /usr/share/e5-infoscreen/www/plugins/e5-keepalive 维护）\n' +
            'number=' + (c.number ?? '') + '\n' +
            'text=' + (c.text ?? 'keepalive') + '\n' +
            'days=' + (c.days ?? 30) + '\n' +
            'card=' + (c.card ?? 0) + '\n' +
            'enabled=' + (c.enabled ? 1 : 0) + '\n';
        sh('mkdir -p ' + q(DIR));
        return write_text(CONF, body, 0o600);
    }

    function now_seconds() {
        let v = trim(sh('date +%s'));
        if (v === '') return 0;
        return int(v);
    }

    function join_lines(parts) {
        let out = '';
        for (let i = 0; i < length(parts); i++) {
            if (i > 0) out = out + '\n';
            out = out + parts[i];
        }
        return out;
    }

    function token_state() {
        let t = trim(read_text(TOKEN));
        if (t === '') return { present: false, tail: '' };
        return { present: true, tail: substr(t, length(t) - 4) };
    }

    function keepalive_cfg() {
        let c = conf_read();
        /* 计划任务不在更新保留范围内：只要配置里 enabled=1，每次调用都补回 crontab 行 */
    function cron_selfheal() {
        let c = conf_read();
        if (c.enabled !== '1') return;
        let st = cron_state();
        if (!st.installed) cron_set(true);
    }

    return {
            number: c.number,
            text: c.text,
            days: c.days,
            card: c.card,
            enabled: c.enabled === '1'
        };
    }

    function forward_cfg() {
        return {
            enabled: uci_get('e5-notify', 'forward', 'enabled', '0') === '1',
            url: uci_get('e5-notify', 'forward', 'url', ''),
            method: uci_get('e5-notify', 'forward', 'method', 'POST'),
            content_type: uci_get('e5-notify', 'forward', 'content_type', 'application/json'),
            body: uci_get('e5-notify', 'forward', 'body', ''),
            timeout: uci_get('e5-notify', 'forward', 'timeout', '10')
        };
    }

    function cron_state() {
        let parts = split(read_text(CRONFILE), '\n');
        let line = '';
        for (let i = 0; i < length(parts); i++) {
            if (index(parts[i], 'e5-keepalive-send') >= 0) line = trim(parts[i]);
        }
        return { installed: line !== '', line: line };
    }

    function sim_state() {
        let o = { modem: null, active_card: 0, cards: [], unread: 0, err: [] };
        try {
            let unread = 0;
            let ul = split(read_text(UNREAD), '\n');
            for (let i = 0; i < length(ul); i++) if (trim(ul[i]) !== '') unread++;
            o.unread = unread;
        } catch (e) { push(o.err, 'unread: ' + `${e}`); }
        try { o.modem = ctx.modem(); } catch (e) { push(o.err, 'modem: ' + `${e}`); }
        try { o.active_card = ctx.sim_card(); } catch (e) { push(o.err, 'sim_card: ' + `${e}`); }
        for (let i = 0; i < 2; i++) {
            try {
                let card = { present: false, operator: '', state: '', signal: '' };
                let r = sh_json('mmcli -m ' + i + ' -J');
                if (type(r) === 'object' && r !== null) {
                    if (type(r.modem) === 'object' && r.modem !== null) {
                        let g = r.modem['3gpp'];
                        if (type(g) === 'object' && g !== null) {
                            card.present = true;
                            if (type(g['operator-name']) === 'string') card.operator = g['operator-name'];
                            if (type(g['registration-state']) === 'string') card.state = g['registration-state'];
                            if (type(g['signal-quality']) === 'number') card.signal = `${g['signal-quality']}`;
                        }
                    }
                }
                push(o.cards, card);
            } catch (e) { push(o.err, 'card' + i + ': ' + `${e}`); }
        }
        return o;
    }

    function last_result() {
        let r = read_text(LASTSEND_JSON);
        let t = null;
        if (trim(r) !== '') {
            try { t = json(r); } catch (e) { t = { raw: substr(r, 0, 200) }; }
        }
        return { last: t, last_at: trim(read_text(LASTSEND)) };
    }

    function install_helper() {
        if (!write_text(SENDHELPER, HELPER, 0o755)) return false;
        sh('chmod 755 ' + q(SENDHELPER));
        return true;
    }

    function cron_set(on) {
        sh('mkdir -p /etc/crontabs');
        let parts = split(read_text(CRONFILE), '\n');
        let keep = [];
        for (let i = 0; i < length(parts); i++) {
            if (index(parts[i], 'e5-keepalive-send') < 0) push(keep, parts[i]);
        }
        if (on) {
            if (!install_helper()) return { ok: false, error: 'cannot write ' + SENDHELPER };
            push(keep, '0 9 * * * ' + SENDHELPER);
        }
        let out = join_lines(keep);
        while (length(out) > 0 && substr(out, 0, 1) === '\n') out = substr(out, 1);
        if (length(out) > 0 && substr(out, length(out) - 1) !== '\n') out = out + '\n';
        if (!write_text(CRONFILE, out, 0o600)) return { ok: false, error: 'cannot write ' + CRONFILE };
        sh('chmod 600 ' + q(CRONFILE));
        sh('/etc/init.d/cron restart 2>/dev/null');
        return { ok: true };
    }

    function pushplus_body(token) {
        return '{"token":"' + token + '","title":"E5 短信 {from}","content":"{text} | 时间 {time} | SIM {sim}"}';
    }

    function pushplus_test() {
        let token = trim(read_text(TOKEN));
        if (token === '') return { ok: false, error: '还没有设置 token' };
        let body = '{"token":"' + token + '","title":"E5 测试推送","content":"来自荣悦 E5 的测试推送"}';
        let out = trim(sh('curl -s -m 20 -X POST -H ' + q('Content-Type: application/json') + ' --data ' + q(body) + ' https://www.pushplus.plus/send'));
        let parsed = null;
        try { parsed = json(out); } catch (e) { parsed = { raw: substr(out, 0, 300) }; }
        return { ok: true, response: parsed };
    }

    return {
        'GET /state': function () {
            cron_selfheal();
            return {
                sim: sim_state(),
                keepalive: keepalive_cfg(),
                forward: forward_cfg(),
                token: token_state(),
                cron: cron_state(),
                result: last_result()
            };
        },

        /* 参数都走 URL 查询串：这台设备的 uhttpd→ucode 链路读不到 POST 的 body */
        'GET /keepalive': function (req) {
            let qp = req.query ?? {};
            let cur = conf_read();
            conf_write({
                number: pick(qp, 'number', cur.number),
                text: pick(qp, 'text', cur.text),
                days: pick(qp, 'days', cur.days),
                card: pick(qp, 'card', cur.card),
                enabled: pick(qp, 'enabled', cur.enabled) === '1'
            });
            return { ok: true, keepalive: keepalive_cfg() };
        },

        'GET /keepalive/send': function (req) {
            let qp = req.query ?? {};
            let num = pick(qp, 'number', keepalive_cfg().number);
            if (num === '') return { ok: false, error: '还没有设置目标号码' };
            let text = pick(qp, 'text', keepalive_cfg().text);
            let card = pick(qp, 'card', keepalive_cfg().card);
            let f = '/tmp/e5-keepalive/send.txt';
            write_text(f, text, 0o600);
            let out = trim(sh('/usr/libexec/e5-sms send ' + q(num) + ' ' + q(f) + ' ' + q(card)));
            let parsed = null;
            try { parsed = json(out); } catch (e) { parsed = { raw: substr(out, 0, 300) }; }
            if (type(parsed) === 'object' && parsed !== null && parsed.ok === true) {
                write_text(LASTSEND, `${now_seconds()}`, 0o644);
            }
            return { ok: true, sent: parsed, number: num, card: card };
        },

        'GET /cron': function (req) {
            let qp = req.query ?? {};
            let on = qp.enabled === '1' || qp.enabled === 'true';
            let r = cron_set(on);
            return { ok: r.ok !== false, error: r.error ?? '', cron: cron_state() };
        },

        'GET /forward/off': function () {
            uci_set_raw('e5-notify', 'forward', 'enabled', '0');
            return { ok: true, forward: forward_cfg() };
        },

        'GET /forward/test': function () {
            let out = trim(sh('/usr/libexec/e5-sms forward-test'));
            return { ok: out !== '', output: substr(out, 0, 400) };
        },

        'GET /forward/log': function () {
            let lines = split(read_text(FORWARD_LOG), '\n');
            let out = '';
            let start = length(lines) - 15;
            if (start < 0) start = 0;
            for (let i = start; i < length(lines); i++) out = out + lines[i] + '\n';
            return { log: out };
        },

        'GET /pushplus/enable': function () {
            let token = trim(read_text(TOKEN));
            if (token === '') return { ok: false, error: '还没有设置 token' };
            uci_set_raw('e5-notify', 'forward', 'url', 'https://www.pushplus.plus/send');
            uci_set_raw('e5-notify', 'forward', 'method', 'POST');
            uci_set_raw('e5-notify', 'forward', 'content_type', 'application/json');
            uci_set_raw('e5-notify', 'forward', 'body', pushplus_body(token));
            uci_set_raw('e5-notify', 'forward', 'enabled', '1');
            return { ok: true, forward: forward_cfg() };
        },

        'GET /pushplus/test': function () {
            return pushplus_test();
        },

        /* token 不经 HTTP：只读状态与清除。设置由 root 在设备上写 /etc/e5-keepalive/pushplus.token */
        'GET /token': function (req) {
            let qp = req.query ?? {};
            if (qp.clear === '1') {
                sh('rm -f ' + q(TOKEN));
                return { ok: true, token: token_state() };
            }
            return { ok: true, token: token_state() };
        }
    };
};

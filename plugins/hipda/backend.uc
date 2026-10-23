'use strict';
/* hipda（4D4Y，Discuz! 7.2）后端：只做参数校验和转发。
   抓页面、解析 HTML、保存登录 cookie 都在 e5-hipda（python3）里做，
   因为 ucode 不能写正则字面量。 */
import { open } from 'fs';

return function (ctx) {
    const DIR = '/etc/e5-infoscreen/plugins/hipda';
    const HELPER = DIR + '/e5-hipda';
    /* 登录和回复各用各的临时文件：同一个文件在并发时会互相覆盖 */
    const TMP_LOGIN = '/tmp/e5-hipda-login.json';
    const TMP_REPLY = '/tmp/e5-hipda-reply.json';

    function run(args) {
        let out = `${ctx.sh('python3 ' + HELPER + ' ' + args + ' 2>/dev/null') ?? ''}`;
        if (length(out) < 2) return { ok: false, error: 'helper 没输出' };
        try { return json(out); } catch (e) { return { ok: false, error: 'helper 返回不是 JSON' }; }
    }

    function posint(v) {
        let n = +v;
        if (n !== n || n < 1 || n > 999999999) return 0;
        return n - (n % 1);
    }

    return {
        /* 登录：用户名、密码、安全提问编号和答案放进临时文件（0600），
           由 helper 从 stdin 读，避免密码里的引号被 shell 拆掉。 */
        'POST /login': function (req) {
            let b = req.body ?? {};
            let u = `${b.u ?? ''}`;
            let p = `${b.p ?? ''}`;
            let q = posint(`${b.q ?? '0'}`);
            let a = `${b.a ?? ''}`;
            if (length(u) < 1 || length(u) > 40) return { ok: false, error: '用户名长度不对' };
            if (length(p) < 1 || length(p) > 80) return { ok: false, error: '密码长度不对' };
            if (length(a) > 60) return { ok: false, error: '答案太长' };
            let f = open(TMP_LOGIN, 'w', 0o600);
            if (!f) return { ok: false, error: 'temp' };
            f.write(sprintf('%J', { u: u, p: p, q: q ? q : 0, a: a }));
            f.close();
            let r = run('login < ' + TMP_LOGIN);
            ctx.sh('shred -u ' + TMP_LOGIN + ' 2>/dev/null || rm -f ' + TMP_LOGIN);
            return r;
        },
        /* 图片诊断：页面报告这一帖解析到几张图、实际加载成功/失败几张。
           排查「缩略图不显示」时看 /tmp/e5-hipda-img.log。 */
        'POST /imgprobe': function (req) {
            let b = req.body ?? {};
            let line = sprintf('%J\n', {
                t: time(), tid: '' + (b.tid ?? ''), mode: '' + (b.mode ?? ''),
                n: +(b.n ?? 0), ok: +(b.ok ?? 0), bad: +(b.bad ?? 0),
                src: substr('' + (b.src ?? ''), 0, 300), err: substr('' + (b.err ?? ''), 0, 200)
            });
            try {
                let f = open('/tmp/e5-hipda-img.log', 'a', 0o644);
                if (f) { f.write(line); f.close(); }
            } catch (e) { }
            return { ok: true };
        },
        /* 回复：内容走临时文件交给 helper，和登录同一套做法（避免引号被 shell 拆） */
        'POST /reply': function (req) {
            let b = req.body ?? {};
            let tid = posint(b.tid);
            let msg = '' + (b.message ?? '');
            if (!tid) return { ok: false, error: 'tid 不对' };
            if (length(msg) < 1 || length(msg) > 20000) return { ok: false, error: '内容长度不对' };
            let f = open(TMP_REPLY, 'w', 0o600);
            if (!f) return { ok: false, error: 'temp' };
            f.write(sprintf('%J', { tid: tid, message: msg, dry: b.dry ? 1 : 0 }));
            f.close();
            let r = run('reply < ' + TMP_REPLY);
            ctx.sh('shred -u ' + TMP_REPLY + ' 2>/dev/null || rm -f ' + TMP_REPLY);
            return r;
        },
        'GET /state': function () {
            return run('state');
        },
        'GET /boards': function () {
            return run('boards');
        },
        'GET /threads': function (req) {
            let fid = posint(req.query?.fid);
            let page = posint(req.query?.page);
            if (!fid) return { ok: false, error: 'bad fid' };
            return run('threads ' + fid + ' ' + (page ? page : 1));
        },
        /* 诊断用：抓指定页面返回纯文本，只允许本站路径 */
        'GET /debug': function (req) {
            let u = `${req.query?.url ?? ''}`;
            if (index(u, 'https://www.4d4y.com/forum/') !== 0) return { ok: false, error: 'bad url' };
            let q = u;
            if (index(q, "'") >= 0) return { ok: false, error: 'bad url' };
            return run("debug '" + q + "'");
        },
        'GET /thread': function (req) {
            let tid = posint(req.query?.tid);
            let page = posint(req.query?.page);
            if (!tid) return { ok: false, error: 'bad tid' };
            return run('thread ' + tid + ' ' + (page ? page : 1));
        }
    };
};

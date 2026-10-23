'use strict';
/* hipda（4D4Y，Discuz! 7.2）后端：只做参数校验和转发。
   抓页面、解析 HTML、保存登录 cookie 都在 e5-hipda（python3）里做，
   因为 ucode 不能写正则字面量。 */
import { open } from 'fs';

return function (ctx) {
    const DIR = '/etc/e5-infoscreen/plugins/hipda';
    const HELPER = DIR + '/e5-hipda';
    const TMP = '/tmp/e5-hipda-in.json';

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
            let f = open(TMP, 'w', 0o600);
            if (!f) return { ok: false, error: 'temp' };
            f.write(sprintf('%J', { u: u, p: p, q: q ? q : 0, a: a }));
            f.close();
            let r = run('login < ' + TMP);
            ctx.sh('shred -u ' + TMP + ' 2>/dev/null || rm -f ' + TMP);
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
        'GET /thread': function (req) {
            let tid = posint(req.query?.tid);
            let page = posint(req.query?.page);
            if (!tid) return { ok: false, error: 'bad tid' };
            return run('thread ' + tid + ' ' + (page ? page : 1));
        }
    };
};

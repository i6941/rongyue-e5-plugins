'use strict';

return function(ctx) {
    const tool = '/etc/e5-infoscreen/plugins/nikki-control/control.py';
    function call(action, body) {
        // Shell quoting treats node names as data, including apostrophes.
        let data = replace(sprintf('%J', body ?? {}), /'/g, "'\\''");
        let raw = ctx.sh(`/usr/bin/python3 ${tool} ${action} '${data}' 2>/dev/null`);
        let result;
        try { result = json(raw ?? 'null'); } catch (_) { result = null; }
        if (!result) result = { ok: false, status: 500, error: '控制程序没有返回结果' };
        if (result.ok === false)
            return { status: result.status ?? 500, type: 'application/json', body: sprintf('%J', result) };
        return result;
    }
    return {
        'GET /status': () => call('status'),
        'GET /groups': () => call('groups'),
        'POST /select': req => call('select', req.body),
        'POST /service': req => call('service', req.body),
        'POST /update': () => call('update')
    };
};

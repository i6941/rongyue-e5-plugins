# ucode constraints on the E5

The plugin backends are [ucode](https://openwrt.org/docs/guide-user/developer/ucode)
scripts running under the device's `uhttpd-mod-ucode`. These are the limits that
actually bit us, written down so the next person does not rediscover them.

## No regular-expression literals

`/[0-9]+/` in a ucode source file makes the backend fail with a 500. The regex
literal is not supported syntax there, and the error surfaces at request time, not
at load time — so it looks like "the plugin is broken" rather than "the file has a
syntax error".

Use `index()`, `substr()` and `length()` for allow-list checks instead:

```c
/* reject anything that is not a plain ASCII token */
function ok_token(s) {
    let i;
    for (i = 0; i < length(s); i++) {
        let c = substr(s, i, 1);
        if (c < 'a' || c > 'z') {
            if (c < 'A' || c > 'Z') {
                if (c < '0' || c > '9') {
                    if (c != '_' && c != '-' && c != '.') {
                        return false;
                    }
                }
            }
        }
    }
    return length(s) > 0;
}
```

String comparison is lexicographic on bytes, which is what the checks above rely on.

## No shell arguments for secrets

Passwords are written to a root-only file and read back at runtime. They are never
placed in a command line, because `/proc/<pid>/cmdline` is world-readable on the
device and an argument would leak there.

```sh
install -d -m 700 /etc/e5-keepalive
printf %s 'the-token' > /etc/e5-keepalive/pushplus.token
chmod 600 /etc/e5-keepalive/pushplus.token
```

## Frontend syntax actually available on the device

The panel's WPE build is a full modern engine, but the syntax it is known to accept
is worth stating explicitly, since the deployed plugins are the proof:

- `const` / `let`
- arrow functions
- `async` / `await`
- optional chaining (`?.`)
- `try` / `finally`

## The panel caches pages

`uhttpd` sends no `Cache-Control` header, so WebKit caches the plugin page. After
updating a plugin you must clear the cache or the old build keeps running:

```sh
rm -rf /tmp/run/e5-infoscreen/.cache/wpe/WebKitCache
```

This is the single most common reason "my change did nothing".

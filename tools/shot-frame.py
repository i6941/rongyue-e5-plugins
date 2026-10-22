#!/usr/bin/env python3
"""从 e5emu 帧服务抓一帧真实画面存成 PNG。

用法：python tools/shot-frame.py [端口] [输出文件]
默认连 ws://127.0.0.1:9510，输出 .notes/img/frame-native.png。

帧格式（native/e5emu.c 里定的）：WebSocket 二进制帧，载荷是
宽 u16le + 高 u16le + RGB565 像素（每像素 2 字节，小端，r5 g6 b5）。
"""
import base64
import hashlib
import os
import socket
import struct
import sys
import time

WS_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"


def ws_connect(host, port, timeout=10.0):
    s = socket.create_connection((host, port), timeout)
    s.settimeout(timeout)
    key = base64.b64encode(os.urandom(16)).decode()
    req = (
        "GET / HTTP/1.1\r\nHost: %s:%d\r\nUpgrade: websocket\r\n"
        "Connection: Upgrade\r\nSec-WebSocket-Key: %s\r\n"
        "Sec-WebSocket-Version: 13\r\n\r\n" % (host, port, key)
    )
    s.sendall(req.encode())
    resp = b""
    while b"\r\n\r\n" not in resp:
        chunk = s.recv(1024)
        if not chunk:
            raise RuntimeError("握手过程中连接被关闭")
        resp += chunk
    status = resp.split(b"\r\n")[0].decode("latin-1")
    if "101" not in status:
        raise RuntimeError("握手失败: %s" % status)
    want = base64.b64encode(hashlib.sha1((key + WS_GUID).encode()).digest()).decode()
    if want.lower() not in resp.decode("latin-1").lower():
        raise RuntimeError("Sec-WebSocket-Accept 校验不过")
    return s, resp[resp.find(b"\r\n\r\n") + 4:]


def read_frame(s, leftover=b""):
    """读一个 WebSocket 二进制帧，返回 (载荷, 剩余缓冲)。"""
    buf = leftover

    def need(n):
        nonlocal buf
        while len(buf) < n:
            chunk = s.recv(65536)
            if not chunk:
                raise RuntimeError("连接被关闭")
            buf += chunk

    need(2)
    b0, b1 = buf[0], buf[1]
    opcode = b0 & 0x0F
    masked = b1 & 0x80
    length = b1 & 0x7F
    off = 2
    if length == 126:
        need(4)
        length = struct.unpack(">H", buf[2:4])[0]
        off = 4
    elif length == 127:
        need(10)
        length = struct.unpack(">Q", buf[2:10])[0]
        off = 10
    if masked:
        need(off + 4)
        off += 4
    need(off + length)
    payload = buf[off:off + length]
    rest = buf[off + length:]
    if opcode != 2:
        raise RuntimeError("不是二进制帧，opcode=%d" % opcode)
    return payload, rest


def send_mask(s, mask):
    """发一帧 4 字节小端按键掩码（客户端帧必须带掩码位）。"""
    body = struct.pack("<I", mask)
    key = os.urandom(4)
    masked = bytes(b ^ key[i & 3] for i, b in enumerate(body))
    frame = b"\x82" + bytes([0x80 | len(body)]) + key + masked
    s.sendall(frame)


def rgb565_to_png(payload, out_path):
    w, h = struct.unpack("<HH", payload[:4])
    pixels = payload[4:]
    need = w * h * 2
    if len(pixels) < need:
        raise RuntimeError("像素不足：%d < %d" % (len(pixels), need))
    raw = bytearray()
    for i in range(w * h):
        v = pixels[i * 2] | (pixels[i * 2 + 1] << 8)
        r = (v >> 11) & 0x1F
        g = (v >> 5) & 0x3F
        b = v & 0x1F
        raw += bytes((
            (r * 255 // 31),
            (g * 255 // 63),
            (b * 255 // 31),
        ))
    try:
        from PIL import Image
        img = Image.frombytes("RGB", (w, h), bytes(raw))
        img.save(out_path)
    except ImportError:
        # 没有 PIL 就写 PPM，Windows 看图软件能开
        out_path = os.path.splitext(out_path)[0] + ".ppm"
        with open(out_path, "wb") as f:
            f.write(b"P6\n%d %d\n255\n" % (w, h))
            f.write(bytes(raw))
    return w, h, out_path


def main():
    port = 9510
    out = None
    press = 0
    wait = 0.0
    args = sys.argv[1:]
    i = 0
    while i < len(args):
        a = args[i]
        if a == "--port" and i + 1 < len(args):
            port = int(args[i + 1]); i += 2
        elif a == "--out" and i + 1 < len(args):
            out = args[i + 1]; i += 2
        elif a == "--press" and i + 1 < len(args):
            press = int(args[i + 1], 0); i += 2
        elif a == "--wait" and i + 1 < len(args):
            wait = float(args[i + 1]); i += 2
        else:
            port = int(a); i += 1
    if out is None:
        out = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            ".notes", "img", "frame-native.png")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    s, leftover = ws_connect("127.0.0.1", port)
    try:
        if press:
            # 先按住再松开：libretro 的按键是电平触发，按一下再放才是一次有效按键
            send_mask(s, press)
            time.sleep(0.25)
            send_mask(s, 0)
        deadline = time.time() + wait
        payload = leftover
        while True:
            if wait > 0 and time.time() < deadline:
                # 等待期间继续把帧读掉，免得内核缓冲区堆满把连接卡住
                try:
                    s.settimeout(0.2)
                    payload, leftover = read_frame(s, leftover)
                    s.settimeout(10.0)
                    continue
                except (socket.timeout, TimeoutError):
                    pass
            break
        payload, leftover = read_frame(s, leftover)
        w, h, path = rgb565_to_png(payload, out)
        print("saved %s  %dx%d  %d bytes payload" % (path, w, h, len(payload)))
    finally:
        s.close()


if __name__ == "__main__":
    main()

"""A Neovim RPC client for the tests, standard library only: msgpack-RPC over the --listen socket.

The tests used to ask Neovim with `nvim --server <socket> --remote-expr <expr>`, a new Neovim process for
every question. This asks the same nvim_eval over one connection that stays open.
"""
import socket
import struct


class RpcError(Exception):
    """Neovim answered the request with an error."""


def pack(value):
    """<value> (None, bool, int, float, str, bytes, list, tuple or dict) as msgpack."""
    if value is None:
        return b"\xc0"
    if value is True:
        return b"\xc3"
    if value is False:
        return b"\xc2"
    if isinstance(value, int):
        if 0 <= value < 0x80:
            return struct.pack("B", value)
        if -32 <= value < 0:
            return struct.pack("b", value)
        if 0 <= value < 2 ** 64:
            return b"\xcf" + struct.pack(">Q", value)
        return b"\xd3" + struct.pack(">q", value)
    if isinstance(value, float):
        return b"\xcb" + struct.pack(">d", value)
    if isinstance(value, str):
        data = value.encode()
        return b"\xdb" + struct.pack(">I", len(data)) + data
    if isinstance(value, bytes):
        return b"\xc6" + struct.pack(">I", len(value)) + value
    if isinstance(value, (list, tuple)):
        return b"\xdd" + struct.pack(">I", len(value)) + b"".join(pack(v) for v in value)
    if isinstance(value, dict):
        return b"\xdf" + struct.pack(">I", len(value)) + b"".join(pack(k) + pack(v) for k, v in value.items())
    raise TypeError(f"can't send {type(value).__name__} to Neovim")


class Reader:
    def __init__(self, recv):
        self.recv = recv
        self.buffer = b""

    def take(self, n):
        while len(self.buffer) < n:
            chunk = self.recv()
            if not chunk:
                raise ConnectionError("Neovim closed the connection")
            self.buffer += chunk
        data, self.buffer = self.buffer[:n], self.buffer[n:]
        return data

    def number(self, fmt):
        return struct.unpack(">" + fmt, self.take(struct.calcsize(fmt)))[0]

    def items(self, n):
        return [self.value() for _ in range(n)]

    def pairs(self, n):
        return {self.value(): self.value() for _ in range(n)}

    def value(self):
        b = self.take(1)[0]
        if b <= 0x7F:
            return b
        if b >= 0xE0:
            return b - 0x100
        if 0x80 <= b <= 0x8F:
            return self.pairs(b & 0x0F)
        if 0x90 <= b <= 0x9F:
            return self.items(b & 0x0F)
        if 0xA0 <= b <= 0xBF:
            return self.take(b & 0x1F).decode(errors="replace")
        simple = {0xC0: None, 0xC2: False, 0xC3: True}
        if b in simple:
            return simple[b]
        sized = {0xC4: "B", 0xC5: "H", 0xC6: "I", 0xD9: "B", 0xDA: "H", 0xDB: "I"}
        if b in sized:
            data = self.take(self.number(sized[b]))
            return data if b <= 0xC6 else data.decode(errors="replace")
        numbers = {0xCA: "f", 0xCB: "d", 0xCC: "B", 0xCD: "H", 0xCE: "I", 0xCF: "Q",
                   0xD0: "b", 0xD1: "h", 0xD2: "i", 0xD3: "q"}
        if b in numbers:
            return self.number(numbers[b])
        if b in (0xDC, 0xDD):
            return self.items(self.number("H" if b == 0xDC else "I"))
        if b in (0xDE, 0xDF):
            return self.pairs(self.number("H" if b == 0xDE else "I"))
        # An ext (a buffer, window or tabpage handle): its data, as the handle it holds
        fixext = {0xD4: 1, 0xD5: 2, 0xD6: 4, 0xD7: 8, 0xD8: 16}
        if b in fixext:
            size = fixext[b]
        elif b in (0xC7, 0xC8, 0xC9):
            size = self.number({0xC7: "B", 0xC8: "H", 0xC9: "I"}[b])
        else:
            raise ValueError(f"not msgpack: byte {b:#x}")
        self.take(1)  # the ext type
        return Reader(None).from_bytes(self.take(size))

    def from_bytes(self, data):
        self.buffer = data
        return self.value()


class Client:
    """One connection to the Neovim listening on <path>."""

    def __init__(self, path, timeout):
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(timeout)
        try:
            self.sock.connect(path)
        except OSError:
            self.sock.close()
            raise
        self.reader = Reader(lambda: self.sock.recv(65536))
        self.next_id = 0

    def request(self, method, *args, timeout=10):
        """What Neovim's API function <method> returns for <args>. Raises RpcError when it fails,
        TimeoutError when Neovim doesn't answer within <timeout> seconds (the connection is then
        unusable: close it)."""
        self.next_id += 1
        msgid = self.next_id
        self.sock.settimeout(timeout)
        self.sock.sendall(pack([0, msgid, method, list(args)]))
        while True:
            message = self.reader.value()
            if message[0] == 1 and message[1] == msgid:
                if message[2] is not None:
                    error = message[2]
                    raise RpcError(error[1] if isinstance(error, list) and len(error) > 1 else error)
                return message[3]
            # A notification, or an answer to a request given up on: not ours

    def close(self):
        self.sock.close()

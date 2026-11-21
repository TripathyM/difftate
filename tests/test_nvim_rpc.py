"""Seam: the msgpack-RPC client the Neovim viewer's tests ask Neovim through
(tests/nvim_rpc.py). It needs no Neovim: a socket pair stands in for its socket."""
import os
import shutil
import socket
import struct
import sys
import tempfile
import threading
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import nvim_rpc  # noqa: E402


def unpack(data):
    return nvim_rpc.Reader(None).from_bytes(data)


class TheCodec(unittest.TestCase):
    def test_what_it_packs_it_reads_back(self):
        for value in [None, True, False, 0, 1, 127, 128, 70000, 2 ** 40, -1, -32, -33, -2 ** 40, 1.5, "",
                      "héllo", "x" * 70000, b"\x00\xff", [], [1, "two", [3]], {"a": 1, "b": [None]}]:
            with self.subTest(value=value):
                self.assertEqual(unpack(nvim_rpc.pack(value)), value)

    def test_it_reads_the_short_forms_neovim_sends(self):
        self.assertEqual(unpack(b"\xa3abc"), "abc")  # fixstr
        self.assertEqual(unpack(b"\x92\x01\xa1x"), [1, "x"])  # fixarray
        self.assertEqual(unpack(b"\x81\xa1k\xc0"), {"k": None})  # fixmap
        self.assertEqual(unpack(b"\xcc\xff"), 255)
        self.assertEqual(unpack(b"\xd0\x80"), -128)
        self.assertEqual(unpack(b"\xca" + struct.pack(">f", 0.5)), 0.5)
        self.assertEqual(unpack(b"\xd9\x02hi"), "hi")  # str8

    def test_a_buffer_window_or_tabpage_reads_as_its_handle(self):
        self.assertEqual(unpack(b"\xd4\x00\x05"), 5, "a fixext 1: buffer 5")
        self.assertEqual(unpack(b"\xc7\x03\x01\xcd\x03\xe8"), 1000, "an ext 8 holding a uint16: window 1000")


class TheClient(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.mkdtemp(prefix="nvim-rpc-")
        self.addCleanup(shutil.rmtree, self.folder, ignore_errors=True)
        self.path = os.path.join(self.folder, "s.sock")
        self.server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.addCleanup(self.server.close)
        self.server.bind(self.path)
        self.server.listen(1)

    def serve(self, answer):
        """A fake Neovim: <answer>(request) is the list of messages it sends back for each request."""
        def run():
            conn, _ = self.server.accept()
            with conn:
                reader = nvim_rpc.Reader(lambda: conn.recv(65536))
                while True:
                    try:
                        request = reader.value()
                    except ConnectionError:
                        return
                    for message in answer(request):
                        conn.sendall(nvim_rpc.pack(message))
        threading.Thread(target=run, daemon=True).start()

    def test_it_answers_with_the_result_of_its_own_request(self):
        seen = []

        def answer(request):
            seen.append(request)
            _, msgid, method, args = request
            # A notification and a stale answer first: neither is this request's
            return [[2, "redraw", []], [1, msgid + 100, None, "stale"], [1, msgid, None, f"{method}:{args[0]}"]]
        self.serve(answer)
        client = nvim_rpc.Client(self.path, timeout=5)
        self.addCleanup(client.close)

        self.assertEqual(client.request("nvim_eval", "1+1"), "nvim_eval:1+1")
        self.assertEqual(client.request("nvim_eval", "2"), "nvim_eval:2")
        self.assertEqual([r[1] for r in seen], [1, 2], "a new id for each request")

    def test_an_error_answer_raises_with_neovims_message(self):
        self.serve(lambda request: [[1, request[1], [0, "Vim:E15: Invalid expression"], None]])
        client = nvim_rpc.Client(self.path, timeout=5)
        self.addCleanup(client.close)

        with self.assertRaisesRegex(nvim_rpc.RpcError, "E15: Invalid expression"):
            client.request("nvim_eval", "(")

    def test_no_answer_in_time_raises_a_timeout(self):
        self.serve(lambda request: [])
        client = nvim_rpc.Client(self.path, timeout=5)
        self.addCleanup(client.close)

        with self.assertRaises(TimeoutError):
            client.request("nvim_eval", "1", timeout=0.2)

    def test_connecting_to_no_socket_raises_an_os_error(self):
        with self.assertRaises(OSError):
            nvim_rpc.Client(os.path.join(self.folder, "none.sock"), timeout=1)


if __name__ == "__main__":
    unittest.main()

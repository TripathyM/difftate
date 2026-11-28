"""The browser viewer's files (#265): / serves layout D and everything it loads, for the sign-in
link's cookie; the page it replaced is gone. The review API serves it in this process, with its own
folder as home; no watcher, no browser."""
import http.client
import re
import os
import shutil
import sys
import tempfile
import unittest
import urllib.parse
from posixpath import dirname, join, normpath

from browser_d import ROOT

sys.path.insert(0, os.path.join(ROOT, "lib"))
from difftate.adapters.inbound.review_api.server import ReviewApi

TYPES = {".js": "text/javascript; charset=utf-8", ".css": "text/css; charset=utf-8"}


class TheBrowserViewerIsServed(unittest.TestCase):
    def setUp(self):
        home = tempfile.mkdtemp(prefix="difftate-d-")
        self.addCleanup(shutil.rmtree, home)
        self.api = ReviewApi(None, home)
        self.api.start()
        self.addCleanup(self.api.stop)
        self.port = int(urllib.parse.urlsplit(self.api.address().url).port)

    def get(self, path, cookie=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        self.addCleanup(conn.close)
        conn.request("GET", path, headers={"Cookie": cookie} if cookie else {})
        r = conn.getresponse()
        return r.status, r.headers, r.read().decode()

    def signed_in(self):
        """The cookie the usual sign-in link gives."""
        link = urllib.parse.urlsplit(self.api.page_url("/some/repo"))
        _, headers, _ = self.get(f"{link.path}?{link.query}")
        return headers["Set-Cookie"].split(";")[0]

    def test_the_page_and_everything_it_loads_are_served_for_the_usual_cookie(self):
        cookie = self.signed_in()
        status, headers, html = self.get("/?folder=%2Fsome%2Frepo", cookie)
        self.assertEqual((status, headers["Content-Type"]), (200, "text/html; charset=utf-8"))

        todo = [urllib.parse.urljoin("/", src) for src in re.findall(r'<(?:script|link)\b[^>]*?(?:src|href)="([^"]+)"', html)]
        self.assertIn("/d/main.js", todo)
        self.assertIn("/d/style.css", todo)
        loaded = set()
        while todo:
            path = todo.pop()
            if path in loaded:
                continue
            loaded.add(path)
            status, headers, body = self.get(path, cookie)
            kind = path[path.rindex("."):]
            self.assertEqual((status, headers["Content-Type"]), (200, TYPES[kind]), path)
            todo += [normpath(join(dirname(path), other)) for other in re.findall(r'^(?:import|export)\b[^;]*?from "([^"]+)"', body, re.M)]
            self.assertEqual(self.get(path)[0], 401, f"{path} without the cookie")
        self.assertIn("/diff.js", loaded, "the page reads the diff with its parser")

    def test_the_page_needs_the_cookie(self):
        self.assertEqual(self.get("/")[0], 401)

    def test_the_page_it_replaced_and_its_own_address_beside_it_are_gone(self):
        cookie = self.signed_in()

        self.assertEqual([self.get(path, cookie)[0] for path in ("/d", "/app.js", "/warnings.js")], [404, 404, 404])


if __name__ == "__main__":
    unittest.main()

"""The Markdown layout D shows (#259), in comments, replies, notes and the Preview tab
(web/d/markdown.js). It gives blocks and spans of text, never HTML: what people and agents write
is untrusted. Node runs it."""
import json
import shutil
import unittest

from browser_d import run_js


@unittest.skipUnless(shutil.which("node"), "needs node")
class TheMarkdown(unittest.TestCase):
    def blocks(self, text):
        return run_js("markdown", f"console.log(JSON.stringify(m.markdown({json.dumps(text)})));")

    def test_paragraphs_keep_their_lines_with_code_and_bold_marked(self):
        got = self.blocks("Why `a **b**` here?\nIt is **very** odd.\n\n\nSecond.")

        self.assertEqual(got, [
            {"kind": "paragraph", "spans": [{"text": "Why "}, {"code": "a **b**"}, {"text": " here?\nIt is "},
                                            {"strong": "very"}, {"text": " odd."}]},
            {"kind": "paragraph", "spans": [{"text": "Second."}]}])

    def test_fenced_code_is_text_as_written_also_when_it_is_never_closed(self):
        got = self.blocks("Try:\n```python\n  x = `1`\n\n- not a list\n```\n~~~\nopen")

        self.assertEqual(got, [{"kind": "paragraph", "spans": [{"text": "Try:"}]},
                               {"kind": "code", "text": "  x = `1`\n\n- not a list"},
                               {"kind": "code", "text": "open"}])

    def test_bulleted_and_numbered_lists_with_a_wrapped_item(self):
        got = self.blocks("- one\n  and more\n* `two`\n1. first\n2) second\ndone")

        self.assertEqual(got, [
            {"kind": "list", "ordered": False, "items": [[{"text": "one and more"}], [{"code": "two"}]]},
            {"kind": "list", "ordered": True, "items": [[{"text": "first"}], [{"text": "second"}]]},
            {"kind": "paragraph", "spans": [{"text": "done"}]}])

    def test_html_and_links_stay_the_text_that_was_written(self):
        got = self.blocks("<img src=x onerror=alert(1)> [x](javascript:alert(1))")

        self.assertEqual(got, [{"kind": "paragraph", "spans": [{"text": "<img src=x onerror=alert(1)> [x](javascript:alert(1))"}]}])

    def test_nothing_written_is_no_blocks(self):
        self.assertEqual(self.blocks(" \n\n"), [])


if __name__ == "__main__":
    unittest.main()

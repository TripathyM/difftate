"""Seam: the Review tab's main.js, read as text.

main.js needs Herdr to load, so no test runs it. A name it imports and then
declares again in a function hides the import there: calling it fails at render
time with "not a function", and the Review tab shows its last working view. The
plain-JS modules' own tests don't see that, and neither does `herdr-app check`.
"""
import os
import re
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MAIN_JS = os.path.join(ROOT, "herdr", "mods", "difftate", "main.js")


def imported_names(source):
    """The local names main.js's `import { … } from "…"` lines bind."""
    names = set()
    for group in re.findall(r"import\s*\{([^}]*)\}\s*from", source):
        for part in group.split(","):
            part = part.strip()
            if part:
                names.add(part.split(" as ")[-1].strip())
    return names


class TheReviewTabsImports(unittest.TestCase):
    def test_no_imported_name_is_declared_again(self):
        with open(MAIN_JS, encoding="utf-8") as f:
            source = f.read()
        declared = set(re.findall(r"\b(?:const|let|var|function|class)\s+([A-Za-z_$][\w$]*)", source))
        self.assertEqual(sorted(imported_names(source) & declared), [])


if __name__ == "__main__":
    unittest.main()

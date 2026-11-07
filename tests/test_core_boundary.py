"""Seam: the core's boundary (ADR 0003, the core knows no technology).

Every module under lib/difftate/core/ is read with ast, so a new file is
covered without listing it. A module breaks the boundary if it imports an
adapter (by name or by a relative path), imports subprocess, http, socket or
urllib, or uses print (called, aliased or as builtins.print). Imports made at
run time by name (__import__, importlib) are out of the checker's reach.
"""
import ast
import os
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LIB = os.path.join(ROOT, "lib")
CORE = os.path.join(LIB, "difftate", "core")

FORBIDDEN_PACKAGES = ("difftate.adapters", "subprocess", "http", "socket", "urllib")


def _is_forbidden(name):
    return any(name == package or name.startswith(package + ".") for package in FORBIDDEN_PACKAGES)


def _absolute(node, module_name, is_package):
    """The module a `from ... import` names, with a relative path resolved."""
    if node.level == 0:
        return node.module or ""
    parts = module_name.split(".")
    package = parts if is_package else parts[:-1]
    base = package[:len(package) - (node.level - 1)]
    return ".".join(base + ([node.module] if node.module else []))


def _uses_print(node):
    if isinstance(node, ast.Name):
        return node.id == "print" and isinstance(node.ctx, ast.Load)
    return (isinstance(node, ast.Attribute) and node.attr == "print"
            and isinstance(node.value, ast.Name) and node.value.id == "builtins")


def boundary_breaks(source, module_name, is_package=False):
    """What in this module's source breaks the core's boundary, one line each.

    module_name is the module's dotted name (difftate.core.review.model), so a
    relative import can be resolved; is_package says it is an __init__.py.
    """
    breaks = []
    for node in ast.walk(ast.parse(source)):
        names = []
        if isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            base = _absolute(node, module_name, is_package)
            # `from difftate import adapters` names the adapters package too
            names = [base] + [f"{base}.{alias.name}" for alias in node.names]
        elif _uses_print(node):
            breaks.append(f"line {node.lineno}: uses print")
        forbidden = [name for name in names if _is_forbidden(name)]
        if forbidden:
            breaks.append(f"line {node.lineno}: imports {forbidden[0]}")
    return breaks


def core_modules():
    """(dotted name, is package, path) for every .py file under core/."""
    for folder, _, files in os.walk(CORE):
        for file in sorted(files):
            if file.endswith(".py"):
                path = os.path.join(folder, file)
                parts = os.path.relpath(path, LIB)[:-len(".py")].split(os.sep)
                is_package = parts[-1] == "__init__"
                if is_package:
                    parts = parts[:-1]
                yield ".".join(parts), is_package, path


class TheCoreKnowsNoTechnology(unittest.TestCase):
    def test_no_module_under_core_imports_an_adapter_or_a_technology_or_prints(self):
        modules = list(core_modules())
        self.assertTrue(modules, "core/ has no modules to check")
        breaks = []
        for name, is_package, path in modules:
            with open(path, encoding="utf-8") as f:
                breaks += [name + " " + b for b in boundary_breaks(f.read(), name, is_package)]
        self.assertEqual(breaks, [])

    def test_the_contexts_and_adapter_sides_are_packages_that_say_what_belongs_there(self):
        packages = ["core", "core/review", "core/changes", "core/dispatch",
                    "adapters", "adapters/inbound", "adapters/outbound"]
        for package in packages:
            with self.subTest(package=package):
                path = os.path.join(LIB, "difftate", *package.split("/"), "__init__.py")
                with open(path, encoding="utf-8") as f:
                    self.assertTrue(ast.get_docstring(ast.parse(f.read())))


class TheBoundaryChecker(unittest.TestCase):
    MODULE = "difftate.core.review.model"

    def breaks(self, source, module_name=MODULE, is_package=False):
        return boundary_breaks(source, module_name, is_package)

    def test_a_module_that_imports_subprocess_breaks_the_boundary(self):
        self.assertEqual(self.breaks("import subprocess\n"), ["line 1: imports subprocess"])

    def test_a_module_that_calls_print_breaks_the_boundary(self):
        self.assertEqual(self.breaks("x = 1\nprint('hello')\n"), ["line 2: uses print"])

    def test_every_technology_is_caught_in_either_import_form(self):
        for source in ("import http.client", "from http.server import HTTPServer", "import socket",
                       "from urllib import request", "import urllib.parse as up", "from subprocess import run"):
            with self.subTest(source=source):
                self.assertEqual(len(self.breaks(source)), 1)

    def test_an_adapter_imported_by_name_or_by_a_relative_path_breaks_the_boundary(self):
        for source in ("import difftate.adapters.outbound.git", "from difftate.adapters import outbound",
                       "from difftate import adapters", "from ...adapters.outbound import git",
                       "from ... import adapters"):
            with self.subTest(source=source):
                self.assertEqual(len(self.breaks(source)), 1)

    def test_a_relative_path_from_a_package_counts_its_own_folder(self):
        # In difftate/core/__init__.py, `..` is difftate
        self.assertEqual(len(self.breaks("from ..adapters import inbound", "difftate.core", True)), 1)
        self.assertEqual(self.breaks("from ..adapters import inbound", "difftate.core.review", True), [])

    def test_the_core_may_import_itself_and_the_standard_library(self):
        source = ("from __future__ import annotations\nimport typing\nfrom dataclasses import dataclass\n"
                  "from . import ports\nfrom ..changes import model\nimport difftate.core.dispatch\n"
                  "import httpx_like_name\n")
        self.assertEqual(self.breaks(source), [])

    def test_print_reached_through_builtins_or_another_name_breaks_the_boundary(self):
        self.assertEqual(self.breaks("import builtins\nbuiltins.print('x')\n"), ["line 2: uses print"])
        self.assertEqual(self.breaks("say = print\nsay('x')\n"), ["line 1: uses print"])

    def test_a_method_named_print_is_not_the_builtin(self):
        self.assertEqual(self.breaks("report.print('x')\n"), [])


if __name__ == "__main__":
    unittest.main()

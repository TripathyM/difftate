"""Opening the review in a viewer: the browser, the Neovim viewer (nvim here
when difftate runs in a terminal; difftate opens no other host).

Each viewer is opened with (url, root): the link to difftate's own page, and
the repository's top folder. It says whether it could be reached. main.py
picks the viewers; --open names one of them, both, or none.
"""
import os
import shlex
import shutil
import subprocess
import sys

BROWSER = "browser"
BOTH = "both"
NONE = "none"  # the reviewer's own viewer: it opens itself, so difftate opens nothing


def where_to_open(viewers):
    """What --open accepts: each viewer's name, then both and none."""
    return (*viewers, BOTH, NONE)


def open_browser(url, root):
    try:
        subprocess.run(["open", url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError:
        pass
    return True


NVIM_COMMAND = ["nvim", "+DifftateOpen"]


def _has_terminal():
    """True when difftate runs in a terminal: stdin and stdout both ttys. (A seam: tests fake it.)"""
    try:
        return sys.stdin.isatty() and sys.stdout.isatty()
    except (AttributeError, ValueError):
        return False


def _print_nvim_command(root):
    print(f"  Neovim: no host to open it in; run: cd {shlex.quote(root)} && {shlex.join(NVIM_COMMAND)}")


def _exec_nvim(root):
    """Replace this process with nvim +DifftateOpen, run in <root>. With no nvim on PATH (or an
    exec that fails): an error on stderr and exit 1. (A seam: tests fake it.)"""
    if not shutil.which(NVIM_COMMAND[0]):
        _no_nvim()
    try:
        os.chdir(root)
        sys.stdout.flush()
        os.execvp(NVIM_COMMAND[0], NVIM_COMMAND)
    except OSError:
        _no_nvim()


def _no_nvim():
    print("difftate: nvim not found on PATH", file=sys.stderr)
    sys.exit(1)


def open_in_nvim(url, root):
    """The Neovim viewer. With a terminal: nvim here, in <root>, replacing this process. With none:
    the command to run is printed; difftate opens no host. Always True: no terminal is no reason
    to open the browser."""
    if _has_terminal():
        _exec_nvim(root)
    else:
        _print_nvim_command(root)
    return True


def open_review(viewers, where, url, root):
    """Open the review in the viewer named <where> (one of <viewers>, or both:
    each of them, the browser first: Neovim may replace this process; or none: nothing opens). A viewer that
    can't be reached falls back to the browser."""
    if where == NONE:
        return
    if where == BOTH:
        for name in sorted(viewers, key=lambda name: name != BROWSER):
            viewers[name](url, root)
    elif not viewers[where](url, root) and where != BROWSER and BROWSER in viewers:
        print("  Falling back to the browser")
        viewers[BROWSER](url, root)

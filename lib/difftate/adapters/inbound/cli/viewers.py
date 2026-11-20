"""Opening the review in a viewer: the browser, the Neovim viewer (in the
host where difftate runs), or the frozen Herdr viewer.

Each viewer is opened with (url, root): the link to difftate's own page, and
the repository's top folder. It says whether it could be reached. main.py
picks the viewers; --open names one of them, or both.
"""
import json
import os
import shlex
import shutil
import subprocess

BROWSER = "browser"
BOTH = "both"


def where_to_open(viewers):
    """What --open accepts: each viewer's name, then both."""
    return (*viewers, BOTH)


def _run(argv):
    try:
        return subprocess.run(argv, capture_output=True, text=True)
    except OSError:
        return None


def open_browser(url, root):
    try:
        subprocess.run(["open", url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError:
        pass
    return True


def _herdr_cli():
    """The Herdr app's command line: $DT_HERDR, else herdr-app on PATH."""
    return os.environ.get("DT_HERDR") or shutil.which("herdr-app") or ""


def _herdr_tab(root, new_tab, say, why_not_opened="could not open a Review tab"):
    """Switch to the Review tab of the repository at <root> in Herdr, or open
    one with the arguments of <new_tab> (a function of the tab's name). <say>
    reports what went wrong. False when Herdr can't be reached or won't open it."""
    cli = _herdr_cli()
    if not cli or not os.access(cli, os.X_OK):
        say("  Herdr: herdr-app not found (set DT_HERDR to the Herdr app's binary)")
        return False
    tabs = _run([cli, "ls"])
    if not tabs or tabs.returncode != 0:
        say("  Herdr: not running")
        return False
    name = f"Review · {os.path.basename(root)}"
    try:
        spaces = json.loads(tabs.stdout).get("spaces", [])
    except (ValueError, AttributeError):
        spaces = []
    existing = next((t["id"] for s in spaces for t in s.get("tabs", []) if t.get("name") == name), None)
    if existing:
        r = _run([cli, "do", "tab.select", json.dumps({"id": existing})])
        if r and r.returncode == 0:
            print(f'  Herdr: switched to the "{name}" tab')
            return True
    r = _run([cli, "do", "tab.new", json.dumps(new_tab(name))])
    if not r or r.returncode != 0:
        say(f"  Herdr: {why_not_opened}")
        return False
    print(f'  Herdr: opened the "{name}" tab')
    return True


def open_in_herdr(url, root):
    """The Herdr viewer, frozen: a Review tab running Herdr's `difftate` mod.
    False when Herdr can't be reached."""
    def mod_tab(name):
        return {"name": name, "mod": "difftate", "props": {"folder": root}}

    return _herdr_tab(root, mod_tab, print, "could not open a Review tab (is the difftate mod installed?)")


NVIM_COMMAND = ["nvim", "+DifftateOpen"]


def _nvim_in_herdr(root):
    """The Neovim viewer's host when difftate runs where Herdr is reachable:
    a `Review · <folder>` tab running nvim in <root>."""
    def nvim_tab(name):
        return {"name": name, "folder": root, "argv": NVIM_COMMAND}

    return _herdr_tab(root, nvim_tab, lambda message: None)


# Where the Neovim viewer opens, in order: the first that takes it wins. Another
# host (tmux, another multiplexer) is one more function here, taking the folder.
NVIM_HOSTS = (_nvim_in_herdr,)


def open_in_nvim(url, root):
    """The Neovim viewer: nvim with the review open, in the first host that
    takes it; with none, the command to run is printed. Always True: a host that
    is missing is no reason to open the browser."""
    if not any(host(root) for host in NVIM_HOSTS):
        print(f"  Neovim: no host to open it in; run: cd {shlex.quote(root)} && {shlex.join(NVIM_COMMAND)}")
    return True


def open_review(viewers, where, url, root):
    """Open the review in the viewer named <where> (one of <viewers>, or both:
    each of them, the browser last). A viewer that can't be reached falls back
    to the browser."""
    if where == BOTH:
        for name in sorted(viewers, key=lambda name: name == BROWSER):
            viewers[name](url, root)
    elif not viewers[where](url, root) and where != BROWSER and BROWSER in viewers:
        print("  Falling back to the browser")
        viewers[BROWSER](url, root)

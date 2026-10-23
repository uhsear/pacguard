#!/usr/bin/env python
"""Wrap the Power Platform pac CLI for a Copilot Studio agent workspace: check by default, refuse an abbreviated flag, refuse a pack pac will reject.

Only four pac calls can be built: auth who, copilot list, copilot push and
copilot pack. Nothing else is reachable from a flag: not pull, publish, delete,
quarantine, clone, create or import. The one call that changes the live agent,
copilot push, runs only when the literal --apply is present together with
--push. The parser sets allow_abbrev=False, so --ap or --appl is a usage error
and never a push.

The decision core is pure: it takes a directory listing and a git status and
returns a verdict, with no file or process behind it. The I/O layer around it
lists a directory, asks git for the status and runs pac.

    python pacguard.py --self-test
    python pacguard.py agents/support
    python pacguard.py agents/support --offline
    python pacguard.py agents/support --push
    python pacguard.py agents/support --push --apply
    python pacguard.py agents/support --pack --publisher-prefix demo --output-path out
    python pacguard.py agents/support --pack --publisher-prefix demo --output-path out --apply

Checks, all without writing anything (git runs with --no-optional-locks, so
it does not refresh the index either):

  git state   a push needs a clean worktree with at least one tracked file, so
              the last committed state is a rollback point. A workspace that git
              ignores has none and reads UNKNOWN. --allow-dirty overrides,
              loudly.
  pack layout pac copilot pack validates a classic workspace (agent.mcs.yml) and
              rejects the extra files a cloned agent carries. This tool refuses
              before the call and lists every entry at once. A CLI-authored
              workspace (agent.sync.yaml) is not refused. --allow-cloned-pack
              overrides, for a pac release that fixes it.

Nothing is written by pacguard itself. pac writes when pacguard runs it, and
pacguard runs it for push or pack only with --apply.

Exit codes: 0 no check refused the run (and the call ran, with --apply). A run
with neither --push nor --pack only reports and always exits 0, whatever it
printed, so read the verdict lines. 1 a check refused the run, 2 a workspace or
pac could not be found or read, 3 pac ran and exited non-zero, 64 usage error,
70 an unexpected crash, which is never a finding.
"""

from __future__ import print_function

import argparse
import ast
import contextlib
import importlib.util
import io
import os
import re
import shutil
import subprocess
import sys
import tempfile
import traceback

# =============================================================================
# CONFIGURATION. Deliberately not flags. Change here, not at the call site.
# =============================================================================

# The only pac calls this tool can build. Anything else raises ValueError.
WHO = "who"
LIST = "list"
PUSH = "push"
PACK = "pack"
ALLOWED_CALLS = ("auth who", "copilot list", "copilot push", "copilot pack")

# Entries pac copilot pack rejected at the top of a classic workspace, observed
# on pac 2.14.1 (see README). The first group is what a cloned agent carries.
# The second is other names the probe runs saw rejected. The third is version
# control and editor files, which any workspace kept in git carries. The lists
# are not complete: pac rejected every other name tried too. Matching is
# case-insensitive.
CLONED_ENTRIES = ("actions", "connectionreferences.mcs.yml", "connectors",
                  "knowledge", "workflows")
PROBED_ENTRIES = ("botcomponents", "components", "dialogs", "entities", "extra",
                  "skills", "translations", "variables")
TOOLING_ENTRIES = (".editorconfig", ".git", ".gitattributes", ".github",
                   ".gitignore", ".vscode", "license", "readme.md")

NOT_A_WORKSPACE = ("not an agent workspace: neither agent.mcs.yml nor "
                   "agent.sync.yaml is here")
CLASSIC_MARKER = "agent.mcs.yml"
CLI_MARKER = "agent.sync.yaml"

LAYOUT_CLASSIC = "classic"
LAYOUT_CLI = "cli-authored"
LAYOUT_UNKNOWN = "unrecognised"

CLEAN = "CLEAN"
DIRTY = "DIRTY"
UNKNOWN = "UNKNOWN"

# A pac output line holding any of these words is withheld. pac auth who prints
# a token expiry line, and a future version could print more. It is a keyword
# filter, not a secret detector: a secret on a line without these words passes.
SECRET_LIST = ("token", "secret", "password", "bearer", "authorization",
               "credential")
SECRET_WORDS = re.compile("|".join(SECRET_LIST), re.IGNORECASE)

EXIT_OK = 0
EXIT_REFUSED = 1
EXIT_MISSING = 2
EXIT_PAC = 3
EXIT_USAGE = 64
EXIT_CRASH = 70

# Modules the self-test allows this file to import. No network module, because
# pacguard opens no socket. pac does that work.
ALLOWED_IMPORTS = frozenset([
    "__future__", "argparse", "ast", "contextlib", "importlib", "io", "os",
    "re", "shutil", "subprocess", "sys", "tempfile", "traceback"])


# ------------------------------------------------------------------- the core
# No file, process or network is touched below this line until "the I/O layer".

def build_argv(verb, project_dir=None, publisher_prefix=None,
               output_path=None):
    """The pac arguments for one verb, without the leading pac. Long option
    names only: pac accepts short aliases, but a long name cannot be mistaken
    for a different option when someone edits this line later."""
    if verb == WHO:
        return ["auth", "who"]
    if verb == LIST:
        return ["copilot", "list"]
    if verb == PUSH:
        _need(verb, project_dir=project_dir)
        return ["copilot", "push", "--project-dir", project_dir]
    if verb == PACK:
        _need(verb, project_dir=project_dir,
              publisher_prefix=publisher_prefix, output_path=output_path)
        return ["copilot", "pack", "--publisher-prefix", publisher_prefix,
                "--project-dir", project_dir, "--output-path", output_path]
    raise ValueError("unknown or disallowed pac call %r. The only calls are: "
                     "%s." % (verb, ", ".join(ALLOWED_CALLS)))


def _need(verb, **named):
    missing = sorted(k for k, v in named.items() if not v)
    if missing:
        raise ValueError("pac %s needs %s" % (verb, ", ".join(missing)))


def show(argv):
    """The command as a person would type it. Quotes an argument with a
    space so the printed line can be pasted."""
    return " ".join('"%s"' % a if " " in a else a for a in argv)


def pack_verdict(entries):
    """Decide whether pac copilot pack will accept a workspace.

    entries is a list of (name, is_dir) for the top of the workspace. Returns
    (layout, rejected). rejected names every entry pac rejects, so one run
    reports all of them and not the first. It is empty for a CLI-authored
    workspace, which pac accepts with extra entries, and for a workspace that
    holds nothing known to be rejected."""
    names = set(n.lower() for n, _ in entries)
    if CLI_MARKER in names:
        return LAYOUT_CLI, []
    if CLASSIC_MARKER not in names:
        return LAYOUT_UNKNOWN, []
    rejected = []
    for name, is_dir in sorted(entries, key=lambda e: e[0].lower()):
        if name.lower() in CLONED_ENTRIES + PROBED_ENTRIES + TOOLING_ENTRIES:
            rejected.append(name + "/" if is_dir else name)
    return LAYOUT_CLASSIC, rejected


def classify_git(returncode, stdout, tracked=True):
    """CLEAN, DIRTY or UNKNOWN from one git status --porcelain result and
    whether git tracks a file in the workspace. UNKNOWN means git could not
    answer, which is not the same as clean. A workspace with nothing tracked
    and nothing to report, such as one that git ignores, has no rollback point
    to be clean against, so it is UNKNOWN too."""
    if returncode != 0:
        return UNKNOWN
    if stdout.strip():
        return DIRTY
    return CLEAN if tracked else UNKNOWN


class Assessment(object):
    """What is known about one workspace."""

    def __init__(self, path, layout, rejected, git):
        self.path = path
        self.layout = layout
        self.rejected = rejected
        self.git = git


def decide(action, assessments, allow_dirty=False, allow_cloned_pack=False):
    """Every reason the requested action must not run. An empty list means it
    may. With no action there is nothing to refuse: the run only reports."""
    refusals = []
    for a in assessments:
        if action == PUSH and a.git != CLEAN and not allow_dirty:
            refusals.append(
                "%s: git status is %s. Commit first, so the last commit is a "
                "rollback point, or pass --allow-dirty." % (a.path, a.git))
        if action == PACK and a.layout == LAYOUT_UNKNOWN:
            refusals.append("%s: %s" % (a.path, NOT_A_WORKSPACE))
        elif action == PACK and a.rejected and not allow_cloned_pack:
            refusals.append(
                "%s: pac copilot pack rejects %s. Pass --allow-cloned-pack "
                "if your pac release accepts them."
                % (a.path, ", ".join(a.rejected)))
    return refusals


def scrub(text):
    """Split pac output into lines and withhold any that look like a
    credential."""
    lines = []
    for line in text.splitlines():
        if SECRET_WORDS.search(line):
            line = "[line withheld: it looks like a credential]"
        lines.append(line)
    return lines


def usage_problem(a):
    """The first reason the flags cannot be combined, or None."""
    if a.push and a.pack:
        return "--push and --pack are separate runs. Pick one."
    if not a.workspace:
        return ("name at least one workspace directory. Use --self-test to "
                "verify the tool without one.")
    if a.apply and not (a.push or a.pack):
        return "--apply needs --push or --pack, because it says what to apply."
    if a.push and len(a.workspace) != 1:
        return ("--push takes exactly one workspace, so a push never reaches "
                "an agent you did not name.")
    if a.push and a.offline:
        return "--offline cannot push. A push needs the sign-in check first."
    if a.pack and not (a.publisher_prefix and a.output_path):
        return "--pack needs --publisher-prefix and --output-path."
    for flag, given, needed, owner in (
            ("--publisher-prefix", a.publisher_prefix, a.pack, "--pack"),
            ("--output-path", a.output_path, a.pack, "--pack"),
            ("--allow-cloned-pack", a.allow_cloned_pack, a.pack, "--pack"),
            ("--allow-dirty", a.allow_dirty, a.push, "--push")):
        if given and not needed:
            return "%s needs %s." % (flag, owner)
    return None


# -------------------------------------------------------------- the I/O layer

def run_command(argv, cwd=None):
    """Run one process. Returns (returncode, stdout, stderr). Raises OSError
    when the program cannot be started. stdin is closed so pac cannot wait
    on a prompt."""
    proc = subprocess.run(argv, cwd=cwd, stdin=subprocess.DEVNULL,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                          encoding="utf-8", errors="replace")
    return proc.returncode, proc.stdout, proc.stderr


def list_entries(path):
    return [(n, os.path.isdir(os.path.join(path, n)))
            for n in sorted(os.listdir(path))]


def git_state(path, git="git"):
    """--no-optional-locks keeps git status from rewriting .git/index.
    --untracked-files=all overrides a status.showUntrackedFiles setting that
    would hide a new file. "-- ." scopes status to the workspace, and ls-files
    lists only the current directory by default."""
    base = [git, "--no-optional-locks"]
    try:
        rc, out, _ = run_command(
            base + ["status", "--porcelain", "--untracked-files=all", "--",
                    "."], cwd=path)
        _, listed, _ = run_command(base + ["ls-files", "--cached"], cwd=path)
    except OSError:
        return UNKNOWN
    return classify_git(rc, out, bool(listed.strip()))


def assess(path):
    layout, rejected = pack_verdict(list_entries(path))
    return Assessment(path, layout, rejected, git_state(path))


def resolve_pac(value):
    """The command prefix for pac, or None when it cannot be found. A .py path
    runs under this interpreter, which is how the self-test stands in for pac
    on every host."""
    if value.lower().endswith(".py"):
        return [sys.executable, value] if os.path.isfile(value) else None
    found = shutil.which(value)
    return [found] if found else None


def echo(text, stream):
    for line in scrub(text):
        if line.strip():
            print("  | %s" % line, file=stream)


def run_pac(pac, argv):
    """Run one pac call and show what it said. Returns its exit code."""
    print("pac %s" % show(argv))
    rc, out, err = run_command(pac + argv)
    echo(out, sys.stdout)
    echo(err, sys.stderr)
    return rc


def describe(a):
    print("workspace %s" % a.path)
    print("  layout: %s" % a.layout)
    note = {CLEAN: "no uncommitted changes",
            DIRTY: "uncommitted changes",
            UNKNOWN: "git could not say, or tracks no file here, so the "
                     "state is not known"}[a.git]
    print("  git: %s (%s)" % (a.git, note))
    if a.layout == LAYOUT_CLI:
        print("  pack: ok (pac accepts extra entries in this layout)")
    elif a.layout == LAYOUT_UNKNOWN:
        print("  pack: %s" % NOT_A_WORKSPACE)
    elif a.rejected:
        print("  pack: pac rejects %s" % ", ".join(a.rejected))
    else:
        print("  pack: ok (nothing here is known to be rejected)")


# ------------------------------------------------------------------ self-test

STUB = r'''
import os
import sys

args = sys.argv[1:]
log = os.environ.get("PACGUARD_STUB_LOG")
if log:
    with open(log, "a") as fh:
        fh.write(" ".join(args) + "\n")
mode = os.environ.get("PACGUARD_STUB_MODE", "")
if args[:1] == ["auth"]:
    print("Stub profile: tester@example.invalid")
    if "secret" in mode:
        print("Access Token: not-a-real-value-0001")
        print("Token Expires: tomorrow")
    if "stderrleak" in mode:
        sys.stderr.write("Authorization: Bearer not-a-real-value-0002\n")
    if "unicode" in mode:
        sys.stdout.buffer.write(b"snowman \xe2\x98\x83\n")
        sys.stdout.buffer.flush()
if args[:1] == ["copilot"]:
    print("stub: copilot " + " ".join(args[1:2]))
if mode and (args[0] if args[0] != "copilot" else args[1]) in mode.split(","):
    sys.stderr.write("stub failure\n")
    sys.exit(7)
'''


def self_test():
    """Run the assertions in a temp directory that is removed even when one
    of them raises, so a crash never leaves pacguard-selftest-* behind."""
    tmp = tempfile.mkdtemp(prefix="pacguard-selftest-")
    saved = dict((k, os.environ.get(k)) for k in
                 ("PACGUARD_STUB_LOG", "PACGUARD_STUB_MODE",
                  "GIT_CEILING_DIRECTORIES"))
    try:
        return _self_test(tmp)
    finally:
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        shutil.rmtree(tmp, ignore_errors=True)


def _self_test(tmp):
    """Assertions over the decision core and the CLI, with a stub standing in
    for pac. No network, no credentials. The only files are under tmp."""
    passed = [0]
    failed = []

    def check(cond, label):
        if cond:
            passed[0] += 1
            print("PASS  %s" % label)
        else:
            failed.append(label)
            print("FAIL  %s" % label)

    def raises(fn, label):
        try:
            fn()
        except ValueError:
            check(True, label)
        except Exception as exc:
            check(False, "%s (wrong exception %r)" % (label, exc))
        else:
            check(False, "%s (no error raised)" % label)

    print("pacguard self-test: temporary files only, no network, no "
          "credentials")
    print("-" * 68)

    # ---- the stub, the workspaces and the driver
    stub = os.path.join(tmp, "stubpac.py")
    with open(stub, "w") as fh:
        fh.write(STUB)
    logs = os.path.join(tmp, "logs")
    os.mkdir(logs)
    # Stops git looking above tmp, so a temp directory inside some other
    # repository cannot turn an UNKNOWN workspace into a clean one.
    os.environ["GIT_CEILING_DIRECTORIES"] = os.path.dirname(
        os.path.realpath(tmp))
    counter = [0]
    all_calls = []

    def drive(argv, mode=""):
        """Run main() with the stub as pac. Returns (rc, out, err, calls)."""
        counter[0] += 1
        log = os.path.join(logs, "%d.txt" % counter[0])
        os.environ["PACGUARD_STUB_LOG"] = log
        os.environ["PACGUARD_STUB_MODE"] = mode
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = main(["--pac", stub] + argv)
        calls = []
        if os.path.exists(log):
            with open(log) as fh:
                calls = fh.read().splitlines()
        all_calls.extend(calls)
        return rc, out.getvalue(), err.getvalue(), calls

    def commit_all(path):
        run_command(["git", "add", "-A"], cwd=path)
        run_command(["git", "-c", "user.name=t", "-c",
                     "user.email=t@example.invalid", "-c",
                     "commit.gpgsign=false", "commit", "-q", "-m", "x"],
                    cwd=path)

    def make(name, files=(), dirs=(), commit=None):
        """A workspace. commit True makes a repository with one commit,
        False leaves untracked files in a repository, None no repository."""
        path = os.path.join(tmp, name)
        os.mkdir(path)
        for f in files:
            with open(os.path.join(path, f), "w") as fh:
                fh.write("synthetic: 1\n")
        for d in dirs:
            os.mkdir(os.path.join(path, d))
        if commit is not None:
            run_command(["git", "init", "-q"], cwd=path)
            if commit:
                commit_all(path)
        return path

    classic = ("agent.mcs.yml", "settings.mcs.yml", "icon.png")
    clean_ws = make("clean", classic, ("topics",), commit=True)
    dirty_ws = make("dirty", classic, ("topics",), commit=True)
    with open(os.path.join(dirty_ws, "settings.mcs.yml"), "a") as fh:
        fh.write("edited: 1\n")
    plain_ws = make("plain", classic, ("topics",))
    plain2_ws = make("plain2", classic, ("topics",))
    cloned_ws = make("cloned", classic + ("connectionreferences.mcs.yml",),
                     ("topics", "actions", "connectors", "knowledge",
                      "workflows"), commit=True)
    cli_ws = make("cli", ("agent.sync.yaml", "settings.mcs.yml", "README.md"),
                  ("actions", ".git"))
    out_dir = os.path.join(tmp, "out")

    # ---- the argv builder: four calls, exact, long names only
    check(build_argv(WHO) == ["auth", "who"],
          "who builds exactly pac auth who")
    check(build_argv(LIST) == ["copilot", "list"],
          "list builds exactly pac copilot list")
    check(build_argv(PUSH, project_dir="ws") ==
          ["copilot", "push", "--project-dir", "ws"],
          "push builds exactly pac copilot push --project-dir")
    check(build_argv(PACK, project_dir="ws", publisher_prefix="demo",
                     output_path="out") ==
          ["copilot", "pack", "--publisher-prefix", "demo", "--project-dir",
           "ws", "--output-path", "out"],
          "pack builds exactly the documented long options")
    every = [build_argv(WHO), build_argv(LIST),
             build_argv(PUSH, project_dir="ws"),
             build_argv(PACK, project_dir="ws", publisher_prefix="demo",
                        output_path="out")]
    check(all(not t.startswith("-") or t.startswith("--")
              for argv in every for t in argv),
          "no built argument is a short alias such as -pd")
    for verb in ("pull", "publish", "delete", "quarantine", "clone", "create",
                 "import", "extract-template", "Push", "push ", "", None):
        raises(lambda v=verb: build_argv(v),
               "the verb %r cannot be built  <-- pinned defect" % (verb,))
    raises(lambda: build_argv(PUSH),
           "push without a project directory is refused")
    raises(lambda: build_argv(PACK, project_dir="ws"),
           "pack without a prefix and an output path is refused")

    # ---- what pac pack rejects, from the directory listing alone
    def entries(*names):
        return [(n.rstrip("/"), n.endswith("/")) for n in names]

    layout, bad = pack_verdict(entries(
        "agent.mcs.yml", "settings.mcs.yml", "icon.png", "topics/", ".mcs/"))
    check(layout == LAYOUT_CLASSIC and bad == [],
          "a plain classic workspace has nothing pac rejects")
    layout, bad = pack_verdict(entries(
        "agent.mcs.yml", "actions/", "connectors/", "knowledge/",
        "workflows/", "connectionreferences.mcs.yml"))
    check(layout == LAYOUT_CLASSIC and bad == [
        "actions/", "connectionreferences.mcs.yml", "connectors/",
        "knowledge/", "workflows/"],
        "a cloned classic workspace lists all five entries at once, a "
        "directory with a slash and a file without  <-- pinned defect")
    layout, bad = pack_verdict(entries("agent.mcs.yml", "ACTIONS/",
                                       "Readme.MD"))
    check(bad == ["ACTIONS/", "Readme.MD"],
          "names match without regard to case")
    layout, bad = pack_verdict(entries(
        "agent.mcs.yml", ".git/", ".gitignore", "README.md"))
    check(bad == [".git/", ".gitignore", "README.md"],
          "version control files are rejected in a classic workspace"
          "  <-- pinned defect")
    layout, bad = pack_verdict(entries(
        "agent.sync.yaml", "actions/", ".git/", "README.md"))
    check(layout == LAYOUT_CLI and bad == [],
          "a CLI-authored workspace with the same extras is not refused"
          "  <-- pinned defect")
    layout, bad = pack_verdict(entries(
        "agent.mcs.yml", "extra/", "entities/", "variables/", "dialogs/",
        "translations/", "skills/", "components/", "botcomponents/"))
    check(bad == ["botcomponents/", "components/", "dialogs/", "entities/",
                  "extra/", "skills/", "translations/", "variables/"],
          "the eight other entries the probe runs saw rejected are listed too"
          "  <-- pinned defect")
    layout, bad = pack_verdict(entries("AGENT.MCS.YML", "Actions/"))
    check(layout == LAYOUT_CLASSIC and bad == ["Actions/"],
          "an upper-case classic marker is still found")
    layout, bad = pack_verdict(entries("Agent.Sync.Yaml", "actions/"))
    check(layout == LAYOUT_CLI and bad == [],
          "an upper-case CLI marker is still found")
    layout, bad = pack_verdict(entries(
        "agent.sync.yaml", "agent.mcs.yml", "actions/"))
    check(layout == LAYOUT_CLI and bad == [],
          "with both markers the workspace counts as cli-authored and is "
          "never refused")
    layout, bad = pack_verdict(entries("notes.txt"))
    check(layout == LAYOUT_UNKNOWN and bad == [],
          "a folder with neither marker is an unrecognised layout")
    layout, bad = pack_verdict([])
    check(layout == LAYOUT_UNKNOWN, "an empty folder is an unrecognised layout")

    # ---- git state
    check(classify_git(0, "") == CLEAN, "empty porcelain output is CLEAN")
    check(classify_git(0, "  \n") == CLEAN,
          "blank porcelain output is CLEAN, not DIRTY")
    check(classify_git(0, " M settings.mcs.yml\n") == DIRTY,
          "a modified file is DIRTY")
    check(classify_git(0, "?? new.mcs.yml\n") == DIRTY,
          "an untracked file is DIRTY")
    check(classify_git(128, "") == UNKNOWN,
          "a failed git is UNKNOWN, never CLEAN  <-- pinned defect")
    check(git_state(clean_ws) == CLEAN, "a committed repository is CLEAN")
    check(git_state(dirty_ws) == DIRTY, "an edited repository is DIRTY")
    check(git_state(make("untracked", classic, ("topics",), commit=False))
          == DIRTY, "a fresh repository with nothing committed is DIRTY")
    check(git_state(plain_ws) == UNKNOWN,
          "a folder outside any repository is UNKNOWN")
    check(git_state(clean_ws, git="no-such-git-xyz") == UNKNOWN,
          "a missing git binary is UNKNOWN, not a crash")
    check(classify_git(0, "", tracked=False) == UNKNOWN,
          "nothing tracked and nothing to report is UNKNOWN, not CLEAN"
          "  <-- pinned defect")
    check(classify_git(0, "?? a\n", tracked=False) == DIRTY,
          "an untracked file is DIRTY even when nothing is tracked yet")

    # A workspace git ignores reports nothing and tracks nothing.
    ign_root = make("ign", (), ("ws",))
    run_command(["git", "init", "-q"], cwd=ign_root)
    with open(os.path.join(ign_root, ".gitignore"), "w") as fh:
        fh.write("ws/\n")
    with open(os.path.join(ign_root, "ws", "agent.mcs.yml"), "w") as fh:
        fh.write("synthetic: 1\n")
    commit_all(ign_root)
    check(git_state(os.path.join(ign_root, "ws")) == UNKNOWN,
          "a workspace that git ignores is UNKNOWN, never CLEAN"
          "  <-- pinned defect")

    # A new file stays visible whatever the user's status settings say.
    hide_ws = make("hide", classic, ("topics",), commit=True)
    run_command(["git", "config", "status.showUntrackedFiles", "no"],
                cwd=hide_ws)
    with open(os.path.join(hide_ws, "topic-new.mcs.yml"), "w") as fh:
        fh.write("synthetic: 1\n")
    check(run_command(["git", "status", "--porcelain"], cwd=hide_ws)[1] == ""
          and git_state(hide_ws) == DIRTY,
          "a new file is DIRTY although status.showUntrackedFiles hides it"
          "  <-- pinned defect")

    # A workspace inside a larger repository is judged on its own files.
    mono = make("mono", (), ("ws", "other"))
    for sub in ("ws", "other"):
        with open(os.path.join(mono, sub, "f.txt"), "w") as fh:
            fh.write("synthetic: 1\n")
    run_command(["git", "init", "-q"], cwd=mono)
    commit_all(mono)
    with open(os.path.join(mono, "other", "new.txt"), "w") as fh:
        fh.write("synthetic: 1\n")
    check(git_state(os.path.join(mono, "ws")) == CLEAN
          and git_state(os.path.join(mono, "other")) == DIRTY,
          "a dirty sibling folder does not make the workspace DIRTY"
          "  <-- pinned defect")

    # The check must not touch the repository. A file whose time changed
    # makes plain git status rewrite .git/index, which is the write.
    idx_ws = make("idx", classic, ("topics",), commit=True)
    marker = os.path.join(idx_ws, "agent.mcs.yml")
    stat = os.stat(marker)
    os.utime(marker, (stat.st_atime, stat.st_mtime + 10))
    index_path = os.path.join(idx_ws, ".git", "index")

    def index_bytes():
        with open(index_path, "rb") as fh:
            return fh.read()

    before = index_bytes()
    git_state(idx_ws)
    drive([idx_ws])
    kept = index_bytes() == before
    run_command(["git", "status", "--porcelain"], cwd=idx_ws)
    check(kept and index_bytes() != before,
          "the check leaves .git/index byte for byte as it was, and a plain "
          "git status would not  <-- pinned defect")

    # ---- the decision
    def a_(git, rejected=(), layout=LAYOUT_CLASSIC):
        return Assessment("w", layout, list(rejected), git)

    check(decide(None, [a_(DIRTY, ["x"])]) == [],
          "with no action nothing is refused, the run only reports")
    check(len(decide(PUSH, [a_(DIRTY)])) == 1,
          "a push from a DIRTY worktree is refused")
    check(len(decide(PUSH, [a_(UNKNOWN)])) == 1,
          "a push where git cannot answer is refused  <-- pinned defect")
    check(decide(PUSH, [a_(CLEAN)]) == [], "a push from a CLEAN worktree is allowed")
    check(decide(PUSH, [a_(DIRTY)], allow_dirty=True) == [],
          "--allow-dirty lets a DIRTY push through")
    check(decide(PUSH, [a_(CLEAN, ["actions/"])]) == [],
          "pack blockers do not stop a push")
    check(len(decide(PACK, [a_(CLEAN, ["actions/"])])) == 1,
          "a pack with blockers is refused")
    check(len(decide(PACK, [a_(CLEAN, layout=LAYOUT_UNKNOWN)],
                     allow_cloned_pack=True)) == 1,
          "no override lets a folder that is not a workspace be packed")
    check(decide(PACK, [a_(DIRTY)]) == [],
          "a DIRTY worktree does not stop a pack, which only reads")
    check(decide(PACK, [a_(CLEAN, ["actions/"])], allow_cloned_pack=True)
          == [], "--allow-cloned-pack lets the pack through")

    # ---- output hygiene
    check(scrub("Access Token: abc\nUser: a") ==
          ["[line withheld: it looks like a credential]", "User: a"],
          "a line that names a token is withheld, the next line is kept")
    check(scrub("CLIENT SECRET=1")[0].startswith("[line withheld"),
          "the match ignores case")
    for word in ("token", "secret", "password", "bearer", "authorization",
                 "credential"):
        check(scrub("x %s y" % word)[0].startswith("[line withheld")
              and scrub("x %s y" % word.upper())[0].startswith("[line"),
              "a line holding %r is withheld in either case  <-- pinned "
              "defect" % word)
    check(scrub("sig=abc123 key=zzz") == ["sig=abc123 key=zzz"],
          "a line with none of the six words is printed, the filter is a "
          "keyword list and not a secret detector")
    check(scrub("") == [], "empty output is no lines")
    buf = io.StringIO()
    echo("a\n\nb\n", buf)
    check(buf.getvalue() == "  | a\n  | b\n",
          "pac output is indented and its blank lines are dropped")
    check(show(["a", "b c"]) == 'a "b c"',
          "an argument with a space is quoted in the printed command")

    # ---- abbreviations: the whole point of allow_abbrev=False
    pins_held = True
    for flag in ("--ap", "--app", "--appl", "--appl=1", "--apply=1"):
        rc, out, err, calls = drive([clean_ws, "--push", flag])
        held = rc == EXIT_USAGE and calls == []
        pins_held = pins_held and held
        check(held, "%s is refused with exit 64 and pac is never started"
              "  <-- pinned defect" % flag)
    parser = _build_parser()
    longs = sorted(o for o in parser._option_string_actions
                   if o.startswith("--") and o != "--help")
    refused = 0
    tried = 0
    # Skipped when a pin above failed: with abbreviations on, --se would start
    # a nested self-test and the run would never end.
    for flag in (longs if pins_held else ()):
        for cut in range(3, len(flag)):
            prefix = flag[:cut]
            if prefix in parser._option_string_actions:
                continue
            tried += 1
            rc, _, _, calls = drive([clean_ws, prefix])
            refused += (rc == EXIT_USAGE and calls == [])
    check(tried > 40 and refused == tried,
          "every proper prefix of every long flag is refused, %d of %d"
          "  <-- pinned defect" % (refused, tried))
    check(drive([clean_ws, "--bogus"])[0] == EXIT_USAGE,
          "an unknown flag exits 64, not argparse's 2")
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = main(["--help"])
    check(rc == 0 and "--apply" in buf.getvalue(),
          "--help prints and exits 0")

    # ---- usage problems, all before any pac call
    cases = (
        ([clean_ws, "--push", "--pack", "--publisher-prefix", "d",
          "--output-path", "o"], "separate runs"),
        ([], "at least one workspace"),
        ([clean_ws, "--apply"], "--apply needs --push or --pack"),
        ([clean_ws, clean_ws, "--push"], "exactly one workspace"),
        ([clean_ws, "--push", "--offline"], "--offline cannot push"),
        ([clean_ws, "--pack"], "--pack needs --publisher-prefix"),
        ([clean_ws, "--pack", "--publisher-prefix", "d"],
         "--pack needs --publisher-prefix and --output-path"),
        ([clean_ws, "--publisher-prefix", "d"],
         "--publisher-prefix needs --pack"),
        ([clean_ws, "--output-path", "o"], "--output-path needs --pack"),
        ([clean_ws, "--allow-cloned-pack"], "--allow-cloned-pack needs --pack"),
        ([clean_ws, "--allow-dirty"], "--allow-dirty needs --push"),
    )
    for argv, text in cases:
        rc, out, err, calls = drive(argv)
        check(rc == EXIT_USAGE and text in err and calls == [],
              "usage: %s" % text)

    # ---- the default is a check
    snapshot = sorted(os.listdir(clean_ws))
    rc, out, err, calls = drive([clean_ws])
    check(rc == 0 and calls == ["auth who", "copilot list"],
          "the default run asks pac who and list and nothing else")
    check("layout: classic" in out and "git: CLEAN" in out and
          "tester@example.invalid" in out,
          "the default run prints the layout, the git state and pac's answer")
    check(sorted(os.listdir(clean_ws)) == snapshot and
          git_state(clean_ws) == CLEAN,
          "the default run changes nothing in the workspace")
    rc, out, err, calls = drive([clean_ws, dirty_ws, cloned_ws])
    check(rc == 0 and out.count("workspace ") == 3,
          "the default run reports every workspace and does not refuse "
          "what it was not asked to do")
    check("pac rejects .git/, actions/, connectionreferences.mcs.yml, "
          "connectors/, knowledge/, workflows/" in out,
          "a cloned workspace shows its pack verdict even on a plain check")
    rc, out, err, calls = drive([plain_ws, "--offline"])
    check(rc == 0 and "git: UNKNOWN" in out,
          "a report-only run exits 0 even when git is UNKNOWN, as the README "
          "says")
    rc, out, err, calls = drive([tmp, "--offline"])
    check(rc == 0 and "layout: unrecognised" in out
          and "not an agent workspace" in out,
          "a report-only run exits 0 even for a folder that is not a "
          "workspace, as the README says")
    rc, out, err, calls = drive([clean_ws, "--offline"])
    check(rc == 0 and calls == [] and "tester" not in out,
          "--offline starts no pac process at all")
    upper_stub = os.path.join(tmp, "STUBUP.PY")
    shutil.copyfile(stub, upper_stub)
    rc, out, err, calls = drive([clean_ws, "--pac", upper_stub])
    check(rc == 0 and calls == ["auth who", "copilot list"],
          "a stand-in whose name ends in .PY runs under this Python")
    rc, out, err, calls = drive([clean_ws], mode="secret")
    check(rc == 0 and "not-a-real-value-0001" not in out + err
          and "Token Expires" not in out + err and "withheld" in out
          and "tester@example.invalid" in out,
          "a credential-looking line from pac never reaches the output"
          "  <-- pinned defect")
    rc, out, err, calls = drive([clean_ws], mode="stderrleak")
    check(rc == 0 and "not-a-real-value-0002" not in out + err
          and "withheld" in err,
          "a credential-looking line on pac's stderr is withheld too"
          "  <-- pinned defect")
    rc, out, err, calls = drive([clean_ws], mode="auth")
    check(rc == EXIT_PAC and calls == ["auth who"] and "exited 7" in err,
          "a failing pac auth who exits 3 and stops before list")
    rc, out, err, calls = drive([clean_ws], mode="list")
    check(rc == EXIT_PAC and calls == ["auth who", "copilot list"],
          "a failing pac copilot list exits 3")
    rc, out, err, calls = drive([clean_ws, "--pac", "no-such-pac-xyz"])
    check(rc == EXIT_MISSING and "not found" in err and calls == [],
          "a pac that is not on the path exits 2")
    rc, out, err, calls = drive([clean_ws, "--pac", os.path.join(tmp, "x.py")])
    check(rc == EXIT_MISSING and "not found" in err,
          "a missing .py stand-in exits 2")
    rc, out, err, calls = drive([os.path.join(tmp, "nowhere")])
    check(rc == EXIT_MISSING and "not a directory" in err and calls == [],
          "a workspace that does not exist exits 2 before any pac call")
    rc, out, err, calls = drive([stub])
    check(rc == EXIT_MISSING and "not a directory" in err,
          "a file in place of a workspace exits 2")
    rc, out, err, calls = drive([clean_ws, "--pac", sys.executable])
    check(rc == EXIT_PAC and "exited" in err,
          "a real executable that fails is reported as exit 3, not as a "
          "finding")

    # ---- push: a dry run first, the live agent only behind --apply
    rc, out, err, calls = drive([clean_ws, "--push"])
    check(rc == 0 and calls == ["auth who", "copilot list"]
          and "Check only" in out and "pac copilot push --project-dir"
          in out,
          "a push without --apply prints the command and does not run it"
          "  <-- pinned defect")
    check(out.index("pac copilot list") < out.index("Check only"),
          "the dry-run notice comes after the read-only calls it follows, "
          "so it never says nothing ran before something did"
          "  <-- pinned defect")
    rc, out, err, calls = drive([dirty_ws, "--push"])
    check(rc == EXIT_REFUSED and calls == [] and "Refused" in out,
          "a dirty push is refused before pac is even asked who")
    rc, out, err, calls = drive([dirty_ws, "--push", "--apply"])
    check(rc == EXIT_REFUSED and calls == [],
          "a dirty push is still refused with --apply")
    rc, out, err, calls = drive([plain_ws, "--push", "--apply"])
    check(rc == EXIT_REFUSED and "UNKNOWN" in out and calls == [],
          "a push from outside a repository is refused with --apply")
    rc, out, err, calls = drive([clean_ws, "--push", "--apply"])
    check(rc == 0 and calls == ["auth who", "copilot list",
                                "copilot push --project-dir " + clean_ws]
          and "pushed" in out,
          "--push --apply runs who, list and then exactly one push")
    rc, out, err, calls = drive([clean_ws, "--push", "--apply",
                                 "--allow-dirty"])
    check(rc == 0 and "ALLOW-DIRTY" not in out,
          "--allow-dirty on a clean worktree prints no warning")
    rc, out, err, calls = drive([dirty_ws, "--push", "--apply",
                                 "--allow-dirty"])
    check(rc == 0 and calls[-1] == "copilot push --project-dir " + dirty_ws
          and "ALLOW-DIRTY" in out,
          "--allow-dirty pushes a dirty worktree and says so")
    rc, out, err, calls = drive([clean_ws, "--push", "--apply"], mode="push")
    check(rc == EXIT_PAC and "exited 7" in err and "pushed" not in out,
          "a failed push exits 3 and never claims it pushed")
    rc, out, err, calls = drive([clean_ws, "--push", "--apply"], mode="auth")
    check(rc == EXIT_PAC and calls == ["auth who"],
          "a failed sign-in check stops the push before it starts")

    notws = make("notws", ("notes.txt",), commit=True)
    rc, out, err, calls = drive([notws, "--push", "--apply"])
    check(rc == 0 and calls[-1] == "copilot push --project-dir " + notws
          and "layout: unrecognised" in out,
          "a push of a folder with no agent marker is left to pac, which "
          "decides, as the README says")

    # ---- pack: the cloned-agent refusal
    pack = ["--pack", "--publisher-prefix", "demo", "--output-path", out_dir]
    rc, out, err, calls = drive([cloned_ws] + pack)
    check(rc == EXIT_REFUSED and calls == [] and "actions/" in out
          and "connectionreferences.mcs.yml" in out and "workflows/" in out,
          "a cloned workspace is refused for pack and every entry is named"
          "  <-- pinned defect")
    rc, out, err, calls = drive([cloned_ws, "--apply"] + pack)
    check(rc == EXIT_REFUSED and calls == [],
          "a cloned workspace is refused for pack with --apply too")
    rc, out, err, calls = drive([cloned_ws, "--allow-cloned-pack"] + pack)
    check(rc == 0 and calls == [] and "Check only" in out,
          "--allow-cloned-pack turns the refusal into a dry run")
    rc, out, err, calls = drive([cloned_ws, "--allow-cloned-pack", "--apply"]
                                + pack)
    check(rc == 0 and calls == [
        "copilot pack --publisher-prefix demo --project-dir " + cloned_ws
        + " --output-path " + out_dir],
        "--allow-cloned-pack --apply runs pack with the exact long options")
    rc, out, err, calls = drive([plain_ws, "--apply"] + pack)
    check(rc == 0 and len(calls) == 1 and calls[0].startswith("copilot pack ")
          and "wrote" not in out and not os.path.exists(out_dir),
          "pack runs alone, with no who or list, and pacguard writes nothing "
          "itself")
    rc, out, err, calls = drive([clean_ws] + pack)
    check(rc == EXIT_REFUSED and "rejects .git/" in out,
          "a workspace that is itself a git repository is refused for pack"
          "  <-- pinned defect")
    rc, out, err, calls = drive([cli_ws, "--apply"] + pack)
    check(rc == 0 and len(calls) == 1,
          "a CLI-authored workspace with extra entries packs"
          "  <-- pinned defect")
    rc, out, err, calls = drive([plain_ws] + pack)
    check(rc == 0 and calls == [] and "Check only" in out,
          "a pack is not gated on git, and a dry run starts no pac process")
    rc, out, err, calls = drive([tmp] + pack)
    check(rc == EXIT_REFUSED and "not an agent workspace" in out,
          "a folder that is not a workspace is refused for pack")
    rc, out, err, calls = drive([plain_ws, plain2_ws, "--apply"] + pack,
                                mode="pack")
    check(rc == EXIT_PAC and len(calls) == 1,
          "a failing pack stops the run before the next workspace")
    rc, out, err, calls = drive([plain_ws, plain2_ws, "--apply"] + pack)
    check(rc == 0 and len(calls) == 2,
          "two workspaces are packed one after the other")

    # ---- pac cannot wait on a prompt
    real_run = subprocess.run
    stdin_seen = []

    def spy(argv, **kwargs):
        stdin_seen.append(kwargs.get("stdin"))
        return real_run(argv, **kwargs)

    subprocess.run = spy
    try:
        run_command([sys.executable, "-c", "pass"])
    finally:
        subprocess.run = real_run
    check(stdin_seen == [subprocess.DEVNULL],
          "every process runs with stdin closed, so pac cannot wait on a "
          "prompt  <-- pinned defect")

    # ---- the guarantee across every run above
    seen = sorted(set(" ".join(c.split()[:2]) for c in all_calls))
    check(all(s in ALLOWED_CALLS for s in seen) and len(seen) == 4,
          "across every run only the four allowed pac calls were ever made"
          "  <-- pinned defect")
    check(sum(1 for c in all_calls if c.startswith("copilot push")) == 5,
          "exactly five pushes were attempted in the whole self-test, "
          "each one behind --push --apply")

    # ---- unexpected failures and odd output
    original = globals()["run_command"]

    def boom(argv, cwd=None):
        raise RuntimeError("synthetic")

    globals()["run_command"] = boom
    try:
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = main([clean_ws, "--offline"])
    finally:
        globals()["run_command"] = original
    check(rc == EXIT_CRASH and "fault in the tool" in err.getvalue(),
          "an unexpected exception exits 70, not the 1 that means refused"
          "  <-- pinned defect")
    os.environ["PACGUARD_STUB_MODE"] = "unicode"
    raw = io.BytesIO()
    narrow = io.TextIOWrapper(raw, encoding="ascii")
    with contextlib.redirect_stdout(narrow):
        rc = main(["--pac", stub, clean_ws])
    narrow.flush()
    check(rc == 0 and b"snowman ?" in raw.getvalue(),
          "a character the console cannot encode prints as ? and the "
          "verdict still arrives  <-- pinned defect")

    # ---- what the source is allowed to contain
    with open(os.path.abspath(__file__), "rb") as fh:
        source = fh.read()
    check(all(b < 128 for b in source), "the source is pure ASCII")
    tree = ast.parse(source.decode("ascii"))
    modules = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(n.name.split(".")[0] for n in node.names)
        elif isinstance(node, ast.ImportFrom):
            modules.add((node.module or "").split(".")[0])
    check(modules <= ALLOWED_IMPORTS,
          "the imports are the standard ones and none opens a socket")
    check(not any(isinstance(n, ast.JoinedStr) for n in ast.walk(tree)),
          "the source has no f-string, so Python 3.9 reads it")

    # ---- the harness itself
    quiet = sys.stdout
    sys.stdout = io.StringIO()
    mark = len(failed)
    try:
        check(False, "probe: a false condition must be recorded")
        raises(lambda: None, "probe: a call that raises nothing must fail")
        raises(lambda: [][0], "probe: the wrong exception must fail")
    finally:
        sys.stdout = quiet
    probe = failed[mark:]
    del failed[mark:]
    check(len(probe) == 3,
          "check() and raises() really do record a failure"
          "  <-- pinned defect")
    raises(lambda: (_ for _ in ()).throw(ValueError("x")),
           "and raises() accepts the ValueError it is looking for")

    # A self-test that raises still removes its temp directory.
    seen = []
    real_body = globals()["_self_test"]

    def exploding(path):
        seen.append(path)
        raise RuntimeError("synthetic")

    globals()["_self_test"] = exploding
    try:
        self_test()
    except RuntimeError:
        seen.append("raised")
    finally:
        globals()["_self_test"] = real_body
    check(len(seen) == 2 and seen[1] == "raised"
          and not os.path.exists(seen[0]),
          "a self-test that raises still removes its temp directory"
          "  <-- pinned defect")

    def summary(passed_count, failures):
        print("-" * 68)
        total = passed_count + len(failures)
        if failures:
            print("%d assertions, %d failed" % (total, len(failures)))
            for f in failures:
                print("  FAILED: %s" % f)
            return 1
        print("%d assertions, 0 failed" % total)
        return 0

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        red = summary(1, ["probe one", "probe two"])
    check(red == 1 and "3 assertions, 2 failed" in buf.getvalue()
          and "  FAILED: probe two" in buf.getvalue(),
          "the footer reports failures by count and by name, and exits 1"
          "  <-- pinned defect")

    # ---- importing the module runs nothing
    spec = importlib.util.spec_from_file_location(
        "pacguard_imported", os.path.abspath(__file__))
    imported = importlib.util.module_from_spec(spec)
    buf = io.StringIO()
    cache_before = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        with contextlib.redirect_stdout(buf):
            spec.loader.exec_module(imported)
    finally:
        sys.dont_write_bytecode = cache_before
    check(buf.getvalue() == "" and imported.classify_git(0, "") == CLEAN,
          "importing the module prints nothing and exposes the core")

    return summary(passed[0], failed)


# ------------------------------------------------------------------------ cli

def _build_parser():
    ap = argparse.ArgumentParser(
        prog="pacguard.py",
        description="Wrap pac for a Copilot Studio agent workspace. Checks "
                    "by default. Only --apply changes anything.",
        epilog="Every flag must be spelled in full. Nothing runs against "
               "the live agent without --push and --apply.",
        allow_abbrev=False,
    )
    ap.add_argument("workspace", nargs="*", metavar="WORKSPACE",
                    help="an agent workspace directory")
    ap.add_argument("--pac", default="pac",
                    help="the pac program (default pac). A .py path runs "
                         "under this Python.")
    ap.add_argument("--offline", action="store_true",
                    help="skip the sign-in check (pac auth who and "
                         "copilot list)")
    ap.add_argument("--push", action="store_true",
                    help="plan pac copilot push for one workspace")
    ap.add_argument("--pack", action="store_true",
                    help="plan pac copilot pack for each workspace")
    ap.add_argument("--publisher-prefix", dest="publisher_prefix",
                    help="the publisher prefix pack needs")
    ap.add_argument("--output-path", dest="output_path",
                    help="the folder pack writes the solution zip to")
    ap.add_argument("--allow-dirty", dest="allow_dirty", action="store_true",
                    help="push even when git status is not CLEAN")
    ap.add_argument("--allow-cloned-pack", dest="allow_cloned_pack",
                    action="store_true",
                    help="pack even when the layout lists entries pac "
                         "rejected")
    ap.add_argument("--apply", action="store_true",
                    help="run the --push or --pack call. Without this "
                         "nothing is changed.")
    ap.add_argument("--self-test", dest="self_test", action="store_true",
                    help="run the offline assertions and exit")
    return ap


def _tolerate_odd_characters():
    """Make print() unable to fail on a character the console cannot encode.

    pac echoes an agent's display name, which can hold any character. A piped
    stdout on Windows is cp1252, and the UnicodeEncodeError exits 1, the code
    that means a check refused the run. A character that cannot be shown is
    printed as ? instead.
    """
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure:
            reconfigure(errors="replace")


def main(argv=None):
    """Run the CLI. An error this code did not anticipate exits 70, because 1
    is the code a scheduled job reads as 'a check refused the run'."""
    _tolerate_odd_characters()
    try:
        return _run(argv)
    except Exception as exc:
        print("error: unexpected %s: %s. This is a fault in the tool, not a "
              "finding about the workspace." % (type(exc).__name__, exc),
              file=sys.stderr)
        traceback.print_exc()
        return EXIT_CRASH


def _run(argv):
    try:
        args = _build_parser().parse_args(
            sys.argv[1:] if argv is None else argv)
    except SystemExit as exc:
        # argparse exits 2 on a flag it refuses, and 2 here means a workspace
        # or pac could not be found. A mistyped --ap is a usage error: 64.
        return EXIT_USAGE if exc.code == 2 else exc.code

    if args.self_test:
        return self_test()

    problem = usage_problem(args)
    if problem:
        print("error: %s" % problem, file=sys.stderr)
        return EXIT_USAGE

    for path in args.workspace:
        if not os.path.isdir(path):
            print("error: %s is not a directory." % path, file=sys.stderr)
            return EXIT_MISSING

    action = PUSH if args.push else PACK if args.pack else None
    assessments = [assess(path) for path in args.workspace]
    print("pacguard: %d workspace(s)" % len(assessments))
    for a in assessments:
        describe(a)

    refusals = decide(action, assessments, args.allow_dirty,
                      args.allow_cloned_pack)
    if refusals:
        print("\nRefused. Nothing was changed.")
        for reason in refusals:
            print("  %s" % reason)
        return EXIT_REFUSED

    # The sign-in check runs for everything but a pack, which is local.
    calls = []
    if not args.offline and action != PACK:
        calls += [build_argv(WHO), build_argv(LIST)]
    if action == PUSH:
        calls.append(build_argv(PUSH, project_dir=args.workspace[0]))
    if action == PACK:
        calls += [build_argv(PACK, project_dir=p,
                             publisher_prefix=args.publisher_prefix,
                             output_path=args.output_path)
                  for p in args.workspace]

    live = [c for c in calls if c[1] in (PUSH, PACK)]
    dry = bool(action) and not args.apply
    if dry:
        # The sign-in check is read-only, so a dry run still makes it.
        calls = [c for c in calls if c not in live]

    if args.allow_dirty and action == PUSH and args.apply and any(
            a.git != CLEAN for a in assessments):
        print("\nALLOW-DIRTY: pushing with no rollback commit.")

    pac = None
    if calls:
        pac = resolve_pac(args.pac)
        if pac is None:
            print("error: pac was not found (%s). Install the Power Platform "
                  "CLI, or pass --offline to skip the sign-in check."
                  % args.pac, file=sys.stderr)
            return EXIT_MISSING

    for call in calls:
        rc = run_pac(pac, call)
        if rc != 0:
            print("error: pac %s exited %d." % (" ".join(call[:2]), rc),
                  file=sys.stderr)
            return EXIT_PAC
        if call in live:
            print("pack done." if call[1] == PACK else "pushed.")

    if dry:
        for call in live:
            print("\nwould run: pac %s" % show(call))
        print("\nCheck only. That call was not run. Re-run with --apply.")
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())

# pacguard

Wrap the Power Platform `pac` CLI for a Copilot Studio agent workspace. It checks by default. It
refuses an abbreviated flag. It refuses a `pac copilot pack` that `pac` is known to reject. The
only call that changes the live agent runs on `--push --apply`, and on nothing else.

This is a pre-1.0 tool. It was built against `pac` 2.14.1. Read the Limits section before you
trust it with a real agent.

Here is how it goes. A team keeps a Copilot Studio agent as files in a folder. A short Python
script wraps `pac`, so nobody types the long commands by hand. The script has a flag named
`--apply`, and `--apply` runs `pac copilot push`, which sends the local files to the live agent.

Python's `argparse` accepts any unambiguous prefix of a long option. So `--ap` is `--apply`, and
so is `--appl`. Nobody chose that. It is the default, and the
[argparse documentation](https://docs.python.org/3.12/library/argparse.html#allow-abbrev) says
so. Someone types `--ap` to try a dry run. The script pushes half-edited files to the agent that
people are talking to.

The first defence is "`pac` rejects abbreviations itself". It does. `pac copilot push --project-d
ws` fails with `An unknown argument --project-d was passed`. But the flag that bit was the
wrapper's flag, not `pac`'s, so `pac`'s strictness does not help.

The second defence is "add a dry run". `pac copilot push` has none. Its usage line on 2.14.1 is
`pac copilot push [--project-dir]`, and nothing else. A wrapper has to supply the dry run, and
a dry run is only worth having if it is the default.

There is a quieter failure on the other side. `pac copilot pack` turns a workspace into a solution
zip. In one earlier run on `pac` 2.10.1, `pack` of a cloned agent failed, because the cloned layout
holds files that `pack` does not accept. `pac` fails loudly, with a long list. It does not
fail early, and a script that runs `pull`, `pack` and `push` in turn finds out in the middle.
Version control is the other cause. A workspace that is its own git repository holds `.git/`, and
`pack` rejects that too. So does one stray `CHANGELOG.md` or `desktop.ini`. Nobody expects a
`.gitignore` to break a deploy.

`pacguard` builds only four `pac` calls. It sets `allow_abbrev=False`. It reads the workspace and
git before it runs anything, and it refuses a pack that `pac` 2.14.1 would reject. It runs the one live call only when the literal `--apply` is present
next to `--push`.

```
$ python pacguard.py --self-test
pacguard self-test: temporary files only, no network, no credentials
--------------------------------------------------------------------
PASS  who builds exactly pac auth who
PASS  list builds exactly pac copilot list
...
PASS  the verb 'pull' cannot be built  <-- pinned defect
PASS  the verb 'publish' cannot be built  <-- pinned defect
...
PASS  a cloned classic workspace lists all five entries at once, a directory with a slash and a file without  <-- pinned defect
...
PASS  version control files are rejected in a classic workspace  <-- pinned defect
PASS  a CLI-authored workspace with the same extras is not refused  <-- pinned defect
PASS  a name that is not on the accepted list is rejected, whatever it is  <-- pinned defect
...
PASS  the eight other entries the probe runs saw rejected are listed too  <-- pinned defect
...
PASS  a classic workspace without settings.mcs.yml will fail in pac  <-- pinned defect
...
PASS  a CLI-authored workspace with '' has no usable layoutVersion  <-- pinned defect
...
PASS  a CLI-authored workspace without settings.mcs.yml will fail in pac  <-- pinned defect
...
PASS  a failed git is UNKNOWN, never CLEAN  <-- pinned defect
...
PASS  nothing tracked and nothing to report is UNKNOWN, not CLEAN  <-- pinned defect
...
PASS  a workspace that git ignores is UNKNOWN, never CLEAN  <-- pinned defect
...
PASS  the check leaves .git/index byte for byte as it was, and a plain git status would not  <-- pinned defect
PASS  the check does not run a core.fsmonitor command from the workspace's own git config, and a plain git status would  <-- pinned defect
...
PASS  a push where git cannot answer is refused  <-- pinned defect
...
PASS  a missing required file refuses the pack and no override lifts it  <-- pinned defect
...
PASS  a line holding 'passwd' is withheld  <-- pinned defect
...
PASS  a bare JWT on a line of its own is withheld  <-- pinned defect
...
PASS  the value on the line after a label is withheld too, a blank line between does not save it  <-- pinned defect
...
PASS  --ap is refused with exit 64 and pac is never started  <-- pinned defect
PASS  --app is refused with exit 64 and pac is never started  <-- pinned defect
PASS  --appl is refused with exit 64 and pac is never started  <-- pinned defect
PASS  --appl=1 is refused with exit 64 and pac is never started  <-- pinned defect
PASS  --apply=1 is refused with exit 64 and pac is never started  <-- pinned defect
PASS  every proper prefix of every long flag is refused, 76 of 76  <-- pinned defect
...
PASS  a report-only run exits 0 even when git is UNKNOWN, as the README says  <-- pinned defect
...
PASS  a credential-looking line from pac never reaches the output  <-- pinned defect
...
PASS  a bare JWT line and the value under a label are withheld, the lines around them are printed  <-- pinned defect
PASS  bytes that are not UTF-8 print as a replacement character and the run goes on  <-- pinned defect
...
PASS  a push without --apply prints the command and does not run it  <-- pinned defect
...
PASS  a push where pac exits 1, the code real pac gave for a failed push, exits 3 and never claims it pushed  <-- pinned defect
...
PASS  --allow-dirty pushes where git is UNKNOWN and says so  <-- pinned defect
...
PASS  a cloned workspace is refused for pack and every entry is named  <-- pinned defect
...
PASS  a classic workspace with ordinary files pac does not know is refused for pack, not reported ok  <-- pinned defect
PASS  a classic workspace without settings.mcs.yml is refused for pack and --allow-cloned-pack does not lift it  <-- pinned defect
PASS  a workspace with both markers and an agent.sync.yaml pac cannot read is refused for pack  <-- pinned defect
...
PASS  across every run only the four allowed pac calls were ever made  <-- pinned defect
...
PASS  an unexpected exception exits 70, not the 1 that means refused  <-- pinned defect
PASS  a pac that is found but cannot start exits 2 with advice, not 70 with a traceback  <-- pinned defect
PASS  the message and the traceback of a crash pass the credential filter too  <-- pinned defect
PASS  a character the console cannot encode prints as ? and the verdict still arrives  <-- pinned defect
...
PASS  the footer reports failures by count and by name, and exits 1  <-- pinned defect
PASS  importing the module prints nothing and exposes the core
--------------------------------------------------------------------
196 assertions, 0 failed
```

The full run prints all 196 assertions. Each `...` line above is where this block is cut.

## What already exists

Use `pac` first. It is the tool that does the work, and `pacguard` calls it. The
[`pac copilot` reference](https://learn.microsoft.com/en-us/power-platform/developer/cli/reference/copilot)
describes `init`, `clone`, `pull`, `push` and `pack`. It says `pull` merges the server draft into
your files with a three-way merge, `push` stops and asks for a `pull` when the same item changed on
both sides, and `pack` is purely local and needs no sign-in. Those are good behaviours. `pac` does
not need a wrapper for them.

Microsoft's [`powerplatform-cli-wrapper`](https://github.com/microsoft/powerplatform-cli-wrapper)
is a different kind of wrapper. Its README describes it as the layer between the Power Platform
Build Tools, the GitHub Actions and `pac`. It serves those hosts. It is not a guard for a person
who types commands.
[`powerplatform-actions`](https://github.com/microsoft/powerplatform-actions) is the supported
route for CI.

Two projects are closer to this one. I read the files named here on 2026-10-29 and ran neither.

- [`rcb0727/powerplatform-mcp-docs`](https://github.com/rcb0727/powerplatform-mcp-docs) is a large
  MCP server for an AI assistant. Its README lists a `pac_copilot_push` tool. The tool previews
  the target and changes nothing unless `confirm=true`. Merge-conflict markers always block it,
  and lint findings block it unless `allowLintFindings=true`. That is a real default dry run, and
  it is stronger than `pacguard` on the content of the files. It serves an assistant that calls
  tools. It is not a small program for a person who types flags, and its README does not mention
  abbreviated flags or the pack layout.
- Microsoft's [`copilot-studio-plugin`](https://github.com/microsoft/copilot-studio-plugin) has a
  `push-agent` skill. The skill tells an assistant to pull, then run `pac copilot push` with an
  explicit `--project-dir`, and to reject a path with unsafe characters. A skill is instructions
  for a model. It is not a program that refuses a flag.

[`jonnybottles/copilot-studio-agent-skills`](https://github.com/jonnybottles/copilot-studio-agent-skills)
is a set of skills that teach an assistant to drive `pac copilot`, checked against `pac` 2.9.3. I
read its README and did not find a push guard there. I did not read the skills themselves.

A search of GitHub for `pac copilot push` found one more repository,
[`KarimaKT/Distribute-Develop-Modern-CopilotStudio-agents`](https://github.com/KarimaKT/Distribute-Develop-Modern-CopilotStudio-agents).
Its description says it deploys by solution import, not by `pac copilot push`. That is another
valid route, and it avoids the problem rather than guarding it.

Four unrelated repositories on GitHub are also named `pacguard`, found with
`gh search repos pacguard` on 2026-10-29. `blackXploit-404/pacguard` is a package guardian.
`Kxzrtx/pacguard` manages Arch Linux updates. `1MEshh/Pacguard` audits Arch PKGBUILD files.
`carlbernal/pacguard` is a Chrome extension that blocks domains with a generated proxy PAC script.
That "PAC" is proxy auto-config, and it is easy to confuse with this tool. None of them has
anything to do with the Power Platform CLI.

On 2026-10-22 I searched GitHub for a small command-line wrapper that adds a default dry run and
a refusal of the pack layout to `pac copilot`, and found none. On 2026-10-29 I found the two
projects above. The search shows only what it found on those days. It does not show that no such
tool exists.

## Requirements

Python 3.9 or newer and nothing else. `git` is needed for the push check. `pac` is needed for
everything but `--offline` and a pack dry run. The self-test needs neither `pac` nor a network.
It uses a small stand-in script for `pac`.

The self-test prints the same 196 assertions on Windows (Python 3.13.2 and 3.9.25) and on Ubuntu
(Python 3.12.3). The three outputs match line for line, so there is no difference to explain. One assertion needs a `git` that runs a
`core.fsmonitor` command on `git status`, and it was run only on git 2.53.0 (Windows) and git
2.43.0 (Ubuntu). `python -W error` compiles the file clean. `pyflakes` is clean on Windows;
Ubuntu has no `pyflakes`, so it was not run there. `coverage run --branch pacguard.py --self-test`
reports 100 percent of statements and branches (765 statements, 172 branches) on Windows.
Coverage is not installed on the Ubuntu host, so I did not measure it there.

`pacguard` opens no socket, so it has no network path to test against a stub server. `pac` makes
the network calls. The self-test pins that the source imports no network module.

```
git clone https://github.com/uhsear/pacguard.git
```

## Usage

```
python pacguard.py --self-test
python pacguard.py agents/support
python pacguard.py agents/support --offline
python pacguard.py agents/support --push
python pacguard.py agents/support --push --apply
python pacguard.py agents/support --pack --publisher-prefix demo --output-path out
python pacguard.py agents/support --pack --publisher-prefix demo --output-path out --apply
```

| Flag | Default | What it does |
|---|---|---|
| `WORKSPACE` | none | One or more agent workspace folders. Required unless `--self-test`. |
| `--pac` | `pac` | The `pac` program. A path ending in `.py` runs under this Python. |
| `--offline` | off | Skip the sign-in check (`pac auth who` and `pac copilot list`). |
| `--push` | off | Plan `pac copilot push` for one workspace. |
| `--pack` | off | Plan `pac copilot pack` for each workspace. |
| `--publisher-prefix` | none | The prefix `pack` needs. Needs `--pack`. |
| `--output-path` | none | The folder `pack` writes the zip to. Needs `--pack`. |
| `--allow-dirty` | off | Push even when git status is not `CLEAN`. Needs `--push`. |
| `--allow-cloned-pack` | off | Pack even when the workspace holds top-level entries `pac` rejects. Needs `--pack`. |
| `--apply` | off | Run the `--push` or `--pack` call. Needs one of them. |
| `--self-test` | off | Run the assertions and exit. Other flags are ignored. |

Every flag must be spelled in full. The parser sets `allow_abbrev=False`, so `--ap`, `--app` and
`--appl` are refused with exit 64 instead of being read as `--apply`. The same holds for every
other proper prefix of every long flag. `--apply=1` is refused too.

The commands that `pacguard` builds use only long option names. `pac` also accepts short aliases
such as `-pd` for `--project-dir`. A long name cannot be mistaken for another option when
someone edits the line later.

**A run with no `--push` and no `--pack` only reports, and it exits 0 whatever it printed.** Read
the `git:` and `pack:` lines. A script that must stop on a bad workspace should add `--push` or
`--pack` and leave out `--apply`. That run starts no live call and exits 1 when a check refuses
it.

This is a real run against the self-test stand-in. `stubpac.py` came from
`python -c "import pacguard; open('stubpac.py', 'w').write(pacguard.STUB)"`. The workspace
`repo/support-agent` sits inside a git repository with one commit:

```
$ python pacguard.py repo/support-agent --push --pac stubpac.py
pacguard: 1 workspace(s)
workspace repo/support-agent
  layout: classic
  git: CLEAN (no uncommitted changes)
  pack: ok (every top-level entry is one pac accepts)
pac auth who
  | Stub profile: tester@example.invalid
pac copilot list
  | stub: copilot list

would run: pac copilot push --project-dir repo/support-agent

Check only. That call was not run. Re-run with --apply.
```

After one line was appended to `settings.mcs.yml`, the same command refused:

```
$ python pacguard.py repo/support-agent --push --pac stubpac.py
pacguard: 1 workspace(s)
workspace repo/support-agent
  layout: classic
  git: DIRTY (uncommitted changes)
  pack: ok (every top-level entry is one pac accepts)

Refused. Nothing was changed.
  repo/support-agent: git status is DIRTY. Commit first, so the last commit is a rollback point, or pass --allow-dirty.
```

An abbreviated flag is a usage error, and a workspace with `actions/` and `knowledge/` folders is
refused for pack:

```
$ python pacguard.py repo/support-agent --ap
usage: pacguard.py [-h] [--pac PAC] [--offline] [--push] [--pack]
                   [--publisher-prefix PUBLISHER_PREFIX]
                   [--output-path OUTPUT_PATH] [--allow-dirty]
                   [--allow-cloned-pack] [--apply] [--self-test]
                   [WORKSPACE ...]
pacguard.py: error: unrecognized arguments: --ap
$ python pacguard.py repo/cloned --offline --pack --publisher-prefix demo --output-path out
pacguard: 1 workspace(s)
workspace repo/cloned
  layout: classic
  git: DIRTY (uncommitted changes)
  pack: pac rejects actions/, knowledge/

Refused. Nothing was changed.
  repo/cloned: pac copilot pack rejects actions/, knowledge/. Pass --allow-cloned-pack if your pac release accepts them.
```

The exit codes of the four commands are 0, 1, 64 and 1. The first command wrote nothing. The
second refused before it asked `pac` anything. The `--apply` paths are not shown here. They are
exercised by the self-test with the stand-in, see Limits.

## What it checks

**The calls.** `build_argv` can build four calls: `auth who`, `copilot list`, `copilot push` and
`copilot pack`. Any other name raises `ValueError`. That includes `pull`, `publish`, `delete`,
`quarantine`, `clone`, `create` and `import`. A flag cannot reach them. Run them with `pac`
itself.

`pull` is left out on purpose. The reference says it merges the server draft into your local
files. A wrapper that is safe by default should not write into your work. `push` already stops
and asks for a `pull` when the same item changed on both sides.

**Git state.** A push needs a `CLEAN` worktree, so the last commit is a rollback point. The check
runs `git status --porcelain --untracked-files=all -- .` and `git ls-files --cached` inside the
workspace. Both run with `--no-optional-locks`, so git does not rewrite `.git/index`, and with
`-c core.fsmonitor=false`, so a workspace copied from elsewhere cannot name a command for git to
run. `DIRTY` means status printed something. `UNKNOWN` means one of three things: git is missing,
the folder is not in a repository, or git tracks no file in the folder. The third case covers a
workspace that `.gitignore` lists, because such a workspace has no commit to roll back to. A push
is refused on `UNKNOWN` and on `DIRTY`. `--allow-dirty` overrides both and prints a warning. A
pack does not gate on git. A pack run still prints the git line, and its verdict ignores it.

**Pack layout.** The check reads the top of the workspace and sorts it into one of three layouts:

| Layout | Marker | What `pacguard` does |
|---|---|---|
| `classic` | `agent.mcs.yml` | Refuse a pack when the folder holds a name outside the accepted list, or lacks `settings.mcs.yml`. |
| `cli-authored` | `agent.sync.yaml` | Accept extra entries. Refuse when `settings.mcs.yml` is missing or `agent.sync.yaml` has no usable `layoutVersion`. |
| `unrecognised` | neither | Always refuse. `--allow-cloned-pack` does not override this. |

A folder with both markers counts as `cli-authored`, because `pac` 2.14.1 packed one when
`agent.sync.yaml` was valid and refused it when `agent.sync.yaml` was not.

`pac` 2.14.1 accepted only these top-level names in a `classic` workspace: `agent.mcs.yml`,
`settings.mcs.yml`, `icon.png`, `topics/` and `.mcs/`. It rejected every other name I tried. That
includes the entries a cloned agent carries (`actions/`, `connectionreferences.mcs.yml`,
`connectors/`, `knowledge/`, `workflows/`), version control and editor files (`.git/`, `.github/`,
`.gitignore`, `.vscode/`, `README.md`, `LICENSE`) and ordinary files (`CHANGELOG.md`,
`desktop.ini`, `Thumbs.db`, `.idea/`). So `pacguard` uses an allow-list and refuses every other
name. `--allow-cloned-pack` overrides it for a `pac` release that accepts more.

A `cli-authored` workspace needs `settings.mcs.yml` and a line `layoutVersion: <whole number>`
at the start of a line in `agent.sync.yaml`. `pac` 2.14.1 refused a quoted number, `1.0`, `-1`,
an indented line and `layoutversion` in lower case. It accepted a trailing comment, a
byte order mark and Windows line endings. It refused version 2 as newer than the version 1 it
supports. `pacguard` reads up to 64 KiB of `agent.sync.yaml` for this and writes nothing.

The name match ignores case. One run lists every entry. `pac` also lists them all in one message,
so the gain is timing: the refusal comes before the call, and a script that chains `pack` after
other steps stops at the start.

A workspace that is its own git repository holds `.git/`, so a `classic` pack of it is refused.
Keep the repository one level above the workspace, or pack from a copy.

**Output.** A line of `pac` output is replaced with a notice when it holds `token`, `secret`,
`password`, `passwd`, `pwd`, `bearer`, `authorization`, `credential`, `access key`, `accesskey`,
`api key`, `apikey`, `api-key`, `private key` or `sig=`, or when it has the shape of a JWT (`eyJ`,
then text, a dot, and more text). If a withheld line ends with a colon or an equals sign, the next
line that holds text is withheld too, because it is the value. The same filter covers the message
and the traceback of a crash. The real `pac auth who` prints a `Token Expires` line, so this fires
in practice. It still prints the signed-in account name and an object id, as `pac` does, so its
output should not be pasted into a ticket. The point of the check is to show which account is
about to push.

**What it does not do.** The reference says `push` reads its target environment from the
workspace's sync metadata, not from the sign-in. So `pac auth who` shows who is signed in. It does
not prove which environment the push will reach.

## Exit codes

| Code | Meaning |
|---|---|
| 0 | With `--push` or `--pack`: every check passed, and with `--apply` the call ran and `pac` exited 0. With neither: the run only reported, whatever the `git:` and `pack:` lines say. |
| 1 | A check refused the `--push` or `--pack` run. Nothing was changed. |
| 2 | A workspace is not a folder, or `pac` was not found, or `pac` was found but could not be started. |
| 3 | `pac` ran and exited non-zero. |
| 64 | Usage error, including an abbreviated or unknown flag. |
| 70 | An unexpected crash. This is a fault in the tool, never a finding. |

A report-only run can still exit 2 or 3, because it runs `pac auth who` and `pac copilot list`
unless you pass `--offline`. A scheduled job reads 1 as "refused", so a crash must not use it.
That is why 70 exists.

## How each claim was exercised

| Claim | Where |
|---|---|
| Only four calls can be built, and short aliases are never emitted | Self-test: the builder cases, 12 verbs refused. |
| `--ap`, `--appl` and every other prefix of every flag are refused | Self-test: 5 pinned prefixes, then a sweep of 76 prefixes. |
| A refused prefix never starts `pac` | Self-test: the stub log is empty after each. |
| `pac` rejects an abbreviated option itself | One manual run on `pac` 2.14.1, see below. |
| A push needs `--push` and `--apply` | Self-test: dry run, dirty, unknown, clean, allow-dirty, pac exit 1 and pac exit 7 cases. |
| Exactly the allowed calls ran across the whole self-test | Self-test: the stub log of every run. |
| A cloned layout is refused for pack | Self-test, and a manual run with real `pac` 2.14.1, see below. |
| Only five top-level names pack in a classic workspace | Manual: probe runs of real `pac copilot pack`, see below. Self-test: ten ordinary names refused. |
| A classic workspace without `settings.mcs.yml` is refused | Self-test, and a manual run with real `pac` 2.14.1. |
| A `cli-authored` workspace packs with extra entries, and needs a usable `layoutVersion` | Self-test (14 `layoutVersion` texts), and manual runs with real `pac` 2.14.1. |
| A credential-looking line, a bare JWT and a value under a label are withheld | Self-test: the stub prints them, the output is searched for them. |
| A crash message and traceback pass the same filter | Self-test: a patched function raises an exception with a bearer line. |
| Bytes that are not UTF-8 do not crash the run | Self-test: a stub that prints byte `0xE9`. |
| A character the console cannot encode does not crash the run | Self-test: an ASCII-only console, a stub that prints U+2603. |
| A `core.fsmonitor` command in the workspace is not run | Self-test: a real repository whose config writes a marker file. A plain `git status` writes it, the check does not. |
| A `pac` that cannot start exits 2 | Self-test: `run_command` raises `OSError`. |
| A non-ASCII workspace name works | Self-test: a folder named with U+00E9 and a space. |
| Nothing is written by `pacguard` | Self-test: the workspace listing is unchanged, the output folder is never created, `.git/index` is byte for byte the same. |
| The source is ASCII, has no f-string and imports no network module | Self-test: read with `ast`. |
| A real `pac` that exits non-zero gives exit 3 | Self-test: the Python interpreter and a stub exit 1 and exit 7. Manual: a real push failure. |

**The manual run with real `pac`.** I installed `pac` 2.14.1 with
`dotnet tool install Microsoft.PowerApps.CLI.Tool` and ran it in a scratch folder on Windows on
2026-10-22. I repeated the pack probes on 2026-10-29. No tenant was involved in the commands
below.

- `pac copilot init` made a `classic` workspace. `pac copilot pack` on it produced a zip.
- With the five cloned entries added, `pac copilot pack` exited 1:
  `Unsupported file: connectionreferences.mcs.yml. Unsupported directory: actions/. Unsupported
  directory: connectors/. Unsupported directory: knowledge/. Unsupported directory: workflows/.`
  No zip was written.
- Each of `.git/`, `.github/`, `.vscode/`, `.gitignore`, `.gitattributes`, `.editorconfig`,
  `README.md` and `LICENSE` alone gave the same kind of error. So did `extra/`, `entities/`,
  `variables/`, `dialogs/`, `translations/`, `skills/`, `components/` and `botcomponents/`. On
  2026-10-29 so did `CHANGELOG.md`, `LICENSE.md`, `CLAUDE.md`, `notes.txt`, `desktop.ini`,
  `Thumbs.db`, `.gitkeep`, `.claude/`, `.idea/` and `.vs/`.
- These were accepted: `agent.mcs.yml`, `settings.mcs.yml`, `icon.png`, `topics/` with nested
  folders, and `.mcs/` with files in it.
- `pac copilot init --authoring-mode cli-copilot` made a `cli-authored` workspace with
  `agent.sync.yaml`. `pack` accepted it with `actions/`, `.git/` and `README.md` added.
- A classic workspace with `agent.mcs.yml` and no `settings.mcs.yml` gave `Missing required file:
  settings.mcs.yml.` An empty folder gave `Missing required file: settings.mcs.yml. Missing
  required file: agent.mcs.yml.`
- A folder with `agent.sync.yaml` and no `settings.mcs.yml` gave `agent.sync.yaml is present, but
  the workspace was not recognized as a CliCopilot layout.` A classic workspace plus an
  `agent.sync.yaml` holding `x: 1` gave `agent.sync.yaml is missing a parseable 'layoutVersion'.`
  The same classic workspace plus a valid `agent.sync.yaml` packed.
- `layoutVersion: 2` gave `This workspace uses a newer layout version (v2) than this build of pac
  supports (v1).` `layoutVersion: 0` packed.
- `pac` read no abbreviation. `--project-d` gave `An unknown argument --project-d was passed`.
  `--publisher-pre` gave `A required argument --publisher-prefix is missing`. Neither ran.
- A second `pack` into the same folder replaced the zip without a warning.
- On 2026-10-29 `pacguard --offline --pack` without `--apply` ran against eight scratch
  workspaces and agreed with real `pac` on each. It refused the one with `CHANGELOG.md` and
  `desktop.ini`, the classic one without `settings.mcs.yml`, the classic one with an unusable
  `agent.sync.yaml`, a CLI one without `settings.mcs.yml` and a CLI one with version 2. It
  accepted a valid CLI workspace, a classic workspace plus a valid `agent.sync.yaml`, and a valid
  classic workspace with `.mcs/`.
- On 2026-10-22 `pacguard --pack --apply` on the `classic` workspace printed `Solution zip
  created`, and exit 0. `pacguard --pack --allow-cloned-pack --apply` on the cloned layout printed
  the error above and exit 3. I did not repeat the `--apply` runs on 2026-10-29.
- `pacguard --push --apply`, with a stand-in only for `auth who` and `copilot list`, ran the real
  `pac copilot push` on a clean git workspace that was never cloned. `pac` exited 1 with
  `No synced workspace found at the specified directory`, and `pacguard` exited 3. `pac` printed
  its `Connected as` line before it failed, so a push attempt signs in even when it then fails.

The cloned layout in these runs is made of empty files and folders with the five names. The names
come from an earlier real clone, observed on `pac` 2.10.1, which I did not repeat. I ran no
`pac copilot clone`, because that needs a tenant.

## Limits

- **No real clone, and no real push, ever succeeded here.** The self-test covers the success path
  with a stand-in. The manual runs covered the failure path. A real successful push against a real
  agent was not exercised.
- **Every `--apply` path was exercised only through the self-test and the 2026-10-22 run.** The
  stub logs and the assertion that only four calls ran are the evidence for them. The manual
  `pac` claims above cannot be re-checked without `pac` 2.14.1. The 2026-10-22 `--apply` runs were
  not repeated.
- **The accepted-name list is observed, not documented.** The reference does not list what `pack`
  accepts. A name that newer `pac` versions accept, or that I never tried, is refused until you
  pass `--allow-cloned-pack`. That flag does not lift a missing `settings.mcs.yml` or a bad
  `layoutVersion`.
- **A push does not check the layout.** A push of a folder with no `agent.mcs.yml` or
  `agent.sync.yaml`, or one above the workspace such as a repository root, is not refused. Only
  pack refuses it. `pac` decides what a push does, and it usually fails with exit 3.
- **Pack replaces a zip with the same name.** `pacguard` does not guard that. It also does not
  check that several workspaces, or the same workspace named twice, write to one output folder.
  `pac` names the zip, so the second run can replace the first.
- **An output folder inside a workspace** makes the next pack see an `out/` entry, which `pac`
  rejects.
- **A workspace that git ignores is `UNKNOWN`, and a push of it is refused.** That holds only when
  git tracks no file in the folder. In a tracked workspace, a file that `.gitignore` lists, or one
  marked assume-unchanged or skip-worktree, can differ from the last commit and the workspace
  still reads `CLEAN`. `git status` does not list it, but `pac push` sends it, so the rollback
  guarantee does not cover that file.
- **`auth who` does not prove the push target.** See "What it does not do" above.
- **`pacguard` writes nothing, but `pac` may.** `pac auth who` and `pac copilot list` run on every
  non-pack run, including a dry run. `pac` may refresh its own token cache when they run.
- **The output filter is a word list and one shape.** A secret on a line without a listed word
  that is not shaped like a JWT passes, and so does a value two lines below its label. The filter
  withholds only the listed words, a JWT shape and the line after a label.
- **The output holds the account name and object id.** `pac` prints them, and `pacguard` shows
  them. Do not paste the output into a ticket.
- **Output is decoded as UTF-8 with replacement.** Output in another encoding shows replacement
  characters. The verdict does not change.
- **There is no timeout on `pac`.** A `pac` that waits for a browser sign-in with stdin closed can
  hang the run.
- **On Windows, a bare name can resolve from the current folder first.** `shutil.which("pac")`
  and the call to `git` can start a `pac.exe` or `git.exe` that sits in the working folder. Do not
  run `pacguard` from a folder you do not trust.
- **A workspace path that starts with a dash** is passed to `pac` as the value of `--project-dir`,
  and `pac` may read it as an option. Write such a path as `./-name`.
- **An unreadable workspace entry** (a permission error while listing the folder) exits 70 as a
  tool fault, not 2.
- **A directory named `agent.mcs.yml` or `agent.sync.yaml`** still counts as the marker. The
  match ignores case on every host, because Windows file names do. A Linux workspace with an
  `Actions/` folder is refused although a case-sensitive `pac` might accept it.
- **The `layoutVersion` rule is a line match, not a YAML parse.** It follows what `pac` 2.14.1 did
  with the texts I tried. A text I did not try may differ.
- **A push needs `.mcs/conn.json`, and `pacguard` does not look for it.** Microsoft's
  `push-agent` skill names that file as the sync metadata. A folder without it fails in `pac`, as
  in the manual run above.
- **Linux ran the self-test only.** There is no `dotnet` on that host, so real `pac` was not run
  there.
- **Piping the output into `head`, or a closed stdout, was not exercised.**
- **The `--pac` stand-in.** A `--pac` path ending in `.py` runs under the current Python. That
  is for the self-test. Do not point it at a script you do not trust.

## Related

Other single-file tools in this portfolio that check first and write only on `--apply`:

- [arcade-rule-deploy](https://github.com/uhsear/arcade-rule-deploy) - deploy Arcade attribute
  rules to a geodatabase, preflight-checked and idempotent.
- [sqldeploy](https://github.com/uhsear/sqldeploy) - preview a T-SQL deploy script one batch at
  a time, and run it only on `--apply`.
- [safe-republish](https://github.com/uhsear/safe-republish) - refuse to truncate a feature class
  when the staged replacement fails a plausibility check.

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
`pack` rejects that too. Nobody expects a `.gitignore` to break a deploy.

`pacguard` builds only four `pac` calls. It sets `allow_abbrev=False`. It reads the workspace and
git before it runs anything. It runs the one live call only when the literal `--apply` is present
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
PASS  version control files are rejected in a classic workspace  <-- pinned defect
PASS  a CLI-authored workspace with the same extras is not refused  <-- pinned defect
PASS  a failed git is UNKNOWN, never CLEAN  <-- pinned defect
PASS  a push where git cannot answer is refused  <-- pinned defect
...
PASS  --ap is refused with exit 64 and pac is never started  <-- pinned defect
PASS  --app is refused with exit 64 and pac is never started  <-- pinned defect
PASS  --appl is refused with exit 64 and pac is never started  <-- pinned defect
PASS  --appl=1 is refused with exit 64 and pac is never started  <-- pinned defect
PASS  --apply=1 is refused with exit 64 and pac is never started  <-- pinned defect
PASS  every proper prefix of every long flag is refused, 76 of 76  <-- pinned defect
...
PASS  a credential-looking line from pac never reaches the output  <-- pinned defect
...
PASS  a push without --apply prints the command and does not run it  <-- pinned defect
...
PASS  a workspace that is itself a git repository is refused for pack  <-- pinned defect
PASS  a CLI-authored workspace with extra entries packs  <-- pinned defect
...
PASS  across every run only the four allowed pac calls were ever made  <-- pinned defect
PASS  an unexpected exception exits 70, not the 1 that means refused  <-- pinned defect
PASS  a character the console cannot encode prints as ? and the verdict still arrives  <-- pinned defect
...
PASS  check() and raises() really do record a failure  <-- pinned defect
...
PASS  the footer reports failures by count and by name, and exits 1  <-- pinned defect
PASS  importing the module prints nothing and exposes the core
--------------------------------------------------------------------
116 assertions, 0 failed
```

The full run prints all 116 assertions. Each `...` line above is where this block is cut.

## What already exists

Use `pac` first. It is the tool that does the work, and `pacguard` calls it. The
[`pac copilot` reference](https://learn.microsoft.com/en-us/power-platform/developer/cli/reference/copilot)
describes `init`, `clone`, `pull`, `push` and `pack`. It says `pull` merges the server draft into
your files with a three-way merge, `push` stops and asks for a `pull` when the same item changed on
both sides, and `pack` is local and needs no sign-in. Those are good behaviours. `pac` does not
need a wrapper for them.

Microsoft's [`powerplatform-cli-wrapper`](https://github.com/microsoft/powerplatform-cli-wrapper)
is a different kind of wrapper. Its README describes it as the layer between the Power Platform
Build Tools, the GitHub Actions and `pac`. It serves those hosts. It is not a guard for a person
who types commands.
[`powerplatform-actions`](https://github.com/microsoft/powerplatform-actions) is the supported
route for CI.

[`jonnybottles/copilot-studio-agent-skills`](https://github.com/jonnybottles/copilot-studio-agent-skills)
is a set of skills that teach an assistant to drive `pac copilot`, checked against `pac` 2.9.3. I
read its README and did not find a push guard there. I did not read the skills themselves.

A search of GitHub for `pac copilot push` found one more repository,
[`KarimaKT/Distribute-Develop-Modern-CopilotStudio-agents`](https://github.com/KarimaKT/Distribute-Develop-Modern-CopilotStudio-agents).
Its description says it deploys by solution import, not by `pac copilot push`. That is another
valid route, and it avoids the problem rather than guarding it.

Two unrelated repositories on GitHub are also named `pacguard`. One is a package guard and the
other manages Arch Linux updates. They have nothing to do with the Power Platform CLI.

I searched GitHub for a wrapper that adds a default dry run and a refusal of the pack layout to
`pac copilot`, and found none on the day I ran it. That shows only that the search found nothing.

## Requirements

Python 3.9 or newer and nothing else. `git` is needed for the push check. `pac` is needed for
everything but `--offline` and a pack dry run. The self-test needs neither `pac` nor a network.
It uses a small stand-in script for `pac`.

The self-test prints the same 116 assertions on Windows (Python 3.13.2 and 3.9.25) and on Ubuntu
(Python 3.12.3). The three outputs match line for line. There is no difference to explain.
`coverage run --branch pacguard.py --self-test` reports 100 percent of statements and branches
on Windows. Coverage is not installed on the Ubuntu host, so I did not measure it there.

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
| `--allow-cloned-pack` | off | Pack even when the layout lists entries `pac` rejects. Needs `--pack`. |
| `--apply` | off | Run the `--push` or `--pack` call. Needs one of them. |
| `--self-test` | off | Run the assertions and exit. Other flags are ignored. |

Every flag must be spelled in full. The parser sets `allow_abbrev=False`, so `--ap`, `--app` and
`--appl` are refused with exit 64 instead of being read as `--apply`. The same holds for every
other proper prefix of every long flag. `--apply=1` is refused too.

The commands that `pacguard` builds use only long option names. `pac` also accepts short aliases
such as `-pd` for `--project-dir`. A long name cannot be mistaken for another option when
someone edits the line later.

A run with no `--push` and no `--pack` only reports. This is a real run against the self-test
stand-in, with the workspace inside a git repository:

```
$ python pacguard.py repo/support-agent --push
pacguard: 1 workspace(s)
workspace repo/support-agent
  layout: classic
  git: CLEAN (no uncommitted changes)
  pack: ok (nothing here is known to be rejected)
pac auth who
  | Stub profile: tester@example.invalid
pac copilot list
  | stub: copilot list

would run: pac copilot push --project-dir repo/support-agent

Check only. That call was not run. Re-run with --apply.
$ python pacguard.py repo/support-agent --push --apply
pacguard: 1 workspace(s)
workspace repo/support-agent
  layout: classic
  git: DIRTY (uncommitted changes)
  pack: ok (nothing here is known to be rejected)

Refused. Nothing was changed.
  repo/support-agent: git status is DIRTY. Commit first, so the last commit is a rollback point, or pass --allow-dirty.
$ python pacguard.py repo/support-agent --ap
pacguard.py: error: unrecognized arguments: --ap
```

The exit codes are 0, 1 and 64 in that order, and the usage text of the last one is cut. The
first command wrote nothing. The second refused before it asked `pac` anything.

## What it checks

**The calls.** `build_argv` can build four calls: `auth who`, `copilot list`, `copilot push` and
`copilot pack`. Any other name raises `ValueError`. That includes `pull`, `publish`, `delete`,
`quarantine`, `clone`, `create` and `import`. A flag cannot reach them. Run them with `pac`
itself.

`pull` is left out on purpose. The reference says it merges the server draft into your local
files. A wrapper that is safe by default should not write into your work. `push` already stops
and asks for a `pull` when the same item changed on both sides.

**Git state.** A push needs a `CLEAN` worktree, so the last commit is a rollback point. The check
runs `git status --porcelain -- .` inside the workspace. `DIRTY` means there is output. `UNKNOWN`
means git could not answer, because it is missing or the folder is not in a repository, and that
is refused too. `--allow-dirty` overrides both and prints a warning. A pack does not look at git.

**Pack layout.** The check reads the top of the workspace and sorts it into one of three layouts:

| Layout | Marker | What `pacguard` does |
|---|---|---|
| `classic` | `agent.mcs.yml` | Refuse a pack when the folder holds an entry from the lists below. |
| `cli-authored` | `agent.sync.yaml` | Never refuse. `pac` accepts extra entries here. |
| `unrecognised` | neither | Always refuse. `--allow-cloned-pack` does not override this. |

The entries `pac` 2.14.1 rejected at the top of a `classic` workspace:

| Group | Entries |
|---|---|
| Left by a cloned agent | `actions/`, `connectionreferences.mcs.yml`, `connectors/`, `knowledge/`, `workflows/` |
| Version control and editor files | `.git/`, `.github/`, `.gitignore`, `.gitattributes`, `.vscode/`, `.editorconfig`, `README.md`, `LICENSE` |

The match ignores case. One run lists every entry. `pac` also lists them all in one message, so
the gain is timing: the refusal comes before the call, and a script that chains `pack` after other
steps stops at the start.

A workspace that is its own git repository holds `.git/`, so a `classic` pack of it is refused.
Keep the repository one level above the workspace, or pack from a copy.

**Output.** A line of `pac` output that contains `token`, `secret`, `password`, `bearer`,
`authorization` or `credential` is replaced with a notice. The real `pac auth who` prints a
`Token Expires` line, so this fires in practice. It still prints the signed-in account name and an
object id, as `pac` does. The point of the check is to show which account is about to push.
Do not paste its output into a ticket.

**What it does not do.** The reference says `push` reads its target environment from the
workspace's sync metadata, not from the sign-in. So `pac auth who` shows who is signed in. It does
not prove which environment the push will reach.

## Exit codes

| Code | Meaning |
|---|---|
| 0 | Every check passed, and with `--apply` the call ran and `pac` exited 0. |
| 1 | A check refused the run. Nothing was changed. |
| 2 | A workspace is not a folder, or `pac` was not found. |
| 3 | `pac` ran and exited non-zero. |
| 64 | Usage error, including an abbreviated or unknown flag. |
| 70 | An unexpected crash. This is a fault in the tool, never a finding. |

A scheduled job reads 1 as "refused", so a crash must not use it. That is why 70 exists.

## How each claim was exercised

| Claim | Where |
|---|---|
| Only four calls can be built, and short aliases are never emitted | Self-test: the builder cases, 12 verbs refused. |
| `--ap`, `--appl` and every other prefix of every flag are refused | Self-test: 5 pinned prefixes, then a sweep of 76 prefixes. |
| A refused prefix never starts `pac` | Self-test: the stub log is empty after each. |
| `pac` rejects an abbreviated option itself | One manual run on `pac` 2.14.1, see below. |
| A push needs `--push` and `--apply` | Self-test: dry run, dirty, unknown, clean, allow-dirty and failed cases. |
| Exactly the allowed calls ran across the whole self-test | Self-test: the stub log of every run. |
| A cloned layout is refused for pack | Self-test, and a manual run with real `pac` 2.14.1, see below. |
| The entry lists match what `pac` rejects | Manual: more than 30 probe runs of real `pac copilot pack`, see below. |
| A `cli-authored` workspace packs with extra entries | Self-test, and a manual run with real `pac` 2.14.1. |
| A credential-looking line is withheld | Self-test: the stub prints a token line, the output is searched for it. |
| A character the console cannot encode does not crash the run | Self-test: an ASCII-only console, a stub that prints U+2603. |
| Nothing is written by `pacguard` | Self-test: the workspace listing is unchanged, the output folder is never created. |
| The source is ASCII, has no f-string and imports no network module | Self-test: read with `ast`. |
| A real `pac` that exits non-zero gives exit 3 | Self-test: the Python interpreter stands in as `pac`. Manual: a real push failure. |

**The manual run with real `pac`.** I installed `pac` 2.14.1 with
`dotnet tool install Microsoft.PowerApps.CLI.Tool` and ran it in a scratch folder on Windows on
2026-10-22. No tenant was involved in the commands below.

- `pac copilot init` made a `classic` workspace. `pac copilot pack` on it produced a zip.
- With the five cloned entries added, `pac copilot pack` exited 1:
  `Unsupported file: connectionreferences.mcs.yml. Unsupported directory: actions/. Unsupported
  directory: connectors/. Unsupported directory: knowledge/. Unsupported directory: workflows/.`
  No zip was written.
- Each of `.git/`, `.github/`, `.vscode/`, `.gitignore`, `.gitattributes`, `.editorconfig`,
  `README.md` and `LICENSE` alone gave the same kind of error. So did `extra/`, `entities/`,
  `variables/`, `dialogs/`, `translations/`, `skills/`, `components/` and `botcomponents/`.
- These were accepted: `agent.mcs.yml`, `settings.mcs.yml`, `icon.png`, `topics/` with nested
  folders, and `.mcs/` with files in it.
- `pac copilot init --authoring-mode cli-copilot` made a `cli-authored` workspace with
  `agent.sync.yaml`. `pack` accepted it with `actions/`, `.git/` and `README.md` added.
- An empty folder gave `Missing required file: settings.mcs.yml. Missing required file:
  agent.mcs.yml.`
- `pac` read no abbreviation. `--project-d` gave `An unknown argument --project-d was passed`.
  `--publisher-pre` gave `A required argument --publisher-prefix is missing`. Neither ran.
- A second `pack` into the same folder replaced the zip without a warning.
- `pacguard --pack --apply` on the `classic` workspace printed `Solution zip created`, and exit 0.
  `pacguard --pack --allow-cloned-pack --apply` on the cloned layout printed the error above and
  exit 3.
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
- **The entry lists are observed, not documented.** The reference does not list what `pack`
  rejects. Newer `pac` versions may accept more. `--allow-cloned-pack` exists for that day.
- **The lists are not complete.** Every other top-level name I tried in a `classic` workspace
  was rejected, and `pacguard` lists only the ones in the table. `pac` still fails loudly for the
  rest, and `pacguard` then exits 3.
- **Pack replaces a zip with the same name.** `pacguard` does not guard that.
- **A workspace that git ignores reads as `CLEAN`.** `git status` prints nothing for an ignored
  path. The git documentation does not say that a clean tree prints nothing, and does not give
  the exit status outside a repository. Both were exercised on git 2.53.0 (Windows) and git 2.43.0
  (Ubuntu), and both behaved as `pacguard` assumes.
- **`auth who` does not prove the push target.** See "What it does not do" above.
- **Linux ran the self-test only.** There is no `dotnet` on that host, so real `pac` was not run
  there.
- **The match ignores case on every host,** because Windows file names do. A Linux workspace
  with an `Actions/` folder is refused although a case-sensitive `pac` might accept it.
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

# Installing Scorekeep

Scorekeep is one file that runs on the Python interpreter you already have. There is
**nothing to compile, no package to install and no service to start** - the optional
steps below only add a command shortcut and the test runner.

## Prerequisites

| Requirement | Why | How to check |
| --- | --- | --- |
| Python **3.9 or newer** (3.11 recommended) | the tool itself | `python3 -V` |
| Nothing else | no compiler, no system library, no database, no network | - |

`argparse`, `re`, `dataclasses` and `sys` are all standard library modules. Scorekeep
uses **no third-party runtime package**, so it works on an offline machine with no
package index reachable.

Package manager: **Python's own `python3 -m pip`** (the only one this project uses).
`requirements.txt` pins one package - `pytest==9.1.1` - and that is the dev/test runner
only. If you never run the test suite, you never need pip at all.

## Step 1 - install (one command, then it exits)

```sh
sh install.sh
```

What it does, in order:

1. checks `python3` exists and is 3.9+;
2. `python3 -m pip install --upgrade pip setuptools wheel` (a failure is only a note -
   no runtime package is needed);
3. `python3 -m pip install -r requirements.txt` (installs pytest);
4. `python3 -m pip install -e . --no-build-isolation` (optional: puts the `scorekeep`
   console script on `PATH`; a failure is only a note);
5. verifies `python3 -c "import scorekeep"` and that pytest imports, and **exits**.

It never installs a system package, never uses `sudo` and **never starts the scorer** -
starting is its own command (step 3). It is safe to re-run.

## Step 2 - data

No seed or migration step exists, on purpose: Scorekeep keeps a session **in memory**
and writes nothing to disk, so there is no datastore to create. A leg's "sample data"
is the board you print at leg start (`--game 501 --players Alice,Bob` gives you Alice
and Bob on 501), and the scripted legs in `examples/` replay a full leg in one command.

## Step 3 - run

```sh
python3 scorekeep.py --help                              # flags and grammar
python3 scorekeep.py --game 501 --players Alice,Bob       # score a 501 leg
python3 scorekeep.py --game 301 --players Alice,Bob       # score a 301 leg
python3 scorekeep.py --game cricket --players Alice,Bob   # score a cricket leg
python3 scorekeep.py --table                              # the 2-170 checkout table
python3 scorekeep.py --checkout 167                       # one route lookup
python3 scorekeep.py --demo                               # scripted full session
```

If step 1 put the console script on `PATH` you can use `scorekeep --game 501 --players
Alice,Bob` instead - the two are identical. With no arguments at all, Scorekeep prints
its usage and exits 0.

Non-interactive / replayable:

```sh
python3 scorekeep.py --game 501 --players Alice,Bob --file examples/501-leg.darts
printf 'T20 T20 T20\nquit\n' | python3 scorekeep.py --game 501 --players Alice,Bob
sh demo.sh
```

## Step 4 - test

```sh
python3 -m pytest
```

Expect `62 passed`. The suite is offline and self-contained: no fixtures to download,
no services, no prompts.

## Configuration

Scorekeep reads **no secrets, no URLs and no ports** - it is a local line-oriented
program with no network code. The only environment variable it honours is the
conventional `NO_COLOR`: set it (to any value) to keep output plain text; `--no-color`
does the same. `.env.example` lists it; Scorekeep never reads a `.env` file, and
works with no environment set at all.

## No accounts

There is no login, no user database and no credentials anywhere in this project, by
design: a single-user local CLI has no account surface. Players are names typed at
setup.

## Troubleshooting

| Symptom | Fix |
| --- | --- |
| `python3: command not found` | install Python 3.9+ from your OS or python.org |
| `SyntaxError` on start | the interpreter is older than 3.9 - check `python3 -V` |
| `ModuleNotFoundError: scorekeep` (tests) | run pytest from the project root: `python3 -m pytest` |
| `pytest: command not found` | `python3 -m pip install -r requirements.txt`, or run `python3 -m pytest` |
| No colour in the terminal | colour is on only for a TTY and off when `NO_COLOR` is set - unset it |
| Scorer exits immediately | that is the no-argument usage line; pass `--game` and `--players` |

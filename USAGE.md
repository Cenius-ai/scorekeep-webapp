# Using Scorekeep

Walkthroughs of everything the tool does, with the real output. Run any block from the
project root. `python3 scorekeep.py --help` prints a short version of this.

- [Score a 501 leg](#score-a-501-leg)
- [Busts](#busts)
- [Checkouts: the table, a lookup, the live score](#checkouts-the-table-a-lookup-the-live-score)
- [Leg summary, the next leg and averages](#leg-summary-the-next-leg-and-averages)
- [Cricket](#cricket)
- [In-leg commands](#in-leg-commands)
- [Scripts and piping](#scripts-and-piping)
- [Exit codes and colour](#exit-codes-and-colour)

## Score a 501 leg

```console
$ python3 scorekeep.py --game 501 --players Alice,Bob
── Leg 1 · 501 ─────────────────────────────────────
  Players: Alice, Bob
  Player        Score
  Alice           501  next
  Bob             501
  Alice throws first.
Alice > T20 T20 S20
  Alice      T20 T20 S20  = 140  →  361
  Alice 361  |  Bob 501  — Bob to throw
Bob > S1 S1 S1
  Bob        S1 S1 S1     = 3  →  498
  Alice 361  |  Bob 498  — Alice to throw
```

One line per turn: the thrower's name, the darts as typed, the points scored, the new
remaining score, then the running board and who throws next. A turn may hold one, two
or three darts; `0` is a miss that still counts as a thrown dart.

`301` works the same way (`--game 301`). Both are double-out.

## Busts

```console
Bob > T20 T20 T20
  Bob        T20 T20 T20  = BUST (went below zero)  →  stays on 162
  Alice 170  |  Bob 162  — Alice to throw
```

A bust prints **one line** and leaves the score exactly as it was at the start of the
turn. Three things bust a turn in 301/501: going below zero, landing on 1, and
reaching zero without a double (`must finish on a double`). Busted darts still count
as thrown, so they count in the average - a bust scores no points.

## Checkouts: the table, a lookup, the live score

```console
$ python3 scorekeep.py --table
── Checkout table · 2-170 ──────────────────────────
     2  D1              87  T17 D18
     3  S1 D1           88  T16 D20
     4  D2              89  T19 D16
...
    79  T13 D20        164  T20 T18 BULL
    82  T14 D20        167  T20 T19 BULL
    85  T15 D20        170  T20 T20 BULL

$ python3 scorekeep.py --checkout 167 --checkout 164 --checkout 169 --checkout 171
  167 → T20 T19 BULL
  164 → T20 T18 BULL
  169 → no checkout
  171 → no checkout - above 170
```

* One preferred route per score, 2-170, printed in **exactly** the notation the scorer
  parses elsewhere, so any route can be typed straight back in.
* `BULL` is the double bull (50), which is why 170 is `T20 T20 BULL`.
* 169, 168, 166, 165, 163, 162 and 159 have no three-dart finish and say `no checkout`;
  anything above 170 says so explicitly.

Mid-leg, without recording a turn:

```console
Alice > checkout
  Alice on 141 → T20 T19 D12
Alice >
```

`checkout <score>` answers for any score you type, and `checkout table` prints the
whole table without leaving the leg.

## Leg summary, the next leg and averages

When a leg is won on a double:

```console
Alice > T20 T19 D12
  Alice      T20 T19 D12  = 141  →  0  · Alice wins leg 1
── Leg 1 result · 501 ──────────────────────────────
  Winner: Alice — 501 finished in 9 darts.
  Player        Points   Darts 3-dart avg
  Alice            501       9   167.00
  Bob                6       6     3.00
  Start leg 2 with the same players? [y/N] > y
── Leg 2 · 501 ─────────────────────────────────────
  Players: Alice, Bob
  Player        Score
  Alice           501
  Bob             501  next
  Bob throws first.
```

`y` starts the next leg with the same players (the other player throws first); `n`
ends the session; `averages`, `board`, `help` or `checkout` print and re-prompt;
anything else is one error line and the same question again.

```console
  Start leg 3 with the same players? [y/N] > averages
── Averages · session (501) ────────────────────────
  Alice
    leg 1     501 pts /  15 darts   100.20
    leg 2     340 pts /  12 darts    85.00
    session   841 pts /  27 darts    93.44
  Bob
    leg 1     339 pts /  12 darts    84.75
    leg 2     501 pts /  15 darts   100.20
    session   840 pts /  27 darts    93.33
```

Each finished leg is recorded for every player: points, darts thrown and
`points x 3 / darts thrown`. A player who has finished no leg reads `no legs
finished`; before any leg finishes the view says `No legs finished yet` and invites
you to play one out. History is session-only - quitting the process clears it.

## Cricket

`--game cricket --players Alice,Bob` (head-to-head; two players).

```console
$ python3 scorekeep.py --game cricket --players Alice,Bob
── Leg 1 · cricket ─────────────────────────────────
  Players: Alice, Bob
  Number    Alice          Bob
  20        –              –
  19        –              –
  18        –              –
  17        –              –
  16        –              –
  15        –              –
  Bull      –              –
  ────────────────────────────────────────────────
  Points    0              0
  ────────────────────────────────────────────────
  * dead — closed by both players, worth no more points
  Alice throws first.
Alice > T20 T20 T20
  Alice      T20 T20 T20  = 20: closed (+6 marks past the close, not scored), +0 pts
  Alice 1 closed · 0 pts  |  Bob 0 closed · 0 pts  — Bob to throw
Bob > T19 T19 T19
  Bob        T19 T19 T19  = 19: closed (+6 marks past the close, not scored), +0 pts
  Alice 1 closed · 0 pts  |  Bob 1 closed · 0 pts  — Alice to throw
Alice > T20
  Alice      T20          = 20: 3 marks score, +60 pts
  Alice 1 closed · 60 pts  |  Bob 1 closed · 0 pts  — Bob to throw
Bob > T20 T20 T20
  Bob        T20 T20 T20  = 20: closed (+6 marks past the close, not scored), +0 pts
  Alice 1 closed · 60 pts  |  Bob 2 closed · 0 pts  — Alice to throw
Alice > T20
  Alice      T20          = 20: dead, no points, +0 pts
  Alice 1 closed · 60 pts  |  Bob 2 closed · 0 pts  — Bob to throw
```

The board shows each player's marks per number: `–` none, `/` one, `X` two,
`⊗ closed` three, with `*` marking numbers that are dead. `board` reprints it at any
time, and after a win the summary prints the final grid:

```console
Alice > BULL BULL
  Alice      BULL BULL    = Bull: closed (+1 mark past the close, not scored), +0 pts
  Alice wins leg 1 — all numbers closed on 60 points.
── Leg 1 result · cricket ──────────────────────────
  Winner: Alice — all numbers closed with 60 points.
  Final board:
...
  Player        Points   Darts 3-dart avg
  Alice             60      21     8.57
  Bob               57      19     9.00
```

Cricket leg records feed the same `averages` view. `checkout` explains that checkouts
belong to 301/501 rather than printing a route.

## In-leg commands

| Command | Effect |
| --- | --- |
| `board` (or `b`) | reprint the current board, changing nothing |
| `checkout` | the current thrower's route out (301/501) |
| `checkout 167` | the route for a score you type |
| `checkout table` | the full 2-170 table |
| `averages` | per-leg and session three-dart averages |
| `new leg` | after a win, start the next leg with the same players |
| `help` (`?`) | the command reference and the token grammar |
| `quit` (`q`) | discard the partial leg and exit 0 |

Anything else - an unknown word, `X99`, `T21`, `T25`, more than three darts - prints
exactly one error line naming the accepted forms, re-prompts the **same** player and
leaves the score and the dart count untouched. Ctrl-C during a leg prints a discard
line and exits 130.

## Scripts and piping

```sh
python3 scorekeep.py --game 501 --players Alice,Bob --file examples/501-leg.darts
printf 'T20 T20 T20\nboard\ncheckout\nquit\n' | python3 scorekeep.py --game 501 --players Alice,Bob
```

`--file` reads the same commands from a file, one per line; blank lines, `#` comments
and trailing comments are ignored. When input is piped (`--file` or a pipe) the typed
lines are echoed after the prompt, so the output reads back as a transcript. Input
ending mid-leg discards the partial leg and exits 0 - it never hangs waiting for a
terminal.

`sh demo.sh` runs the whole product non-interactively: help, the checkout table,
route lookups, a two-leg 501 session with a bust and a 170 finish, a full cricket leg
and a 301 leg from a file.

## Exit codes and colour

| Code | Meaning |
| --- | --- |
| 0 | a leg was scored, a command succeeded, or `quit`/end-of-input closed the session |
| 1 | setup could not complete (fewer than two players, or cricket with more than two) |
| 2 | usage error: unknown `--game`, a `--checkout` value that is not a number, an unreadable `--file` |
| 130 | interrupted (Ctrl-C) |

Results go to stdout, errors (`error: ...`) to stderr, so piping stdout stays clean.
Colour is emitted only when stdout is a terminal, and is disabled by `NO_COLOR` or
`--no-color`. No colour carries meaning on its own - the prompt and the winning line
both say what they are in words.

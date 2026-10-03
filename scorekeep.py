#!/usr/bin/env python3
"""Scorekeep - a darts leg scorer for 301, 501 and cricket.

Plain Python, standard library only, one file. There is no network, no disk
state and no account surface: a session lives in memory until you quit.

    python3 scorekeep.py --game 501 --players Alice,Bob
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Sequence, TextIO, Tuple

APP = "Scorekeep"
VERSION = "1.0.0"

# -- THEME: the committed design direction (see README "Design") -------------
# archetype : cli
# style     : calm-precise, terminal dark, monospace, compact
# accent    : oklch(0.58 0.12 160) -- the same colour in hex is #228f61
# shape     : no chrome; box-drawing rules; aligned columns
# signal    : one accent only, and never colour alone -- every coloured state
#             also carries a word ("wins", the thrower's name in the prompt)
ACCENT_HEX = "#228f61"
ACCENT_RGB = (34, 143, 97)
RULE_WIDTH = 52

GAME_TYPES = ("301", "501", "cricket")
X01_TYPES = ("301", "501")
CRICKET_NUMBERS = (20, 19, 18, 17, 16, 15, 25)
CRICKET_LABELS = {25: "Bull"}
MISS_TOKEN = "0"
TOKEN_HELP = "S1-S20, D1-D20, T1-T20, 25 (outer bull), BULL or D25 (inner bull), 0 (miss)"
TOKEN_FORMS = (
    ("S1-S20", "single, 1-20"),
    ("D1-D20", "double - the finishing double in 301/501"),
    ("T1-T20", "treble"),
    ("25", "outer bull, 25 points, one cricket mark"),
    ("BULL", "inner bull, 50 points, two cricket marks (D25 is the same dart)"),
    ("0", "miss, no score"),
)
COMMAND_HELP = (
    ("board", "reprint the board (scores, or cricket marks and points)"),
    ("checkout", "current thrower's route out (301/501 only)"),
    ("checkout 167", "route for a typed remaining score"),
    ("checkout table", "the full 2-170 checkout table"),
    ("averages", "per-leg and session three-dart averages"),
    ("new leg", "start the next leg after a win"),
    ("help", "this reference"),
    ("quit", "discard the partial leg and exit"),
)
NO_CHECKOUT_SCORES = (169, 168, 166, 165, 163, 162, 159)


# -- Colour -------------------------------------------------------------------

def _accent(text: str, enabled: bool) -> str:
    if not enabled:
        return text
    return "\x1b[38;2;%d;%d;%dm%s\x1b[0m" % (ACCENT_RGB[0], ACCENT_RGB[1], ACCENT_RGB[2], text)


def rule(title: str = "", width: int = RULE_WIDTH) -> str:
    """A box-drawing separator, optionally prefixed with a left-aligned title."""
    if not title:
        return "\u2500" * width
    head = "\u2500\u2500 %s " % title
    return head + "\u2500" * max(0, width - len(head))


def wrap(text: str, width: int = RULE_WIDTH, indent: str = "  ") -> List[str]:
    words = text.split()
    lines: List[str] = []
    current = indent
    for word in words:
        if len(current) + len(word) + 1 > width and current != indent:
            lines.append(current.rstrip())
            current = indent
        current += word + " "
    if current.strip():
        lines.append(current.rstrip())
    return lines


# -- Token grammar ------------------------------------------------------------

class TokenError(ValueError):
    """A typed dart token outside the grammar."""


@dataclass(frozen=True)
class Dart:
    token: str        # exactly what the scorer accepts, e.g. T20 / S5 / D16 / 25 / BULL / 0
    segment: int      # 1-20, or 25 for the bull, 0 for a miss
    multiplier: int   # 1, 2 or 3 (0 for a miss)
    value: int        # points for this dart
    is_double: bool
    is_bull: bool


_TOKEN_RE = re.compile(
    r"^(?:(?P<mult>[SDT])(?P<num>\d{1,2})|(?P<bare>\d{1,2})|(?P<bull>BULL))$"
)


def _miss() -> Dart:
    return Dart(MISS_TOKEN, 0, 0, 0, False, False)


def _bull(token: str, multiplier: int) -> Dart:
    if multiplier == 2:
        return Dart(token, 25, 2, 50, True, True)
    return Dart(token, 25, 1, 25, False, True)


def parse_token(raw: str) -> Dart:
    """Parse one dart token. Raises TokenError with a human-readable reason."""
    token = raw.strip().upper()
    if not token:
        raise TokenError("empty dart token")
    match = _TOKEN_RE.match(token)
    if not match:
        raise TokenError("'%s' is not a dart token" % raw.strip())
    if match.group("bull"):
        return _bull(token, 2)
    if match.group("bare") is not None:
        number = int(match.group("bare"))
        if number == 0:
            return _miss()
        if number == 25:
            return _bull(token, 1)
        if 1 <= number <= 20:
            return Dart(token, number, 1, number, False, False)
        raise TokenError("'%s' is not on the board" % raw.strip())
    multiplier = {"S": 1, "D": 2, "T": 3}[match.group("mult")]
    number = int(match.group("num"))
    if number == 25:
        if multiplier == 1:
            return _bull(token, 1)
        if multiplier == 2:
            return _bull(token, 2)
        raise TokenError("there is no treble bull - use BULL for 50")
    if not 1 <= number <= 20:
        raise TokenError("'%s' is not on the board" % raw.strip())
    return Dart(token, number, multiplier, number * multiplier, multiplier == 2, False)


def parse_turn(line: str) -> List[Dart]:
    """Parse a turn line of up to three dart tokens."""
    tokens = line.split()
    if not tokens:
        raise TokenError("no darts in that line - type up to three tokens, or 'help'")
    if len(tokens) > 3:
        raise TokenError("a turn has at most three darts (got %d)" % len(tokens))
    return [parse_token(token) for token in tokens]


# -- Checkout table -----------------------------------------------------------
# One preferred route per score, in exactly the notation the scorer accepts.
# Validated on startup and by the test suite: every route sums to its score and
# finishes on a double (BULL is the double bull).

CHECKOUT_TABLE: Dict[int, Tuple[str, ...]] = {
    s: tuple(text.split()) for s, text in {
        2: "D1", 3: "S1 D1", 4: "D2", 5: "S1 D2", 6: "D3", 7: "S3 D2", 8: "D4",
        9: "S1 D4", 10: "D5", 11: "S3 D4", 12: "D6", 13: "S5 D4", 14: "D7",
        15: "S7 D4", 16: "D8", 17: "S1 D8", 18: "D9", 19: "S3 D8", 20: "D10",
        21: "S5 D8", 22: "D11", 23: "S7 D8", 24: "D12", 25: "S9 D8", 26: "D13",
        27: "S11 D8", 28: "D14", 29: "S13 D8", 30: "D15", 31: "S15 D8",
        32: "D16", 33: "S1 D16", 34: "D17", 35: "S3 D16", 36: "D18",
        37: "S5 D16", 38: "D19", 39: "S7 D16", 40: "D20", 41: "S9 D16",
        42: "S10 D16", 43: "S11 D16", 44: "S12 D16", 45: "S13 D16",
        46: "S6 D20", 47: "S15 D16", 48: "S8 D20", 49: "S9 D20", 50: "BULL",
        51: "S11 D20", 52: "S12 D20", 53: "S13 D20", 54: "S14 D20",
        55: "S15 D20", 56: "S16 D20", 57: "S17 D20", 58: "S18 D20",
        59: "S19 D20", 60: "S20 D20", 61: "T15 D8", 62: "T10 D16",
        63: "T13 D12", 64: "T16 D8", 65: "T19 D4", 66: "T14 D12", 67: "T17 D8",
        68: "T20 D4", 69: "T19 D6", 70: "T18 D8", 71: "T13 D16", 72: "T16 D12",
        73: "T19 D8", 74: "T14 D16", 75: "T17 D12", 76: "T20 D8", 77: "T19 D10",
        78: "T18 D12", 79: "T13 D20", 80: "T20 D10", 81: "T19 D12",
        82: "T14 D20", 83: "T17 D16", 84: "T20 D12", 85: "T15 D20",
        86: "T18 D16", 87: "T17 D18", 88: "T16 D20", 89: "T19 D16",
        90: "T20 D15", 91: "T17 D20", 92: "T20 D16", 93: "T19 D18",
        94: "T18 D20", 95: "T19 D19", 96: "T20 D18", 97: "T19 D20",
        98: "T20 D19", 99: "T19 S10 D16", 100: "T20 D20", 101: "T20 S9 D16",
        102: "T20 S10 D16", 103: "T20 S11 D16", 104: "T20 S12 D16",
        105: "T20 S13 D16", 106: "T20 S14 D16", 107: "T20 S15 D16",
        108: "T20 S16 D16", 109: "T20 S17 D16", 110: "T20 S18 D16",
        111: "T20 S19 D16", 112: "T20 S20 D16", 113: "T20 S13 D20",
        114: "T20 S14 D20", 115: "T20 S15 D20", 116: "T20 S16 D20",
        117: "T20 S17 D20", 118: "T20 S18 D20", 119: "T20 S19 D20",
        120: "T20 S20 D20", 121: "T20 T11 D14", 122: "T20 T12 D13",
        123: "T20 T13 D12", 124: "T20 T14 D11", 125: "25 T20 D20",
        126: "T20 T18 D6", 127: "T20 T17 D8", 128: "T20 T16 D10",
        129: "T20 T19 D6", 130: "T20 T18 D8", 131: "T20 T17 D10",
        132: "T20 T16 D12", 133: "T20 T19 D8", 134: "T20 T18 D10",
        135: "T20 T17 D12", 136: "T20 T20 D8", 137: "T20 T19 D10",
        138: "T20 T18 D12", 139: "T20 T19 D11", 140: "T20 T20 D10",
        141: "T20 T19 D12", 142: "T20 T14 D20", 143: "T20 T17 D16",
        144: "T20 T20 D12", 145: "T20 T15 D20", 146: "T20 T18 D16",
        147: "T20 T17 D18", 148: "T20 T16 D20", 149: "T20 T19 D16",
        150: "T20 T20 D15", 151: "T20 T17 D20", 152: "T20 T20 D16",
        153: "T20 T19 D18", 154: "T20 T18 D20", 155: "T20 T19 D19",
        156: "T20 T20 D18", 157: "T20 T19 D20", 158: "T20 T20 D19",
        160: "T20 T20 D20", 161: "T20 T17 BULL", 164: "T20 T18 BULL",
        167: "T20 T19 BULL", 170: "T20 T20 BULL",
    }.items()
}


@dataclass(frozen=True)
class CheckoutRoute:
    remaining: int
    darts: Tuple[str, ...]
    valid: bool
    reason: str  # '' | 'no checkout' | 'above 170'

    @property
    def text(self) -> str:
        if self.valid:
            return " ".join(self.darts)
        return self.reason


def checkout_route(score: int) -> CheckoutRoute:
    """The preferred route out for a remaining score, or an explicit refusal."""
    if score in CHECKOUT_TABLE:
        return CheckoutRoute(score, CHECKOUT_TABLE[score], True, "")
    if score > 170:
        return CheckoutRoute(score, (), False, "no checkout - above 170")
    if score < 2:
        return CheckoutRoute(score, (), False, "no checkout - nothing left to finish")
    return CheckoutRoute(score, (), False, "no checkout")


def check_checkout_table() -> None:
    """Guard the published table: every route must be typeable and must sum."""
    for score, tokens in CHECKOUT_TABLE.items():
        darts = [parse_token(token) for token in tokens]
        if len(darts) > 3:
            raise AssertionError("score %d needs more than three darts" % score)
        if sum(dart.value for dart in darts) != score:
            raise AssertionError("score %d: route does not sum" % score)
        if not darts[-1].is_double:
            raise AssertionError("score %d: route does not finish on a double" % score)
    published = set(CHECKOUT_TABLE) | set(NO_CHECKOUT_SCORES)
    if published != set(range(2, 171)):
        raise AssertionError(
            "every score from 2 to 170 needs a route or a no-checkout answer"
        )


# -- Session model ------------------------------------------------------------

@dataclass
class LegRecord:
    player_name: str
    leg_index: int
    mode: str
    points_scored: int
    darts_thrown: int
    three_dart_average: float


@dataclass
class Player:
    name: str
    legs_finished: List[LegRecord] = field(default_factory=list)
    session_darts: int = 0
    session_points: int = 0

    @property
    def session_average(self) -> float:
        if self.session_darts == 0:
            return 0.0
        return self.session_points * 3.0 / self.session_darts


@dataclass
class TurnResult:
    outcome: str          # 'ok' | 'bust' | 'win'
    darts: List[Dart]
    points: int
    reason: str = ""      # for a bust: why it busted
    notes: List[str] = field(default_factory=list)  # cricket: what each dart did


def three_dart_average(points: int, darts: int) -> float:
    if darts <= 0:
        return 0.0
    return points * 3.0 / darts


@dataclass
class X01Leg:
    index: int
    mode: str
    names: List[str]
    remaining: Dict[str, int] = field(default_factory=dict)
    darts_thrown: Dict[str, int] = field(default_factory=dict)
    points_scored: Dict[str, int] = field(default_factory=dict)
    winner: Optional[str] = None

    @property
    def finished(self) -> bool:
        return self.winner is not None

    def apply_turn(self, player: str, darts: List[Dart]) -> TurnResult:
        start = self.remaining[player]
        running = start
        thrown = 0
        for dart in darts:
            thrown += 1
            running -= dart.value
            if running < 0:
                return self._bust(player, darts[:thrown], "went below zero")
            if running == 1:
                return self._bust(player, darts[:thrown], "left on 1")
            if running == 0:
                if dart.is_double:
                    self.remaining[player] = 0
                    self.darts_thrown[player] += thrown
                    self.points_scored[player] += start
                    self.winner = player
                    return TurnResult("win", darts[:thrown], start)
                return self._bust(player, darts[:thrown], "must finish on a double")
        self.remaining[player] = running
        self.darts_thrown[player] += thrown
        self.points_scored[player] += start - running
        return TurnResult("ok", darts, start - running)

    def _bust(self, player: str, darts: List[Dart], reason: str) -> TurnResult:
        # A busted turn scores nothing; the darts thrown still count as thrown.
        self.darts_thrown[player] += len(darts)
        return TurnResult("bust", darts, 0, reason)


@dataclass
class CricketLeg:
    index: int
    names: List[str]
    marks: Dict[str, Dict[int, int]] = field(default_factory=dict)
    points: Dict[str, int] = field(default_factory=dict)
    darts_thrown: Dict[str, int] = field(default_factory=dict)
    winner: Optional[str] = None

    @property
    def finished(self) -> bool:
        return self.winner is not None

    def opponent_of(self, player: str) -> str:
        others = [name for name in self.names if name != player]
        return others[0]

    def closed_count(self, player: str) -> int:
        return sum(1 for number in CRICKET_NUMBERS if self.marks[player][number] >= 3)

    def is_dead(self, number: int) -> bool:
        return all(self.marks[name][number] >= 3 for name in self.names)

    def marks_for(self, dart: Dart) -> int:
        """Cricket marks a single dart is worth on a scored number."""
        if dart.is_bull:
            return 2 if dart.is_double else 1
        return dart.multiplier

    def apply_turn(self, player: str, darts: List[Dart]) -> TurnResult:
        """Credit marks, then points on numbers the thrower has already closed
        while the opponent has not. Marks past the close inside one turn are not
        scored, and a number closed by both players is dead."""
        opponent = self.opponent_of(player)
        incoming: Dict[int, int] = {}
        off_target = 0
        for dart in darts:
            if dart.segment not in CRICKET_NUMBERS:
                off_target += 1
                continue
            incoming[dart.segment] = incoming.get(dart.segment, 0) + self.marks_for(dart)
        scored = 0
        notes: List[str] = []
        for number, marks in incoming.items():
            label = CRICKET_LABELS.get(number, str(number))
            value = 25 if number == 25 else number
            own = self.marks[player][number]
            if own >= 3:
                # Already closed: every mark scores until the opponent closes it.
                if self.marks[opponent][number] < 3:
                    scored += marks * value
                    notes.append("%s: %d mark%s score" % (label, marks, _s(marks)))
                else:
                    notes.append("%s: dead, no points" % label)
                continue
            taken = min(3 - own, marks)
            self.marks[player][number] = own + taken
            past = marks - taken
            if self.marks[player][number] < 3:
                notes.append("%s: %d mark%s" % (label, taken, _s(taken)))
                continue
            note = "%s: closed" % label
            if past:
                # Closing and scoring in one turn is not scored: score on a
                # closed number in a later turn.
                note += " (+%d mark%s past the close, not scored)" % (past, _s(past))
            notes.append(note)
        if off_target:
            notes.append("off-target: %d dart%s" % (off_target, _s(off_target)))
        self.darts_thrown[player] += len(darts)
        self.points[player] += scored
        result = TurnResult("ok", darts, scored, notes=notes)
        if self._has_won(player):
            self.winner = player
            result.outcome = "win"
        return result

    def _has_won(self, player: str) -> bool:
        # Closing every number wins unless the opponent is ahead on points; the
        # tie branch matters because two closed players make every number dead.
        return self.closed_count(player) == len(CRICKET_NUMBERS) and self.points[player] >= max(
            self.points[name] for name in self.names
        )


def _s(count: int) -> str:
    return "" if count == 1 else "s"


@dataclass
class Game:
    mode: str
    players: List[Player]
    leg_index: int = 1
    current: int = 0
    start_index: int = 0
    leg: object = None
    status: str = "in_leg"  # in_leg | leg_won

    @property
    def names(self) -> List[str]:
        return [player.name for player in self.players]

    @property
    def current_name(self) -> str:
        return self.players[self.current].name

    def player(self, name: str) -> Player:
        return next(p for p in self.players if p.name == name)

    def start_leg(self) -> None:
        names = self.names
        if self.mode == "cricket":
            self.leg = CricketLeg(
                index=self.leg_index,
                names=list(names),
                marks={name: {n: 0 for n in CRICKET_NUMBERS} for name in names},
                points={name: 0 for name in names},
                darts_thrown={name: 0 for name in names},
            )
        else:
            score = int(self.mode)
            self.leg = X01Leg(
                index=self.leg_index,
                mode=self.mode,
                names=list(names),
                remaining={name: score for name in names},
                darts_thrown={name: 0 for name in names},
                points_scored={name: 0 for name in names},
            )
        self.current = self.start_index
        self.status = "in_leg"

    def advance(self) -> None:
        self.current = (self.current + 1) % len(self.players)

    def record_leg(self) -> None:
        """Close the finished leg into per-player history."""
        leg = self.leg
        for name in self.names:
            darts = leg.darts_thrown[name]
            points = leg.points_scored[name] if self.mode in X01_TYPES else leg.points[name]
            record = LegRecord(
                player_name=name,
                leg_index=leg.index,
                mode=self.mode,
                points_scored=points,
                darts_thrown=darts,
                three_dart_average=three_dart_average(points, darts),
            )
            player = self.player(name)
            player.legs_finished.append(record)
            player.session_darts += darts
            player.session_points += points
        self.status = "leg_won"

    def begin_next_leg(self) -> None:
        self.leg_index += 1
        self.start_index = (self.start_index + 1) % len(self.players)
        self.start_leg()


# -- Console ------------------------------------------------------------------

class Console:
    """Line-oriented stdin/stdout. Echoes input when stdin is not a terminal so
    a recorded or piped session reads back as a transcript."""

    def __init__(
        self,
        stream: TextIO,
        out: TextIO,
        echo: bool = False,
        color: bool = False,
    ) -> None:
        self.stream = stream
        self.out = out
        self.echo = echo
        self.color = color
        self.skipped_input = False

    def write(self, text: str = "") -> None:
        print(text, file=self.out)

    def lines(self, items: Iterable[str]) -> None:
        for item in items:
            self.write(item)

    def accent(self, text: str) -> str:
        return _accent(text, self.color)

    def ask(self, prompt: str) -> Optional[str]:
        """Write the prompt and read one line. Returns None at end of input."""
        self.out.write(prompt)
        self.out.flush()
        raw = self.stream.readline()
        if raw == "":
            self.out.write("")
            return None
        line = raw.rstrip("\r\n")
        if self.echo:
            self.write(line)
        return line.strip()


# -- Rendering ----------------------------------------------------------------

def board_lines(game: Game) -> List[str]:
    leg = game.leg
    if game.mode == "cricket":
        rows = [("  Number    " + "".join("%-15s" % p.name for p in game.players)).rstrip()]
        for number in CRICKET_NUMBERS:
            label = CRICKET_LABELS.get(number, str(number))
            dead = " *" if leg.is_dead(number) else ""
            cells = "".join("%-15s" % _marks_text(leg.marks[p.name][number]) for p in game.players)
            rows.append(("  %-9s %s%s" % (label, cells, dead)).rstrip())
        rows.append("  " + "\u2500" * 48)
        rows.append(
            (
                "  %-9s %s"
                % ("Points", "".join("%-15d" % leg.points[p.name] for p in game.players))
            ).rstrip()
        )
        rows.append("  " + "\u2500" * 48)
        rows.append("  * dead \u2014 closed by both players, worth no more points")
        return rows
    rows = ["  %-12s %6s" % ("Player", "Score")]
    for player in game.players:
        marker = "" if leg.finished else ("  next" if player.name == game.current_name else "")
        rows.append("  %-12s %6d%s" % (player.name, leg.remaining[player.name], marker))
    return rows


def _marks_text(marks: int) -> str:
    if marks <= 0:
        return "\u2013"
    if marks >= 3:
        return "\u2297 closed"
    return "/" if marks == 1 else "X"


def print_board(console: Console, game: Game, header: bool = True) -> None:
    if header:
        console.write(rule("Leg %d \u00b7 %s" % (game.leg_index, game.mode)))
    console.lines(board_lines(game))
    if header and not game.leg.finished:
        console.write("  %s to throw." % game.current_name)


def scores_line(game: Game) -> str:
    leg = game.leg
    if game.mode == "cricket":
        parts = [
            "%s %d closed \u00b7 %d pts" % (p.name, leg.closed_count(p.name), leg.points[p.name])
            for p in game.players
        ]
    else:
        parts = ["%s %d" % (p.name, leg.remaining[p.name]) for p in game.players]
    tail = "  \u2014 %s to throw" % game.current_name if not leg.finished else ""
    return "  " + "  |  ".join(parts) + tail


def print_turn(console: Console, game: Game, player: str, result: TurnResult) -> None:
    tokens = " ".join(dart.token for dart in result.darts) or "-"
    leg = game.leg
    if game.mode == "cricket":
        detail = "; ".join(result.notes) if result.notes else "no marks"
        console.write("  %-10s %-12s = %s, +%d pts" % (player, tokens, detail, result.points))
        if result.outcome == "win":
            console.write(
                "  %s wins leg %d \u2014 all numbers closed on %d points."
                % (console.accent(player), leg.index, leg.points[player])
            )
        return
    if result.outcome == "win":
        console.write(
            "  %-10s %-12s = %d  \u2192  0  \u00b7 %s wins leg %d"
            % (player, tokens, result.points, console.accent(player), leg.index)
        )
    elif result.outcome == "bust":
        console.write(
            "  %-10s %-12s = BUST (%s)  \u2192  stays on %d"
            % (player, tokens, result.reason, leg.remaining[player])
        )
    else:
        console.write(
            "  %-10s %-12s = %d  \u2192  %d" % (player, tokens, result.points, leg.remaining[player])
        )


def leg_summary_lines(game: Game) -> List[str]:
    leg = game.leg
    lines = [rule("Leg %d result \u00b7 %s" % (leg.index, game.mode))]
    winner = leg.winner
    if game.mode == "cricket":
        lines.append(
            "  Winner: %s \u2014 all numbers closed with %d points."
            % (winner, leg.points[winner])
        )
        lines.append("  Final board:")
        lines.extend(board_lines(game))
    else:
        lines.append(
            "  Winner: %s \u2014 %s finished in %d darts."
            % (winner, game.mode, leg.darts_thrown[winner])
        )
    lines.append("  %-12s %7s %7s %8s" % ("Player", "Points", "Darts", "3-dart avg"))
    for player in game.players:
        points = leg.points_scored[player.name] if game.mode in X01_TYPES else leg.points[player.name]
        darts = leg.darts_thrown[player.name]
        average = "\u2013" if darts == 0 else "%.2f" % three_dart_average(points, darts)
        lines.append("  %-12s %7d %7d %8s" % (player.name, points, darts, average))
    return lines


def averages_lines(game: Game) -> List[str]:
    lines = [rule("Averages \u00b7 session (%s)" % game.mode)]
    if all(not player.legs_finished for player in game.players):
        lines.append("  No legs finished yet \u2014 play a leg to completion to record averages.")
        return lines
    for player in game.players:
        lines.append("  %s" % player.name)
        if not player.legs_finished:
            lines.append("    no legs finished")
            continue
        for record in player.legs_finished:
            lines.append(
                "    leg %-3d %5d pts / %3d darts %8.2f"
                % (
                    record.leg_index,
                    record.points_scored,
                    record.darts_thrown,
                    record.three_dart_average,
                )
            )
        lines.append(
            "    session %5d pts / %3d darts %8.2f"
            % (player.session_points, player.session_darts, player.session_average)
        )
    return lines


def checkout_table_lines() -> List[str]:
    lines = [rule("Checkout table \u00b7 2-170")]
    scores = list(range(2, 171))
    half = (len(scores) + 1) // 2
    left, right = scores[:half], scores[half:]
    for index, score in enumerate(left):
        cell_left = "%4d  %-11s" % (score, checkout_route(score).text)
        if index < len(right):
            other = right[index]
            lines.append("  %s   %4d  %s" % (cell_left, other, checkout_route(other).text))
        else:
            lines.append(("  %s" % cell_left).rstrip())
    return lines


def help_lines() -> List[str]:
    lines = [rule("%s help" % APP)]
    lines.append("  Darts \u2014 up to three per turn, separated by spaces:")
    for token, meaning in TOKEN_FORMS:
        lines.append("    %-9s %s" % (token, meaning))
    lines.append("  In-leg commands:")
    for command, meaning in COMMAND_HELP:
        lines.append("    %-16s %s" % (command, meaning))
    lines.extend(wrap("Scoring: 301/501 are double-out, so you must reach exactly zero on a "
                      "double or the double bull (BULL). Going below zero, landing on 1 or "
                      "reaching zero without a double busts the turn and leaves the score unchanged."))
    lines.extend(wrap("Cricket uses 15-20 and the bull. Three marks close a number; marks on a "
                      "number you have already closed score its value until your opponent "
                      "closes it too, and a number closed by both players is dead. Marks that "
                      "run past the close inside the same turn are not scored - score on a "
                      "closed number in a later turn. Close every number and be level or ahead "
                      "on points to win the leg."))
    return lines


def setup_lines(game: Game) -> List[str]:
    lines = [rule("Leg %d \u00b7 %s" % (game.leg_index, game.mode))]
    lines.append("  Players: %s" % ", ".join(game.names))
    lines.extend(board_lines(game))
    lines.append("  %s throws first." % game.current_name)
    return lines


# -- Command handling ---------------------------------------------------------

def parse_score(text: str) -> int:
    try:
        return int(text)
    except ValueError:
        raise TokenError("'%s' is not a number \u2014 give a remaining score from 2 to 170" % text)


def handle_command(console: Console, game: Game, line: str) -> str:
    """Handle a non-dart line. Returns 'continue' or 'quit'."""
    lowered = " ".join(line.lower().split())
    if lowered in ("quit", "exit", "q"):
        console.write("  Partial leg discarded \u2014 nothing was recorded. Goodbye.")
        return "quit"
    if lowered in ("help", "?", "h"):
        console.lines(help_lines())
        return "continue"
    if lowered in ("board", "b", "scores"):
        print_board(console, game)
        return "continue"
    if lowered in ("averages", "avg", "average", "history"):
        console.lines(averages_lines(game))
        return "continue"
    if lowered in ("new leg", "newleg", "new", "next leg"):
        if game.status != "leg_won":
            console.write("  No finished leg yet \u2014 finish this one first.")
            return "continue"
        game.begin_next_leg()
        console.lines(setup_lines(game))
        return "continue"
    if lowered == "table" or lowered.startswith("checkout"):
        argument = lowered[len("checkout"):].strip() if lowered.startswith("checkout") else "table"
        handle_checkout(console, game, argument)
        return "continue"
    raise TokenError("'%s' is not a dart token or a known command (type 'help')" % line.strip())


def handle_checkout(console: Console, game: Game, argument: str) -> None:
    if argument == "table":
        console.lines(checkout_table_lines())
        return
    if argument:
        score = parse_score(argument)
        route = checkout_route(score)
        console.write("  %d \u2192 %s" % (score, route.text))
        return
    if game.mode == "cricket":
        console.write("  Checkouts are a 301/501 idea \u2014 cricket is won on marks and points.")
        return
    if game.status == "leg_won":
        console.write("  Leg %d is finished \u2014 start the next leg for a live route." % game.leg_index)
        return
    score = game.leg.remaining[game.current_name]
    route = checkout_route(score)
    console.write("  %s on %d \u2192 %s" % (game.current_name, score, route.text))
    if not route.valid and score <= 170:
        console.write("  No three-dart finish from %d \u2014 score to leave a route." % score)


def handle_line(console: Console, game: Game, line: str) -> str:
    """Route one typed line: an in-leg command, or a turn of up to three darts."""
    tokens = line.split()
    if not tokens:
        console.write("  No input \u2014 type up to three dart tokens, or 'help'.")
        return "continue"
    if not _looks_like_dart(tokens[0]):
        return handle_command(console, game, line)
    player = game.current_name
    darts = parse_turn(line)
    result = game.leg.apply_turn(player, darts)
    print_turn(console, game, player, result)
    if result.outcome != "win":
        game.advance()
        console.write(scores_line(game))
        return "continue"
    game.record_leg()
    console.lines(leg_summary_lines(game))
    return "continue"


# -- Session loop -------------------------------------------------------------

def run_session(console: Console, game: Game) -> int:
    game.start_leg()
    console.lines(setup_lines(game))
    while True:
        if game.status == "leg_won":
            prompt = "  Start leg %d with the same players? [y/N] > " % (game.leg_index + 1)
            answer = console.ask(prompt)
            if answer is None:
                console.write("  Input closed \u2014 session ended. Averages are not persisted.")
                return 0
            lowered = " ".join(answer.lower().split())
            if lowered in ("y", "yes", "new leg", "newleg", "new", "next leg"):
                game.begin_next_leg()
                console.lines(setup_lines(game))
                continue
            if lowered in ("n", "no", "quit", "exit", "q"):
                console.write(
                    "  Session ended after %d leg%s. History lives in memory only."
                    % (game.leg_index, "" if game.leg_index == 1 else "s")
                )
                return 0
            try:
                if handle_command(console, game, answer) == "quit":
                    return 0
            except TokenError as error:
                console.write("  %s" % error)
            continue
        answer = console.ask("%s > " % console.accent(game.current_name))
        if answer is None:
            console.write("  Input closed \u2014 partial leg discarded. Goodbye.")
            return 0
        try:
            if handle_line(console, game, answer) == "quit":
                return 0
        except TokenError as error:
            console.write("  %s. Use %s." % (error, TOKEN_HELP))


def _looks_like_dart(token: str) -> bool:
    return bool(token) and (_TOKEN_RE.match(token.upper()) is not None)


# -- Setup --------------------------------------------------------------------

def parse_players(values: Sequence[str]) -> List[str]:
    names: List[str] = []
    for value in values:
        for chunk in value.split(","):
            name = chunk.strip()
            if name:
                names.append(name)
    return names


def validate_players(names: List[str], mode: str) -> Optional[str]:
    if len(names) < 2:
        return "two players are required - e.g. --players Alice,Bob"
    if mode == "cricket" and len(names) != 2:
        return "cricket is a head-to-head two-player game"
    if mode != "cricket" and len(names) > 6:
        return "at most six players on a board"
    if len(set(name.lower() for name in names)) != len(names):
        return "player names must be unique"
    return None


def ask_for_setup(console: Console, mode: str, seeding: Optional[List[str]]) -> Optional[Game]:
    names = list(seeding or [])
    problem = validate_players(names, mode)
    while problem:
        console.write("  %s" % problem)
        answer = console.ask("  Players (comma separated, at least two) > ")
        if answer is None:
            return None
        names = parse_players([answer])
        problem = validate_players(names, mode)
    return Game(mode=mode, players=[Player(name) for name in names])


# -- Demo ---------------------------------------------------------------------
# A scripted, deterministic end-to-end session: one 501 leg with a bust and a
# 170 checkout, a second leg, the averages view, then a cricket leg.

DEMO_501 = [
    # leg 1 - Alice to 170 and a T20 T20 BULL finish, Bob busts on 162
    "T20 S20 S20", "S20 S20 T20", "T20 T20 S20", "T20 T20 S20",
    "S20 S20 S20", "S19 T20 S20", "board", "S20 S5 D3",
    "T20 T20 T20", "checkout", "T20 T20 BULL",
    "y",
    # leg 2 - Bob starts, Alice busts on 161 and Bob finishes on 102
    "S20 S20 T20", "T20 S20 S20", "T20 T20 S20", "S20 S20 T20",
    "S19 T20 S20", "T20 T20 S20", "S20 S20 S20", "T20 T20 T20",
    "T20 S10 D16", "checkout 102", "averages", "n",
]

DEMO_CRICKET = [
    # 20 and 19 are closed and scored on, everything else is closed and goes dead
    "T20 T20 T20", "T19 T19 T19", "T20", "T19",
    "T18 T18 T18", "T18 T18 T18", "T17 T17 T17", "T17 T17 T17",
    "T16 T16 T16", "T16 T16 T16", "T15 T15 T15", "T15 T15 T15",
    "T19 T19 T19", "board", "T20 T20 T20",
    # the winning bull: all seven numbers closed, ahead on points
    "BULL BULL", "averages", "n",
]


class ScriptedConsole(Console):
    """A console fed from a fixed list of lines, echoing each one."""

    def __init__(self, lines: Sequence[str], out: TextIO, color: bool = False) -> None:
        super().__init__(sys.stdin, out, echo=True, color=color)
        self._lines = list(lines)
        self._index = 0

    def ask(self, prompt: str) -> Optional[str]:
        self.out.write(prompt)
        if self._index >= len(self._lines):
            self.out.write("")
            return None
        line = self._lines[self._index]
        self._index += 1
        self.write(line)
        return line.strip()


def run_demo(console: Console) -> int:
    console.write(rule("%s demo \u00b7 501 with Alice and Bob" % APP))
    console.lines(
        wrap("A full 501 leg: a bust, a mid-leg checkout request, a 170 finish and the "
             "leg summary, then a second leg and the session averages.")
    )
    game = Game(mode="501", players=[Player("Alice"), Player("Bob")])
    run_session(ScriptedConsole(DEMO_501, console.out, console.color), game)
    console.write("")
    console.write(rule("%s demo \u00b7 cricket with Alice and Bob" % APP))
    console.lines(
        wrap("Alice and Bob trade marks on 20 down to 15; note the dead numbers, the points "
             "on closed numbers and the winning bull.")
    )
    cricket = Game(mode="cricket", players=[Player("Alice"), Player("Bob")])
    run_session(ScriptedConsole(DEMO_CRICKET, console.out, console.color), cricket)
    console.write("")
    console.write("  Demo complete. Run '%s --help' for flags and the token grammar." % _prog())
    return 0


def _prog() -> str:
    return os.path.basename(sys.argv[0]) or "scorekeep.py"


# -- Entry point --------------------------------------------------------------

EPILOG = """\
examples:
  python3 scorekeep.py                                  # usage
  python3 scorekeep.py --game 501 --players Alice,Bob   # score a leg
  python3 scorekeep.py --game cricket --players Alice,Bob
  python3 scorekeep.py --table                          # the 2-170 checkout table
  python3 scorekeep.py --checkout 167 --checkout 169    # route lookups
  python3 scorekeep.py --demo                           # scripted end-to-end session

In-leg commands: board, checkout, checkout <score>, checkout table, averages,
new leg, help, quit. Darts: %s""" % TOKEN_HELP


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="scorekeep",
        description="Darts leg scorer for 301, 501 and cricket, with checkout routes and "
                    "per-player three-dart averages.",
        epilog=EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--version", action="version", version="%s %s" % (APP.lower(), VERSION))
    parser.add_argument("-g", "--game", metavar="TYPE", help="301, 501 or cricket")
    parser.add_argument("-p", "--players", metavar="NAMES", nargs="+",
                        help="player names, comma or space separated")
    parser.add_argument("-f", "--file", metavar="PATH", help="run commands from a script file")
    parser.add_argument("-c", "--checkout", metavar="SCORE", action="append",
                        help="print the preferred route for SCORE (repeatable)")
    parser.add_argument("-t", "--table", action="store_true",
                        help="print the full 2-170 checkout table")
    parser.add_argument("--demo", action="store_true", help="run a scripted demonstration")
    parser.add_argument("--no-color", action="store_true", help="never emit ANSI colour")
    return parser


def usage_text() -> str:
    return (
        "%s %s - darts leg scorer for 301, 501 and cricket.\n"
        "\n"
        "  %s --game 501 --players Alice,Bob      score a 501 leg\n"
        "  %s --game 301 --players Alice,Bob      score a 301 leg\n"
        "  %s --game cricket --players Alice,Bob  score a cricket leg\n"
        "\n"
        "  --table, --checkout SCORE, --demo, --help, --version\n"
        "  Darts: %s"
        % (APP, VERSION, _prog(), _prog(), _prog(), TOKEN_HELP)
    )


def _colour_enabled(no_color: bool) -> bool:
    if no_color or os.environ.get("NO_COLOR") is not None:
        return False
    return bool(getattr(sys.stdout, "isatty", lambda: False)())


def read_script(path: str) -> List[str]:
    """One command per line; blank lines, '#' comments and trailing comments are
    ignored so a script file can be annotated."""
    with open(path, "r", encoding="utf-8") as handle:
        lines = [line.split("#", 1)[0].strip() for line in handle]
    return [line for line in lines if line]


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(errors="replace")
        except (ValueError, OSError):
            pass
    color = _colour_enabled(args.no_color)
    console = Console(sys.stdin, sys.stdout, echo=False, color=color)

    check_checkout_table()

    if args.checkout:
        for raw in args.checkout:
            try:
                score = parse_score(raw)
            except TokenError as error:
                print("error: %s" % error, file=sys.stderr)
                return 2
            console.write("  %d \u2192 %s" % (score, checkout_route(score).text))
        return 0

    if args.table:
        console.lines(checkout_table_lines())
        return 0

    if args.demo:
        return run_demo(console)

    if args.game is not None and args.game.lower() not in GAME_TYPES:
        print(
            "error: unknown game type '%s'. Choose 301, 501 or cricket." % args.game,
            file=sys.stderr,
        )
        return 2

    if args.game is None and not args.players and not args.file:
        print(usage_text())
        return 0

    mode = (args.game or "501").lower()
    names = parse_players(args.players or [])
    problem = validate_players(names, mode)
    if problem is None:
        game = Game(mode=mode, players=[Player(name) for name in names])
    else:
        # One error line, then the setup prompt asks again.
        game = ask_for_setup(console, mode, names)
        if game is None:
            print("error: %s" % problem, file=sys.stderr)
            return 1

    if args.file:
        try:
            scripted = read_script(args.file)
        except OSError as error:
            print("error: cannot read script %s (%s)" % (args.file, error.strerror), file=sys.stderr)
            return 2
        return run_session(ScriptedConsole(scripted, sys.stdout, color), game)
    return run_session(console, game)


if __name__ == "__main__":
    try:
        _exit_code = main()
    except BrokenPipeError:  # e.g. `scorekeep --table | head`
        os.dup2(os.open(os.devnull, os.O_WRONLY), sys.stdout.fileno())
        _exit_code = 0
    except KeyboardInterrupt:
        print("\nInterrupted - the partial leg was discarded. Goodbye.")
        _exit_code = 130
    sys.exit(_exit_code)

"""Test suite for Scorekeep (dev-only; the shipped artifact is scorekeep.py)."""

import io
import os
import subprocess
import sys

import pytest

import scorekeep as sk

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(ROOT, "scorekeep.py")


# -- helpers ------------------------------------------------------------------

def new_game(mode="501", names=("Alice", "Bob")):
    return sk.Game(mode=mode, players=[sk.Player(name) for name in names])


def run_lines(lines, mode="501", names=("Alice", "Bob")):
    out = io.StringIO()
    console = sk.ScriptedConsole(list(lines), out)
    game = new_game(mode, names)
    code = sk.run_session(console, game)
    return code, out.getvalue(), game


def cli(*args, stdin=""):
    return subprocess.run(
        [sys.executable, SCRIPT] + list(args),
        input=stdin,
        capture_output=True,
        text=True,
        cwd=ROOT,
        timeout=30,
    )


# -- F1: token grammar --------------------------------------------------------

@pytest.mark.parametrize(
    "token,value,is_double",
    [
        ("T20", 60, False),
        ("S5", 5, False),
        ("D16", 32, True),
        ("25", 25, False),
        ("BULL", 50, True),
        ("D25", 50, True),
        ("S25", 25, False),
        ("0", 0, False),
        ("20", 20, False),
        ("t20", 60, False),
        ("bull", 50, True),
    ],
)
def test_tokens_parse_to_the_right_value(token, value, is_double):
    dart = sk.parse_token(token)
    assert dart.value == value
    assert dart.is_double is is_double


@pytest.mark.parametrize("token", ["X99", "T21", "T25", "S26", "D0", "Q5", "", "BULLSEYE", "20x", "S1.5"])
def test_bad_tokens_are_rejected(token):
    with pytest.raises(sk.TokenError):
        sk.parse_token(token)


def test_parse_turn_takes_one_to_three_darts():
    assert len(sk.parse_turn("T20 D16")) == 2
    assert len(sk.parse_turn("0 0 0")) == 3
    with pytest.raises(sk.TokenError):
        sk.parse_turn("")
    with pytest.raises(sk.TokenError):
        sk.parse_turn("T20 T20 T20 T20")
    with pytest.raises(sk.TokenError):
        sk.parse_turn("T20 X99")


# -- F2: checkout table -------------------------------------------------------

def test_checkout_table_is_complete_and_typeable():
    assert len(sk.CHECKOUT_TABLE) == 162
    for score in range(2, 171):
        if score in sk.NO_CHECKOUT_SCORES:
            assert sk.checkout_route(score).text == "no checkout"
            continue
        route = sk.checkout_route(score)
        assert route.valid, score
        darts = [sk.parse_token(token) for token in route.darts]
        assert len(darts) <= 3
        assert sum(dart.value for dart in darts) == score
        assert darts[-1].is_double
    assert not set(sk.NO_CHECKOUT_SCORES) & set(sk.CHECKOUT_TABLE)


def test_named_checkout_routes():
    assert sk.checkout_route(170).text == "T20 T20 BULL"
    assert sk.checkout_route(167).text == "T20 T19 BULL"
    assert sk.checkout_route(164).text == "T20 T18 BULL"
    assert sk.checkout_route(161).text == "T20 T17 BULL"
    assert sk.checkout_route(50).text == "BULL"
    assert sk.checkout_route(2).text == "D1"
    assert sk.checkout_route(169).text == "no checkout"
    assert sk.checkout_route(171).reason == "no checkout - above 170"
    assert sk.checkout_route(1).valid is False


def test_every_published_route_wins_when_typed_back_in():
    """A shown route uses only tokens the throwing loop accepts, and scores
    exactly its own total - so it can be typed straight back in."""
    for score, tokens in sk.CHECKOUT_TABLE.items():
        leg = sk.X01Leg(
            index=1,
            mode="501",
            names=["Alice", "Bob"],
            remaining={"Alice": score, "Bob": 501},
            darts_thrown={"Alice": 0, "Bob": 0},
            points_scored={"Alice": 0, "Bob": 0},
        )
        result = leg.apply_turn("Alice", [sk.parse_token(token) for token in tokens])
        assert result.outcome == "win", score
        assert leg.remaining["Alice"] == 0
        assert result.points == score


# -- F1: X01 scoring loop -----------------------------------------------------

def test_turn_scores_and_passes_the_throw():
    code, output, game = run_lines(["T20 T20 T20", "quit"])
    assert code == 0
    assert "= 180  \u2192  321" in output
    assert "Bob to throw" in output
    assert game.leg.remaining["Alice"] == 321
    assert game.status == "in_leg"


def test_two_dart_turn_and_a_miss_turn():
    _, output, game = run_lines(["T20 D16", "0 0 0", "quit"])
    assert game.leg.remaining["Alice"] == 501 - 92
    assert game.leg.darts_thrown["Alice"] == 2
    assert game.leg.remaining["Bob"] == 501
    assert game.leg.darts_thrown["Bob"] == 3


def test_bust_below_zero_restores_the_score_and_passes_the_turn():
    game = new_game()
    game.start_leg()
    game.leg.remaining["Alice"] = 32
    result = game.leg.apply_turn("Alice", sk.parse_turn("T20"))
    assert result.outcome == "bust"
    assert game.leg.remaining["Alice"] == 32
    assert game.leg.points_scored["Alice"] == 0
    assert game.leg.darts_thrown["Alice"] == 1
    _, output, api_game = run_lines(
        [
            "T20 T20 T20", "S20 S20 S20", "T20 T20 T20", "S20 S20 S20",
            "T20 T20 T20", "quit",
        ]
    )
    assert "BUST (went below zero)" in output
    assert api_game.leg.remaining["Alice"] == 141
    assert api_game.leg.darts_thrown["Alice"] == 9


def test_landing_on_one_is_a_bust():
    game = new_game()
    game.start_leg()
    game.leg.remaining["Alice"] = 21
    result = game.leg.apply_turn("Alice", sk.parse_turn("S20"))
    assert result.outcome == "bust"
    assert result.reason == "left on 1"
    assert game.leg.remaining["Alice"] == 21


def test_exact_zero_without_a_double_is_a_bust():
    game = new_game()
    game.start_leg()
    game.leg.remaining["Alice"] = 60
    result = game.leg.apply_turn("Alice", sk.parse_turn("T20"))
    assert result.outcome == "bust"
    assert result.reason == "must finish on a double"
    assert game.leg.remaining["Alice"] == 60


def test_win_on_a_double_records_the_leg():
    code, output, game = run_lines(
        ["T20 T20 T20", "S1 S1 S1", "T20 T20 T20", "S1 S1 S1", "T20 T19 D12", "n"]
    )
    assert "wins leg 1" in output
    assert code == 0
    record = game.player("Bob").legs_finished[-1]
    assert record.darts_thrown == 6
    assert record.points_scored == 6
    alice = game.player("Alice").legs_finished[-1]
    assert alice.points_scored == 501
    assert alice.darts_thrown == 9
    assert alice.three_dart_average == pytest.approx(501 * 3 / 9)


def test_win_from_forty_with_s20_d10():
    game = new_game()
    game.start_leg()
    game.leg.remaining["Alice"] = 40
    result = game.leg.apply_turn("Alice", sk.parse_turn("S20 D10"))
    assert result.outcome == "win"
    assert game.leg.remaining["Alice"] == 0
    assert game.leg.darts_thrown["Alice"] == 2
    assert game.leg.points_scored["Alice"] == 40


def test_bad_token_leaves_the_turn_untouched():
    code, output, game = run_lines(["X99", "T20 T20 T20", "quit"])
    assert game.leg.remaining["Alice"] == 321
    assert game.leg.darts_thrown["Alice"] == 3
    assert "X99" in output
    assert output.count("Use S1-S20") >= 1


def test_unknown_command_is_one_error_line_and_same_player_again():
    _, output, game = run_lines(["frobnicate", "T20 T20 T20", "quit"])
    assert "frobnicate" in output
    assert game.leg.remaining["Alice"] == 321
    assert game.current_name == "Bob"


def test_partial_turn_is_not_recorded():
    _, output, game = run_lines(["T20 X99", "quit"])
    assert game.leg.remaining["Alice"] == 501
    assert game.leg.darts_thrown["Alice"] == 0
    assert "X99" in output


# -- F5: in-leg commands ------------------------------------------------------

def test_board_reprints_without_changing_state():
    _, output, game = run_lines(["T20 T20 T20", "board", "quit"])
    assert output.count("Player        Score") == 2
    assert game.leg.remaining["Alice"] == 321


def test_help_lists_commands_and_tokens():
    _, output, _ = run_lines(["help", "quit"])
    for expected in ("board", "checkout", "averages", "new leg", "quit", "25", "BULL", "T20"):
        assert expected in output


def test_checkout_command_answers_for_the_live_score():
    _, output, game = run_lines(
        ["T20 T20 T20", "S20 S20 S20", "T20 T20 T20", "S20 S20 S20", "checkout", "quit"]
    )
    assert "Alice on 141 \u2192 T20 T19 D12" in output
    assert game.leg.remaining["Alice"] == 141
    assert game.current_name == "Alice"


def test_checkout_command_with_a_typed_score():
    _, output, _ = run_lines(["checkout 167", "checkout 169", "quit"])
    assert "167 \u2192 T20 T19 BULL" in output
    assert "169 \u2192 no checkout" in output


def test_checkout_table_command():
    _, output, _ = run_lines(["checkout table", "quit"])
    assert "170" in output and "T20 T20 BULL" in output
    assert output.count("no checkout") >= len(sk.NO_CHECKOUT_SCORES)


def test_quit_discards_the_partial_leg():
    code, output, game = run_lines(["T20 T20 T20", "quit"])
    assert code == 0
    assert "discarded" in output
    assert game.player("Alice").legs_finished == []


# -- F3: averages -------------------------------------------------------------

def test_averages_across_two_legs():
    _, output, game = run_lines(
        [
            "T20 T20 T20", "S1 S1 S1", "T20 T20 T20", "S1 S1 S1", "T20 T19 D12",
            "y",
            "T20 T20 T20", "S1 S1 S1", "T20 T20 T20", "S1 S1 S1", "T20 T19 D12",
            "averages", "n",
        ]
    )
    assert game.leg_index == 2
    assert "leg 1" in output and "leg 2" in output
    assert output.count("session") >= 2
    alice = game.player("Alice")
    assert [record.leg_index for record in alice.legs_finished] == [1, 2]
    assert alice.session_darts == 15
    assert alice.session_average == pytest.approx(507 * 3 / 15)


def test_averages_before_any_leg():
    _, output, _ = run_lines(["averages", "quit"])
    assert "No legs finished yet" in output


def test_player_without_a_finished_leg_reads_no_legs_finished():
    game = new_game()
    game.player("Alice").legs_finished.append(
        sk.LegRecord("Alice", 1, "501", 501, 9, 501 * 3 / 9)
    )
    lines = sk.averages_lines(game)
    text = "\n".join(lines)
    assert "no legs finished" in text
    assert "Alice" in text and "Bob" in text


def test_second_leg_starts_with_the_other_player():
    _, output, game = run_lines(
        ["T20 T20 T20", "S1 S1 S1", "T20 T20 T20", "S1 S1 S1", "T20 T19 D12", "y", "quit"]
    )
    assert game.leg_index == 2
    assert game.start_index == 1
    assert game.current_name == "Bob"
    assert "Bob throws first." in output


def test_new_leg_before_a_win_is_refused():
    _, output, game = run_lines(["new leg", "quit"])
    assert "No finished leg yet" in output
    assert game.leg_index == 1


# -- F4: cricket --------------------------------------------------------------

def cricket_leg():
    game = new_game("cricket")
    game.start_leg()
    return game, game.leg


def test_cricket_marks_and_points():
    _, leg = cricket_leg()
    result = leg.apply_turn("Alice", sk.parse_turn("T20 T20 T20"))
    assert leg.marks["Alice"][20] == 3
    assert leg.points["Alice"] == 0  # marks past the close are not scored
    assert result.notes == ["20: closed (+6 marks past the close, not scored)"]

    result = leg.apply_turn("Alice", sk.parse_turn("T20"))
    assert leg.points["Alice"] == 60
    assert result.points == 60

    leg.apply_turn("Bob", sk.parse_turn("T20 T20 T20"))
    assert leg.marks["Bob"][20] == 3
    assert leg.is_dead(20)
    assert leg.points["Bob"] == 0

    result = leg.apply_turn("Alice", sk.parse_turn("T20"))
    assert leg.points["Alice"] == 60
    assert result.notes == ["20: dead, no points"]


def test_cricket_bull_marks_and_off_target_darts():
    _, leg = cricket_leg()
    leg.apply_turn("Alice", sk.parse_turn("25 BULL"))
    assert leg.marks["Alice"][25] == 3  # 25 is one mark, BULL is two
    leg.apply_turn("Bob", sk.parse_turn("S5 0 0"))
    assert leg.darts_thrown["Bob"] == 3
    assert all(leg.marks["Bob"][number] == 0 for number in sk.CRICKET_NUMBERS)


def test_cricket_win_needs_every_number_closed():
    _, leg = cricket_leg()
    for number in (20, 19, 18, 17, 16, 15):
        leg.apply_turn("Alice", sk.parse_turn("T%d T%d T%d" % (number, number, number)))
    assert leg.winner is None
    result = leg.apply_turn("Alice", sk.parse_turn("BULL BULL"))
    assert result.outcome == "win"
    assert leg.winner == "Alice"


def test_cricket_closed_but_behind_does_not_win():
    _, leg = cricket_leg()
    leg.points["Bob"] = 100
    for number in (20, 19, 18, 17, 16, 15):
        leg.apply_turn("Alice", sk.parse_turn("T%d T%d T%d" % (number, number, number)))
    leg.apply_turn("Alice", sk.parse_turn("BULL BULL"))
    assert leg.winner is None


def test_cricket_session_records_averages():
    code, output, game = run_lines(
        [
            "T20 T20 T20", "T19 T19 T19", "T20", "T19",
            "T18 T18 T18", "T18 T18 T18", "T17 T17 T17", "T17 T17 T17",
            "T16 T16 T16", "T16 T16 T16", "T15 T15 T15", "T15 T15 T15",
            "T19 T19 T19", "T20 T20 T20", "BULL BULL",
            "averages", "n",
        ],
        mode="cricket",
    )
    assert code == 0
    assert "wins leg 1" in output
    records = game.player("Alice").legs_finished
    assert len(records) == 1
    assert records[0].mode == "cricket"
    assert records[0].points_scored == 60
    assert records[0].three_dart_average == pytest.approx(60 * 3 / 21)
    assert "Averages" in output


def test_cricket_checkout_command_explains_itself():
    _, output, _ = run_lines(["checkout", "quit"], mode="cricket")
    assert "Checkouts are a 301/501 idea" in output


# -- CLI contract -------------------------------------------------------------

def test_no_arguments_prints_usage_and_exits_zero(capsys):
    assert sk.main([]) == 0
    out = capsys.readouterr().out
    for expected in ("301", "501", "cricket", "S1-S20", "BULL"):
        assert expected in out


def test_unknown_game_type_exits_non_zero_with_one_error_line():
    result = cli("--game", "701")
    assert result.returncode == 2
    assert "701" in result.stderr
    assert "301, 501 or cricket" in result.stderr
    assert "Traceback" not in result.stderr


def test_table_flag_prints_every_route():
    result = cli("--table")
    assert result.returncode == 0
    assert "T20 T20 BULL" in result.stdout
    assert " 2  D1" in result.stdout


def test_checkout_flag():
    result = cli("--checkout", "167", "--checkout", "169")
    assert result.returncode == 0
    assert "167 \u2192 T20 T19 BULL" in result.stdout
    assert "169 \u2192 no checkout" in result.stdout
    assert cli("--checkout", "abc").returncode == 2


def test_version_flag():
    result = cli("--version")
    assert result.returncode == 0
    assert sk.VERSION in result.stdout


def test_demo_runs_end_to_end_without_input():
    result = cli("--demo")
    assert result.returncode == 0
    assert result.stdout.count("wins leg") >= 2
    assert "Averages" in result.stdout
    assert "Traceback" not in result.stderr


def test_script_file_runs_a_leg_non_interactively():
    result = cli("--game", "501", "--players", "Alice,Bob", "--file", "examples/501-leg.darts")
    assert result.returncode == 0
    assert "wins leg 1" in result.stdout
    assert "BUST" in result.stdout


def test_piped_stdin_scores_a_leg_and_exits_cleanly():
    result = cli(
        "--game", "501", "--players", "Alice,Bob", "--no-color",
        stdin="T20 T20 T20\nS1 S1 S1\nT20 T20 T20\nS1 S1 S1\nT20 T19 D12\nn\n",
    )
    assert result.returncode == 0
    assert "Alice wins leg 1" in result.stdout
    assert "Traceback" not in result.stderr


def test_one_player_name_is_reported_then_re_prompted():
    result = cli("--game", "501", "--players", "Alice", stdin="Alice,Bob\nquit\n")
    assert "two players are required" in result.stdout
    assert result.stdout.count("two players are required") == 1


def test_cricket_rejects_more_than_two_players():
    result = cli("--game", "cricket", "--players", "A,B,C", stdin="")
    assert result.returncode == 1
    assert "head-to-head" in result.stderr

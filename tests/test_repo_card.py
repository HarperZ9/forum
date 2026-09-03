"""The README card fits the columns it is drawn in, and says one thing.

A card is a table rendered to SVG: a key column, a value column, and a note
column beside them, with a footnote under the rule. None of the three is
clipped by the renderer, so a sentence that outgrows its column draws over the
one next to it and every other check stays green. These measure the drawing
rather than read the spec.

The measuring is done here, from scripts/face-metrics.json, and not by calling
the renderer. An earlier version asked repo_card how wide its own text was, so
the check and the drawing shared one guess and agreed with each other whatever
that guess said. Four cards shipped past the right rule under a green suite.
This walks each measured face on its own instead, and asks whether the line
fits in that face, so the two can now disagree.

Everything here settles whether the card fits its columns and matches its
spec. Whether the card is TRUE of what this tool does to a piece of context is
a different question, and tests/test_context_budget.py settles that one by
driving the code.
"""
import importlib.util
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ART = ROOT / "docs" / "art"
SCRIPTS = ROOT / "scripts"


def _load(name):
    if str(SCRIPTS) not in sys.path:
        sys.path.insert(0, str(SCRIPTS))
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


CARD = _load("repo_card")
FACES = json.loads(
    (SCRIPTS / "face-metrics.json").read_text(encoding="utf-8"))
FIRST, LAST = FACES["range"]

# What draws each element: which font stack, which weight, its size in pixels
# and its letter-spacing in em. Taken from the card's own <style> block and
# from the two elements that override the family on themselves.
DRAWN = {
    "note": ("sans", "regular", 11.5, 0.0),
    "foot": ("sans", "regular", 11.5, 0.0),
    "title": ("sans", "bold", 21.0, 0.0),
    "kicker": ("mono", "regular", 11.0, 0.16),
    "head": ("mono", "regular", 11.0, 0.16),
    "source": ("mono", "regular", 11.5, 0.0),
    "key": ("mono", "bold", 13.0, 0.0),
    "value": ("mono", "regular", 12.0, 0.0),
}
BOUND = {("sans", "regular"): CARD.SANS, ("sans", "bold"): CARD.SANS_BOLD,
         ("mono", "regular"): CARD.MONO_REG, ("mono", "bold"): CARD.MONO_BOLD}


def _cards() -> list[dict]:
    specs = [json.loads(p.read_text(encoding="utf-8"))
             for p in sorted(ART.glob("*.art.json"))]
    return [card for spec in specs for card in spec.get("cards", [])]


def _widest_face(text: str, role: str) -> tuple[str, float]:
    """The face that draws this string widest, and what it draws, in pixels."""
    group, weight, size, tracking = DRAWN[role]
    drawn = {}
    for name, face in FACES[group][weight].items():
        off = max(face)
        total = sum(face[ord(c) - FIRST] if FIRST <= ord(c) <= LAST else off
                    for c in text)
        drawn[name] = total / 1000.0 * size + tracking * size * len(text)
    return max(drawn.items(), key=lambda pair: pair[1])


def _over(text: str, role: str, budget: float, label: str) -> list[str]:
    name, width = _widest_face(text, role)
    if width <= budget:
        return []
    return [f"{label} draws {width:.0f}px into a {budget:.0f}px column "
            f"in {name}: {text!r}"]


def _lines_that_run_long(text: str, label: str, role: str, budget: float,
                         limit: int) -> list[str]:
    """Two ways a wrapped column goes wrong, and the second is the one a
    joined-text check misses. Dropping the ending is the obvious one. The other
    is a single token longer than the budget: the wrapper is greedy, so it
    leaves that token alone on its line, the joined text still equals the
    source, and the drawing runs off the page with every check green."""
    drawn = CARD._wrap(text, budget, limit)
    bad = []
    if " ".join(drawn) != " ".join(text.split()):
        bad.append(f"{label} loses its ending")
    for line in drawn:
        bad += _over(line, role, budget, label)
    return bad


def _card_text_that_overflows(card: dict) -> list[str]:
    """Every string the card draws, against the room it is drawn in."""
    page = CARD.W - CARD.PAD * 2
    bad = []
    for field in card["fields"]:
        bad += _over(field["key"], "key", CARD.KEY_W + CARD.GUTTER - 16,
                     "the key")
        bad += _over(field["value"], "value", CARD.VAL_W, "the value")
        bad += _lines_that_run_long(
            field["note"], f'the note under {field["key"]!r}', "note",
            CARD.NOTE_BUDGET, CARD.NOTE_LINES)
    bad += _lines_that_run_long(card["footnote"], "the footnote", "foot",
                                CARD.FOOT_BUDGET, CARD.FOOT_LINES)
    for label, role, text in (
            ("the title", "title", card.get("title", "")),
            ("the kicker", "kicker", card.get("kicker", "").upper()),
            ("the source line", "source", "$ " + card.get("source", ""))):
        bad += _over(text, role, page, label)
    for head in card.get("heads", CARD.HEADS):
        bad += _over(head.upper(), "head", CARD.NOTE_W, "the column head")
    return bad


def test_there_is_a_card_to_check():
    assert _cards(), "no spec carries a card"


def test_no_card_text_runs_out_of_its_column():
    for card in _cards():
        assert not _card_text_that_overflows(card), card["file"]


def test_that_card_check_can_actually_fail():
    """A green suite otherwise proves only that the check ran. The third row is
    the greedy-wrap case: one unbreakable token, nothing dropped."""
    control = {
        "fields": [{"key": "k" * 90, "value": "v" * 90, "note": "fine"},
                   {"key": "k", "value": "v", "note": "word " * 200},
                   {"key": "k", "value": "v", "note": "x" * 120}],
        "footnote": "word " * 400,
        "title": "T" * 200, "kicker": "k" * 200, "source": "s" * 200,
        "heads": ["H" * 60, "h", "h"],
    }
    assert len(_card_text_that_overflows(control)) == 9


def test_the_renderer_wraps_to_a_bound_no_measured_face_exceeds():
    """The renderer wraps with one table and this file measures with another,
    and this is what keeps them honest about each other. For every character,
    what the renderer assumes has to be at least what each measured face draws.
    A width guessed from a character's class fails on the first lowercase m."""
    for (group, weight), bound in BOUND.items():
        assert len(bound) == LAST - FIRST + 1, f"{group} {weight} is short"
        for name, face in FACES[group][weight].items():
            for index, thousandths in enumerate(face):
                assert bound[index] >= thousandths / 1000.0 - 1e-9, (
                    f"{name} draws {chr(FIRST + index)!r} wider than the "
                    f"renderer assumes it does")


def test_every_character_a_card_draws_was_measured():
    """A character outside the measured range falls back to the widest glyph
    in the face, which is a guess. Cards are written in ASCII so that never has
    to happen, and this is what holds them to it."""
    for card in _cards():
        strings = [card["title"], card["kicker"], card["source"],
                   card["footnote"], *card.get("heads", ())]
        for field in card["fields"]:
            strings += [field["key"], field["value"], field["note"]]
        for text in strings:
            off = sorted({c for c in text if not FIRST <= ord(c) <= LAST})
            assert not off, f'{card["file"]} draws unmeasured {off!r}'


def test_a_card_wears_exactly_one_hot_mark():
    """Verdict-only colour. Two marks and the drawing stops saying which row
    carries the claim; none and the colour is decoration."""
    for card in _cards():
        marked = [f["key"] for f in card["fields"]
                  if f.get("tone", "none") != "none"]
        assert len(marked) == 1, f'{card["file"]} marks {marked}'


def test_a_card_draws_shapes_not_digits():
    """A token count or a byte count is wrong by the next commit, so the value
    column carries the shape of a value rather than a literal that will rot."""
    for card in _cards():
        for field in card["fields"]:
            assert not re.search(r"[0-9a-f]{12,}", field["value"]), field["key"]
            assert not re.search(r"[0-9]{5,}", field["value"]), field["key"]


def test_the_readme_describes_the_card_it_shows():
    """GitHub draws a card as an <img>, and an <img> hides the description the
    SVG carries inside it. The README alt attribute is the whole of what a
    reader who cannot see the card gets, so it has to be the one in the spec."""
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    for card in _cards():
        assert card["alt"] in readme, (
            f'{card["file"]}: the README describes it as something else')

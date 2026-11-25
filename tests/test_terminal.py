from io import StringIO

import pytest
from rich.console import Console

from retail_agent.terminal import RichTerminal


@pytest.fixture
def typed(monkeypatch):
    def type_lines(text: str) -> RichTerminal:
        monkeypatch.setattr("sys.stdin", StringIO(text))
        return RichTerminal(Console(file=StringIO()))

    return type_lines


def test_returns_the_typed_message_without_surrounding_spaces(typed):
    assert typed("  monthly revenue \n").read() == "monthly revenue"


def test_skips_blank_lines(typed):
    assert typed("\n   \ntop products\n").read() == "top products"


@pytest.mark.parametrize("word", ["exit", "quit", "EXIT"])
def test_exit_word_means_the_executive_leaves(typed, word):
    assert typed(f"{word}\nnever read\n").read() is None


def test_closed_input_means_the_executive_leaves(typed):
    assert typed("").read() is None

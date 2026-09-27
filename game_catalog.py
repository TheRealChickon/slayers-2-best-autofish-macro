"""Explicit supported-game registry for the launcher; no speculative entries."""
from dataclasses import dataclass
from typing import Callable


def start_ouwland(mode):
    from control_actions import resume
    return resume(mode)


@dataclass(frozen=True)
class Game:
    name: str
    modes: tuple[str, ...]
    start: Callable[[str], str]


GAMES = {
    'project-slayers-2': Game('Project Slayers 2 / Ouwland', ('assist', 'spot', 'full', 'damage'), start_ouwland),
}


def get_game(key):
    try:return GAMES[key]
    except KeyError:raise ValueError(f'Unknown game: {key}. Run autofish games.') from None

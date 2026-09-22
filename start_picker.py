"""Small keyboard picker. Selecting a game alone never starts a controller."""
import msvcrt
import sys
from app_config import MODES
from game_catalog import GAMES, get_game


def choose(title, options, colors=False):
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        raise ValueError('Use an interactive terminal, or specify --game and --mode.')
    selected=0
    def draw(first=False):
        if not first:sys.stdout.write(f'\033[{len(options)+2}A')
        lines=[title]+[f"{'>' if i==selected else ' '} {i+1}. {label}" for i,(_,label) in enumerate(options)]
        lines+=['Up/Down select   Enter choose   Q cancel']
        for index,line in enumerate(lines):
            focused=index==selected+1
            ink='\033[33m' if colors and focused else ''
            reset='\033[0m' if ink else ''
            sys.stdout.write('\033[2K'+ink+line+reset+'\n')
        sys.stdout.flush()
    draw(True)
    while True:
        key=msvcrt.getwch()
        if key in ('\x00','\xe0'):
            key=msvcrt.getwch()
            if key=='H':selected=(selected-1)%len(options)
            elif key=='P':selected=(selected+1)%len(options)
        elif key in ('q','Q','\x07','\x03'):
            return None
        elif key=='\r':return options[selected][0]
        elif key.isdigit() and 1<=int(key)<=len(options):selected=int(key)-1
        draw()


def start(args, colors=False):
    game_key=args.game
    if game_key is None:
        game_key=choose('Choose a game',[(key,game.name) for key,game in GAMES.items()],colors)
    if game_key is None:return 0
    game=get_game(game_key)
    mode=args.mode
    if mode is None:
        mode=choose(game.name,[(key,MODES[key]) for key in game.modes],colors)
    if mode is None:return 0
    if mode not in game.modes:raise ValueError(f'{game.name} does not support mode {mode}.')
    print(game.start(mode),flush=True)
    if not args.no_ui and sys.stdin.isatty() and sys.stdout.isatty():
        from terminal_app import Terminal
        return Terminal().run()
    return 0

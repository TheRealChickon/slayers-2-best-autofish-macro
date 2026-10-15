"""Full-terminal cast and reel animation; visual only, with no game input."""

import math


FOREGROUND = {
    'sky': '79;112;124', 'star': '119;150;155', 'gold': '227;188;98',
    'line': '177;201;195', 'water': '68;157;178', 'foam': '127;216;223',
    'float': '231;119;101', 'fish': '111;184;190',
}
SKY = '7;16;25'
WATER = '8;36;48'
RESET = '\033[0m'


def scene_frame(columns, lines, progress, phase):
    """Render one terminal-sized frame; opening casts, closing reels in."""
    width, height = max(1, columns-1), max(1, lines-1)
    surface = round(height*.68)
    cells = [[(' ', 'sky', WATER if y >= surface else SKY)
              for _ in range(width)] for y in range(height)]

    def put(x, y, char, tone):
        if 0 <= x < width and 0 <= y < height:
            _, _, background = cells[y][x]
            cells[y][x] = (char, tone, background)

    # The scene uses the whole terminal: open sky above moving water.
    for index in range(max(5, width//9)):
        x = (index*37+11) % width
        y = (index*11+3) % max(1, surface-3)
        put(x, y, '·', 'star')
    title = 'F I S H I N G'
    for index, char in enumerate(title):
        put((width-len(title))//2+index, 1, char, 'gold')
    current = round(progress*5)
    for y in range(surface, height):
        for x in range(width):
            if y == surface and (x+current) % 4 == 0:
                put(x, y, '≈', 'foam')
            elif y > surface and (x*3+y*7+current) % 23 == 0:
                put(x, y, '·', 'water')

    base_x, base_y = round(width*.12), surface-2
    tip_x = round(width*.39) + round(2*math.sin(math.pi*progress))
    tip_y = max(3, round(height*.19) - round(math.sin(math.pi*progress)))
    travel = progress if phase == 'opening' else 1-progress
    travel = travel*travel*(3-2*travel)
    float_x = round(tip_x+2+(width-8-tip_x-2)*travel)
    float_y = round((1-travel)**2*(tip_y+1)
                    + 2*(1-travel)*travel*max(1, tip_y-5)
                    + travel**2*(surface-1))

    # A light curved line follows the float through the casting arc.
    control_y = max(1, min(tip_y, float_y)-round(height*.10))
    steps = max(8, (float_x-tip_x)*2)
    for step in range(steps+1):
        t = step/steps
        x = round(tip_x+(float_x-tip_x)*t)
        y = round((1-t)**2*tip_y + 2*(1-t)*t*control_y + t*t*float_y)
        put(x, y, '·', 'line')

    # Rod, handle and reel stay anchored while the tip flexes.
    for step in range(max(1, (tip_x-base_x)*2)+1):
        t = step/max(1, (tip_x-base_x)*2)
        put(round(base_x+(tip_x-base_x)*t),
            round(base_y+(tip_y-base_y)*t), '╱', 'gold')
    for offset, char in ((-3, '━'), (-2, '━'), (-1, '◉')):
        put(base_x+offset, base_y, char, 'gold')
    put(tip_x, tip_y, '◆', 'gold')
    put(float_x, float_y-1, '│', 'line')
    put(float_x, float_y, '●', 'float')

    if travel > .84:
        for dx, dy, char in ((-3, 0, '✦'), (3, 0, '✦'), (-2, 1, '·'), (2, 1, '·')):
            put(float_x+dx, surface+dy-1, char, 'foam')
    fish_x = round(width*.70 - progress*min(12, width//8))
    for index, char in enumerate('><(((o>'):
        put(fish_x+index, min(height-2, surface+3), char, 'fish')

    result = []
    for row in cells:
        runs = []
        for char, tone, background in row:
            if runs and runs[-1][1:] == (tone, background):
                runs[-1] = (runs[-1][0]+char, tone, background)
            else:
                runs.append((char, tone, background))
        result.append(''.join(
            f'\033[38;2;{FOREGROUND[tone]};48;2;{background}m{text}'
            for text, tone, background in runs) + RESET)
    return result

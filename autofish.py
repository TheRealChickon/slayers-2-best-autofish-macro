"""PATH command entry point; bare autofish opens the existing dashboard."""
import sys
from fishing_cli import main


if __name__ == '__main__':
    raise SystemExit(main(sys.argv[1:] or ['tui'], prog='autofish'))

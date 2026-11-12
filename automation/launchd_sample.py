"""User-level LaunchAgent sample body.

This process does not start the dispatcher, does not call once or watch, and
does not load a plist. A breaker file makes it exit without doing work.
"""
import sys
from pathlib import Path


def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    if any(token in {'load', 'bootstrap', 'launchctl', 'sudo', 'once', 'watch'} for token in args):
        return 2
    if '--breaker' in args:
        index = args.index('--breaker')
        if index + 1 >= len(args):
            return 2
        breaker = Path(args[index + 1])
        if breaker.name == 'state.db' or breaker.is_symlink():
            return 2
        try:
            present = breaker.is_file()
        except OSError:
            return 2
        if present:
            return 0
    sys.stdout.write('sample only; dispatcher not started\n')
    return 0


if __name__ == '__main__':
    sys.exit(main())

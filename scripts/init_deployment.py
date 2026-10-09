"""Create a private local deployment configuration without printing credentials."""
import argparse
import os
import secrets
from pathlib import Path


def initialize_configuration(destination: Path) -> None:
    configuration = (
        f'API_AUTH_TOKEN={secrets.token_urlsafe(48)}\n'
        'API_ALLOWED_ORIGINS=http://localhost:5173,http://127.0.0.1:5173\n'
        'LIVE_TRADING_ENABLED=false\n'
    )
    descriptor = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, 'w') as output:
        output.write(configuration)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=Path('.env'))
    arguments = parser.parse_args()
    try:
        initialize_configuration(arguments.output)
    except FileExistsError:
        parser.exit(1, 'Configuration already exists; it was not overwritten.\n')
    except OSError:
        parser.exit(1, 'Unable to create private configuration; check directory permissions.\n')
    print('Private configuration created. Read it locally to obtain the operator token. Live trading remains disabled.')


if __name__ == '__main__':
    main()

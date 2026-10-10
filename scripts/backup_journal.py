"""Create an exclusive, integrity-checked SQLite journal backup; never restore over live state."""
import argparse
import os
import sqlite3
from pathlib import Path


def backup_journal(source: Path, destination: Path) -> None:
    if not source.is_file():
        raise ValueError('Source journal does not exist')
    descriptor = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    os.close(descriptor)
    try:
        source_connection = sqlite3.connect(source.resolve().as_uri() + '?mode=ro', uri=True)
        try:
            backup_connection = sqlite3.connect(destination)
            try:
                source_connection.backup(backup_connection)
                if backup_connection.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                    raise ValueError('Backup integrity verification failed')
            finally:
                backup_connection.close()
        finally:
            source_connection.close()
    except (sqlite3.Error, OSError, ValueError):
        destination.unlink(missing_ok=True)
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('destination', type=Path)
    arguments = parser.parse_args()
    try:
        backup_journal(arguments.source, arguments.destination)
    except (sqlite3.Error, OSError, ValueError):
        parser.exit(1, 'Backup failed; verify source, destination and permissions. Existing backups are never overwritten.\n')
    print('Backup completed and SQLite integrity verified.')


if __name__ == '__main__':
    main()

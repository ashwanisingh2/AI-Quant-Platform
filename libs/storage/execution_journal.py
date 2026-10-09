"""Single-node durable execution journal. No credentials or raw SDK responses."""
import json
import os
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path


def now():
    return datetime.now(timezone.utc).isoformat()


class ExecutionJournal:
    def __init__(self, path=None):
        self.path = Path(path or os.environ.get('EXECUTION_DB', 'data/execution.sqlite3'))
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS runs (
                    id TEXT PRIMARY KEY, created_at TEXT, updated_at TEXT,
                    broker TEXT, instrument TEXT, mode TEXT, state TEXT,
                    resolution_note TEXT);
                CREATE TABLE IF NOT EXISTS intents (
                    id TEXT PRIMARY KEY, run_id TEXT NOT NULL, created_at TEXT,
                    symbol TEXT, side TEXT, qty INTEGER, purpose TEXT,
                    state TEXT, broker_order_id TEXT,
                    FOREIGN KEY(run_id) REFERENCES runs(id));
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY, created_at TEXT, run_id TEXT,
                    kind TEXT, details TEXT);
            ''')
        self.path.chmod(0o600)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA foreign_keys=ON')
        db.execute('PRAGMA journal_mode=WAL')
        db.execute('PRAGMA synchronous=FULL')
        try:
            with db:
                yield db
        finally:
            db.close()

    def create_run(self, broker, instrument, mode):
        run_id = uuid.uuid4().hex
        with self.connect() as db:
            # Atomic admission even if two requests race. All live runs require
            # explicit reconciliation before another live session can begin.
            db.execute('BEGIN IMMEDIATE')
            if mode == 'live' and db.execute(
                "SELECT 1 FROM runs WHERE mode='live' AND state != 'reconciled' LIMIT 1"
            ).fetchone():
                raise ValueError('Reconcile the previous live session before starting another')
            db.execute('INSERT INTO runs VALUES (?,?,?,?,?,?,?,?)',
                       (run_id, now(), now(), broker, instrument, mode, 'starting', None))
        self.event(run_id, 'run.created')
        return run_id

    def transition(self, run_id, state):
        with self.connect() as db:
            db.execute('UPDATE runs SET state=?, updated_at=? WHERE id=?', (state, now(), run_id))
        self.event(run_id, 'run.' + state)

    def event(self, run_id, kind, details=None):
        with self.connect() as db:
            db.execute('INSERT INTO events(created_at,run_id,kind,details) VALUES (?,?,?,?)',
                       (now(), run_id, kind, json.dumps(details or {})))

    def intent(self, run_id, symbol, side, qty, purpose):
        intent_id = uuid.uuid4().hex
        with self.connect() as db:
            db.execute('INSERT INTO intents VALUES (?,?,?,?,?,?,?,?,?)',
                       (intent_id, run_id, now(), symbol, side, qty, purpose, 'prepared', None))
        return intent_id

    def outcome(self, intent_id, state, broker_order_id=None):
        with self.connect() as db:
            db.execute('UPDATE intents SET state=?, broker_order_id=? WHERE id=?',
                       (state, str(broker_order_id) if broker_order_id else None, intent_id))

    def snapshot(self):
        with self.connect() as db:
            runs = [dict(r) for r in db.execute('SELECT * FROM runs ORDER BY created_at DESC LIMIT 50')]
            intents = [dict(r) for r in db.execute('SELECT * FROM intents ORDER BY created_at DESC LIMIT 100')]
            events = [dict(r) for r in db.execute('SELECT * FROM events ORDER BY id DESC LIMIT 100')]
            unresolved = db.execute("SELECT COUNT(*) FROM runs WHERE mode='live' AND state!='reconciled'").fetchone()[0]
        return {'runs': runs, 'intents': intents, 'events': events,
                'unresolved_live_runs': unresolved}

    def reconcile(self, run_id, note):
        with self.connect() as db:
            if not db.execute('SELECT 1 FROM runs WHERE id=?', (run_id,)).fetchone():
                raise KeyError(run_id)
            db.execute("UPDATE runs SET state='reconciled', resolution_note=?, updated_at=? WHERE id=?",
                       (note, now(), run_id))
        self.event(run_id, 'run.manually_reconciled')

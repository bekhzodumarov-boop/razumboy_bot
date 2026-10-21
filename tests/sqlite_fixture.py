"""Isolated production schema/methods, without historical backup seed data."""
from contextlib import closing, contextmanager

from database import Database


class TestDatabase(Database):
    def _restore_backup_if_empty(self):
        pass

    @contextmanager
    def _connect(self):
        # sqlite3's own context commits/rolls back but does not close on Windows.
        with closing(super()._connect()) as conn, conn:
            yield conn

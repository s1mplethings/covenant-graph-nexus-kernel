"""Append-only transport evidence. Retention is an explicit archival operation."""
import logging
import os


class EvidenceJournal(logging.FileHandler):
    def __init__(self, filename):
        super().__init__(filename, mode='a', encoding='utf-8')

    def emit(self, record):
        # Callers also use emit directly; serialize those writes as well.
        self.acquire()
        try:
            super().emit(record)
            self.flush()
            os.fsync(self.stream.fileno())
        finally:
            self.release()

    def handleError(self, record):
        # logging's default prints and continues, losing critical evidence.
        raise

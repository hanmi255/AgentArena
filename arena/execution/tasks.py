"""Durable execution jobs, transactional outbox and fenced worker leases."""

import time


class LeaseLost(Exception):
    pass


class TaskStore:
    def __init__(self, database, lease_seconds=15):
        self.db = database
        self.lease_seconds = lease_seconds

    def enqueue(self, arena_id, interval):
        with self.db.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            arena = connection.execute("SELECT status FROM arenas WHERE id=?", (arena_id,)).fetchone()
            if arena["status"] == "completed":
                raise ValueError("比赛已结束")
            if arena["status"] == "stepping":
                raise ValueError("本轮正在结算")
            row = connection.execute("SELECT * FROM execution_jobs WHERE arena_id=? AND state IN ('queued','running')", (arena_id,)).fetchone()
            if row:
                job_id = row["id"]
            else:
                cursor = connection.execute("INSERT INTO execution_jobs(arena_id,interval,state) VALUES(?,?,'queued')", (arena_id, interval))
                job_id = cursor.lastrowid
                connection.execute("INSERT INTO command_outbox(job_id) VALUES(?)", (job_id,))
            connection.execute("UPDATE arenas SET status='running',error=NULL,updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=?", (arena_id,))
        return job_id

    def pause(self, arena_id):
        with self.db.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute("UPDATE arenas SET status='paused',updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=? AND status='running'", (arena_id,))
            connection.execute("UPDATE execution_jobs SET state='paused' WHERE arena_id=? AND state='queued'", (arena_id,))

    def claim(self, owner, job_id=None):
        now = time.time()
        with self.db.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            query = """SELECT j.* FROM execution_jobs j JOIN arenas a ON j.arena_id=a.id
                       WHERE a.status='running' AND ((j.state='queued' AND j.available_at<=?) OR (j.state='running' AND j.lease_until<?))"""
            params = [now, now]
            if job_id is not None:
                query += " AND j.id=?"
                params.append(job_id)
            row = connection.execute(query + " ORDER BY j.id LIMIT 1", params).fetchone()
            if row is None:
                return None
            connection.execute("""UPDATE execution_jobs SET state='running',owner=?,lease_version=lease_version+1,
                                  lease_until=?,attempts=attempts+1,updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=?""",
                               (owner, now + self.lease_seconds, row["id"]))
            return dict(connection.execute("SELECT * FROM execution_jobs WHERE id=?", (row["id"],)).fetchone())

    @staticmethod
    def assert_lease(connection, job):
        row = connection.execute("SELECT owner,lease_version,lease_until,state FROM execution_jobs WHERE id=?", (job["id"],)).fetchone()
        if row is None or row["state"] != "running" or row["owner"] != job["owner"] or row["lease_version"] != job["lease_version"] or row["lease_until"] < time.time():
            raise LeaseLost("执行租约已失效")

    def heartbeat(self, job):
        with self.db.connect() as connection:
            self.assert_lease(connection, job)
            connection.execute("UPDATE execution_jobs SET lease_until=? WHERE id=?", (time.time() + self.lease_seconds, job["id"]))

    def finish(self, job, state, error=None):
        with self.db.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            self.assert_lease(connection, job)
            arena = connection.execute("SELECT status FROM arenas WHERE id=?", (job["arena_id"],)).fetchone()
            # A resume can arrive while the current round is finishing.
            if state == "paused" and arena["status"] == "running":
                return False
            connection.execute("UPDATE execution_jobs SET state=?,error=?,lease_until=0,updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=?", (state, error, job["id"]))
            if state == "failed":
                connection.execute("UPDATE arenas SET status='paused',error=?,updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=?", (error, job["arena_id"]))
        return True

    def retry(self, job, message):
        with self.db.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            self.assert_lease(connection, job)
            connection.execute("UPDATE execution_jobs SET state='queued',owner='',lease_until=0,available_at=?,error=? WHERE id=?", (time.time() + min(8, 2 ** job["attempts"]), message, job["id"]))
            connection.execute("INSERT INTO command_outbox(job_id) VALUES(?) ON CONFLICT(job_id) DO UPDATE SET published_at=NULL", (job["id"],))

    def suspend_for_approval(self, job):
        with self.db.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            self.assert_lease(connection, job)
            connection.execute("UPDATE execution_jobs SET state='paused',lease_until=0 WHERE id=?", (job["id"],))
            connection.execute("UPDATE arenas SET status='awaiting_approval',updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=?", (job["arena_id"],))

    def pending_events(self):
        with self.db.connect() as connection:
            return [dict(row) for row in connection.execute("SELECT * FROM command_outbox WHERE published_at IS NULL ORDER BY id LIMIT 20")]

    def published(self, event_id):
        with self.db.connect() as connection:
            connection.execute("UPDATE command_outbox SET published_at=? WHERE id=?", (time.time(), event_id))

    def listing(self, arena_id):
        with self.db.connect() as connection:
            return [dict(row) for row in connection.execute("SELECT * FROM execution_jobs WHERE arena_id=? ORDER BY id DESC", (arena_id,))]

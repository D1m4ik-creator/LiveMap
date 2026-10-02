"""The manifest must describe the same snapshot pg_dump exports."""

import importlib.util
from pathlib import Path
import unittest
import os
import shutil
import subprocess
from uuid import uuid4
from unittest.mock import MagicMock, patch
import psycopg2
from psycopg2 import sql

spec = importlib.util.spec_from_file_location("backup", Path(__file__).resolve().parents[1] / "scripts/cloud_backup.py")
backup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(backup)


class BackupSnapshotTests(unittest.TestCase):
    def test_counts_share_exported_readonly_snapshot(self):
        connection = MagicMock()
        cursor = connection.cursor.return_value.__enter__.return_value
        cursor.fetchone.return_value = ("00000003-00000001-1",)
        with patch.object(backup, "counts", return_value={"places": 16}) as counts:
            manifest, snapshot = backup.snapshot_manifest(connection, "livemap")
        connection.set_session.assert_called_once_with(isolation_level="REPEATABLE READ", readonly=True)
        cursor.execute.assert_called_once_with("SELECT pg_export_snapshot()")
        counts.assert_called_once_with(cursor, "livemap")
        self.assertEqual(snapshot, "00000003-00000001-1")
        self.assertTrue(manifest["consistent_snapshot"])
        self.assertEqual(manifest["counts"], {"places": 16})
        connection.commit.assert_not_called()
        connection.close.assert_not_called()

    @unittest.skipUnless(os.environ.get("POSTGRES_HOST") and (shutil.which("pg_dump") or os.environ.get("PG_DUMP_DOCKER_CONTAINER")), "Needs disposable CI PostgreSQL and pg_dump")
    def test_dump_excludes_writes_after_manifest(self):
        schema = "backup_test_" + uuid4().hex[:12]
        env = {**os.environ, "PGHOST": os.environ["POSTGRES_HOST"],
               "PGPORT": os.environ["POSTGRES_PORT"], "PGUSER": os.environ["POSTGRES_USER"],
               "PGPASSWORD": os.environ["POSTGRES_PASSWORD"], "PGDATABASE": os.environ["POSTGRES_DB"]}
        def connect():
            return psycopg2.connect(host=env["PGHOST"], port=env["PGPORT"], user=env["PGUSER"],
                                    password=env["PGPASSWORD"], dbname=env["PGDATABASE"])
        writer, snapshot_connection = connect(), connect()
        try:
            with writer, writer.cursor() as cursor:
                cursor.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
                for table in backup.TABLES:
                    cursor.execute(sql.SQL("CREATE TABLE {}.{} (id integer)").format(sql.Identifier(schema), sql.Identifier(table)))
                cursor.execute(sql.SQL("INSERT INTO {}.places VALUES (1)").format(sql.Identifier(schema)))
            manifest, snapshot = backup.snapshot_manifest(snapshot_connection, schema)
            with writer, writer.cursor() as cursor:
                cursor.execute(sql.SQL("INSERT INTO {}.places VALUES (2)").format(sql.Identifier(schema)))
            command = ["pg_dump"]
            if container := os.environ.get("PG_DUMP_DOCKER_CONTAINER"):
                command = ["docker", "exec", container, "pg_dump", "--username=" + env["PGUSER"], "--dbname=" + env["PGDATABASE"]]
            dump = subprocess.run(command + ["--data-only", "--no-owner", "--no-acl",
                                             "--schema=" + schema, "--snapshot=" + snapshot],
                                  env=env, capture_output=True, text=True, check=True, timeout=30).stdout
            records = dump.split(f"COPY {schema}.places (id) FROM stdin;\n", 1)[1].split("\\.\n", 1)[0]
            self.assertEqual(records.splitlines(), ["1"])
            self.assertEqual(manifest["counts"]["places"], 1)
        finally:
            snapshot_connection.close()
            writer.rollback()
            with writer, writer.cursor() as cursor:
                cursor.execute(sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(sql.Identifier(schema)))
            writer.close()


if __name__ == "__main__":
    unittest.main()

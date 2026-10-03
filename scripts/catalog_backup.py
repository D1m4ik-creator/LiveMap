"""Consistent, encrypted application backup through the regular SQL connection.

Fallback for poolers that disconnect pg_dump. Schema is rebuilt from the exact
Alembic revision in the archive. This is an application backup, not a backup of
Supabase Auth, Storage, extensions, roles, or project settings.
"""

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from uuid import uuid4

from alembic.config import Config as AlembicConfig
from alembic.script import ScriptDirectory
from psycopg2 import sql

from cloud_backup import TABLES, Config, connect, connection_env, counts


DATA_TABLES = tuple(table for table in TABLES if table != "alembic_version")


def write_record(output, value):
    output.write((json.dumps(value, ensure_ascii=False, separators=(",", ":")) + "\n").encode())


def export(config, recipient, target, age="age"):
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        raise ValueError("Refusing to overwrite archive")
    process = subprocess.Popen([age, "-r", recipient, "-o", str(target)], stdin=subprocess.PIPE)
    try:
        with connect(connection_env(config, migration=False)) as connection:
            connection.set_session(isolation_level="REPEATABLE READ", readonly=True)
            schema = config.database_schema
            with connection.cursor() as cursor:
                cursor.execute("SELECT tablename FROM pg_tables WHERE schemaname=%s", (schema,))
                if {row[0] for row in cursor} != set(TABLES):
                    raise ValueError("Unexpected table set: update the backup format before exporting")
                cursor.execute(sql.SQL("SELECT version_num FROM {}.alembic_version").format(sql.Identifier(schema)))
                revision = cursor.fetchone()[0]
                manifest = {"format": "livemap-catalog-v1", "schema": schema, "revision": revision,
                            "created_at": datetime.now(timezone.utc).isoformat(), "counts": counts(cursor, schema)}
                write_record(process.stdin, manifest)
            digest = hashlib.sha256()
            for table in DATA_TABLES:
                with connection.cursor(name="backup_" + table) as cursor:
                    expression = sql.SQL("to_jsonb(t)")
                    if table == "places":
                        expression = sql.SQL("to_jsonb(t) - 'geometry' || jsonb_build_object('geometry', encode(extensions.ST_AsEWKB(t.geometry), 'hex'))")
                    cursor.execute(sql.SQL("SELECT {} FROM {}.{} t ORDER BY id").format(expression, sql.Identifier(schema), sql.Identifier(table)))
                    cursor.itersize = 250
                    for (row,) in cursor:
                        record = {"table": table, "row": row}
                        encoded = (json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n").encode()
                        digest.update(encoded)
                        process.stdin.write(encoded)
            write_record(process.stdin, {"sha256": digest.hexdigest()})
        process.stdin.close()
        if process.wait(timeout=30):
            raise RuntimeError("Encryption failed")
        return {**manifest, "archive": str(target), "bytes": target.stat().st_size}
    except BaseException:
        process.kill()
        process.wait()
        target.unlink(missing_ok=True)
        raise


def verify(config, archive, identity, age="age"):
    if config.postgres_ssl or config.postgres_host not in ("localhost", "127.0.0.1", "::1"):
        raise ValueError("Restore verification requires an isolated local PostGIS server")
    env = connection_env(config, migration=False)
    restore_name = "livemap_restore_" + uuid4().hex[:16]
    admin = connect({**env, "PGDATABASE": "postgres"})
    admin.autocommit = True
    created = False
    try:
        with tempfile.TemporaryDirectory(prefix="livemap-restore-") as staging:
            bundle = Path(staging) / "catalog.jsonl"
            subprocess.run([age, "-d", "-i", str(identity), "-o", str(bundle), str(archive)], check=True)
            with bundle.open("rb") as source:
                manifest = json.loads(source.readline(64_001))
                if manifest.get("format") != "livemap-catalog-v1" or not re.fullmatch(r"[a-z_][a-z0-9_]*", manifest["schema"]):
                    raise ValueError("Invalid archive manifest")
                scripts = ScriptDirectory.from_config(AlembicConfig("alembic.ini"))
                if not scripts.get_revision(manifest["revision"]):
                    raise ValueError("Unknown schema revision")
                schema = manifest["schema"]
                with admin.cursor() as cursor:
                    cursor.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(restore_name)))
                    created = True
                restore_env = {**env, "PGDATABASE": restore_name}
                with connect(restore_env) as connection, connection.cursor() as cursor:
                    cursor.execute("CREATE SCHEMA extensions; CREATE EXTENSION postgis SCHEMA extensions")
                    if schema != "public":
                        cursor.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
                migration_env = {**os.environ, "POSTGRES_HOST": env["PGHOST"], "POSTGRES_PORT": env["PGPORT"],
                    "POSTGRES_DB": restore_name, "POSTGRES_USER": env["PGUSER"], "POSTGRES_PASSWORD": env["PGPASSWORD"],
                    "POSTGRES_MIGRATION_USER": env["PGUSER"], "POSTGRES_MIGRATION_PASSWORD": env["PGPASSWORD"],
                    "POSTGRES_SSL": "false", "DATABASE_SCHEMA": schema}
                subprocess.run([sys.executable, "-m", "alembic", "upgrade", manifest["revision"]], env=migration_env, check=True)
                digest = hashlib.sha256()
                footer = None
                with connect(restore_env) as connection, connection.cursor() as cursor:
                    for raw in source:
                        record = json.loads(raw)
                        if "sha256" in record:
                            if footer is not None:
                                raise ValueError("Duplicate archive footer")
                            footer = record["sha256"]
                            continue
                        if footer is not None or record.get("table") not in DATA_TABLES:
                            raise ValueError("Invalid table or record after footer")
                        digest.update(raw)
                        table, row = record["table"], record["row"]
                        columns = list(row)
                        cursor.execute(sql.SQL("INSERT INTO {}.{} ({}) VALUES ({})").format(
                            sql.Identifier(schema), sql.Identifier(table),
                            sql.SQL(",").join(map(sql.Identifier, columns)),
                            sql.SQL(",").join(sql.Placeholder() for _ in columns)), tuple(row.values()))
                    if footer != digest.hexdigest():
                        raise ValueError("Archive content checksum mismatch")
                    actual = counts(cursor, schema)
                    if actual != manifest["counts"]:
                        raise ValueError("Restored row counts differ from the snapshot")
                    cursor.execute(sql.SQL("SELECT count(*) FROM {}.places WHERE NOT extensions.ST_IsValid(geometry)").format(sql.Identifier(schema)))
                    if cursor.fetchone()[0]:
                        raise ValueError("Invalid restored geometry")
                    for table in DATA_TABLES:
                        cursor.execute(sql.SQL("SELECT pg_get_serial_sequence(%s, 'id'), max(id) FROM {}.{}").format(sql.Identifier(schema), sql.Identifier(table)), (schema + "." + table,))
                        sequence, maximum = cursor.fetchone()
                        if sequence:
                            cursor.execute("SELECT setval(%s, %s, %s)", (sequence, maximum or 1, maximum is not None))
                    # Confirm restore can continue accepting inserts without ID collisions.
                    cursor.execute(sql.SQL("INSERT INTO {}.admin_users(username,password_hash,role) VALUES (%s,%s,'editor') RETURNING id").format(sql.Identifier(schema)), ("restore-proof-" + uuid4().hex[:8], "not-a-login-hash"))
                    cursor.fetchone()
                    connection.rollback()
                return {"restore_verified": True, "counts": actual, "revision": manifest["revision"], "geometry_valid": True, "sequences_verified": True}
    finally:
        if created:
            with admin.cursor() as cursor:
                cursor.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(restore_name)))
        admin.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("backup", "verify"))
    parser.add_argument("--env-file", default=".env.supabase")
    parser.add_argument("--recipient")
    parser.add_argument("--identity", type=Path)
    parser.add_argument("--archive", type=Path)
    parser.add_argument("--output", type=Path, default=Path("backups"))
    args = parser.parse_args()
    config = Config(_env_file=args.env_file)
    if args.mode == "backup":
        if not args.recipient:
            parser.error("--recipient required")
        target = args.output / ("livemap-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + ".catalog.age")
        result = export(config, args.recipient, target)
    else:
        if not args.identity or not args.archive:
            parser.error("--identity and --archive required")
        result = verify(config, args.archive, args.identity)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()

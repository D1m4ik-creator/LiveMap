"""Application-schema pg_dump, encrypted before leaving this machine.

Requires PostgreSQL 17+ tools and age. Passwords reach child processes through
environment variables only. The recovery identity must be kept outside GitHub.
"""

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import struct
import tempfile
from uuid import uuid4

import psycopg2
from psycopg2 import sql

from livemap.core.config import Config


TABLES = ("places", "sources", "cameras", "admin_users", "admin_sessions", "audit_events", "camera_checks", "camera_reports", "alembic_version")


def connection_env(config: Config, *, migration: bool) -> dict[str, str]:
    database = config.migration_database if migration else config.database
    result = {**os.environ, "PGHOST": database.host, "PGPORT": str(database.port),
              "PGDATABASE": database.db, "PGUSER": database.user,
              "PGPASSWORD": database.password.get_secret_value(),
              "PGSSLMODE": "verify-full" if database.ssl else "disable"}
    if database.ssl_ca_file:
        result["PGSSLROOTCERT"] = str(Path(database.ssl_ca_file).resolve())
    return result


def connect(env: dict[str, str]):
    return psycopg2.connect(host=env["PGHOST"], port=env["PGPORT"], dbname=env["PGDATABASE"],
                            user=env["PGUSER"], password=env["PGPASSWORD"],
                            sslmode=env["PGSSLMODE"], sslrootcert=env.get("PGSSLROOTCERT", ""), connect_timeout=15)


def counts(cursor, schema: str) -> dict[str, int]:
    query = sql.SQL(" UNION ALL ").join(
        sql.SQL("SELECT {}, count(*) FROM {}.{}").format(sql.Literal(table), sql.Identifier(schema), sql.Identifier(table))
        for table in TABLES
    )
    cursor.execute(query)
    return dict(cursor.fetchall())


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("backup", "verify"))
    parser.add_argument("--env-file", type=Path, default=Path(".env.supabase"))
    parser.add_argument("--pg-bin", type=Path, default=Path("/usr/bin"))
    parser.add_argument("--age", default="age")
    parser.add_argument("--docker-client", action="store_true", help="Run Linux pg_dump in postgres:17-alpine")
    parser.add_argument("--recipient")
    parser.add_argument("--identity", type=Path)
    parser.add_argument("--archive", type=Path)
    parser.add_argument("--output", type=Path, default=Path("backups"))
    args = parser.parse_args()
    config = Config(_env_file=args.env_file)
    env = connection_env(config, migration=args.mode == "backup")
    suffix = ".exe" if os.name == "nt" else ""
    with tempfile.TemporaryDirectory(prefix="livemap-backup-") as staging:
        directory = Path(staging)
        bundle, dump = directory / "backup.bin", directory / "database.dump"
        if args.mode == "backup":
            if not args.recipient:
                parser.error("backup requires --recipient (public age key)")
            args.output.mkdir(parents=True, exist_ok=True)
            target = args.output / ("livemap-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + ".dump.age")
            if target.exists():
                raise ValueError("Backup already exists; refusing to overwrite")
            with connect(env) as connection, connection.cursor() as cursor:
                manifest = {"schema": config.database_schema, "created_at": datetime.now(timezone.utc).isoformat(),
                            "counts": counts(cursor, config.database_schema),
                            "counts_note": "Observed immediately before pg_dump; dump uses its own consistent snapshot."}
                connection.commit()
            connection.close()
            # Plaintext stays in memory/pipes until age encrypts it.
            header = json.dumps(manifest).encode("utf-8")
            encrypt = subprocess.Popen([args.age, "--recipient", args.recipient, "--output", str(target)], stdin=subprocess.PIPE)
            try:
                encrypt.stdin.write(b"LMAP1" + struct.pack(">I", len(header)) + header)
                encrypt.stdin.flush()
                command = [str(args.pg_bin / ("pg_dump" + suffix))]
                dump_env = env
                if args.docker_client:
                    command = ["docker", "run", "--rm", "-i"]
                    for name in ("PGHOST", "PGPORT", "PGDATABASE", "PGUSER", "PGPASSWORD", "PGSSLMODE", "PGSSLROOTCERT"):
                        command.extend(["--env", name])
                    if env.get("PGSSLROOTCERT"):
                        command.extend(["--volume", env["PGSSLROOTCERT"] + ":/ca.crt:ro"])
                        dump_env = {**env, "PGSSLROOTCERT": "/ca.crt"}
                    command.extend(["postgres:17-alpine", "pg_dump"])
                subprocess.run(command + ["--format=custom", "--no-owner", "--no-acl",
                                "--schema=" + config.database_schema], env=dump_env, stdout=encrypt.stdin, check=True, timeout=180)
                encrypt.stdin.close()
                if encrypt.wait() != 0:
                    raise RuntimeError("Encryption failed")
            except BaseException:
                encrypt.kill()
                encrypt.wait()
                target.unlink(missing_ok=True)
                raise
            print(json.dumps({"encrypted_archive": str(target), **manifest}, ensure_ascii=False))
        else:
            if not args.archive or not args.identity:
                parser.error("verify requires --archive and --identity")
            if config.postgres_ssl or config.postgres_host not in ("localhost", "127.0.0.1", "::1"):
                raise ValueError("Restore verification is allowed only against a local isolated database")
            subprocess.run([args.age, "--decrypt", "--identity", str(args.identity), "--output", str(bundle), str(args.archive)], check=True)
            with bundle.open("rb") as archive:
                if archive.read(5) != b"LMAP1":
                    raise ValueError("Invalid LiveMap backup header")
                header_length = struct.unpack(">I", archive.read(4))[0]
                if header_length > 64_000:
                    raise ValueError("Backup manifest too large")
                manifest = json.loads(archive.read(header_length))
                with dump.open("wb") as output:
                    while chunk := archive.read(1024 * 1024):
                        output.write(chunk)
            restore_name = "livemap_restore_" + uuid4().hex[:16]
            admin_env = {**env, "PGDATABASE": "postgres"}
            admin = connect(admin_env)
            admin.autocommit = True
            created = False
            try:
                with admin.cursor() as cursor:
                    cursor.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(restore_name)))
                    created = True
                    cursor.execute("DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='livemap_app') THEN CREATE ROLE livemap_app NOLOGIN; END IF; END $$")
                restore_env = {**env, "PGDATABASE": restore_name}
                with connect(restore_env) as connection, connection.cursor() as cursor:
                    cursor.execute("CREATE SCHEMA extensions; CREATE EXTENSION postgis SCHEMA extensions")
                connection.close()
                subprocess.run([str(args.pg_bin / ("pg_restore" + suffix)), "--dbname=" + restore_name,
                                "--no-owner", "--no-acl", "--exit-on-error", "--single-transaction", str(dump)], env=restore_env, check=True)
                with connect(restore_env) as connection, connection.cursor() as cursor:
                    actual = counts(cursor, manifest["schema"])
                    stable_tables = ("places", "sources", "cameras", "admin_users", "camera_reports", "alembic_version")
                    if any(actual[table] != manifest["counts"][table] for table in stable_tables):
                        raise ValueError("Catalog changed during export; repeat verification with writes paused")
                    cursor.execute(sql.SQL("SELECT count(*) FROM {}.places WHERE NOT extensions.ST_IsValid(geometry)").format(sql.Identifier(manifest["schema"])))
                    assert cursor.fetchone()[0] == 0, "Invalid restored geometry"
                connection.close()
                print(json.dumps({"restore_verified": True, "counts": actual, "all_counts_match": actual == manifest["counts"], "isolated_database": restore_name}))
            finally:
                if created:
                    with admin.cursor() as cursor:
                        cursor.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(restore_name)))
                admin.close()


if __name__ == "__main__":
    main()

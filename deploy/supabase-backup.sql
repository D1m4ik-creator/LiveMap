-- Application backup reader. Password is provisioned separately, never in Git.
DO $$ BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'livemap_backup') THEN
    CREATE ROLE livemap_backup NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOBYPASSRLS;
  END IF;
END $$;
GRANT CONNECT ON DATABASE postgres TO livemap_backup;
GRANT USAGE ON SCHEMA livemap, extensions TO livemap_backup;
GRANT SELECT ON ALL TABLES IN SCHEMA livemap TO livemap_backup;
ALTER DEFAULT PRIVILEGES FOR ROLE livemap_owner IN SCHEMA livemap GRANT SELECT ON TABLES TO livemap_backup;
ALTER ROLE livemap_backup SET default_transaction_read_only = on;
DO $$ DECLARE item record; BEGIN
  FOR item IN SELECT tablename FROM pg_tables WHERE schemaname='livemap' AND rowsecurity LOOP
    IF NOT EXISTS (SELECT FROM pg_policies WHERE schemaname='livemap' AND tablename=item.tablename AND policyname='backup_read') THEN
      EXECUTE format('CREATE POLICY backup_read ON livemap.%I FOR SELECT TO livemap_backup USING (true)', item.tablename);
    END IF;
  END LOOP;
END $$;

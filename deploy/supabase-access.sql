-- Run as the database administrator after Alembic, not as livemap_app.
-- The private schema is deliberately absent from the Supabase Data API.
REVOKE ALL ON SCHEMA livemap FROM PUBLIC, anon, authenticated;
REVOKE ALL ON ALL TABLES IN SCHEMA livemap FROM PUBLIC, anon, authenticated;
REVOKE INSERT, UPDATE, DELETE ON livemap.alembic_version FROM livemap_app;

DO $$
DECLARE target text;
BEGIN
  FOREACH target IN ARRAY ARRAY[
    'places', 'sources', 'cameras', 'camera_checks', 'camera_reports',
    'admin_users', 'admin_sessions', 'audit_events'
  ] LOOP
    EXECUTE format('ALTER TABLE livemap.%I ENABLE ROW LEVEL SECURITY', target);
    IF NOT EXISTS (
      SELECT 1 FROM pg_policies WHERE schemaname = 'livemap'
        AND tablename = target AND policyname = 'backend_access'
    ) THEN
      EXECUTE format(
        'CREATE POLICY backend_access ON livemap.%I TO livemap_app USING (true) WITH CHECK (true)',
        target
      );
    END IF;
  END LOOP;
END $$;

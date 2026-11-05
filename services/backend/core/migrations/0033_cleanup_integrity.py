from django.db import migrations

FORWARD = """
CREATE FUNCTION core_cleanup_request_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF OLD.project_id <> NEW.project_id OR OLD.material_id IS DISTINCT FROM NEW.material_id
        OR OLD.scope <> NEW.scope OR OLD.created_by_id <> NEW.created_by_id
        OR OLD.request_key <> NEW.request_key OR OLD.request_digest <> NEW.request_digest
        OR OLD.manifest <> NEW.manifest OR OLD.created_at <> NEW.created_at
        OR OLD.status = 'succeeded' OR NEW.generation < OLD.generation
        OR NEW.generation > OLD.generation + 1
    THEN RAISE EXCEPTION 'cleanup_request_immutable' USING ERRCODE = '23514'; END IF;
    IF NEW.status = 'succeeded' AND (NEW.completed_at IS NULL OR EXISTS (
        SELECT 1 FROM core_cleanupitem WHERE request_id = NEW.id
        AND status NOT IN ('removed', 'shared')
    )) THEN RAISE EXCEPTION 'cleanup_incomplete' USING ERRCODE = '23514'; END IF;
    RETURN NEW;
END;
$$;
CREATE FUNCTION core_cleanup_item_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF OLD.request_id <> NEW.request_id OR OLD.kind <> NEW.kind OR OLD.key <> NEW.key
        OR OLD.target <> NEW.target OR OLD.status IN ('removed', 'shared')
    THEN RAISE EXCEPTION 'cleanup_item_immutable' USING ERRCODE = '23514'; END IF;
    RETURN NEW;
END;
$$;
CREATE FUNCTION core_cleanup_attempt_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF OLD.request_id <> NEW.request_id OR OLD.generation <> NEW.generation
        OR OLD.started_at <> NEW.started_at OR OLD.finished_at IS NOT NULL
    THEN RAISE EXCEPTION 'cleanup_attempt_immutable' USING ERRCODE = '23514'; END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER cleanup_request_guard BEFORE UPDATE ON core_cleanuprequest
    FOR EACH ROW EXECUTE FUNCTION core_cleanup_request_guard();
CREATE TRIGGER cleanup_item_guard BEFORE UPDATE ON core_cleanupitem
    FOR EACH ROW EXECUTE FUNCTION core_cleanup_item_guard();
CREATE TRIGGER cleanup_attempt_guard BEFORE UPDATE ON core_cleanupattempt
    FOR EACH ROW EXECUTE FUNCTION core_cleanup_attempt_guard();
"""
REVERSE = """
DROP TRIGGER cleanup_request_guard ON core_cleanuprequest;
DROP TRIGGER cleanup_item_guard ON core_cleanupitem;
DROP TRIGGER cleanup_attempt_guard ON core_cleanupattempt;
DROP FUNCTION core_cleanup_request_guard();
DROP FUNCTION core_cleanup_item_guard();
DROP FUNCTION core_cleanup_attempt_guard();
"""


class Migration(migrations.Migration):
    dependencies = [("core", "0032_cleanup_requests")]
    operations = [migrations.RunSQL(FORWARD, REVERSE)]

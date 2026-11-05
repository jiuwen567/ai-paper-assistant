from django.db import migrations

FORWARD = """
CREATE FUNCTION core_check_parse_scope() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM core_parserun r
        JOIN core_materialversion v ON v.id = r.source_version_id
        JOIN core_material m ON m.id = v.material_id
        JOIN core_job j ON j.id = r.job_id
        WHERE m.project_id <> j.project_id AND (
            (TG_TABLE_NAME = 'core_parserun' AND r.id = NEW.id) OR
            (TG_TABLE_NAME = 'core_job' AND j.id = NEW.id) OR
            (TG_TABLE_NAME = 'core_material' AND m.id = NEW.id) OR
            (TG_TABLE_NAME = 'core_materialversion' AND v.id = NEW.id)
        )
    ) THEN
        RAISE EXCEPTION 'parse_project_scope' USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER parse_scope_run AFTER INSERT OR UPDATE OF source_version_id, job_id
ON core_parserun FOR EACH ROW EXECUTE FUNCTION core_check_parse_scope();
CREATE TRIGGER parse_scope_job AFTER UPDATE OF project_id ON core_job
FOR EACH ROW WHEN (OLD.project_id IS DISTINCT FROM NEW.project_id)
EXECUTE FUNCTION core_check_parse_scope();
CREATE TRIGGER parse_scope_material AFTER UPDATE OF project_id ON core_material
FOR EACH ROW WHEN (OLD.project_id IS DISTINCT FROM NEW.project_id)
EXECUTE FUNCTION core_check_parse_scope();
CREATE TRIGGER parse_scope_version AFTER UPDATE OF material_id ON core_materialversion
FOR EACH ROW WHEN (OLD.material_id IS DISTINCT FROM NEW.material_id)
EXECUTE FUNCTION core_check_parse_scope();
"""
REVERSE = """
DROP TRIGGER parse_scope_version ON core_materialversion;
DROP TRIGGER parse_scope_material ON core_material;
DROP TRIGGER parse_scope_job ON core_job;
DROP TRIGGER parse_scope_run ON core_parserun;
DROP FUNCTION core_check_parse_scope();
"""


class Migration(migrations.Migration):
    dependencies = [("core", "0006_parserun_sourcechunk_parserun_unique_parse_version_and_more")]
    operations = [migrations.RunSQL(FORWARD, REVERSE)]

from django.db import migrations

TABLES = ["exporttemplateversion", "exportsnapshot", "exportsource", "exportdownload"]
FORWARD = """
CREATE FUNCTION core_export_scope() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM core_exportsnapshot e
        JOIN core_job j ON j.id = e.job_id
        JOIN core_manuscriptrevision r ON r.id = e.manuscript_revision_id
        JOIN core_manuscript m ON m.id = r.manuscript_id
        JOIN core_disclosurerevision d ON d.id = e.disclosure_revision_id
        WHERE e.project_id <> j.project_id OR e.project_id <> m.project_id
            OR e.project_id <> d.project_id OR NOT d.verified OR j.kind <> 'export'
            OR j.input_snapshot->>'snapshot_id' IS DISTINCT FROM e.id::text
    ) THEN RAISE EXCEPTION 'export_snapshot_scope' USING ERRCODE = '23514'; END IF;
    IF EXISTS (
        SELECT 1 FROM core_exportsource s
        JOIN core_exportsnapshot e ON e.id = s.snapshot_id
        JOIN core_materialversion v ON v.id = s.source_version_id
        JOIN core_material m ON m.id = v.material_id
        WHERE e.project_id <> m.project_id
    ) THEN RAISE EXCEPTION 'export_source_scope' USING ERRCODE = '23514'; END IF;
    RETURN NEW;
END;
$$;
CREATE FUNCTION core_export_file_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF OLD.snapshot_id <> NEW.snapshot_id OR OLD.generation <> NEW.generation
        OR OLD.bucket <> NEW.bucket OR OLD.object_key <> NEW.object_key
        OR OLD.created_at <> NEW.created_at OR OLD.published_at IS NOT NULL
    THEN RAISE EXCEPTION 'export_file_immutable' USING ERRCODE = '23514'; END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER export_file_guard BEFORE UPDATE ON core_exportfile
    FOR EACH ROW EXECUTE FUNCTION core_export_file_guard();
"""
FORWARD += "\n".join(
    f"CREATE TRIGGER export_immutable_{table} BEFORE UPDATE ON core_{table} "
    "FOR EACH ROW EXECUTE FUNCTION core_manuscript_immutable();\n"
    f"CREATE TRIGGER export_scope_{table} AFTER INSERT ON core_{table} "
    "FOR EACH ROW EXECUTE FUNCTION core_export_scope();"
    for table in TABLES
)
PARENTS = {
    "job": "project_id, kind, input_snapshot",
    "materialversion": "material_id",
    "material": "project_id",
}
FORWARD += "\n" + "\n".join(
    f"CREATE TRIGGER export_parent_{table} AFTER UPDATE OF {fields} ON core_{table} "
    "FOR EACH ROW EXECUTE FUNCTION core_export_scope();"
    for table, fields in PARENTS.items()
)
REVERSE = "\n".join(f"DROP TRIGGER export_parent_{table} ON core_{table};" for table in PARENTS)
REVERSE += "\n" + "\n".join(
    f"DROP TRIGGER export_immutable_{table} ON core_{table};\n"
    f"DROP TRIGGER export_scope_{table} ON core_{table};"
    for table in TABLES
)
REVERSE += """
DROP TRIGGER export_file_guard ON core_exportfile;
DROP FUNCTION core_export_file_guard();
DROP FUNCTION core_export_scope();
"""


class Migration(migrations.Migration):
    dependencies = [("core", "0029_word_exports")]
    operations = [migrations.RunSQL(FORWARD, REVERSE)]

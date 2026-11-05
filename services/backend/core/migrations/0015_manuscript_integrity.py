from django.db import migrations

FORWARD = """
CREATE FUNCTION core_check_manuscript_scope() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF TG_TABLE_NAME = 'core_revisionblock' THEN
        IF NOT EXISTS (
            SELECT 1 FROM core_blockversion v
            JOIN core_contentblock b ON b.id = v.block_id
            JOIN core_manuscriptrevision r ON r.manuscript_id = b.manuscript_id
            WHERE v.id = NEW.block_version_id AND b.id = NEW.block_id AND r.id = NEW.revision_id
        ) THEN
            RAISE EXCEPTION 'manuscript_block_scope' USING ERRCODE = '23514';
        END IF;
    ELSE
        IF TG_OP = 'UPDATE' AND NEW.project_id <> OLD.project_id THEN
            RAISE EXCEPTION 'manuscript_project_immutable' USING ERRCODE = '23514';
        END IF;
        IF NEW.current_revision_id IS NOT NULL AND NOT EXISTS (
            SELECT 1 FROM core_manuscriptrevision r
            WHERE r.id = NEW.current_revision_id AND r.manuscript_id = NEW.id
        ) THEN
            RAISE EXCEPTION 'manuscript_current_scope' USING ERRCODE = '23514';
        END IF;
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER manuscript_current_scope BEFORE INSERT OR UPDATE ON core_manuscript
    FOR EACH ROW EXECUTE FUNCTION core_check_manuscript_scope();
CREATE TRIGGER manuscript_block_scope BEFORE INSERT ON core_revisionblock
    FOR EACH ROW EXECUTE FUNCTION core_check_manuscript_scope();

CREATE FUNCTION core_manuscript_immutable() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'manuscript_history_immutable' USING ERRCODE = '23514';
END;
$$;
""" + "\n".join(
    f"CREATE TRIGGER manuscript_immutable_{table} BEFORE UPDATE ON core_{table} "
    "FOR EACH ROW EXECUTE FUNCTION core_manuscript_immutable();"
    for table in ["contentblock", "blockversion", "manuscriptrevision", "revisionblock"]
)
REVERSE = (
    "\n".join(
        f"DROP TRIGGER manuscript_immutable_{table} ON core_{table};"
        for table in ["contentblock", "blockversion", "manuscriptrevision", "revisionblock"]
    )
    + """
DROP FUNCTION core_manuscript_immutable();
DROP TRIGGER manuscript_current_scope ON core_manuscript;
DROP TRIGGER manuscript_block_scope ON core_revisionblock;
DROP FUNCTION core_check_manuscript_scope();
"""
)


class Migration(migrations.Migration):
    dependencies = [("core", "0014_contentblock_blockversion_manuscript_and_more")]
    operations = [migrations.RunSQL(FORWARD, REVERSE)]

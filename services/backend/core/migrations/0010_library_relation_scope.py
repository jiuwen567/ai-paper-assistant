from django.db import migrations

TABLES = {
    "evidencecard": "chunk_id, bibliography_revision_id",
    "bibliographyrevision": "bibliography_id",
    "bibliography": "source_version_id",
    "sourcechunk": "run_id",
    "parserun": "source_version_id",
    "materialversion": "material_id",
    "material": "project_id",
    "job": "project_id",
    "embeddingindex": "job_id, dimension",
    "chunkembedding": "index_id, chunk_id, vector",
}

FUNCTION = """
CREATE FUNCTION core_check_library_scope() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM core_evidencecard e
        JOIN core_sourcechunk c ON c.id = e.chunk_id
        JOIN core_parserun r ON r.id = c.run_id
        JOIN core_bibliographyrevision br ON br.id = e.bibliography_revision_id
        JOIN core_bibliography b ON b.id = br.bibliography_id
        WHERE r.source_version_id <> b.source_version_id AND (
            (TG_TABLE_NAME = 'core_evidencecard' AND e.id = NEW.id) OR
            (TG_TABLE_NAME = 'core_sourcechunk' AND c.id = NEW.id) OR
            (TG_TABLE_NAME = 'core_parserun' AND r.id = NEW.id) OR
            (TG_TABLE_NAME = 'core_bibliographyrevision' AND br.id = NEW.id) OR
            (TG_TABLE_NAME = 'core_bibliography' AND b.id = NEW.id)
        )
    ) THEN
        RAISE EXCEPTION 'evidence_source_scope' USING ERRCODE = '23514';
    END IF;
    IF EXISTS (
        SELECT 1 FROM core_chunkembedding e
        JOIN core_embeddingindex i ON i.id = e.index_id
        JOIN core_job j ON j.id = i.job_id
        JOIN core_sourcechunk c ON c.id = e.chunk_id
        JOIN core_parserun r ON r.id = c.run_id
        JOIN core_materialversion v ON v.id = r.source_version_id
        JOIN core_material m ON m.id = v.material_id
        WHERE (m.project_id <> j.project_id OR vector_dims(e.vector) <> i.dimension) AND (
            (TG_TABLE_NAME = 'core_chunkembedding' AND e.id = NEW.id) OR
            (TG_TABLE_NAME = 'core_embeddingindex' AND i.id = NEW.id) OR
            (TG_TABLE_NAME = 'core_job' AND j.id = NEW.id) OR
            (TG_TABLE_NAME = 'core_sourcechunk' AND c.id = NEW.id) OR
            (TG_TABLE_NAME = 'core_parserun' AND r.id = NEW.id) OR
            (TG_TABLE_NAME = 'core_materialversion' AND v.id = NEW.id) OR
            (TG_TABLE_NAME = 'core_material' AND m.id = NEW.id)
        )
    ) THEN
        RAISE EXCEPTION 'embedding_space_scope' USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;
"""
FORWARD = FUNCTION + "\n".join(
    f"CREATE TRIGGER library_scope_{table} AFTER "
    f"{'INSERT OR ' if table in ['evidencecard', 'chunkembedding'] else ''}UPDATE OF {columns} "
    f"ON core_{table} FOR EACH ROW EXECUTE FUNCTION core_check_library_scope();"
    for table, columns in TABLES.items()
)
REVERSE = (
    "\n".join(f"DROP TRIGGER library_scope_{table} ON core_{table};" for table in reversed(TABLES))
    + "\nDROP FUNCTION core_check_library_scope();"
)


class Migration(migrations.Migration):
    dependencies = [("core", "0009_alter_evidencecard_bibliography_revision_and_more")]
    operations = [migrations.RunSQL(FORWARD, REVERSE)]

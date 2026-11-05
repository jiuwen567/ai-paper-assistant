from django.db import migrations

PARENTS = {
    "job": "project_id",
    "sourcechunk": "run_id",
    "parserun": "source_version_id",
    "bibliographyrevision": "bibliography_id",
    "bibliography": "source_version_id",
    "materialversion": "material_id",
    "material": "project_id",
}
CHILDREN = ["expressionsuggestion", "expressiondecision", "manuscriptcitation"]
FORWARD = """
CREATE FUNCTION core_check_expression_scope() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM core_expressionsuggestion s
        JOIN core_job j ON j.id = s.job_id
        JOIN core_manuscriptrevision r ON r.id = s.manuscript_revision_id
        JOIN core_manuscript m ON m.id = r.manuscript_id
        WHERE j.project_id <> m.project_id OR NOT EXISTS (
            SELECT 1 FROM core_revisionblock b
            WHERE b.revision_id = r.id AND b.block_version_id = s.block_version_id
        )
    ) THEN
        RAISE EXCEPTION 'expression_suggestion_scope' USING ERRCODE = '23514';
    END IF;
    IF EXISTS (
        SELECT 1 FROM core_expressiondecision d
        JOIN core_expressionsuggestion s ON s.id = d.suggestion_id
        JOIN core_manuscriptrevision original ON original.id = s.manuscript_revision_id
        JOIN core_manuscriptrevision result ON result.id = d.manuscript_revision_id
        WHERE original.manuscript_id <> result.manuscript_id
    ) THEN
        RAISE EXCEPTION 'expression_decision_scope' USING ERRCODE = '23514';
    END IF;
    IF EXISTS (
        SELECT 1 FROM core_manuscriptcitation c
        JOIN core_blockversion v ON v.id = c.block_version_id
        JOIN core_contentblock b ON b.id = v.block_id
        JOIN core_manuscript m ON m.id = b.manuscript_id
        JOIN core_sourcechunk ch ON ch.id = c.chunk_id
        JOIN core_parserun p ON p.id = ch.run_id
        JOIN core_materialversion f ON f.id = p.source_version_id
        JOIN core_material material ON material.id = f.material_id
        LEFT JOIN core_bibliographyrevision br ON br.id = c.bibliography_revision_id
        LEFT JOIN core_bibliography bibliography ON bibliography.id = br.bibliography_id
        WHERE m.project_id <> material.project_id OR bibliography.source_version_id <> f.id
    ) THEN
        RAISE EXCEPTION 'manuscript_citation_scope' USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;
"""
FORWARD += "\n".join(
    f"CREATE TRIGGER expression_scope_{table} AFTER INSERT ON core_{table} "
    "FOR EACH ROW EXECUTE FUNCTION core_check_expression_scope();\n"
    f"CREATE TRIGGER expression_immutable_{table} BEFORE UPDATE ON core_{table} "
    "FOR EACH ROW EXECUTE FUNCTION core_manuscript_immutable();"
    for table in CHILDREN
)
FORWARD += "\n" + "\n".join(
    f"CREATE TRIGGER expression_parent_{table} AFTER UPDATE OF {column} ON core_{table} "
    f"FOR EACH ROW WHEN (OLD.{column} IS DISTINCT FROM NEW.{column}) "
    "EXECUTE FUNCTION core_check_expression_scope();"
    for table, column in PARENTS.items()
)
REVERSE = "\n".join(f"DROP TRIGGER expression_parent_{table} ON core_{table};" for table in PARENTS)
REVERSE += "\n" + "\n".join(
    f"DROP TRIGGER expression_scope_{table} ON core_{table};\n"
    f"DROP TRIGGER expression_immutable_{table} ON core_{table};"
    for table in CHILDREN
)
REVERSE += "\nDROP FUNCTION core_check_expression_scope();"


class Migration(migrations.Migration):
    dependencies = [("core", "0018_expressiondecision_expressionsuggestion_and_more")]
    operations = [migrations.RunSQL(FORWARD, REVERSE)]

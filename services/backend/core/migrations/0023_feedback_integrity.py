from django.db import migrations

TABLES = [
    "feedback",
    "feedbackcandidate",
    "feedbacktask",
    "feedbackcandidatedecision",
    "feedbacktaskrevision",
    "mentorreport",
]
PARENTS = {
    "job": "project_id",
    "sourcechunk": "run_id",
    "parserun": "source_version_id",
    "materialversion": "material_id",
    "material": "project_id",
}
FORWARD = """
CREATE FUNCTION core_check_feedback_scope() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM core_feedback f
        LEFT JOIN core_manuscriptrevision r ON r.id = f.manuscript_revision_id
        LEFT JOIN core_manuscript m ON m.id = r.manuscript_id
        LEFT JOIN core_sourcechunk c ON c.id = f.source_chunk_id
        LEFT JOIN core_parserun p ON p.id = c.run_id
        LEFT JOIN core_materialversion v ON v.id = p.source_version_id
        LEFT JOIN core_material material ON material.id = v.material_id
        WHERE (m.project_id IS NOT NULL AND m.project_id <> f.project_id)
            OR (material.project_id IS NOT NULL AND material.project_id <> f.project_id)
            OR (f.block_version_id IS NOT NULL AND NOT EXISTS (
                SELECT 1 FROM core_revisionblock b WHERE b.revision_id = r.id
                    AND b.block_version_id = f.block_version_id
            ))
    ) THEN
        RAISE EXCEPTION 'feedback_location_scope' USING ERRCODE = '23514';
    END IF;
    IF EXISTS (
        SELECT 1 FROM core_feedbackcandidate c
        JOIN core_feedback f ON f.id = c.feedback_id
        JOIN core_job j ON j.id = c.job_id
        WHERE f.project_id <> j.project_id
    ) THEN
        RAISE EXCEPTION 'feedback_candidate_scope' USING ERRCODE = '23514';
    END IF;
    IF EXISTS (
        SELECT 1 FROM core_feedbackcandidatedecision d
        JOIN core_feedbackcandidate c ON c.id = d.candidate_id
        JOIN core_feedbacktask t ON t.id = d.task_id
        WHERE t.feedback_id <> c.feedback_id
    ) THEN
        RAISE EXCEPTION 'feedback_decision_scope' USING ERRCODE = '23514';
    END IF;
    IF EXISTS (
        SELECT 1 FROM core_feedbacktaskrevision tr
        JOIN core_feedbacktask t ON t.id = tr.task_id
        JOIN core_feedback f ON f.id = t.feedback_id
        JOIN core_manuscriptrevision r ON r.id = tr.manuscript_revision_id
        JOIN core_manuscript m ON m.id = r.manuscript_id
        WHERE m.project_id <> f.project_id OR NOT EXISTS (
            SELECT 1 FROM core_revisionblock b WHERE b.revision_id = r.id
                AND b.block_version_id = tr.block_version_id
        )
    ) THEN
        RAISE EXCEPTION 'feedback_task_location_scope' USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;
"""
FORWARD += "\n".join(
    f"CREATE TRIGGER feedback_scope_{table} AFTER INSERT ON core_{table} "
    "FOR EACH ROW EXECUTE FUNCTION core_check_feedback_scope();\n"
    f"CREATE TRIGGER feedback_immutable_{table} BEFORE UPDATE ON core_{table} "
    "FOR EACH ROW EXECUTE FUNCTION core_manuscript_immutable();"
    for table in TABLES
)
FORWARD += "\n" + "\n".join(
    f"CREATE TRIGGER feedback_parent_{table} AFTER UPDATE OF {column} ON core_{table} "
    f"FOR EACH ROW WHEN (OLD.{column} IS DISTINCT FROM NEW.{column}) "
    "EXECUTE FUNCTION core_check_feedback_scope();"
    for table, column in PARENTS.items()
)
REVERSE = "\n".join(f"DROP TRIGGER feedback_parent_{table} ON core_{table};" for table in PARENTS)
REVERSE += "\n" + "\n".join(
    f"DROP TRIGGER feedback_scope_{table} ON core_{table};\n"
    f"DROP TRIGGER feedback_immutable_{table} ON core_{table};"
    for table in TABLES
)
REVERSE += "\nDROP FUNCTION core_check_feedback_scope();"


class Migration(migrations.Migration):
    dependencies = [("core", "0022_feedback_feedbackcandidate_feedbacktask_and_more")]
    operations = [migrations.RunSQL(FORWARD, REVERSE)]

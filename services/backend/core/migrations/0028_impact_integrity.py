from django.db import migrations

TABLES = ["materialchange", "impactrun", "impactitem", "impactdecision"]
PARENTS = {
    "materialversion": "material_id, number",
    "material": "project_id",
    "job": "project_id",
}
FORWARD = """
CREATE FUNCTION core_check_impact_scope() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM core_materialchange c
        JOIN core_materialversion a ON a.id = c.source_version_id
        JOIN core_materialversion b ON b.id = c.replacement_id
        WHERE a.material_id <> b.material_id OR a.number >= b.number
    ) THEN RAISE EXCEPTION 'material_change_scope' USING ERRCODE = '23514'; END IF;
    IF EXISTS (
        SELECT 1 FROM core_impactrun r
        JOIN core_materialchange c ON c.id = r.change_id
        JOIN core_materialversion v ON v.id = c.source_version_id
        JOIN core_material m ON m.id = v.material_id
        JOIN core_manuscriptrevision mr ON mr.id = r.manuscript_revision_id
        JOIN core_manuscript ms ON ms.id = mr.manuscript_id
        WHERE m.project_id <> ms.project_id
    ) THEN RAISE EXCEPTION 'impact_run_scope' USING ERRCODE = '23514'; END IF;
    IF EXISTS (
        SELECT 1 FROM core_impactitem i
        JOIN core_impactrun r ON r.id = i.run_id
        JOIN core_materialchange c ON c.id = r.change_id
        JOIN core_materialversion v ON v.id = c.source_version_id
        JOIN core_material m ON m.id = v.material_id
        LEFT JOIN core_expressionsuggestion s ON s.id = i.suggestion_id
        LEFT JOIN core_job sj ON sj.id = s.job_id
        LEFT JOIN core_feedbacktask t ON t.id = i.task_id
        LEFT JOIN core_feedback f ON f.id = t.feedback_id
        LEFT JOIN core_job j ON j.id = i.job_id
        WHERE (sj.project_id IS NOT NULL AND sj.project_id <> m.project_id)
            OR (f.project_id IS NOT NULL AND f.project_id <> m.project_id)
            OR (j.project_id IS NOT NULL AND (j.project_id <> m.project_id
                OR j.input_snapshot->'impact'->>'run_id' IS DISTINCT FROM r.id::text))
            OR (i.block_version_id IS NOT NULL AND NOT EXISTS (
                SELECT 1 FROM core_revisionblock rb WHERE rb.revision_id = r.manuscript_revision_id
                    AND rb.block_version_id = i.block_version_id))
    ) THEN RAISE EXCEPTION 'impact_item_scope' USING ERRCODE = '23514'; END IF;
    RETURN NEW;
END;
$$;
DROP TRIGGER graph_event_materialversion ON core_materialversion;
CREATE TRIGGER graph_event_materialversion AFTER INSERT OR UPDATE OF status, usage_state,
    usage_version OR DELETE ON core_materialversion
    FOR EACH ROW EXECUTE FUNCTION core_graph_changed();
"""
FORWARD += "\n".join(
    f"CREATE TRIGGER impact_scope_{table} AFTER INSERT ON core_{table} "
    "FOR EACH ROW EXECUTE FUNCTION core_check_impact_scope();\n"
    f"CREATE TRIGGER impact_immutable_{table} BEFORE UPDATE ON core_{table} "
    "FOR EACH ROW EXECUTE FUNCTION core_manuscript_immutable();"
    for table in TABLES
)
FORWARD += "\n" + "\n".join(
    f"CREATE TRIGGER impact_parent_{table} AFTER UPDATE OF {columns} ON core_{table} "
    "FOR EACH ROW EXECUTE FUNCTION core_check_impact_scope();"
    for table, columns in PARENTS.items()
)
REVERSE = "\n".join(f"DROP TRIGGER impact_parent_{table} ON core_{table};" for table in PARENTS)
REVERSE += "\n" + "\n".join(
    f"DROP TRIGGER impact_scope_{table} ON core_{table};\n"
    f"DROP TRIGGER impact_immutable_{table} ON core_{table};"
    for table in TABLES
)
REVERSE += """
DROP FUNCTION core_check_impact_scope();
DROP TRIGGER graph_event_materialversion ON core_materialversion;
CREATE TRIGGER graph_event_materialversion AFTER INSERT OR UPDATE OF status OR DELETE
    ON core_materialversion FOR EACH ROW EXECUTE FUNCTION core_graph_changed();
"""


class Migration(migrations.Migration):
    dependencies = [("core", "0027_material_impacts")]
    operations = [migrations.RunSQL(FORWARD, REVERSE)]

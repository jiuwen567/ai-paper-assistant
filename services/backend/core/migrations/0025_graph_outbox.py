from django.db import migrations

# 事件在业务事务内产生；不依赖 on_commit 投递成功，也覆盖批量插入和管理命令。
FORWARD = """
CREATE FUNCTION core_graph_dirty(pid uuid) RETURNS bigint LANGUAGE plpgsql AS $$
DECLARE v bigint;
BEGIN
    IF NOT EXISTS (SELECT 1 FROM core_project WHERE id = pid) THEN RETURN NULL; END IF;
    INSERT INTO core_graphstate(project_id, revision, applied_revision, last_error, updated_at)
        VALUES (pid, 1, 0, '', now())
        ON CONFLICT (project_id) DO UPDATE
        SET revision = core_graphstate.revision + 1, updated_at = now()
        RETURNING revision INTO v;
    INSERT INTO core_graphevent(project_id, revision, created_at, attempts, error_code)
        VALUES (pid, v, now(), 0, '');
    RETURN v;
END;
$$;

CREATE FUNCTION core_graph_changed() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE row_data jsonb; pid uuid;
BEGIN
    IF TG_OP = 'DELETE' THEN row_data := to_jsonb(OLD); ELSE row_data := to_jsonb(NEW); END IF;
    CASE TG_TABLE_NAME
    WHEN 'core_project' THEN pid := (row_data->>'id')::uuid;
    WHEN 'core_manuscript', 'core_material', 'core_evidencelink'
        THEN pid := (row_data->>'project_id')::uuid;
    WHEN 'core_evidencelinkrevision' THEN
        SELECT project_id INTO pid FROM core_evidencelink
            WHERE id = (row_data->>'link_id')::uuid;
    WHEN 'core_reviewrecord' THEN
        SELECT project_id INTO pid FROM core_job WHERE id = (row_data->>'job_id')::uuid;
    WHEN 'core_reviewfinding' THEN
        SELECT j.project_id INTO pid FROM core_reviewrecord r JOIN core_job j ON j.id = r.job_id
            WHERE r.id = (row_data->>'review_id')::uuid;
    WHEN 'core_manuscriptcitation' THEN
        SELECT m.project_id INTO pid FROM core_blockversion b
            JOIN core_contentblock c ON c.id = b.block_id
            JOIN core_manuscript m ON m.id = c.manuscript_id
            WHERE b.id = (row_data->>'block_version_id')::uuid;
    WHEN 'core_parserun' THEN
        SELECT m.project_id INTO pid FROM core_materialversion v
            JOIN core_material m ON m.id = v.material_id
            WHERE v.id = (row_data->>'source_version_id')::uuid;
    WHEN 'core_sourcechunk' THEN
        SELECT m.project_id INTO pid FROM core_parserun p
            JOIN core_materialversion v ON v.id = p.source_version_id
            JOIN core_material m ON m.id = v.material_id
            WHERE p.id = (row_data->>'run_id')::uuid;
    WHEN 'core_materialversion' THEN
        SELECT project_id INTO pid FROM core_material WHERE id = (row_data->>'material_id')::uuid;
    ELSE RAISE EXCEPTION 'unknown_graph_source';
    END CASE;
    IF pid IS NOT NULL THEN PERFORM core_graph_dirty(pid); END IF;
    RETURN NULL;
END;
$$;

CREATE FUNCTION core_evidence_link_scope() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM core_evidencelink l
        JOIN core_manuscriptrevision r ON r.id = l.manuscript_revision_id
        JOIN core_manuscript ms ON ms.id = r.manuscript_id
        JOIN core_blockversion b ON b.id = l.block_version_id
        JOIN core_sourcechunk c ON c.id = l.chunk_id
        JOIN core_parserun p ON p.id = c.run_id
        JOIN core_materialversion v ON v.id = p.source_version_id
        JOIN core_material m ON m.id = v.material_id
        LEFT JOIN core_bibliographyrevision br ON br.id = l.bibliography_revision_id
        LEFT JOIN core_bibliography bib ON bib.id = br.bibliography_id
        WHERE l.project_id <> ms.project_id OR l.project_id <> m.project_id
            OR (bib.source_version_id IS NOT NULL AND bib.source_version_id <> v.id)
            OR NOT EXISTS (SELECT 1 FROM core_revisionblock rb
                WHERE rb.revision_id = r.id AND rb.block_version_id = b.id)
            OR l.claim = '' OR l.evidence_quote = ''
            OR substring(b.text FROM l.claim_start + 1 FOR char_length(l.claim)) <> l.claim
            OR substring(c.text FROM l.evidence_start + 1
                FOR char_length(l.evidence_quote)) <> l.evidence_quote
    ) THEN RAISE EXCEPTION 'evidence_link_scope' USING ERRCODE = '23514'; END IF;
    RETURN NEW;
END;
$$;
"""

EVENTS = {
    "project": "INSERT",
    "manuscript": "INSERT OR UPDATE OF current_revision_id OR DELETE",
    "material": "INSERT OR UPDATE OF access_state, state_version OR DELETE",
    "materialversion": "INSERT OR UPDATE OF status OR DELETE",
    "parserun": "UPDATE OF published_at OR DELETE",
    "sourcechunk": "UPDATE OR DELETE",
    "evidencelink": "INSERT OR DELETE",
    "evidencelinkrevision": "INSERT OR DELETE",
    "reviewrecord": "INSERT OR DELETE",
    "reviewfinding": "INSERT OR UPDATE OF status, revision OR DELETE",
    "manuscriptcitation": "INSERT OR DELETE",
}
FORWARD += "\n".join(
    f"CREATE TRIGGER graph_event_{table} AFTER {events} ON core_{table} "
    "FOR EACH ROW EXECUTE FUNCTION core_graph_changed();"
    for table, events in EVENTS.items()
)
FORWARD += """
CREATE TRIGGER evidence_link_scope AFTER INSERT ON core_evidencelink
    FOR EACH ROW EXECUTE FUNCTION core_evidence_link_scope();
CREATE TRIGGER evidence_link_immutable BEFORE UPDATE ON core_evidencelink
    FOR EACH ROW EXECUTE FUNCTION core_manuscript_immutable();
CREATE TRIGGER evidence_link_revision_immutable BEFORE UPDATE ON core_evidencelinkrevision
    FOR EACH ROW EXECUTE FUNCTION core_manuscript_immutable();
"""
PARENTS = {
    "sourcechunk": "text, run_id",
    "parserun": "source_version_id",
    "materialversion": "material_id",
    "material": "project_id",
    "bibliography": "source_version_id",
    "bibliographyrevision": "bibliography_id",
}
FORWARD += "\n".join(
    f"CREATE TRIGGER evidence_link_parent_{table} AFTER UPDATE OF {fields} ON core_{table} "
    "FOR EACH ROW EXECUTE FUNCTION core_evidence_link_scope();"
    for table, fields in PARENTS.items()
)
FORWARD += "\nSELECT core_graph_dirty(id) FROM core_project;"
REVERSE = "\n".join(f"DROP TRIGGER graph_event_{table} ON core_{table};" for table in EVENTS)
REVERSE += "\n" + "\n".join(
    f"DROP TRIGGER evidence_link_parent_{table} ON core_{table};" for table in PARENTS
)
REVERSE += """
DROP TRIGGER evidence_link_scope ON core_evidencelink;
DROP TRIGGER evidence_link_immutable ON core_evidencelink;
DROP TRIGGER evidence_link_revision_immutable ON core_evidencelinkrevision;
DROP FUNCTION core_evidence_link_scope();
DROP FUNCTION core_graph_changed();
DROP FUNCTION core_graph_dirty(uuid);
"""


class Migration(migrations.Migration):
    dependencies = [("core", "0024_evidence_graph")]
    operations = [migrations.RunSQL(FORWARD, REVERSE)]

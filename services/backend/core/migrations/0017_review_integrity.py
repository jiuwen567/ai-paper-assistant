from django.db import migrations

FORWARD = """
CREATE FUNCTION core_check_review_scope() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM core_reviewrecord r
        JOIN core_job j ON j.id = r.job_id
        JOIN core_manuscriptrevision mr ON mr.id = r.manuscript_revision_id
        JOIN core_manuscript m ON m.id = mr.manuscript_id
        LEFT JOIN core_reviewrecord previous ON previous.id = r.previous_review_id
        LEFT JOIN core_job pj ON pj.id = previous.job_id
        WHERE (j.project_id <> m.project_id
            OR (previous.id IS NOT NULL AND pj.project_id <> j.project_id))
          AND ((TG_TABLE_NAME = 'core_reviewrecord' AND r.id = NEW.id)
            OR (TG_TABLE_NAME = 'core_job' AND (j.id = NEW.id OR pj.id = NEW.id)))
    ) THEN
        RAISE EXCEPTION 'review_project_scope' USING ERRCODE = '23514';
    END IF;
    IF TG_TABLE_NAME = 'core_reviewfinding' THEN
        IF NOT EXISTS (
            SELECT 1 FROM core_reviewrecord r
            JOIN core_revisionblock b ON b.revision_id = r.manuscript_revision_id
            WHERE r.id = NEW.review_id AND b.block_version_id = NEW.block_version_id
        ) THEN
            RAISE EXCEPTION 'review_block_scope' USING ERRCODE = '23514';
        END IF;
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER review_project_scope AFTER INSERT ON core_reviewrecord
FOR EACH ROW EXECUTE FUNCTION core_check_review_scope();
CREATE TRIGGER review_job_scope AFTER UPDATE OF project_id ON core_job
FOR EACH ROW EXECUTE FUNCTION core_check_review_scope();
CREATE TRIGGER review_block_scope AFTER INSERT ON core_reviewfinding
FOR EACH ROW EXECUTE FUNCTION core_check_review_scope();
CREATE TRIGGER review_record_immutable BEFORE UPDATE ON core_reviewrecord
FOR EACH ROW EXECUTE FUNCTION core_manuscript_immutable();
CREATE TRIGGER review_decision_immutable BEFORE UPDATE ON core_reviewdecision
FOR EACH ROW EXECUTE FUNCTION core_manuscript_immutable();
CREATE FUNCTION core_review_finding_immutable() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF (NEW.review_id, NEW.block_version_id, NEW.category, NEW.model_output)
        IS DISTINCT FROM (OLD.review_id, OLD.block_version_id, OLD.category, OLD.model_output) THEN
        RAISE EXCEPTION 'review_finding_immutable' USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER review_finding_immutable BEFORE UPDATE ON core_reviewfinding
FOR EACH ROW EXECUTE FUNCTION core_review_finding_immutable();
"""
REVERSE = """
DROP TRIGGER review_finding_immutable ON core_reviewfinding;
DROP FUNCTION core_review_finding_immutable();
DROP TRIGGER review_decision_immutable ON core_reviewdecision;
DROP TRIGGER review_record_immutable ON core_reviewrecord;
DROP TRIGGER review_block_scope ON core_reviewfinding;
DROP TRIGGER review_job_scope ON core_job;
DROP TRIGGER review_project_scope ON core_reviewrecord;
DROP FUNCTION core_check_review_scope();
"""


class Migration(migrations.Migration):
    dependencies = [("core", "0016_reviewrecord_reviewfinding_reviewdecision_and_more")]
    operations = [migrations.RunSQL(FORWARD, REVERSE)]

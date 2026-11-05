from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [("core", "0010_library_relation_scope")]
    operations = [
        migrations.RunSQL(
            """
            UPDATE core_job j SET input_snapshot = j.input_snapshot ||
                jsonb_build_object('source_state_version', m.state_version)
            FROM core_parserun r
            JOIN core_materialversion v ON v.id = r.source_version_id
            JOIN core_material m ON m.id = v.material_id
            WHERE r.job_id = j.id AND j.kind = 'parse';
            """,
            "UPDATE core_job SET input_snapshot = input_snapshot - 'source_state_version' "
            "WHERE kind = 'parse';",
        ),
    ]

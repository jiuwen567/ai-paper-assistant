import hashlib
import json

from django.db import migrations

# 自制示例规则固定在迁移内，不读取可能在未来改变的应用默认值。
VALUE = {
    "code": "department-default",
    "name": "中文论文示例模板（自制）",
    "source_label": "项目自行编写的排版规则，非院系官方模板",
    "rights_note": "本项目为导出功能自行编写，无第三方模板文件或受限素材。",
    "layout": {
        "page_width_mm": 210.0,
        "page_height_mm": 297.0,
        "margin_top_mm": 25.0,
        "margin_bottom_mm": 25.0,
        "margin_left_mm": 30.0,
        "margin_right_mm": 25.0,
        "body_font": "宋体",
        "latin_font": "Times New Roman",
        "heading_font": "黑体",
        "body_size_pt": 12.0,
        "title_size_pt": 18.0,
        "heading_sizes_pt": [16.0, 14.0, 12.0, 12.0, 12.0, 12.0, 12.0, 12.0, 12.0],
        "line_spacing": 1.5,
        "first_line_chars": 2.0,
        "caption_size_pt": 10.5,
        "header_size_pt": 9.0,
        "header_text": "{title}",
        "toc_levels": 3,
    },
}


def forward(apps, schema_editor):
    template = apps.get_model("core", "ExportTemplateVersion")
    fingerprint = hashlib.sha256(
        json.dumps(VALUE, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()
    template.objects.create(number=1, digest=fingerprint, **VALUE)


def reverse(apps, schema_editor):
    apps.get_model("core", "ExportTemplateVersion").objects.filter(
        code=VALUE["code"], number=1
    ).delete()


class Migration(migrations.Migration):
    dependencies = [("core", "0030_export_integrity")]
    operations = [migrations.RunPython(forward, reverse)]

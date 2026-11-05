"""首版使用可审阅的排版规则，不接受可执行模板或宏。"""

from django.db import connection, transaction
from django.db.models import Max
from rest_framework import serializers

from core.ai_jobs import digest
from core.models import ExportTemplateVersion
from core.reading import StrictSerializer

DEFAULT_LAYOUT = {
    "page_width_mm": 210,
    "page_height_mm": 297,
    "margin_top_mm": 25,
    "margin_bottom_mm": 25,
    "margin_left_mm": 30,
    "margin_right_mm": 25,
    "body_font": "宋体",
    "latin_font": "Times New Roman",
    "heading_font": "黑体",
    "body_size_pt": 12,
    "title_size_pt": 18,
    "heading_sizes_pt": [16, 14, 12, 12, 12, 12, 12, 12, 12],
    "line_spacing": 1.5,
    "first_line_chars": 2,
    "caption_size_pt": 10.5,
    "header_size_pt": 9,
    "header_text": "{title}",
    "toc_levels": 3,
}
DEFAULT_CODE = "department-default"
DEFAULT_NAME = "中文论文示例模板（自制）"
DEFAULT_SOURCE = "项目自行编写的排版规则，非院系官方模板"
DEFAULT_RIGHTS = "本项目为导出功能自行编写，无第三方模板文件或受限素材。"


class LayoutInput(StrictSerializer):
    page_width_mm = serializers.FloatField(min_value=100, max_value=420)
    page_height_mm = serializers.FloatField(min_value=100, max_value=594)
    margin_top_mm = serializers.FloatField(min_value=10, max_value=50)
    margin_bottom_mm = serializers.FloatField(min_value=10, max_value=50)
    margin_left_mm = serializers.FloatField(min_value=10, max_value=50)
    margin_right_mm = serializers.FloatField(min_value=10, max_value=50)
    body_font = serializers.CharField(max_length=80)
    latin_font = serializers.CharField(max_length=80)
    heading_font = serializers.CharField(max_length=80)
    body_size_pt = serializers.FloatField(min_value=9, max_value=18)
    title_size_pt = serializers.FloatField(min_value=12, max_value=36)
    heading_sizes_pt = serializers.ListField(
        child=serializers.FloatField(min_value=9, max_value=36), min_length=9, max_length=9
    )
    line_spacing = serializers.FloatField(min_value=1, max_value=3)
    first_line_chars = serializers.FloatField(min_value=0, max_value=4)
    caption_size_pt = serializers.FloatField(min_value=9, max_value=18)
    header_size_pt = serializers.FloatField(min_value=8, max_value=14)
    header_text = serializers.CharField(max_length=200, allow_blank=True)
    toc_levels = serializers.IntegerField(min_value=1, max_value=9)

    def validate(self, data):
        if (
            data["page_width_mm"] - data["margin_left_mm"] - data["margin_right_mm"] < 80
            or data["page_height_mm"] - data["margin_top_mm"] - data["margin_bottom_mm"] < 80
        ):
            raise serializers.ValidationError("扣除页边距后的正文区域过小。")
        return data


class TemplateInput(StrictSerializer):
    code = serializers.RegexField(r"^[a-z0-9]+(?:-[a-z0-9]+)*$", max_length=80)
    name = serializers.CharField(max_length=200)
    source_label = serializers.CharField(max_length=500)
    rights_note = serializers.CharField(max_length=2000)
    layout = LayoutInput()


def template_data(template):
    return {
        "id": str(template.pk),
        "code": template.code,
        "number": template.number,
        "name": template.name,
        "source_label": template.source_label,
        "rights_note": template.rights_note,
        "layout": template.layout,
        "digest": template.digest,
    }


@transaction.atomic
def register_template(value, user):
    serializer = TemplateInput(data=value)
    serializer.is_valid(raise_exception=True)
    data = serializer.validated_data
    # 相同模板编码的首次登记也串行化，避免两个维护命令同时分配 v1。
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT pg_advisory_xact_lock(hashtext(%s))", ["export-template:" + data["code"]]
        )
    fingerprint = digest(data)
    previous = ExportTemplateVersion.objects.filter(code=data["code"]).order_by("-number").first()
    if previous and previous.digest == fingerprint:
        return previous, False
    number = (
        ExportTemplateVersion.objects.filter(code=data["code"]).aggregate(value=Max("number"))[
            "value"
        ]
        or 0
    ) + 1
    return ExportTemplateVersion.objects.create(
        number=number, created_by=user, digest=fingerprint, **data
    ), True

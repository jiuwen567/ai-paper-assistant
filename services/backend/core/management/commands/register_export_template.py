import json
from pathlib import Path

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from rest_framework.exceptions import ValidationError

from core.exports.templates import register_template


class Command(BaseCommand):
    help = "管理员登记有权使用的 Word 排版规则；内容变化追加版本，不修改已有模板。"

    def add_arguments(self, parser):
        parser.add_argument("file", help="排版规则 JSON 文件")
        parser.add_argument("--user", required=True, help="维护者的管理员账号")
        parser.add_argument(
            "--rights-confirmed", action="store_true", help="已核对模板使用权限及来源说明"
        )

    def handle(self, *args, **options):
        user = (
            get_user_model()
            .objects.filter(username=options["user"], is_active=True, is_superuser=True)
            .first()
        )
        if user is None or not options["rights_confirmed"]:
            raise CommandError("需要有效管理员账号，并明确确认模板使用权限。")
        try:
            value = json.loads(Path(options["file"]).read_text())
            template, created = register_template(value, user)
        except (OSError, ValueError, ValidationError):
            raise CommandError("模板文件无法读取或格式不符，请核对 JSON 规则。") from None
        self.stdout.write(
            f"{'已登记' if created else '已存在'} {template.code} v{template.number}"
            f" · {template.digest}"
        )

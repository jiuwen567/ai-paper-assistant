"""只生成菜单配置，不调用公众号发布接口。"""

import json
from urllib.parse import urlparse

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "生成公众号小程序入口和使用帮助菜单 JSON；由具备权限的管理员配置。"

    def add_arguments(self, parser):
        parser.add_argument("--web-url", required=True)

    def handle(self, *args, **options):
        url = options["web_url"].rstrip("/")
        parsed = urlparse(url)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
        ):
            raise CommandError("请提供不含凭据、查询参数和片段的 HTTPS 网站根地址。")
        if not settings.WECHAT_APP_ID:
            raise CommandError("请先配置服务端 WECHAT_APP_ID。")
        self.stdout.write(
            json.dumps(
                {
                    "button": [
                        {
                            "type": "miniprogram",
                            "name": "我的论文",
                            "url": url + "/wechat",
                            "appid": settings.WECHAT_APP_ID,
                            "pagepath": "pages/projects/projects",
                        },
                        {"type": "view", "name": "使用帮助", "url": url + "/wechat"},
                    ]
                },
                ensure_ascii=False,
                indent=2,
            )
        )

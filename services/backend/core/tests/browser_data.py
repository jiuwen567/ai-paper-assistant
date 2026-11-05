"""浏览器验收专用自制数据，只允许在 DEBUG 开发环境创建与清理随机前缀账号。"""

import json
import os
import re
import secrets
import sys

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

import django  # noqa: E402

django.setup()

from django.conf import settings  # noqa: E402
from django.contrib.auth import get_user_model  # noqa: E402
from django.db import transaction  # noqa: E402

from core.models import Project, ProjectPolicy, WechatIdentity  # noqa: E402


def main():
    data = json.load(sys.stdin)
    prefix = data["prefix"]
    if not settings.DEBUG or not re.fullmatch(r"e2e-[0-9a-f]{32}", prefix):
        raise ValueError("只允许清理开发环境中带随机验收前缀的专用测试数据。")
    usernames = [f"{prefix}-{role}" for role in ["owner", "reviewer", "outsider"]]
    users = get_user_model()
    with transaction.atomic():
        if data["action"] == "create":
            password = secrets.token_urlsafe(24)
            owner, reviewer, outsider = [
                users.objects.create_user(username=name, password=password) for name in usernames
            ]
            other = Project.objects.create(owner=outsider, name="自制隔离测试项目")
            ProjectPolicy.objects.create(project=other, version=1, created_by=outsider)
            print(
                json.dumps(
                    {
                        "owner": owner.username,
                        "reviewer": reviewer.username,
                        "reviewerId": reviewer.pk,
                        "password": password,
                        "otherId": str(other.pk),
                    }
                )
            )
        elif data["action"] == "binding":
            # 自制身份绕过微信服务，仅验证 Web 绑定交互，不冒充真实微信登录。
            from core.wechat import login_wechat
            print(json.dumps(login_wechat(prefix), default=str))
        elif data["action"] == "cleanup":
            WechatIdentity.objects.filter(open_id=prefix).delete()
            Project.objects.filter(owner__username__in=usernames).delete()
            users.objects.filter(username__in=usernames).delete()
        else:
            raise ValueError("未知操作。")


if __name__ == "__main__":
    main()

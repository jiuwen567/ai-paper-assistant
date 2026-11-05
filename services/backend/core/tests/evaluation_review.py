"""生成离线复核表；文本通过 textContent 展示，模型输出不能执行脚本。"""

import json
from pathlib import Path

from core.tests.evaluation_metrics import review_template


def render(run):
    payload = json.dumps({"run": run, "review": review_template(run)}, ensure_ascii=False)
    payload = (
        payload.replace("<", "\\u003c").replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")
    )
    return Path(__file__).with_suffix(".html").read_text().replace("__PAYLOAD__", payload)

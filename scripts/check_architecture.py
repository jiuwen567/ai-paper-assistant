"""检查运行时代码的文件规模、公共层依赖与业务层对视图的反向引用。"""

import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LIMIT = 400
SOURCES = (
    "services/backend",
    "services/pi-runner/src",
    "apps/web/src",
    "apps/web/scripts",
    "apps/miniapp/miniprogram",
    "scripts",
)
SUFFIXES = {".py", ".ts", ".vue", ".css", ".wxss", ".wxml"}


def runtime_files():
    for directory in SOURCES:
        for path in (ROOT / directory).rglob("*"):
            if (
                path.suffix in SUFFIXES
                and not {"tests", "migrations", "__pycache__"}.intersection(path.parts)
                and not path.name.endswith((".test.ts", ".d.ts"))
            ):
                yield path


def violations(path):
    source = path.read_text()
    if len(source.splitlines()) > LIMIT:
        yield f"超过 {LIMIT} 行，请按职责拆分"
    if path.is_relative_to(ROOT / "apps/web/src"):
        layer = path.relative_to(ROOT / "apps/web/src").parts[0]
        if layer in {"api", "ui", "composables", "utils"} and re.search(
            r"['\"]@/(features|app)/", source
        ):
            yield "公共前端模块不得依赖业务组件或应用布局"
    if path.suffix != ".py" or "core" not in path.parts:
        return
    http_entry = path.stem in {"views", "urls"} or path.stem.endswith("_views")
    public_layer = path.parent.name in {"common", "storage"}
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.ImportFrom) or not node.module:
            continue
        if not http_entry and (node.module.endswith(".views") or node.module.endswith("_views")):
            yield f"第 {node.lineno} 行反向依赖视图 {node.module}"
        if (
            public_layer
            and node.module.startswith("core.")
            and not node.module.startswith(("core.common.", "core.storage."))
        ):
            yield f"第 {node.lineno} 行公共层依赖业务模块 {node.module}"


def main():
    failures = [
        f"{path.relative_to(ROOT)}: {message}"
        for path in sorted(runtime_files())
        for message in violations(path)
    ]
    if failures:
        raise SystemExit("\n".join(failures))
    print("分层与运行时代码文件长度检查通过（上限 400 行）。")


if __name__ == "__main__":
    main()

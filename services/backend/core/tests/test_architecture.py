"""模块重组不得产生数据库迁移或改变业务接口入口。"""

from django.apps import apps
from django.db.migrations.autodetector import MigrationAutodetector
from django.db.migrations.loader import MigrationLoader
from django.db.migrations.state import ProjectState
from django.urls import resolve
from django.utils.translation import override


def test_model_packages_keep_existing_migration_state():
    # 与 makemigrations 一致，禁用翻译后比较惰性 verbose_name。
    with override(None):
        loader = MigrationLoader(None)
        changes = MigrationAutodetector(
            loader.project_state(), ProjectState.from_apps(apps)
        ).changes(graph=loader.graph)
    assert changes == {}
    for model in apps.get_app_config("core").get_models():
        assert model._meta.app_label == "core"
        assert model._meta.db_table == f"core_{model._meta.model_name}"


def test_domain_urls_keep_public_paths():
    project = "00000000-0000-0000-0000-000000000001"
    routes = {
        "/api/v1/auth/session/": "SessionView",
        "/api/v1/health/ready/": "ReadyView",
        "/api/v1/projects/": "ProjectListView",
        f"/api/v1/projects/{project}/manuscript/": "ManuscriptView",
        f"/api/v1/projects/{project}/reading/tasks/": "ReadingTaskView",
        f"/api/v1/projects/{project}/cleanup/": "CleanupCreateView",
    }
    for path, expected in routes.items():
        assert resolve(path).func.view_class.__name__ == expected

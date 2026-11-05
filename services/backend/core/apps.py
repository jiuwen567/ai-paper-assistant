from django.apps import AppConfig


class CoreConfig(AppConfig):
    name = "core"

    def ready(self):
        from django.db.models.signals import pre_delete

        from core.graph import project_deleting
        from core.models import Project

        pre_delete.connect(project_deleting, sender=Project, dispatch_uid="graph_project_deleting")

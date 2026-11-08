from rest_framework import serializers

from core.models import Project, ProjectMember, ProjectPolicy
from core.projects.access import AI_ACTIONS, project_role


class LoginSerializer(serializers.Serializer):
    username = serializers.CharField(max_length=150)
    password = serializers.CharField(max_length=1024, trim_whitespace=False, write_only=True)


class PolicySerializer(serializers.ModelSerializer):
    created_by = serializers.CharField(source="created_by.username", read_only=True)

    class Meta:
        model = ProjectPolicy
        fields = [
            "id",
            "version",
            "source",
            "source_version",
            "notes",
            "verified",
            "allowed_actions",
            "created_by",
            "created_at",
        ]
        read_only_fields = fields


class ProjectSerializer(serializers.ModelSerializer):
    role = serializers.SerializerMethodField()
    is_owner = serializers.SerializerMethodField()
    policy = serializers.SerializerMethodField()
    owner_name = serializers.CharField(source="owner.username", read_only=True)

    class Meta:
        model = Project
        fields = [
            "id",
            "name",
            "paper_type",
            "requirements",
            "template",
            "version",
            "created_at",
            "updated_at",
            "role",
            "is_owner",
            "owner_name",
            "policy",
        ]
        read_only_fields = fields

    def get_role(self, obj):
        return project_role(self.context["request"].user, obj)

    def get_is_owner(self, obj):
        return obj.owner_id == self.context["request"].user.pk

    def get_policy(self, obj):
        return PolicySerializer(obj.policies.order_by("-version").first()).data


class ProjectInputSerializer(serializers.ModelSerializer):
    template = serializers.ChoiceField(
        choices=["department-default"], allow_blank=True, required=False
    )

    class Meta:
        model = Project
        fields = ["name", "paper_type", "requirements", "template"]
        extra_kwargs = {"requirements": {"max_length": 20000}}


class VersionSerializer(serializers.Serializer):
    version = serializers.IntegerField(min_value=1)


class PolicyInputSerializer(VersionSerializer):
    source = serializers.CharField(max_length=500, allow_blank=True)
    source_version = serializers.CharField(max_length=120, allow_blank=True)
    notes = serializers.CharField(max_length=20000, allow_blank=True)
    verified = serializers.BooleanField()
    allowed_actions = serializers.ListField(
        child=serializers.ChoiceField(choices=list(AI_ACTIONS)), max_length=len(AI_ACTIONS)
    )

    def validate(self, attrs):
        if attrs["verified"] and (not attrs["source"] or not attrs["source_version"]):
            raise serializers.ValidationError("核对规则时必须填写规则来源和来源版本。")
        if not attrs["verified"] and attrs["allowed_actions"]:
            raise serializers.ValidationError("规则未核对，不能启用 AI 辅助。")
        attrs["allowed_actions"] = sorted(set(attrs["allowed_actions"]))
        return attrs


class MemberInputSerializer(VersionSerializer):
    username = serializers.CharField(max_length=150)
    role = serializers.ChoiceField(choices=ProjectMember.Role.choices)


class MemberSerializer(serializers.ModelSerializer):
    username = serializers.CharField(source="user.username")

    class Meta:
        model = ProjectMember
        fields = ["user_id", "username", "role"]


class AIActionSerializer(serializers.Serializer):
    action = serializers.ChoiceField(choices=list(AI_ACTIONS))
    policy_version = serializers.IntegerField(min_value=1)

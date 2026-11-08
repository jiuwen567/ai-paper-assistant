from rest_framework import serializers

from core.models import Job, JobAttempt
from core.projects.access import AI_ACTIONS


class SampleInputSerializer(serializers.Serializer):
    text = serializers.CharField(max_length=10000)
    source_version = serializers.IntegerField(min_value=1)
    steps = serializers.IntegerField(min_value=1, max_value=10, default=3)


class JobInputSerializer(serializers.Serializer):
    kind = serializers.ChoiceField(choices=["sample"])
    idempotency_key = serializers.CharField(max_length=128)
    input_snapshot = SampleInputSerializer()
    ai_action = serializers.ChoiceField(choices=["", *AI_ACTIONS], default="")
    policy_version = serializers.IntegerField(min_value=1)


class AttemptSerializer(serializers.ModelSerializer):
    class Meta:
        model = JobAttempt
        fields = [
            "generation",
            "started_at",
            "finished_at",
            "status",
            "error_code",
            "error_message",
        ]


class JobSerializer(serializers.ModelSerializer):
    attempts = AttemptSerializer(many=True, read_only=True)

    class Meta:
        model = Job
        fields = [
            "id",
            "kind",
            "input_snapshot",
            "ai_action",
            "policy_version",
            "status",
            "generation",
            "lease_until",
            "progress",
            "retryable",
            "error_code",
            "error_message",
            "output",
            "created_at",
            "updated_at",
            "attempts",
        ]

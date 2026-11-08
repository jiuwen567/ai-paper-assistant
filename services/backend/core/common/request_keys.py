import json

from core.common.digests import digest


def fingerprint(data):
    return digest(json.loads(json.dumps(data, default=str)))

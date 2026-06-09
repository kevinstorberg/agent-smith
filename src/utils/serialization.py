import json
import uuid
from datetime import datetime


class _Encoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, datetime):
            return obj.isoformat()
        if isinstance(obj, uuid.UUID):
            return str(obj)
        return super().default(obj)


def serialize_json(data: dict) -> str:
    return json.dumps(data, cls=_Encoder)

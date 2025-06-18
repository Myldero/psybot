from mongoengine import Document, StringField, BooleanField, LongField, DictField, ListField


class Ctf(Document):
    name = StringField(required=True)
    channel_id = LongField(required=True)
    role_id = LongField(required=True)
    info = DictField(required=False)
    info_id = LongField(required=True)
    private = BooleanField(required=True)
    archived = BooleanField(required=True, default=False)
    voice_channels = ListField(LongField(), default=[])
    meta = {
        'indexes': [
            {
                'fields': ['channel_id'],
                'unique': True
            }
        ]
    }

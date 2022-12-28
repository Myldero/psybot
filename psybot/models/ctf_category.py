from mongoengine import Document, StringField, IntField, LongField


class CtfCategory(Document):
    name = StringField(required=True)
    count = IntField(required=True)
    guild_id = LongField(required=True)
    meta = {
        'indexes': [
            {
                'fields': ['name', 'guild_id'],
                'unique': True
            }
        ]
    }

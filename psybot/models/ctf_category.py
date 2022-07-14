from mongoengine import Document, StringField, IntField


class CtfCategory(Document):
    name = StringField(required=True, unique=True)
    count = IntField(required=True)

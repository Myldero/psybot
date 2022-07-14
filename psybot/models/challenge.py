from mongoengine import Document, StringField, IntField, BooleanField, ListField, ReferenceField, LongField
from psybot.models.ctf import Ctf


class Challenge(Document):
    name = StringField(required=True)
    channel_id = LongField(required=True)
    category = StringField(required=True)
    ctf = ReferenceField(Ctf, required=True)
    solvers = ListField(LongField(), default=[])
    working_on = ListField(LongField(), default=[])
    solved = BooleanField(required=True, default=False)

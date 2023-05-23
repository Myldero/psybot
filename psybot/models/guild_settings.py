from mongoengine import Document, LongField, StringField, BooleanField


class GuildSettings(Document):
    guild_id = LongField(required=True)
    team_role = LongField(required=True)
    admin_role = LongField(required=True)
    ctfs_category = LongField(required=True)
    incomplete_category = LongField(required=True)
    complete_category = LongField(required=True)
    archive_category = LongField(required=True)
    ctf_archive_category = LongField(required=True)
    export_channel = LongField(required=True)
    enforce_categories = BooleanField(default=True)
    send_work_message = BooleanField(default=True)
    use_team_role_as_acl = BooleanField(default=False)
    hedgedoc_url = StringField(required=True, max_length=100, default="https://demo.hedgedoc.org")
    ctftime_team = StringField(max_length=50)
    meta = {
        'indexes': [
            {
                'fields': ['guild_id'],
                'unique': True
            }
        ]
    }

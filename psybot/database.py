from psybot.config import config

from mongoengine import connect

client = connect(db=config.mongodb_db, host=config.mongodb_uri)
db = client[config.mongodb_db]


def create_indexes():
    db.ctf.create_index('channel_id', unique=True)

    db.challenge.create_index('channel_id', unique=True)
    db.challenge.create_index('ctf_id')

    db.backup_category.create_index('category_id', unique=True)
    db.backup_category.create_index('original_id')

    db.ctf_category.create_index('name', unique=True)

    db.discord_ids.create_index('guild_id', unique=True)

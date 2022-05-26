from psybot import db


async def create_indexes():
    await db.ctf.create_index('channel_id', unique=True)

    await db.challenge.create_index('channel_id', unique=True)
    await db.challenge.create_index('ctf_id')

    await db.backup_category.create_index('category_id', unique=True)
    await db.backup_category.create_index('original_id')


def create_from_fiskebot():
    # TODO: Create migration from fiskebot
    pass

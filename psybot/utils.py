import discord

from database import db


MAX_CHANNELS = 500
CATEGORY_MAX_CHANNELS = 50


def get_category_pos(category_channel: discord.CategoryChannel, name: str):
    ctf, category, _ = name.split("-")
    same_category_channel = None
    same_ctf_channel = None
    for channel in category_channel.text_channels:
        if channel.name.startswith(f"{ctf}-"):
            same_ctf_channel = channel
        if channel.name.startswith(f"{ctf}-{category}-"):
            same_category_channel = channel

    if same_category_channel:
        return same_category_channel.position
    elif same_ctf_channel:
        return same_ctf_channel.position + 1
    elif category_channel.text_channels:
        ctf_pos = category_channel.text_channels[-1].position // 1000 + 1
        return ctf_pos * 1000
    else:
        return 0


async def get_backup_category(original_category: discord.CategoryChannel):
    backups = []
    async for cat in db.backup_category.find({'original_id': original_category.id}).sort('index', 1):
        backups.append(cat)
        category = original_category.guild.get_channel(cat['category_id'])
        if len(category.channels) < CATEGORY_MAX_CHANNELS:
            return category
    idx = 2 if not backups else backups[-1]['index']+1
    new_category = await original_category.guild.create_category(f"{original_category.name} {idx}", position=original_category.position)
    await db.backup_category.insert_one({'original_id': original_category.id, 'category_id': new_category.id, 'index': idx})
    return new_category


async def free_backup_category(category: discord.CategoryChannel):
    if len(category.channels) == 0:
        backup_category = await db.backup_category.find_one({'category_id': category.id})
        if backup_category is not None:
            await db.backup_category.delete_one({'category_id': category.id})
            await category.delete(reason="Removing unused backup category")


async def delete_channel(channel: discord.TextChannel):
    original_category = channel.category
    await channel.delete(reason="Deleted CTF channels")
    await free_backup_category(original_category)


async def create_channel(name: str, overwrites: dict, category: discord.CategoryChannel, challenge=True):
    if len(category.channels) == CATEGORY_MAX_CHANNELS:
        category = await get_backup_category(category)

    if challenge:
        pos = get_category_pos(category, name)
        return await category.create_text_channel(name, overwrites=overwrites, position=pos)
    else:
        return await category.create_text_channel(name, overwrites=overwrites)


async def move_channel(channel: discord.TextChannel, goal_category: discord.CategoryChannel, challenge=True):
    if goal_category == channel.category:
        return
    if len(goal_category.channels) == CATEGORY_MAX_CHANNELS:
        goal_category = await get_backup_category(goal_category)

    original_category = channel.category

    if challenge:
        pos = get_category_pos(goal_category, channel.name)
        await channel.edit(category=goal_category, position=pos)
    else:
        await channel.edit(category=goal_category)

    await free_backup_category(original_category)

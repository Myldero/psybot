import asyncio
import sys

import discord
import pymongo.errors
from discord import app_commands

import ctf, ctftime, challenge, notes
from config import config
from database import db, create_indexes

intents = discord.Intents.all()

client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)

challenge.add_commands(tree)
ctf.add_commands(tree)
ctftime.add_commands(tree)
notes.add_commands(tree)


@client.event
async def setup_hook():
    client.add_view(notes.ModalNoteView())
    client.add_view(notes.HedgeDocNoteView(""))


@client.event
async def on_ready():
    try:
        await db.command("ping")
    except pymongo.errors.ServerSelectionTimeoutError:
        print("Could not connect to MongoDB", file=sys.stderr)
        exit(1)
    await create_indexes()
    await config.setup_discord_ids(client.get_guild(config.guild_id), db)
    await tree.sync(guild=discord.Object(config.guild_id))
    # await tree.sync()  # Syncing global commands
    print(f"{client.user.name} Online")


async def main():
    async with client:
        await client.start(config.bot_token)


if __name__ == '__main__':
    asyncio.run(main())

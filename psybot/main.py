import asyncio
import discord
from discord import app_commands

from psybot import ctf, ctftime, challenge, notes
from psybot.config import config
from psybot.database import db

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
    await config.setup_discord_ids(client.get_guild(config.guild_id), db)
    await tree.sync(guild=discord.Object(config.guild_id))
    # await tree.sync()  # Syncing global commands
    print(f"{client.user.name} Online")

    guild = client.get_guild(config.guild_id)
    channel = guild.get_channel(config.export_channel)


async def main():
    async with client:
        await client.start(config.bot_token)

asyncio.run(main())

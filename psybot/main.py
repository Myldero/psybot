import asyncio
import logging
import pymongo.errors
import discord

from discord import app_commands

from psybot.modules import ctf, ctftime, challenge, notes, psybot
from psybot.config import config
from psybot.database import db
from psybot.utils import setup_settings

logging.basicConfig(level=logging.INFO)

intents = discord.Intents.all()

client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)

guild_obj = discord.Object(id=config.guild_id) if config.guild_id else None
challenge.add_commands(tree, guild_obj)
ctf.add_commands(tree, guild_obj)
ctftime.add_commands(tree, guild_obj)
notes.add_commands(tree, guild_obj)
psybot.add_commands(tree, guild_obj)


@client.event
async def setup_hook():
    client.add_view(notes.ModalNoteView())
    client.add_view(notes.HedgeDocNoteView(""))
    client.add_view(challenge.WorkView())
    client.add_view(ctf.ResponseView())
    client.add_dynamic_items(ctf.RequestButton)


@client.event
async def on_ready():
    try:
        db.command("ping")
    except pymongo.errors.ServerSelectionTimeoutError:
        logging.critical("Could not connect to MongoDB")
        exit(1)
    if config.guild_id:
        guild = client.get_guild(config.guild_id)
        if guild:
            await setup_settings(guild)
            await tree.sync(guild=guild_obj)
    else:
        for guild in client.guilds:
            await setup_settings(guild)
        await tree.sync()
    logging.info(f"{client.user.name} Online")


@client.event
async def on_guild_join(guild: discord.Guild):
    if config.guild_id is None or config.guild_id == guild.id:
        logging.info(f"{client.user.name} has joined guild \"{guild.name}\"")
        await setup_settings(guild)
        if config.guild_id:
            await tree.sync(guild=guild_obj)


@tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    async def send_response(message):
        if interaction.response.is_done():
            await interaction.edit_original_response(content=message)
        else:
            await interaction.response.send_message(message, ephemeral=True)
    try:
        raise error
    except app_commands.CommandInvokeError as e:
        try:
            raise e.original
        except AssertionError:
            await send_response("An assertion failed when running this command")
            raise
        except Exception:
            await send_response("An error occurred when running this command")
            raise
    except app_commands.AppCommandError:
        if error.args:
            await send_response(error.args[0])


async def main():
    async with client:
        await client.start(config.bot_token)


if __name__ == '__main__':
    asyncio.run(main())

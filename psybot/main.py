import asyncio
import discord
from discord import app_commands

from psybot import ctf
from psybot import ctftime
from psybot import challenge
from psybot import GUILD_ID, BOT_TOKEN

intents = discord.Intents.all()

client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)

challenge.add_commands(tree)
ctf.add_commands(tree)
ctftime.add_commands(tree)


@client.event
async def on_ready():
    await tree.sync(guild=discord.Object(GUILD_ID))
    # await tree.sync()  # Syncing global commands
    print(f"{client.user.name} Online")


async def main():
    async with client:
        await client.start(BOT_TOKEN)

asyncio.run(main())

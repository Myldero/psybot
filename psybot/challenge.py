import re
from typing import Optional

from discord import app_commands
import discord
from psybot import GUILD_ID, INCOMPLETE_CATEGORY, COMPLETE_CATEGORY, db
from psybot.utils import move_channel


async def check_challenge(interaction: discord.Interaction):
    chall_db = await db.challenge.find_one({'channel_id': interaction.channel.id})

    if chall_db is None or not isinstance(interaction.channel, discord.TextChannel):
        await interaction.response.send_message("Not a challenge!", ephemeral=True)
        return None, None
    ctf_db = await db.ctf.find_one({'_id': chall_db['ctf_id']})
    if ctf_db.get('archived'):
        await interaction.response.send_message("This CTF is archived!", ephemeral=True)
        return None, None
    return chall_db, ctf_db


@app_commands.command(description="Marks a challenge as done")
async def done(interaction: discord.Interaction, contributors: Optional[str]):
    chall_db, ctf_db = await check_challenge(interaction)
    if chall_db is None or not isinstance(interaction.channel, discord.TextChannel):
        return

    users = chall_db.get('contributors') if chall_db.get('contributors') else []
    if interaction.user.id not in users:
        users.append(interaction.user.id)
    if contributors is not None:
        for user in [int(i) for i in re.findall(r'<@!?(\d+)>', contributors)]:
            if user not in users:
                users.append(user)

    await db.challenge.update_one({'_id': chall_db['_id']}, {'$set': {'contributors': users}})

    await move_channel(interaction.channel, interaction.guild.get_channel(COMPLETE_CATEGORY))

    msg = "{} was solved by ".format(interaction.channel.mention) + " ".join(f"<@!{user}>" for user in users) + " !"
    await interaction.guild.get_channel(ctf_db['channel_id']).send(msg)
    await interaction.response.send_message("Challenge moved to done!")


@app_commands.command(description="Marks a challenge as undone")
async def undone(interaction: discord.Interaction):
    chall_db, ctf_db = await check_challenge(interaction)
    if chall_db is None or not isinstance(interaction.channel, discord.TextChannel):
        return

    if not chall_db.get('contributors'):
        await interaction.response.send_message("This challenge is already undone!", ephemeral=True)
        return

    await db.challenge.update_one({'channel_id': interaction.channel.id}, {'$unset': {'contributors': 1}})

    await move_channel(interaction.channel, interaction.guild.get_channel(INCOMPLETE_CATEGORY))

    await interaction.response.send_message("Reopened challenge as not done")


def add_commands(tree: app_commands.CommandTree):
    tree.add_command(done, guild=discord.Object(id=GUILD_ID))
    tree.add_command(undone, guild=discord.Object(id=GUILD_ID))

import os
import random
import re
import string
from typing import Optional, Tuple

from discord import app_commands
import discord
from pymongo.errors import DuplicateKeyError
import pandas as pd
import dataframe_image as dfi

from psybot.config import config
from psybot.models.ctf_category import CtfCategory
from psybot.utils import move_channel
from psybot.modules.ctf import category_autocomplete, get_ctf_db

from psybot.models.challenge import Challenge, Working
from psybot.models.ctf import Ctf


async def check_challenge(interaction: discord.Interaction) -> Tuple[Optional[Challenge], Optional[Ctf]]:
    chall_db: Challenge = Challenge.objects(channel_id=interaction.channel.id).first()
    if chall_db is None or not isinstance(interaction.channel, discord.TextChannel):
        await interaction.response.send_message("Not a challenge!", ephemeral=True)
        return None, None
    ctf_db: Ctf = chall_db.ctf
    if ctf_db.archived:
        await interaction.response.send_message("This CTF is archived!", ephemeral=True)
        return None, None
    return chall_db, ctf_db


@app_commands.command(description="Marks a challenge as done")
async def done(interaction: discord.Interaction, contributors: Optional[str]):
    chall_db, ctf_db = await check_challenge(interaction)
    if chall_db is None or not isinstance(interaction.channel, discord.TextChannel):
        return

    users = chall_db.solvers
    if interaction.user.id not in users:
        users.append(interaction.user.id)
    if contributors is not None:
        for user in [int(i) for i in re.findall(r'<@!?(\d+)>', contributors)]:
            if user not in users:
                users.append(user)

    chall_db.solvers = users
    chall_db.solved = True
    chall_db.save()

    await move_channel(interaction.channel, interaction.guild.get_channel(config.complete_category))

    msg = ":tada: {} was solved by ".format(interaction.channel.mention) + " ".join(f"<@!{user}>" for user in users) + " !"
    await interaction.guild.get_channel(ctf_db.channel_id).send(msg)
    await interaction.response.send_message("Challenge moved to done!")


@app_commands.command(description="Marks a challenge as undone")
async def undone(interaction: discord.Interaction):
    chall_db, ctf_db = await check_challenge(interaction)
    if chall_db is None or not isinstance(interaction.channel, discord.TextChannel):
        return

    if not chall_db.solved:
        await interaction.response.send_message("This challenge is not done yet!", ephemeral=True)
        return

    chall_db.solvers = []
    chall_db.solved = False
    chall_db.save()

    await move_channel(interaction.channel, interaction.guild.get_channel(config.incomplete_category))
    await interaction.response.send_message("Reopened challenge as not done")


class CategoryCommands(app_commands.Group):

    @app_commands.command(description="Create CTF category suggestion")
    async def create(self, interaction: discord.Interaction, category: str):
        try:
            ctf_category = CtfCategory(name=category, count=5)
            ctf_category.save()
        except DuplicateKeyError:
            await interaction.response.send_message("CTF category already exists", ephemeral=True)
        else:
            await interaction.response.send_message("Created CTF category", ephemeral=True)

    @app_commands.command(description="Delete CTF category suggestion")
    @app_commands.autocomplete(category=category_autocomplete)
    async def delete(self, interaction: discord.Interaction, category: str):
        if not interaction.guild.get_role(config.admin_role) in interaction.user.roles:
            await interaction.response.send_message("Only an admin can delete categories", ephemeral=True)
            return
        ctf_category: CtfCategory = CtfCategory.objects(name=category).first()
        if ctf_category is None:
            await interaction.response.send_message("Unknown CTF category", ephemeral=True)
        else:
            ctf_category.delete()
            await interaction.response.send_message("Deleted CTF category", ephemeral=True)


working_names = ["None", "Seen", "Worked", "Much Work"]
working_colors = [("ffffff", "000000"), ("b4c4df", "000000"), ("2685bb", "f1f1f1"), ("023858", "f1f1f1")]


def set_style(a):
    return ['background-color: #{}; color: #{}'.format(*working_colors[i if i else 0]) for i in a]


class WorkingCommands(app_commands.Group):
    @app_commands.command(description="Set working status on the challenge")
    @app_commands.choices(value=[app_commands.Choice(name=name, value=i) for i, name in enumerate(working_names)])
    async def set(self, interaction: discord.Interaction, value: int, user: Optional[discord.Member]):
        chall_db, ctf_db = await check_challenge(interaction)
        if chall_db is None or not isinstance(interaction.channel, discord.TextChannel):
            return
        if user is None:
            user = interaction.user

        if value == 0:
            chall_db.working.filter(user=user.id).delete()
        else:
            work = chall_db.working.filter(user=user.id).first()
            if work is None:
                work = chall_db.working.create(user=user.id, value=value)
            work.value = value
        chall_db.save()
        await interaction.response.send_message(f"Updated working status to {working_names[value]}", ephemeral=True)

    @app_commands.command(description="Get list of people working on the challenge")
    async def get(self, interaction: discord.Interaction):
        chall_db, ctf_db = await check_challenge(interaction)
        if chall_db is None or not isinstance(interaction.channel, discord.TextChannel):
            return
        out = ""
        for work in sorted(chall_db.working, key=lambda x: -x.value):
            user = interaction.guild.get_member(work.user)
            out += f"{user.mention} {working_names[work.value]} ({work.value})\n"

        await interaction.response.send_message(out if out else "Nobody is working on this", ephemeral=True,
                                                allowed_mentions=discord.AllowedMentions.none())

    @app_commands.command(description="Get table of all work on challenges")
    async def table(self, interaction: discord.Interaction):
        if not (ctf_db := await get_ctf_db(interaction, archived=None)) or not isinstance(interaction.channel, discord.TextChannel):
            return
        challs = sorted(Challenge.objects(ctf=ctf_db), key=lambda x: (x.category, x.name))
        tbl = {}
        for i, chall in enumerate(challs):
            for work in chall.working:
                user = interaction.guild.get_member(work.user)
                nm = f"{user.name}"
                if nm not in tbl:
                    tbl[nm] = [''] * len(challs)
                tbl[nm][i] = work.value

        if not tbl:
            await interaction.response.send_message("No work has been done on any challenges yet", ephemeral=True)
            return

        df = pd.DataFrame(tbl, [chall.category + "-" + chall.name for chall in challs])
        df_styled = df.style.apply(set_style)
        # df_styled = df.style.background_gradient(vmin=0, vmax=len(working_names)-1)
        filename = '/tmp/{}.png'.format(random.choice(string.ascii_letters) for _ in range(10))
        dfi.export(df_styled, filename)
        await interaction.response.send_message(file=discord.File(filename, filename='overview.png'), ephemeral=True)
        os.remove(filename)


def add_commands(tree: app_commands.CommandTree):
    tree.add_command(done, guild=discord.Object(id=config.guild_id))
    tree.add_command(undone, guild=discord.Object(id=config.guild_id))
    tree.add_command(CategoryCommands(name="category"), guild=discord.Object(id=config.guild_id))
    tree.add_command(WorkingCommands(name="working"), guild=discord.Object(id=config.guild_id))

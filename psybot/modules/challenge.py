import os
import random
import re
import string
from typing import Optional, Tuple

from discord import app_commands
import discord
from mongoengine import NotUniqueError
import matplotlib.pyplot as plt
from matplotlib.table import Table, Cell

from psybot.models.ctf_category import CtfCategory
from psybot.utils import move_channel, is_team_admin, get_incomplete_category, get_complete_category, sanitize_channel_name
from psybot.modules.ctf import category_autocomplete, get_ctf_db

from psybot.models.challenge import Challenge
from psybot.models.ctf import Ctf


async def check_challenge(interaction: discord.Interaction) -> Tuple[Optional[Challenge], Optional[Ctf]]:
    chall_db: Challenge = Challenge.objects(channel_id=interaction.channel_id).first()
    if chall_db is None:
        raise app_commands.AppCommandError("Not a challenge!")
    ctf_db: Ctf = chall_db.ctf
    if ctf_db.archived:
        raise app_commands.AppCommandError("This CTF is archived!")
    return chall_db, ctf_db


@app_commands.command(description="Marks a challenge as done")
@app_commands.guild_only
async def done(interaction: discord.Interaction, contributors: Optional[str]):
    chall_db, ctf_db = await check_challenge(interaction)
    assert isinstance(interaction.channel, discord.TextChannel)

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

    await move_channel(interaction.channel, get_complete_category(interaction.guild))

    msg = ":tada: {} was solved by ".format(interaction.channel.mention) + " ".join(f"<@!{user}>" for user in users) + " !"
    await interaction.guild.get_channel(ctf_db.channel_id).send(msg)
    await interaction.response.send_message("Challenge moved to done!")


@app_commands.command(description="Marks a challenge as undone")
@app_commands.guild_only
async def undone(interaction: discord.Interaction):
    chall_db, ctf_db = await check_challenge(interaction)
    assert isinstance(interaction.channel, discord.TextChannel)

    if not chall_db.solved:
        raise app_commands.AppCommandError("This challenge is not done yet!")

    chall_db.solvers = []
    chall_db.solved = False
    chall_db.save()

    await move_channel(interaction.channel, get_incomplete_category(interaction.guild))
    await interaction.response.send_message("Reopened challenge as not done")


class CategoryCommands(app_commands.Group):

    @app_commands.command(description="Create CTF category suggestion")
    @app_commands.guild_only
    async def create(self, interaction: discord.Interaction, category: str):
        category = sanitize_channel_name(category)
        try:
            ctf_category = CtfCategory(name=category, guild_id=interaction.guild_id, count=5)
            ctf_category.save()
        except NotUniqueError:
            await interaction.response.send_message("CTF category already exists", ephemeral=True)
        else:
            await interaction.response.send_message("Created CTF category", ephemeral=True)

    @app_commands.command(description="Delete CTF category suggestion")
    @app_commands.autocomplete(category=category_autocomplete)
    @app_commands.guild_only
    @app_commands.check(is_team_admin)
    async def delete(self, interaction: discord.Interaction, category: str):
        ctf_category: CtfCategory = CtfCategory.objects(name=category, guild_id=interaction.guild_id).first()
        if ctf_category is None:
            await interaction.response.send_message("Unknown CTF category", ephemeral=True)
        else:
            ctf_category.delete()
            await interaction.response.send_message("Deleted CTF category", ephemeral=True)


WORKING_NAMES = ["None", "Working", "Has Worked"]
WORKING_COLORS = ['#ffffff', '#00b618', '#ffab00']
CELL_HEIGHT = 35 / 77
CELL_WIDTH = 100 / 77


def export_table(solves: dict, challs: list, filename: str):
    height = len(challs)
    width = len(solves)

    fig, ax = plt.subplots(figsize=(width * CELL_WIDTH, height * CELL_HEIGHT))
    ax.axis('off')
    tbl = Table(ax, loc="center")

    def add_cell(r, c, text=None, color='w', loc='center', edges='closed'):
        tbl[r, c] = Cell((r, c), text=text, facecolor=color, edgecolor=color, width=1 / width, height=1 / height,
                         loc=loc, visible_edges=edges)

    for row, name in enumerate(challs):
        add_cell(row + 1, 0, text=name, loc='left')

    for col, name in enumerate(solves.keys()):
        add_cell(0, col + 1, text=name, edges='B', color='black')
        tbl[0, col + 1].auto_set_font_size(fig.canvas.get_renderer())
        for row, val in enumerate(solves[name]):
            color = WORKING_COLORS[val] if 0 <= val < len(WORKING_COLORS) else 'w'
            add_cell(row + 1, col + 1, color=color)
    tbl.auto_set_column_width(0)
    tbl.auto_set_font_size(False)
    ax.add_table(tbl)
    plt.savefig(filename, bbox_inches='tight', pad_inches=0)


@app_commands.command(description="Shortcut to set working status on the challenge")
@app_commands.guild_only
async def w(interaction: discord.Interaction):
    chall_db, ctf_db = await check_challenge(interaction)
    assert isinstance(interaction.channel, discord.TextChannel)

    user = interaction.user
    value = 1

    for chall in Challenge.objects(ctf=ctf_db):
        if chall.id == chall_db.id:
            continue
        work = chall.working.filter(user=user.id).first()
        if work is not None and work.value == 1:
            work.value = 2
            chall.working.save()
            chall.save()
    work = chall_db.working.filter(user=user.id).first()
    if work is None:
        work = chall_db.working.create(user=user.id, value=1)
    work.value = value
    chall_db.working.save()
    chall_db.save()
    await interaction.response.send_message(f"Updated working status to Working", ephemeral=True)


class WorkingCommands(app_commands.Group):
    @app_commands.command(description="Set working status on the challenge")
    @app_commands.choices(value=[app_commands.Choice(name=name, value=i) for i, name in enumerate(WORKING_NAMES)])
    @app_commands.guild_only
    async def set(self, interaction: discord.Interaction, value: int, user: Optional[discord.Member]):
        chall_db, ctf_db = await check_challenge(interaction)
        assert isinstance(interaction.channel, discord.TextChannel)

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
        await interaction.response.send_message(f"Updated working status to {WORKING_NAMES[value]}", ephemeral=True)

    @app_commands.command(description="Get list of people working on the challenge")
    @app_commands.guild_only
    async def get(self, interaction: discord.Interaction):
        chall_db, ctf_db = await check_challenge(interaction)
        assert isinstance(interaction.channel, discord.TextChannel)

        out = ""
        for work in sorted(chall_db.working, key=lambda x: -x.value):
            user = interaction.guild.get_member(work.user)
            out += f"{user.mention} {WORKING_NAMES[work.value]} ({work.value})\n"

        await interaction.response.send_message(out if out else "Nobody is working on this", ephemeral=True,
                                                allowed_mentions=discord.AllowedMentions.none())

    @app_commands.command(description="Get table of all work on challenges")
    @app_commands.choices(filter=[
        app_commands.Choice(name='all', value=0),
        app_commands.Choice(name='current', value=1)
    ])
    @app_commands.guild_only
    async def table(self, interaction: discord.Interaction, filter: int = 1):
        ctf_db = await get_ctf_db(interaction, archived=None)
        assert isinstance(interaction.channel, discord.TextChannel)

        await interaction.response.defer(ephemeral=True)
        if filter == 0:
            challs = Challenge.objects(ctf=ctf_db)
        else:
            challs = Challenge.objects(ctf=ctf_db, solved=False)
        challs = sorted(challs, key=lambda x: (x.category or '', x.name))
        tbl = {}
        for i, chall in enumerate(challs):
            for work in chall.working:
                user = interaction.guild.get_member(work.user)
                nm = f"{user.nick if user.nick else user.name}"
                if nm not in tbl:
                    tbl[nm] = [0] * len(challs)
                tbl[nm][i] = work.value

        if not tbl:
            await interaction.edit_original_response(content="No work has been done on any challenges yet")
            return

        filename = '/tmp/{}.png'.format(random.choice(string.ascii_letters) for _ in range(10))
        export_table(tbl, [(chall.category + "-" if chall.category else '') + chall.name for chall in challs], filename)
        await interaction.edit_original_response(attachments=[discord.File(filename, filename='overview.png')])
        os.remove(filename)


def add_commands(tree: app_commands.CommandTree, guild: Optional[discord.Object]):
    tree.add_command(done, guild=guild)
    tree.add_command(undone, guild=guild)
    tree.add_command(w, guild=guild)
    tree.add_command(CategoryCommands(name="category"), guild=guild)
    tree.add_command(WorkingCommands(name="working"), guild=guild)

import re
import time
from typing import Optional

from diff_match_patch import diff_match_patch
from discord import app_commands, ui
import discord
from psybot.config import config
from psybot.database import db
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

    await move_channel(interaction.channel, interaction.guild.get_channel(config.complete_category))

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

    await move_channel(interaction.channel, interaction.guild.get_channel(config.incomplete_category))

    await interaction.response.send_message("Reopened challenge as not done")


class NoteView(ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @ui.button(label="Edit", emoji="📝", style=discord.ButtonStyle.primary, custom_id='note:edit_note')
    async def edit_note(self, interaction: discord.Interaction, button: ui.Button):
        original = interaction.message.embeds[0].description

        class EditNoteModal(ui.Modal, title='Edit Note'):
            edit = ui.TextInput(label='Edit', style=discord.TextStyle.paragraph, default=original)

            async def on_submit(self, submit_interaction: discord.Interaction):
                dmp = diff_match_patch()
                diff = dmp.diff_main(self.edit.default, self.edit.value, True)
                patches = dmp.patch_make(self.edit.default, self.edit.value, diff)
                new_message = await interaction.message.fetch()
                result, success = dmp.patch_apply(patches, new_message.embeds[0].description)
                print(success)

                embed = new_message.embeds[0]
                embed.description = result
                await interaction.message.edit(embed=embed)
                await submit_interaction.response.defer()

        await interaction.response.send_modal(EditNoteModal())

    @ui.button(label="Pin/unpin me", emoji="📌", style=discord.ButtonStyle.secondary, custom_id='note:toggle_pin')
    async def toggle_pin(self, interaction: discord.Interaction, button: ui.Button):
        if interaction.message.pinned:
            await interaction.message.unpin()
        else:
            await interaction.message.pin()
        await interaction.response.edit_message()


@app_commands.command(description="Creates a new note")
async def note(interaction: discord.Interaction):
    await interaction.response.send_message(embed=discord.Embed(title="note", description="note goes here", colour=0x00FFFF),
                                            view=NoteView())


def add_commands(tree: app_commands.CommandTree):
    tree.add_command(done, guild=discord.Object(id=config.guild_id))
    tree.add_command(undone, guild=discord.Object(id=config.guild_id))
    tree.add_command(note, guild=discord.Object(id=config.guild_id))

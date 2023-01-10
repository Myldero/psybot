import datetime
import logging
from typing import Optional

import aiohttp
import discord
from diff_match_patch import diff_match_patch
from discord import app_commands, ui

from psybot.utils import get_settings

MODAL_NOTE_COLOR = 0x202222
HEDGEDOC_NOTE_COLOR = 0xA84300

class ModalNoteView(ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @ui.button(label="Edit", emoji="📝", style=discord.ButtonStyle.secondary, custom_id='modal_note:edit_note')
    async def edit_note(self, interaction: discord.Interaction, _button: ui.Button):
        original = interaction.message.embeds[0].description

        class EditNoteModal(ui.Modal, title='Edit Note'):
            edit = ui.TextInput(label='Edit', style=discord.TextStyle.paragraph, default=original)

            async def on_submit(self, submit_interaction: discord.Interaction):
                dmp = diff_match_patch()
                diff = dmp.diff_main(self.edit.default, self.edit.value, True)
                patches = dmp.patch_make(self.edit.default, self.edit.value, diff)
                new_message = await interaction.message.fetch()
                result, success = dmp.patch_apply(patches, new_message.embeds[0].description)

                await interaction.message.edit(embed=discord.Embed(title="note", description=result, color=MODAL_NOTE_COLOR, timestamp=datetime.datetime.now()))
                await submit_interaction.response.defer()

        await interaction.response.send_modal(EditNoteModal())

    @ui.button(label="Pin/Unpin", emoji="📌", style=discord.ButtonStyle.secondary, custom_id='modal_note:toggle_pin')
    async def toggle_pin(self, interaction: discord.Interaction, _button: ui.Button):
        if interaction.message.pinned:
            await interaction.message.unpin()
        else:
            await interaction.message.pin()
        await interaction.response.defer()

    @ui.button(label="Move Down", emoji="⏬", style=discord.ButtonStyle.secondary, custom_id='modal_note:move_down')
    async def move_down(self, interaction: discord.Interaction, _button: ui.Button):
        is_pinned = interaction.message.pinned
        embeds = interaction.message.embeds
        await interaction.message.delete()
        new_message = await interaction.channel.send(embeds=embeds, view=ModalNoteView())
        if is_pinned:
            await new_message.pin()


class HedgeDocNoteView(ui.View):
    def __init__(self, url):
        super().__init__(timeout=None)
        children = self.children
        self.clear_items()
        self.add_item(ui.Button(label="Edit", emoji="📝", style=discord.ButtonStyle.secondary, url=url))
        for i in children:
            self.add_item(i)

    @ui.button(label="Update", emoji="⌛", style=discord.ButtonStyle.secondary, custom_id='hedgedoc_note:update')
    async def update(self, interaction: discord.Interaction, _button: ui.Button):
        await interaction.response.defer()
        url = interaction.message.components[0].children[0].url.replace("?edit", "")
        async with aiohttp.ClientSession() as session:
            async with session.get(url + "/download") as response:
                if response.status != 200:
                    logging.warning("Something went wrong when downloading")
                    return
                new_description = (await response.text())[:4096]

                await interaction.message.edit(embed=discord.Embed(title="note", description=new_description, color=HEDGEDOC_NOTE_COLOR, timestamp=datetime.datetime.now()))

    @ui.button(label="Pin/Unpin", emoji="📌", style=discord.ButtonStyle.secondary, custom_id='hedgedoc_note:toggle_pin')
    async def toggle_pin(self, interaction: discord.Interaction, _button: ui.Button):
        if interaction.message.pinned:
            await interaction.message.unpin()
        else:
            await interaction.message.pin()
        await interaction.response.defer()

    @ui.button(label="Move Down", emoji="⏬", style=discord.ButtonStyle.secondary, custom_id='hedgedoc_note:move_down')
    async def move_down(self, interaction: discord.Interaction, _button: ui.Button):
        is_pinned = interaction.message.pinned
        embeds = interaction.message.embeds
        url = interaction.message.components[0].children[0].url
        await interaction.message.delete()
        new_message = await interaction.channel.send(embeds=embeds, view=HedgeDocNoteView(url))
        if is_pinned:
            await new_message.pin()


@app_commands.command(description="Creates a new note")
@app_commands.choices(type=[
    app_commands.Choice(name="modal", value="modal"),
    app_commands.Choice(name="doc", value="doc")
])
async def note(interaction: discord.Interaction, type: str = "doc"):
    if type == "modal":
        await interaction.response.send_message(embed=discord.Embed(title="note", description="note goes here", color=MODAL_NOTE_COLOR, timestamp=datetime.datetime.now()),
                                            view=ModalNoteView())
    elif type == "doc":
        await interaction.response.defer()
        hedgedoc_url = "https://demo.hedgedoc.org"
        if interaction.guild is not None:
            settings = get_settings(interaction.guild)
            if settings.hedgedoc_url:
                hedgedoc_url = settings.hedgedoc_url

        async with aiohttp.ClientSession() as session:
            async with session.get(hedgedoc_url + "/new") as response:
                if response.status != 200:
                    await interaction.edit_original_response(content="Could not create a HedgeDoc note")
                    return
                await interaction.edit_original_response(embed=discord.Embed(title="note", description="", color=HEDGEDOC_NOTE_COLOR, timestamp=datetime.datetime.now()),
                                                    view=HedgeDocNoteView(str(response.url) + "?edit"))


def add_commands(tree: app_commands.CommandTree, guild: Optional[discord.Object]):
    tree.add_command(note, guild=guild)

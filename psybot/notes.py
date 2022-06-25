import aiohttp
import discord
from diff_match_patch import diff_match_patch
from discord import app_commands, ui

from config import config


class ModalNoteView(ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @ui.button(label="Edit", emoji="📝", style=discord.ButtonStyle.secondary, custom_id='modal_note:edit_note')
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

                await interaction.message.delete()
                await interaction.channel.send(
                    embed=discord.Embed(title="note", description=result, colour=0x00FFFF),
                    view=ModalNoteView())
                await submit_interaction.response.defer()

        await interaction.response.send_modal(EditNoteModal())


HEDGEDOC_URL = "https://demo.hedgedoc.org"


class HedgeDocNoteView(ui.View):
    def __init__(self, url):
        super().__init__(timeout=None)
        children = self.children
        self.clear_items()
        self.add_item(ui.Button(label="Edit", emoji="📝", style=discord.ButtonStyle.secondary, url=url))
        self.add_item(children[0])

    @ui.button(label="Update", emoji="⌛", style=discord.ButtonStyle.secondary, custom_id='hedgedoc_note:update')
    async def update(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.defer()
        url = interaction.message.components[0].children[0].url.replace("?edit", "")
        async with aiohttp.ClientSession() as session:
            async with session.get(url + "/download") as response:
                if response.status != 200:
                    print("Something went wrong when downloading")
                    return
                new_description = (await response.text())[:4096]

                await interaction.message.delete()
                await interaction.channel.send(
                    embed=discord.Embed(title="note", description=new_description, colour=0x00FFFF),
                    view=HedgeDocNoteView(url + "?edit"))


@app_commands.command(description="Creates a new note")
@app_commands.choices(type=[
    app_commands.Choice(name="modal", value="modal"),
    app_commands.Choice(name="doc", value="doc")
])
async def note(interaction: discord.Interaction, type: str = "doc"):
    if type == "modal":
        await interaction.response.send_message(embed=discord.Embed(title="note", description="note goes here", colour=0x00FFFF),
                                            view=ModalNoteView())
    elif type == "doc":
        await interaction.response.defer()
        async with aiohttp.ClientSession() as session:
            async with session.get(HEDGEDOC_URL + "/new") as response:
                if response.status != 200:
                    await interaction.edit_original_message(content="Could not create a HedgeDoc note")
                    return
                await interaction.edit_original_message(embed=discord.Embed(title="note", description="", colour=0x00FFFF),
                                                    view=HedgeDocNoteView(str(response.url) + "?edit"))


def add_commands(tree: app_commands.CommandTree):
    tree.add_command(note, guild=discord.Object(id=config.guild_id))

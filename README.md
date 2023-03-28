# PsyBot
A discord bot that provides tools for collaboration in CTFs. Inspired by [fiskebot](https://github.com/ekofiskctf/fiskebot)

## Features
* Create a CTF with `/ctf create <name> [ctftime_link]`. When a CTFTime link is supplied, most information is automatically entered. <br />
  When `private` is set, team members are not automatically added to the CTF and will have to be invited with the `/invite` command.
* Create categories to be used with challenges using `/category create <name>`
* Create channels for individual challenges with `/add <category> <name>`
* Set working status on a challenge using the button in the channel, with `/working set Working` or the shortcut `/w`
* `/working table` to see who is working on which challenges
* Mark a challenge as done with `/done [contributors]`
* `/note` to create a note that can be edited by multiple people using HedgeDoc.
* `/note modal` to create a note that can be edited from within discord. Simultaneous changes will be merged together using diff-match-patch. 
* `/ctf archive` to archive old ctfs
* `/ctf export` to save all the channels of a ctf as a json file. <br />
  Use in conjunction with `/ctf delete` to free up channels when reaching the 500 channel limit.
* `/ctftime team` to see your team's top 10 CTFs. <br />
  Set your team name with `/psybot set key:ctftime_team value:kalmarunionen`
## Installation
First, you need to create a bot on https://discord.com/developers/applications. \
Then invite it with the following link, replacing `CLIENT_ID` with your actual id:
https://discord.com/api/oauth2/authorize?client_id=CLIENT_ID&permissions=8&scope=bot%20applications.commands

### With `docker-compose`
Create a `.env` file like this:
```
BOT_TOKEN=token
GUILD_ID=optional_guild_id
```
Create the backups directory
```sh
mkdir ./backups; chown 1000:1000 ./backups
```
Then run `docker-compose up -d`

### Manually
Install dependencies with pip
```sh
python3 -m pip install -r requirements.txt
```
Install MongoDB and set it up. \
Set up `BOT_TOKEN` and optionally `GUILD_ID` environment variables.

Run the script
```sh
./bot.py
```

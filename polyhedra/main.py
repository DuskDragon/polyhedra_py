from idleiss.core import GameEngine
import time
import bisect

#import argparse
#import os
import json
#import random

import discord
from discord.ext import tasks
import logging
import asyncio

heartbeat_step = 300 #seconds, minute aligned UTC timestamp aligned. Min = 120

#bisect tools
def index(a, x):
    'Locate the leftmost value in sorted list a exactly equal to x'
    i = bisect.bisect_left(a, x)
    if i != len(a) and a[i] == x:
        return i
    return None

def is_present(a, x):
    'Return if sorted list a contains x'
    i = bisect.bisect_left(a, x)
    if i != len(a) and a[i] == x:
        return True
    return False

class Admin_Panel(discord.ui.View):
    def __init__(self, interaction):
        self.selection = None
        self.interaction = interaction
        super().__init__(timeout=None)

    @discord.ui.button(style=discord.ButtonStyle.green, label='Standard', custom_id='standard')
    async def select_standard(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.selection != None:
            return
        self.selection = 'Standard'
        self.interaction = interaction
        self.stop()

    @discord.ui.button(style=discord.ButtonStyle.red, label='Admin', custom_id='admin')
    async def select_admin(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.selection != None:
            return
        self.selection = 'Admin'
        self.interaction = interaction
        self.stop()

    # async def on_timeout(self):
        # if self.selection != None:
            # return
        # self.stop()

class PolyhedraClient(discord.Client):
    def __init__(self, Config):
        #config for both
        self.config = Config
        self.userlist = []
        self.admin_id = int(Config.get('IdleISS_Admin'))
        #idleiss interface
        universe_filename = Config['IdleISS_Universe_Config']
        library_filename = Config['IdleISS_Ships_Config']
        self.engine = GameEngine(universe_filename, library_filename)
        self.engine_lock = asyncio.Lock()
        self.engine_is_ready = False
        #idleiss debug
        print(''.join(self.engine.universe.debug_output))
        print(f"Universe successfully loaded from {universe_filename}")
        print(f"Starships successfully loaded from {library_filename}: ")
        print(f"\tImported {len(self.engine.library.ship_data)} ships")
        #discord setup
        allowed_mentions = discord.AllowedMentions(roles=True, everyone=False, users=False)
        intents = discord.Intents(
            guilds = True,
            members = True,
            messages = True,
            message_content = True,
            guild_messages = True,
            dm_messages = True,
            dm_reactions = True,
            guild_reactions = True,
            emojis = True,
            reactions = True,
        )
        self.synced = False
        self.tree = None
        super().__init__(
            intents=intents,
            allowed_mentions=allowed_mentions,
            heartbeat_timeout=Config['heartbeat_timeout'],
            chunk_guilds_at_startup=False,
        )
        self.tree = discord.app_commands.CommandTree(self)
        self.process_command_tree()

    def process_command_tree(self):
        if self.config.get('IdleISS_Server') == None:
            return
        tree = self.tree

        @tree.command(guild = discord.Object(id = self.config['IdleISS_Server']), name = 'test', description = 'testing')
        async def test(interaction: discord.Interaction):
            await interaction.response.send_message(f'I am working! I was made with Discord.py', ephemeral=True)

        @tree.command(guild = discord.Object(id = self.config['IdleISS_Server']), name = 'register', description = 'Start Playing IdleISS')
        async def register(interaction: discord.Interaction):
            await interaction.response.defer(ephemeral=True, thinking=True)
            print(f'/register defered: <@{interaction.user.id}>') #debug
            present = True
            #grab engine_lock before modifying the userlist
            async with self.engine_lock:
                present = is_present(self.userlist, f'<@{interaction.user.id}>')
                if not present:
                    bisect.insort(self.userlist, f'<@{interaction.user.id}>')
            #as soon as we are done interacting with IDLEISS release lock on IDLEISS
            #TODO update this text, perhaps with a config or "language pack"
            #TODO needs to be updated to interaction.followup.send
            if not present:
                await interaction.followup.send(f'Your fleet has been dispached to construct your first structure.', ephemeral=True)
                print(f'/register followup: <@{interaction.user.id}> added') #debug
            else:
                await interaction.followup.send(f'You have already registered.', ephemeral=True)
                print(f'/register followup: <@{interaction.user.id}> already exists') #debug
                #TODO spam protection increment

        @tree.command(guild = discord.Object(id = self.config['IdleISS_Server']), name = 'info', description = 'Display information about a specific solar system.')
        @discord.app_commands.describe(system_name='The solar system to inspect')
        async def info(interaction: discord.Interaction, system_name: str):
            panel = False
            if interaction.user.id == self.admin_id:
                panel = True
                view = Admin_Panel(interaction)
                await interaction.response.send_message('Select mode:', view=view, ephemeral=True)
                await view.wait() # Wait for View to stop listening for input
                if view.selection == None:
                    return #no way to update view currently
                if view.selection == 'Admin':
                    response = 'error: no such system'
                    async with self.engine_lock:
                        response = self.engine.info_system(system_name)
                    await view.interaction.response.edit_message(content=response, view=None)
                    return
            # if admin is not selected or user is not admin then we fall through the above code
            # and land at normal standard info command
            if panel:
                await view.interaction.response.edit_message(content='Not implemented for non-admins yet.', view=None) #ephemeral=True) #TODO Implement this
                return
            await interaction.response.send_message(content=f'Not implemented for non-admins yet.', ephemeral=True) #TODO IMPLEMENT THIS

        #admin commands
        if self.admin_id == None:
            return
        @tree.command(guild = discord.Object(id = self.config['IdleISS_Server']), name = 'inspect', description = 'Admin Only: Inspect a user')
        @discord.app_commands.describe(username='The user to inspect')
        async def inspect(interaction: discord.Interaction, username: str):
            if interaction.user.id != self.admin_id:
                await interaction.response.send_message(f'You do not have admin access.', ephemeral=True)
                #TODO spam protection increment
                return
            await interaction.response.defer(ephemeral=True, thinking=True)
            if username[2] == '!': #<@!id> means there is a nickname for this server, this converts to non-nickname mode
                username = username.removeprefix('<@!')
                username = f'<@{username}'
            response = 'error: no such user'
            async with self.engine_lock:
                response = self.engine.inspect_user(username)
            await interaction.followup.send(response, ephemeral=True)

    async def on_ready(self):
        print('Logged on as {0}!'.format(self.user))
        await self.wait_until_ready()
        if self.config.get('IdleISS_Server') != None:
            if not self.synced:
                await self.tree.sync(guild = discord.Object(id = self.config['IdleISS_Server']))
                self.synced = True
                print('IdleISS Server Commands Updated')
            if (
                    not self.engine_heartbeat.is_running() and
                    not self._heartbeat_align.is_running()
                ):
                self._heartbeat_align.start()
        else:
            #generates OAUTH2 invite for:
            #Read Messages/View Channels
            #Manage Events
            #Send Messages
            #Embed Links
            #Attach Files
            #Read Message History
            #Attach Files
            #Add Reactions
            #Use Slash Commands
            #10737536064
            print('No Discord Server ID in config file, cannot load slash commands to server.')
            print(f'Invite: https://discordapp.com/oauth2/authorize?client_id={self.user.id}&scope=bot&permissions=10737536064&scope=bot%20applications.commands')

    @tasks.loop(seconds=0.5, count=(int(heartbeat_step)*2)+1, reconnect=True)
    async def _heartbeat_align(self):
        if self.engine_heartbeat.is_running():
            self._heartbeat_align.stop()
            return
        async with self.engine_lock:
            if (
                    int(time.time()) % heartbeat_step >= 10 and
                    int(time.time()) % heartbeat_step <= 50
                ):
                self.engine_heartbeat.start()
                self._heartbeat_align.stop()

    @tasks.loop(minutes=float(heartbeat_step/60), count=None, reconnect=True)
    async def engine_heartbeat(self):
        updates = ''
        async with self.engine_lock:
            channel = self.get_channel(int(self.config['IdleISS_Reports_Channel']))
            current_time = int(time.time())
            await channel.send(f'heartbeat: <t:{current_time}>') #debug
            mes_manager = self.engine.update_world(self.userlist, current_time)
            message_array = mes_manager.get_broadcasts_with_time_diff(current_time)
            #TODO manage large event lists
            updates = '\n'.join(message_array)
            if updates != '':
                await channel.send(f'Events:\n{updates}',allowed_mentions=None)

    async def on_message(self, message):
        if message.author == self.user:
            return
        if message.guild == None:
            print('Direct Message with {0.author}: {0.content}'.format(message))
        else:
            print('#{0.channel}-{0.author}: {0.content}'.format(message))
        #delete any message posted in IdleISS_Commands_Channel
        if message.guild != None and message.channel != None:
            if (
                    message.channel.id == int(self.config.get('IdleISS_Commands_Channel', '0')) and
                    message.guild.id == int(self.config.get('IdleISS_Server', '0')) and
                    message.author.id != int(self.config.get('IdleISS_Admin', '0'))
                ):
                    counter = 0
                    while counter <= 10:
                        try:
                            await message.delete()
                            break
                        except discord.Forbidden:
                            print(f'Did not have access to delete a message in {message.channel} with ID:{message.channel.id}')
                            raise
                            break
                        except discord.NotFound:
                            break
                        except discord.HTTPException as err:
                            print(f'Failed to delete message in {message.channel}: {err.status} - {err.code} - {err.text}')
                            await asyncio.sleep(60)
                            counter += 1
        # example of responding to raw message_content, likely to be removed in later versions of discord API
        # if message.content.startswith('$hello'):
            # reply = 'Hello!'
            # if message.guild == None:
                # print(f'Sending Direct Message to: {message.author}: {reply}')
            # else:
                # print(f'Sending #{message.channel}: {reply}')
            # await message.channel.send('Hello!')

def run():
    #load config
    config_file = 'config/private_config.json'
    config = None
    with open(config_file, "r") as fd:
        config = json.load(fd)
        fd.close()

    #validate polyhedra config
    #validation of IdleISS config done in GameEngine
    if config == {}:
        print(f'{config_file} not found or empty')
        return
    if config.get('IdleISS_Universe_Config') == None:
        print(f'{config_file} missing IdleISS_Universe_Config')
        return
    if config.get('IdleISS_Ships_Config') == None:
        print(f'{config_file} missing IdleISS_Ships_Config')
        return

    #attempt IdleISS state from storage
    if config.get('polyhedra_save_file') == None:
        print(f'{config_file} missing polyhedra_save_file')
        return
    #with open(config['polyhedra_save_file'], 'r') as fd:
    #    json.load(fd)
    #    fd.close()

    #setup logging
    logger = logging.getLogger('discord')
    if config.get('LoggingLevel') == 'CRITICAL':
        logger.setLevel(logging.CRITICAL)
        print('Logging set to CRITICAL')
    elif config.get('LoggingLevel') == 'ERROR':
        logger.setLevel(logging.ERROR)
    elif config.get('LoggingLevel') == 'WARNING':
        logger.setLevel(logging.WARNING)
    elif config.get('LoggingLevel') == 'DEBUG':
        logger.setLevel(logging.DEBUG)
    else:# config.get('LoggingLevel') == None # or INFO or anything else
        logger.setLevel(level=logging.INFO)
    handler = logging.FileHandler(filename='discord.log', encoding='utf-8', mode='w')
    handler.setFormatter(logging.Formatter('%(asctime)s:%(levelname)s:%(name)s: %(message)s'))
    logger.addHandler(handler)

    #check for key
    if config.get('DiscordAPIKey') == None:
        print(f'{config_file}: DiscordAPIKey value not found')
        return

    if config.get('IdleISS_Admin') == None:
        print(f'{config_file}: IdleISS_Admin value not found, admin commands will be disabled')

    print(f'Configured IdleISS Discord Server: {config.get("IdleISS_Server")}')
    #instance Client
    client = PolyhedraClient(config)

    #run Client
    client.run(config['DiscordAPIKey'])

if __name__ == '__main__':
    run()

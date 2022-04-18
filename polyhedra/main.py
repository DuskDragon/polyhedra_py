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

class PolyhedraClient(discord.Client):
    def __init__(self, Config):
        #config for both
        self.config = Config
        self.userlist = []
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
        if self.config.get('IdleISS_Discord_Server') == None:
            return
        tree = self.tree

        @tree.command(guild = discord.Object(id = self.config['IdleISS_Discord_Server']), name = 'test', description = 'testing')
        async def slash(interaction: discord.Interaction):
            await interaction.response.send_message(f'I am working! I was made with Discord.py', ephemeral=True)

        @tree.command(guild = discord.Object(id = self.config['IdleISS_Discord_Server']), name = 'register', description = 'Start Playing IdleISS')
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

    async def on_ready(self):
        print('Logged on as {0}!'.format(self.user))
        await self.wait_until_ready()
        if self.config.get('IdleISS_Discord_Server') != None:
            if not self.synced:
                await self.tree.sync(guild = discord.Object(id = self.config['IdleISS_Discord_Server']))
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
            #TODO: replace with full IdleISS interface
            channel = self.get_channel(int(self.config['IdleISS_Reports_Channel']))
            current_time = int(time.time())
            await channel.send(f'heartbeat: <t:{current_time}>') #debug
            mes_manager = self.engine.update_world(self.userlist, current_time)
            message_array = mes_manager.get_broadcasts_with_time_diff(current_time)
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

    print(f'Configured IdleISS Discord Server: {config.get("IdleISS_Discord_Server")}')
    #instance Client
    client = PolyhedraClient(config)

    #run Client
    client.run(config['DiscordAPIKey'])

if __name__ == '__main__':
    run()

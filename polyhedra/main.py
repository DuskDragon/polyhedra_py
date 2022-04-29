from idleiss.core import GameEngine
from idleiss.core import InvalidSaveData
import bisect
import time
import os
import pathlib
import json
#import argparse

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

#time tools
def time_left(now, then):
    'Converts epoch timestamps into {w}d, {x}h, {y}m, {z}s'
    out = ''
    diff = int(then - now)
    if diff < 0:
        return out
    if diff == 0:
        out = '1s'
    day = int(diff/86400)
    hr = int((diff%86400)/3600)
    min = int((diff%3600)/60)
    sec = int(diff%60)
    if diff > 86400:
        out = f'{day}d {hr}h {min}m {sec}s'
    elif diff > 3600:
        out = f'{hr}h {min}m {sec}s'
    elif diff > 60:
        out = f'{min}m {sec}s'
    else:
        out = f'{sec}s'
    return out

class Admin_Panel(discord.ui.View):
    def __init__(self):
        self.selection = None
        self.interaction = None
        super().__init__(timeout=600)

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

    async def on_timeout(self):
        self.stop()

class Scanning_Panel(discord.ui.View):
    def __init__(self, scan_timestamps, scan_recharges):
        self.selection = None
        self.interaction = None
        super().__init__(timeout=600)
        now = int(time.time())
        low_time = int(scan_timestamps.get('low',0) + scan_recharges.get('low',0))
        focus_time = int(scan_timestamps.get('focus',0) + scan_recharges.get('focus',0))
        high_time = int(scan_timestamps.get('high',0) + scan_recharges.get('high',0))
        if (now <= low_time):
            for x in self.children:
                if x.custom_id == 'low':
                    x.disabled = True
                    x.label = f'Recharging: {time_left(now,low_time)}'
        if (now <= focus_time):
            for x in self.children:
                if x.custom_id == 'focus':
                    x.disabled = True
                    x.label = f'Recharging: {time_left(now,focus_time)}'
        if (now <= high_time):
            for x in self.children:
                if x.custom_id == 'high':
                    x.disabled = True
                    x.label = f'Recharging: {time_left(now,high_time)}'

    @discord.ui.button(style=discord.ButtonStyle.green, label='Low Energy Scan', custom_id='low')
    async def select_low(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.selection != None:
            return
        self.selection = 'low'
        self.interaction = interaction
        self.stop()

    @discord.ui.button(style=discord.ButtonStyle.blurple, label='Focused Scan', custom_id='focus')
    async def select_focus(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.selection != None:
            return
        self.selection = 'focus'
        self.interaction = interaction
        self.stop()

    @discord.ui.button(style=discord.ButtonStyle.red, label='High Energy Scan', custom_id='high')
    async def select_high(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.selection != None:
            return
        self.selection = 'high'
        self.interaction = interaction
        self.stop()

    async def on_timeout(self):
        self.stop()

class PolyhedraClient(discord.Client):
    def __init__(self, Config):
        #config for both
        self.config = Config
        self.userlist = []
        self._active_commands = {}
        self.admin_id = int(Config.get('IdleISS_Admin', '0'))
        self.home_server = int(Config.get('IdleISS_Server', '0'))
        self.quiet_channel = int(self.config.get('IdleISS_Commands_Channel', '0'))
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
        self.tree = None
        super().__init__(
            intents=intents,
            allowed_mentions=allowed_mentions,
            heartbeat_timeout=Config['heartbeat_timeout'],
            chunk_guilds_at_startup=False,
        )
        self.tree = discord.app_commands.CommandTree(self)
        self.process_command_tree()
        #this must be set before _load_from_savefile as it can be modified there
        self.synced = False
        #idleiss interface
        savedata_filename = Config['Polyhedra_Savefile']
        self._load_from_savefile(savedata_filename)
        self.engine_lock = asyncio.Lock()
        self.check_time = -1


    def _register_view(self, view, interaction):
        """
        Whenever an ephemeral view is generated it must be registered to that
        user. This allows _register_view to stop all previous views in order
        to make sure a user has only one active ephemeral view at a time.
        """
        #kill previous view instance
        old_view = self._active_commands.get(f'<@{interaction.user.id}>', None)
        if old_view != None:
            old_view.stop()
        # tag this view onto our current active command for this user
        self._active_commands[f'<@{interaction.user.id}>'] = view
        return view

    def _load_from_savefile(self, save_filename):
        """
        This function sets self.engine state based on the savefile
        This is likely not the greatest implemenation.
        TODO maybe clean it up eventually and/or rewrite it
        """
        save = None
        universe_filename = self.config['IdleISS_Universe_Config']
        library_filename = self.config['IdleISS_Ships_Config']
        with open(save_filename, 'r') as fd:
            save = json.load(fd)
        if save == {}:
            print(f'Polyhedra_Savefile is new. Generating fresh IdleISS instance...')
            self.engine = GameEngine(universe_filename, library_filename, {})
        else:
            savedata_engine = save.get('engine', None)
            savedata_userlist = save.get('userlist', None)
            if ( #TODO move to validate function and make more robust
                    savedata_engine == None or
                    savedata_userlist == None
                ):
                raise InvalidSaveData(f'{save_filename} contains invalid save data, delete the file or replace with valid save data to continue.')
            self.engine = GameEngine(universe_filename, library_filename, savedata_engine)
            #TODO add more validation here before blindly copying over
            self.userlist = savedata_userlist
            print(f'Successfully loaded savefile: {save_filename}')
            #TODO check if command tree matches saved file, if so then set self.synced = True
        #idleiss load information
        print(''.join(self.engine.universe.debug_output))
        print(f'Universe successfully loaded from {universe_filename}')
        print(f'Starships successfully loaded from {library_filename}: ')
        print(f'\tImported {len(self.engine.library.ship_data)} ships')

    def _populate_savefile(self, timestamp):
        """
        The function that calls this one must aquire a lock on self.engine_lock.
        TODO: enforce this by moving it inside this?
        """
        engine_savedata = self.engine.generate_savedata()
        savedata = {
            'engine': engine_savedata,
            'userlist': self.userlist,
        }
        #verify that dump doesn't fail before writing
        testout = json.dumps(savedata, indent=4)
        with open(self.config['Polyhedra_Savefile'], 'w') as fd:
            fd.write(testout)
        print(f'savefile generated at {timestamp}')

    def process_command_tree(self):
        if self.home_server == 0:
            return
        tree = self.tree

        # @tree.command(guild = discord.Object(id = self.home_server), name = 'test', description = 'testing')
        # async def test(interaction: discord.Interaction):
            # await interaction.response.send_message(f'I am working! I was made with Discord.py', ephemeral=True)

        @tree.command(guild = discord.Object(id = self.home_server), name = 'register', description = 'Start Playing IdleISS')
        async def register(interaction: discord.Interaction):
            await interaction.response.defer(ephemeral=True, thinking=True)
            present = True
            #grab engine_lock before modifying the userlist
            async with self.engine_lock:
                present = is_present(self.userlist, f'<@{interaction.user.id}>')
                if not present:
                    bisect.insort(self.userlist, f'<@{interaction.user.id}>')
            #as soon as we are done interacting with IDLEISS release lock on IDLEISS
            #TODO update this text, perhaps with a config or "language pack"
            #TODO needs to be updated to interaction.followup.send
            time_to_next_tick = 149
            if self.check_time != -1:
                time_to_next_tick = (self.check_time - (int(time.time()) % heartbeat_step)) % heartbeat_step
            if not present:
                await interaction.followup.send(f'Your fleet has been directed to place your first structure. The fleet is already in system and will align the structure\'s orbit with the local equatorial plane in about {time_to_next_tick+1} seconds.', ephemeral=True)
            else:
                await interaction.followup.send(f'You have already registered.', ephemeral=True)
                #TODO spam protection increment

        @tree.command(guild = discord.Object(id = self.home_server), name = 'scan', description = 'Scan local space for signal returns to investigate.')
        async def scan(interaction: discord.Interaction):
            await interaction.response.defer(ephemeral=True, thinking=True)
            async with self.engine_lock:
                present = is_present(self.userlist, f'<@{interaction.user.id}>')
                if not present:
                    await interaction.followup.send('You are not registered. Please use /register to start playing IdleISS.', ephemeral=True)
                    return

            #todo implement into IdleISS, using these stubs for now
            now = int(time.time())
            scan_timestamps = {
                'low': now-(2*((60*60)-(60*5))),
                'focus': now-(2*((60*60*4)-(60*5*4))),
                'high': now-(2*((60*60*24)-(60*5*24))),
            }
            scan_recharges = {
                'low': ((60*60)-(60*5)),
                'focus': ((60*60*4)-(60*5*4)),
                'high': ((60*60*24)-(60*5*24)),
            }
            view = self._register_view(Scanning_Panel(scan_timestamps,scan_recharges), interaction)
            # display view and wait
            await interaction.followup.send('Select scanning mode:', view=view, ephemeral=True)
            await view.wait() # Wait for View to stop listening for input
            if view.selection == None:
                output = 'This interaction has timed out.'
                await interaction.edit_original_message(content=output, view=None)
                return
            present = True
            async with self.engine_lock:
                output = ''
                present = is_present(self.userlist, f'<@{interaction.user.id}>')
                if not present:
                    output = 'You are not registered. Please use /register to start playing IdleISS.'
                # TODO validate user is not using the double command exploit
                # pull updated timestamps again from GameEngine
                else:
                    now = int(time.time())
                    if view.selection == 'low':
                        # using the updated GameEngine scan timeouts
                        if False: #TODO
                            output = 'too soon' #TODO
                        else:
                            output = 'low result'
                            pass #TODO
                    elif view.selection == 'focus':
                        # using the updated GameEngine scan timeouts
                        if False: #TODO
                            output = 'too soon' #TODO
                        else:
                            output = 'focus result'
                            pass #TODO
                    elif view.selection == 'high':
                        # using the updated GameEngine scan timeouts
                        if False: #TODO
                            output = 'too soon' #TODO
                        else:
                            output = 'high result'
                        pass #TODO
                    else:
                        output = 'timeout'
                        pass
            await view.interaction.response.edit_message(content=output, view=None)

        @tree.command(guild = discord.Object(id = self.home_server), name = 'info', description = 'Display information about a specific solar system.')
        @discord.app_commands.describe(system_name='The solar system to inspect')
        async def info(interaction: discord.Interaction, system_name: str):
            panel = False
            if interaction.user.id == self.admin_id:
                panel = True
                view = self._register_view(Admin_Panel(), interaction)
                await interaction.response.send_message('Select mode:', view=view, ephemeral=True)
                await view.wait() # Wait for View to stop listening for input
                if view.selection == None:
                    output = 'This interaction has timed out.'
                    await interaction.edit_original_message(content=output, view=None)
                    return
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
        if self.admin_id == 0:
            return
        @tree.command(guild = discord.Object(id = self.home_server), name = 'inspect', description = 'Admin Only: Inspect a user')
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
        print(f'Logged on as {self.user}!')
        await self.wait_until_ready()
        if self.home_server != None:
            if not self.synced:
                #TODO DO NOT UPDATE CONSTANTLY
                await self.tree.sync(guild = discord.Object(id = self.home_server))
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
            check = int(time.time())
            if (
                    check % heartbeat_step >= 10 and
                    check % heartbeat_step <= 50
                ):
                self.check_time = check % heartbeat_step
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
            self._populate_savefile(current_time)
            message_array = mes_manager.get_broadcasts_with_time_diff(current_time)
            if not mes_manager.is_empty:
                for x in mes_manager.container:
                    print(f'{x[0]} {x[1]}: {x[2]}')
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
        #delete any message posted in IdleISS_Commands_Channel: self.quiet_channel
        if message.guild != None and message.channel != None:
            if (
                    message.channel.id == self.quiet_channel and
                    message.guild.id == self.home_server and
                    message.author.id != self.admin_id
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
    with open(config_file, 'r') as fd:
        config = json.load(fd)

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
    if config.get('Polyhedra_Savefile') == None:
        print(f'{config_file} missing Polyhedra_Savefile location')
        return

    #if Polyhedra_Savefile does not exist, create it:
    savefile = pathlib.Path(config['Polyhedra_Savefile'])
    savefile.touch(exist_ok=True)

    #if the file is empty write an empty dictionary
    if os.path.getsize(config['Polyhedra_Savefile']) == 0:
        with open(config['Polyhedra_Savefile'], 'w') as fd:
            print(f'Polyhedra_Savefile is empty. Creating new save.')
            fd.write('{}')

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
    client = PolyhedraClient(config) #, savefile) TODO

    #run Client
    client.run(config['DiscordAPIKey'])

if __name__ == '__main__':
    run()

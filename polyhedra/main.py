from idleiss.core import GameEngine

#import argparse
#import os
import json
#import random

import discord
import logging

class PolyhedraClient(discord.Client):
    def __init__(self, Config):
        self.config = Config
        intents = discord.Intents.default()
        intents.messages = True
        intents.message_content = True
        intents.guilds = True
        intents.invites = True
        intents.guild_messages = True
        intents.dm_messages = True
        intents.dm_reactions = True
        intents.guild_reactions = True
        discord.Client.__init__(self, intents=intents)
        self.tree = discord.app_commands.CommandTree(self)
        self.tree.add_command(self.slash)

    async def on_ready(self):
        print('Logged on as {0}!'.format(self.user))
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
        print(f'Invite: https://discordapp.com/oauth2/authorize?client_id={self.user.id}&scope=bot&permissions=10737536064')

    async def on_message(self, message):
        if message.author == self.user:
            return
        if message.guild == None:
            print('Direct Message with {0.author}: {0.content}'.format(message))
        else:
            print('#{0.channel}-{0.author}: {0.content}'.format(message))

        if message.content.startswith('$hello'):
            reply = 'Hello!'
            if message.guild == None:
                print(f'Sending Direct Message to: {message.author}: {reply}')
            else:
                print(f'Sending #{message.channel}: {reply}')
            await message.channel.send('Hello!')

    @discord.app_commands.command()
    async def slash(interaction: discord.Interaction, number: int, string: str):
        await interaction.response.send_message(f'{number=} {string=}', ephemeral=True)

def run():

    #load config
    config_file = 'private_config.json'
    fd = open(config_file)
    config = json.load(fd)
    fd.close()

    #setup logging
    logger = logging.getLogger('discord')
    if config.get('LoggingLevel') == 'CRITICAL':
        logger.setLevel(logging.CRITICAL)
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

    #pull key
    if config.get('DiscordAPIKey') == None:
        print(f'{config_file} not found')
        return

    #start Client
    client = PolyhedraClient(config)
    client.run(config['DiscordAPIKey'])

if __name__ == "__main__":
    run()

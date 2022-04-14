from idleiss.core import GameEngine

#import argparse
#import os
import json
#import random

import discord

class MyClient(discord.Client):
    def __init__(self):
        intents = discord.Intents.default()
        #intents.message_content = True
        discord.Client.__init__(self, intents=intents)

    async def on_ready(self):
        print('Logged on as {0}!'.format(self.user))

    async def on_message(self, message):
        print('Message from {0.author}: {0.content}'.format(message))
        if message.author == client.user:
            return

        if message.content.startswith('$hello'):
            await message.channel.send('Hello!')

def run():

    config_file = 'private_config.json'
    fd = open(config_file)
    config = json.load(fd)
    fd.close()

    if config.get('DiscordAPIKey') == None:
        print(f'{config_file} not found')
        return

    client = MyClient()
    client.run(config['DiscordAPIKey'])

if __name__ == "__main__":
    run()

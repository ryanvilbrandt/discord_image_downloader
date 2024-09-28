import json
import os
import re
import shutil
import sys
from datetime import datetime

import aiohttp
import discord
import pytz
from discord import Message
from discord.ext import commands

# Define your bot's prefix and intents
intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
intents.messages = True

# Create bot instance
bot = commands.Bot(command_prefix="!", intents=intents)

if not os.path.isfile("settings.json"):
    shutil.copy("settings.json.dist", "settings.json")
    print("No settings.json file found. Created a new file from the default. "
          "Please add your bot token and all other needed information and then run this script again.")
    raise SystemExit(0)

with open("settings.json") as f:
    settings = json.load(f)

# Replace with your bot'"'s token
DISCORD_TOKEN = settings["token"]

# Folder to save images
DOWNLOAD_FOLDER = settings["download_folder"]

# Define the servers and channels you want to scan
SERVERS = set(settings["servers"].keys())


def parse_start_time(timestamp: str) -> datetime:
    if not timestamp:
        return datetime(2024, 1, 1)
    try:
        return datetime.strptime(timestamp, "%Y-%m-%d %H:%M:%S.%f%z")
    except ValueError:
        try:
            dt = datetime.strptime(timestamp, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            dt = datetime.strptime(timestamp, "%Y-%m-%d")
        return dt.replace(tzinfo=pytz.UTC)


def get_image_urls(message: Message) -> list[str]:
    extensions = "jpg|jpeg|gif|png"
    urls = []
    for attachment in message.attachments:
        m = re.search(fr"(\.({extensions}))\??", attachment.url)
        if m:
            urls.append(attachment.url)
    for embed in message.embeds:
        if embed.image.url:
            url = embed.image.url
            if "rendercombined" not in url:  # Skip fixvx combined images, so we'll open the browser to them later
                m = re.search(fr"(\.({extensions}))\??", url)
                if m:
                    urls.append(url)
        if embed.thumbnail.url:
            url = embed.thumbnail.url
            if "rendercombined" not in url:  # Skip fixvx combined images, so we'll open the browser to them later
                m = re.search(fr"(\.({extensions}))\??", url)
                if m:
                    urls.append(url)
                if "cdn.bsky.app" in url:
                    m = re.search(fr"(@({extensions}))$", url)
                    if m:
                        urls.append(url)
    m = re.search(r"https://\S+", message.content)
    if m:
        url = m.group(0)
        m = re.search(fr"(\.({extensions}))\??", url)
        if m:
            urls.append(url)
    if not urls:
        if "https://" in message.content:
            print(f"No URLs found for message={message.content}")
            m = re.search(r"https://\S+", message.content)
            if m:
                os.system(f"start \"\" {m.group(0)}")
    return urls


def get_image_filename_from_url(url: str) -> str:
    url = url.split("?")[0].rsplit("/", 1)[1]
    if url.endswith(":large"):
        url = url[:-6]
    m = re.search(r"(@(jpg|jpeg|gif|png))$", url)
    if m:
        url = url.replace(m.group(1), m.group(1).replace("@", "."))
    return url


# Function to download the image
async def download_image(url, folder, filename):
    filepath = os.path.join(folder, filename)
    if os.path.isfile(filepath):
        print(f"Already downloaded {filepath}")
        return
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as resp:
            if resp.status == 200:
                with open(os.path.join(folder, filename), "wb") as f:
                    f.write(await resp.read())
                print(f"Downloaded {filename}")
            elif resp.status == 404:
                print(f"404 error when trying to download {url}", file=sys.stderr)
            else:
                raise FileNotFoundError(f"HTTP {resp.status} error ({resp.url}): {resp.content}")


def update_parsed_message_time(message: Message, channel_settings: dict):
    channel_settings["last_parsed_message_time"] = message.created_at.strftime("%Y-%m-%d %H:%M:%S.%f%z")


def save_settings(settings: dict):
    with open("settings.json", "w") as f:
        json.dump(settings, f, indent=2)


# Event handler when the bot is ready
@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")

    try:
        # Iterate over each server
        for guild in bot.guilds:
            if str(guild.id) in SERVERS:
                print(f"Scanning server: {guild.name}")

                # Iterate over each channel
                server_settings = settings["servers"][str(guild.id)]
                target_channel_ids = set(server_settings["channels"].keys())
                for channel in guild.text_channels:
                    if str(channel.id) in target_channel_ids:
                        try:
                            print(f"Scanning channel: {channel.name}")
                            channel_settings = server_settings["channels"][str(channel.id)]

                            # Retrieve the message history
                            start_time = parse_start_time(channel_settings.get("last_parsed_message_time"))
                            async for message in channel.history(limit=None, after=start_time):
                                urls = get_image_urls(message)
                                print(f"Message: {message.content}")

                                # Download image URLs
                                for url in urls:
                                    filename = get_image_filename_from_url(url)
                                    filename = f"{message.id}_{filename}"
                                    await download_image(url, DOWNLOAD_FOLDER, filename)

                                update_parsed_message_time(message, channel_settings)
                        finally:
                            save_settings(settings)
    finally:
        # Stop the bot after scanning
        await bot.close()


# Start the bot
bot.run(DISCORD_TOKEN)

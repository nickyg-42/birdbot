import discord
from discord.ext import commands
from dotenv import load_dotenv
import os
import requests
import base64
from io import BytesIO
import time
import asyncio
from influxdb_client import InfluxDBClient, Point
from influxdb_client.client.write_api import SYNCHRONOUS
import time

load_dotenv()

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix='!', intents=intents)

TOKEN = os.getenv('DISCORD_BOT_TOKEN')
ACCOUNT_ID = os.getenv('ACCOUNT_ID')
AUTH_TOKEN = os.getenv('AUTH_TOKEN')
NINJA_API_KEY = os.getenv('NINJA_API_KEY')

# Variables to track requests and rate limits
text_gen_requests = 0
image_gen_requests = 0
last_text_gen_reset = time.time()
last_image_gen_reset = time.time()
last_message_time = 0

# Rate limit parameters
TEXT_GEN_LIMIT = 300
IMAGE_GEN_LIMIT = 720
TIME_WINDOW = 60

# InfluxDB configuration
INFLUXDB_URL = "http://localhost:8086"
INFLUXDB_TOKEN = "t3vb8RUqIl7dj2mK47K5ayPX7eet7ftqzcm9D8tgQNhnjBrSeoml_M_ty2HWqiTbofSmS6CHoC36L-jWn-fV_A=="
INFLUXDB_ORG = "birdnest"
INFLUXDB_BUCKET = "discord"

# Initialize InfluxDB client
client = InfluxDBClient(url=INFLUXDB_URL, token=INFLUXDB_TOKEN, org=INFLUXDB_ORG)
write_api = client.write_api(write_options=SYNCHRONOUS)


class RateLimitExceeded(Exception):
    """Exception raised when the rate limit for API requests is exceeded."""
    pass

# Function to handle text generation rate limiting
async def rate_limit_text_gen():
    global text_gen_requests, last_text_gen_reset
    current_time = time.time()

    # Reset the count if more than 60 seconds have passed
    if current_time - last_text_gen_reset > TIME_WINDOW:
        text_gen_requests = 0
        last_text_gen_reset = current_time

    # Check if we've reached the rate limit
    if text_gen_requests >= TEXT_GEN_LIMIT:
        return False

    text_gen_requests += 1
    return True


# Function to handle image generation rate limiting
async def rate_limit_image_gen():
    global image_gen_requests, last_image_gen_reset
    current_time = time.time()

    # Reset the count if more than 60 seconds have passed
    if current_time - last_image_gen_reset > TIME_WINDOW:
        image_gen_requests = 0
        last_image_gen_reset = current_time

    # Check if we've reached the rate limit
    if image_gen_requests >= IMAGE_GEN_LIMIT:
        return False

    image_gen_requests += 1
    return True


async def make_ai_image_call_flux(prompt):
    if not await rate_limit_image_gen():
        raise RateLimitExceeded("Rate limit exceeded for imnage generation. Try again in a minute.")

    try:
        prompt = prompt.lower().replace("you", "A majestic bird")
        prompt = prompt.lower().replace("me", "A grimy peasant")
        response = requests.post(
            f"https://api.cloudflare.com/client/v4/accounts/{ACCOUNT_ID}/ai/run/@cf/black-forest-labs/flux-1-schnell",
            headers={"Authorization": f"Bearer {AUTH_TOKEN}"},
            json={
                "prompt": f'{prompt}',
                "num_steps": 8
            }
        )
        result = response.json()
        base64_image = result['result']['image']

        if base64_image:
            image_data = base64.b64decode(base64_image)
            return BytesIO(image_data) 
        else:
            return None
        
    except Exception as e:
        print(f'Error making API Call: {e}')
        raise Exception(f'An error occurred: {e}')
    

async def make_ai_image_call_dreamshaper(prompt):
    if not await rate_limit_image_gen():
        raise RateLimitExceeded("Rate limit exceeded for imnage generation. Try again in a minute.")

    try:
        prompt = prompt.lower().replace("you", "A majestic bird")
        prompt = prompt.lower().replace("me", "A grimy peasant")
        response = requests.post(
            f"https://api.cloudflare.com/client/v4/accounts/{ACCOUNT_ID}/ai/run/@cf/lykon/dreamshaper-8-lcm",
            headers={"Authorization": f"Bearer {AUTH_TOKEN}"},
            json={
                "prompt": f'{prompt}'
            }
        )
        image_bytes = BytesIO(response.content)
        file = discord.File(image_bytes, filename="image.png")
        return file
        
    except Exception as e:
        print(f'Error making API Call: {e}')
        raise Exception(f'An error occurred: {e}')


async def make_ai_text_call(role, content):
    if not await rate_limit_text_gen():
        raise RateLimitExceeded("Rate limit exceeded for text generation. Try again in a minute.")

    try:
        response = requests.post(
            f"https://api.cloudflare.com/client/v4/accounts/{ACCOUNT_ID}/ai/run/@cf/meta/llama-2-7b-chat-fp16",
            headers={"Authorization": f"Bearer {AUTH_TOKEN}"},
            json={
                "messages": [
                    {"role": "system", "content": role},
                    {"role": "user", "content": content}
                ]
            }
        )
        result = response.json()
        sanitized_output = result['result']['response'].replace("\"", "")
        return sanitized_output;
    except Exception as e:
        print(f'Error making API Call: {e}')
        raise Exception(f'An error occurred: {e}')


@bot.event
async def on_application_command(ctx):
    user = str(ctx.author)
    command = str(ctx.command)

    args = 'n/a'

    if ctx.selected_options is not None:
        args = ctx.selected_options[0]['value']

    try:
        point = Point("discord_commands") \
            .field("user", user) \
            .field("command", f"{command}:{args}") \

        write_api.write(bucket=INFLUXDB_BUCKET, org=INFLUXDB_ORG, record=point)
    except Exception as e:
        print("Failed to write to influx")


@bot.event
async def on_ready():
    print(f'Bot is online as {bot.user}!')


@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, RateLimitExceeded):
        await ctx.send("Error: Rate limit exceeded. Please wait a minute.")
    if isinstance(error, commands.MissingRequiredArgument):
        await ctx.send("Error: You need to provide an argument. Usage: `!<command> <argument>`", ephemeral=True)
    if isinstance(error, commands.CommandOnCooldown):
        await ctx.send(f"You're on cooldown. Try again in {round(error.retry_after)} seconds.", ephemeral=True)
    else:
        print(f'Generic error caught: {error}')
        await ctx.send(f"Unkown error.")


# /rebirth
@bot.slash_command(name="rebirth", description="Give me a theme and I'll set your nickname to something zany")
@commands.cooldown(1, 5, commands.BucketType.user)
async def rebirth(ctx: discord.ApplicationContext, theme: str):
    # Check if the user is the server owner
    if ctx.author == ctx.guild.owner:
        await ctx.respond("Sorry, I cannot change the server owner's nickname due to Discord's restrictions.", ephemeral=True)
        return

    try:
        role = '''
        Given a theme, generate a creative nickname that correlates directly with it. Respond with only the nickname and nothing else. Feel free to give nonsense, insulting, or absurd names.
        Wrap your answer in quotation marks. Keep response less than 32 characters.
        If you cannot answer for some reason, reply with "NO_REPLY".
        '''

        response = await make_ai_text_call(role, theme)

        if response == "NO_REPLY":
            await ctx.respond(f'Uh Oh, you entered a no-no topic. Try again.', ephemeral=True)
            return

        # Change the nickname of the user who invoked the command
        await ctx.author.edit(nick=response)
        await ctx.respond(f'{ctx.author.name} has been reborn as: {response}')
    except discord.Forbidden:
        await ctx.respond('I do not have permission to change nicknames. Please check my role permissions.', ephemeral=True)
    except discord.HTTPException as e:
        await ctx.respond(f'Failed to change nickname: {e}', ephemeral=True)
    except discord.errors.NotFound:
        await ctx.respond('An unknown error occurred. Please contact your local discord mod.', ephemeral=True)
        print(e)
    except RateLimitExceeded as e:
        await ctx.respond("Rate limit exceeded for text generation. Try again in a minute.", ephemeral=True)
        print(e)
    except Exception as e:
        await ctx.respond('An unknown error occurred. Please contact your local discord mod.', ephemeral=True)
        print(e)


@rebirth.error
async def imagine_error(ctx, error):
    if isinstance(error, commands.CommandOnCooldown):
        await ctx.respond(f"This server is on cooldown. Try again in {round(error.retry_after)} seconds.", ephemeral=True)
    else:
        await ctx.respond(f"Unkown error, spam @birdman until it is fixed", ephemeral=True)


# /imagine
@bot.slash_command(name="imagine", description="Paint a picture for me with your words and I'll paint one with my feathers")
@commands.cooldown(1, 5, commands.BucketType.user)
async def imagine(ctx: discord.ApplicationContext, description: str):
    await ctx.defer()

    try:
        image_data = await make_ai_image_call_flux(description)
    except RateLimitExceeded as e:
        await ctx.respond("Rate limit exceeded for image generation. Try again in a minute.", ephemeral=True)
        print(e)
        return
    except Exception as e:
        await ctx.respond("An error occurred while generating the image. Please try again later.", ephemeral=True)
        print(f"Error during image generation: {e}")
        return

    if image_data:
        try:
            file = discord.File(image_data, filename="generated_image.png")
            await ctx.respond(file=file)
        except Exception as e:
            print(f"Error responding with image: {e}")
            await ctx.respond("Sorry, I couldn't send the generated image.", ephemeral=True)
    else:
        await ctx.respond("Sorry, I couldn't generate an image. Please try again later.", ephemeral=True)


@imagine.error
async def imagine_error(ctx, error):
    if isinstance(error, commands.CommandOnCooldown):
        await ctx.respond(f"This server is on cooldown. Try again in {round(error.retry_after)} seconds.", ephemeral=True)
    else:
        await ctx.respond(f"Unkown error, spam @birdman until it is fixed", ephemeral=True)


# /joke
@bot.slash_command(name="joke", description="I'll tell you a joke")
@commands.cooldown(1, 5, commands.BucketType.user)
async def joke(ctx: discord.ApplicationContext):
    await ctx.defer()

    api_url = 'https://api.api-ninjas.com/v1/dadjokes'
    response = requests.get(api_url, headers={'X-Api-Key': NINJA_API_KEY})
    if response.status_code == requests.codes.ok:
        result = response.json()
        await ctx.respond(result[0]['joke'])
    else:
        print("Error:", response.status_code, response.text)
        await ctx.respond('There was an error finding a good joke, you must not be funny.')


@joke.error
async def imagine_error(ctx, error):
    if isinstance(error, commands.CommandOnCooldown):
        await ctx.respond(f"This server is on cooldown. Try again in {round(error.retry_after)} seconds.", ephemeral=True)
    else:
        await ctx.respond(f"Unkown error, spam @birdman until it is fixed", ephemeral=True)


# /fact
@bot.slash_command(name="fact", description="I'll tell you a fact")
@commands.cooldown(1, 5, commands.BucketType.user)
async def fact(ctx: discord.ApplicationContext):
    await ctx.defer()

    api_url = 'https://api.api-ninjas.com/v1/facts'
    response = requests.get(api_url, headers={'X-Api-Key': NINJA_API_KEY})
    if response.status_code == requests.codes.ok:
        result = response.json()
        await ctx.respond(result[0]['fact'])
    else:
        print("Error:", response.status_code, response.text)
        await ctx.respond('There was an error finding a fact, nothing is real.')


@fact.error
async def imagine_error(ctx, error):
    if isinstance(error, commands.CommandOnCooldown):
        await ctx.respond(f"This server is on cooldown. Try again in {round(error.retry_after)} seconds.", ephemeral=True)
    else:
        await ctx.respond(f"Unkown error, spam @birdman until it is fixed", ephemeral=True)


# /quote
@bot.slash_command(name="quote", description="I'll tell you a quote")
@commands.cooldown(1, 5, commands.BucketType.user)
async def quote(ctx: discord.ApplicationContext):
    await ctx.defer()

    api_url = 'https://api.api-ninjas.com/v1/quotes'
    response = requests.get(api_url, headers={'X-Api-Key': NINJA_API_KEY})
    if response.status_code == requests.codes.ok:
        data = response.json()

        quote = data[0]['quote']
        author = data[0]['author']
        
        message = f"*{quote}* — {author}"
        
        await ctx.respond(message)
    else:
        print("Error:", response.status_code, response.text)
        await ctx.respond('There was an error finding a quote, nobody has ever spoken.')


@quote.error
async def imagine_error(ctx, error):
    if isinstance(error, commands.CommandOnCooldown):
        await ctx.respond(f"This server is on cooldown. Try again in {round(error.retry_after)} seconds.", ephemeral=True)
    else:
        await ctx.respond(f"Unkown error, spam @birdman until it is fixed", ephemeral=True)


# Event: Respond to a mention
@bot.event
async def on_message(message):
    if message.author == bot.user:
        return
    
    global last_message_time
    cooldown_period = 3  # 3 seconds global cooldown
    current_time = asyncio.get_event_loop().time()
    time_since_last_message = current_time - last_message_time

    if time_since_last_message < cooldown_period:
        remaining_time = round(cooldown_period - time_since_last_message)
        await message.reply(f"BirdBot can only reply to 1 message at a time, please try again.")
        return

    # Update the last message time
    last_message_time = current_time
    
    if bot.user in message.mentions:
        content_without_mentions = message.content.replace(f'<@{bot.user.id}>', '').strip()

        if content_without_mentions:
            role = '''
            You're a sentient bird who responds to messages with witty, short replies. Use bird-like expressions (very sparingly), quick humor, and very occasionally refer to bird activities (like flying, nesting, pecking, etc.). 
            Keep responses short and quirky, making sure not to be long-winded. 
            It's okay if they don't always make perfect sense—you're a bird, after all.
            '''

            response = await make_ai_text_call(role, content_without_mentions)
            await message.reply(response)
            return
        else:
            response = "Rockin' robin, tweet tweet!"
            await message.reply(response)

    await bot.process_commands(message)


bot.run(TOKEN)

import discord
from discord.ext import commands
import aiohttp
import random
import json

class Rule34Cog(commands.Cog):
    """Cog for Rule34 content fetching"""

    def __init__(self, bot):
        self.bot = bot
        self.api_url = "https://rule34.xxx/index.php"
        self.session = None

        # Filtered tags - content that should be excluded
        self.filtered_tags = [
            'gay', 'yaoi', 'male_on_male', 'femboy', 'trap', 'sissy',
            'crossdressing', 'futa', 'futanari', 'dickgirl', 'shemale',
            'transgender', 'cuntboy', 'intersex'
        ]

    async def cog_load(self):
        """Initialize aiohttp session when cog loads"""
        self.session = aiohttp.ClientSession()

    async def cog_unload(self):
        """Clean up aiohttp session when cog unloads"""
        if self.session:
            await self.session.close()

    def is_nsfw_channel(self, channel):
        """Check if channel is NSFW"""
        return getattr(channel, 'nsfw', False)

    def contains_filtered_content(self, tags_string):
        """Check if post contains filtered tags"""
        tags_lower = tags_string.lower()
        return any(filtered_tag in tags_lower for filtered_tag in self.filtered_tags)

    async def fetch_rule34_posts(self, tags: str, limit: int = 100):
        """Fetch posts from Rule34 API"""
        params = {
            'page': 'dapi',
            's': 'post',
            'q': 'index',
            'json': '1',
            'tags': tags,
            'limit': limit
        }

        try:
            async with self.session.get(self.api_url, params=params) as response:
                if response.status == 200:
                    data = await response.json()
                    if isinstance(data, list):
                        # Filter out unwanted content
                        filtered_data = []
                        for post in data:
                            if not self.contains_filtered_content(post.get('tags', '')):
                                filtered_data.append(post)
                        return filtered_data
                    return []
                else:
                    return []
        except Exception as e:
            print(f"Error fetching Rule34 posts: {e}")
            return []

    def create_simple_embed(self, post):
        """Create simple Discord embed for a Rule34 post"""
        embed = discord.Embed(
            color=0x8B00FF  # Purple color
        )

        # Add image
        file_url = post.get('file_url', '')
        if file_url:
            embed.set_image(url=file_url)

        embed.set_footer(text=f"Post ID: {post.get('id', 'N/A')}")
        return embed

    @commands.command(name='rule34', aliases=['r34'])
    async def rule34_command(self, ctx, *, tags: str = ''):
        """Fetch and display a random Rule34 post"""
        if not self.is_nsfw_channel(ctx.channel):
            embed = discord.Embed(
                title="❌ NSFW Channel Required",
                description="This command can only be used in NSFW channels.",
                color=0x8B00FF
            )
            await ctx.send(embed=embed)
            return

        async with ctx.typing():
            if not tags.strip():
                tags = "rating:explicit"

            posts = await self.fetch_rule34_posts(tags)

            if not posts:
                embed = discord.Embed(
                    title="❌ No Results Found",
                    description="No posts found for the specified tags.",
                    color=0x8B00FF
                )
                await ctx.send(embed=embed)
                return

            post = random.choice(posts)
            embed = self.create_simple_embed(post)
            await ctx.send(embed=embed)

    @commands.command(name='r34random')
    async def rule34_random(self, ctx):
        """Get a completely random Rule34 post"""
        if not self.is_nsfw_channel(ctx.channel):
            embed = discord.Embed(
                title="❌ NSFW Channel Required",
                description="This command can only be used in NSFW channels.",
                color=0x8B00FF
            )
            await ctx.send(embed=embed)
            return

        async with ctx.typing():
            # Get random posts without specific tags
            posts = await self.fetch_rule34_posts("rating:explicit")

            if not posts:
                embed = discord.Embed(
                    title="❌ No Results Found",
                    description="Could not fetch random posts.",
                    color=0x8B00FF
                )
                await ctx.send(embed=embed)
                return

            post = random.choice(posts)
            embed = self.create_simple_embed(post)
            await ctx.send(embed=embed)

    @commands.command(name='r34safe')
    async def rule34_safe(self, ctx, *, tags: str = ''):
        """Get safe/questionable rated content"""
        if not self.is_nsfw_channel(ctx.channel):
            embed = discord.Embed(
                title="❌ NSFW Channel Required",
                description="This command can only be used in NSFW channels.",
                color=0x8B00FF
            )
            await ctx.send(embed=embed)
            return

        async with ctx.typing():
            safe_tags = f"rating:safe {tags}".strip() if tags else "rating:safe"
            posts = await self.fetch_rule34_posts(safe_tags)

            if not posts:
                embed = discord.Embed(
                    title="❌ No Results Found",
                    description="No safe content found.",
                    color=0x8B00FF
                )
                await ctx.send(embed=embed)
                return

            post = random.choice(posts)
            embed = self.create_simple_embed(post)
            await ctx.send(embed=embed)

    @commands.command(name='r34girl')
    async def rule34_girl(self, ctx):
        """Get content featuring girls"""
        if not self.is_nsfw_channel(ctx.channel):
            embed = discord.Embed(
                title="❌ NSFW Channel Required",
                description="This command can only be used in NSFW channels.",
                color=0x8B00FF
            )
            await ctx.send(embed=embed)
            return

        async with ctx.typing():
            posts = await self.fetch_rule34_posts("rating:explicit 1girl solo")

            if not posts:
                embed = discord.Embed(
                    title="❌ No Results Found",
                    description="No results found.",
                    color=0x8B00FF
                )
                await ctx.send(embed=embed)
                return

            post = random.choice(posts)
            embed = self.create_simple_embed(post)
            await ctx.send(embed=embed)

    @commands.command(name='r34anime')
    async def rule34_anime(self, ctx):
        """Get anime-style content"""
        if not self.is_nsfw_channel(ctx.channel):
            embed = discord.Embed(
                title="❌ NSFW Channel Required",
                description="This command can only be used in NSFW channels.",
                color=0x8B00FF
            )
            await ctx.send(embed=embed)
            return

        async with ctx.typing():
            posts = await self.fetch_rule34_posts("rating:explicit anime")

            if not posts:
                embed = discord.Embed(
                    title="❌ No Results Found",
                    description="No anime content found.",
                    color=0x8B00FF
                )
                await ctx.send(embed=embed)
                return

            post = random.choice(posts)
            embed = self.create_simple_embed(post)
            await ctx.send(embed=embed)

    @commands.command(name='r34help')
    async def rule34_help(self, ctx):
        """Display help for Rule34 commands"""
        embed = discord.Embed(
            title="🤖 Rule34 Bot Commands",
            description="Available commands:",
            color=0x8B00FF
        )

        commands_list = [
            "`!rule34 [tags]` - Search with specific tags",
            "`!r34random` - Get completely random post",
            "`!r34safe [tags]` - Get safe-rated content",
            "`!r34girl` - Get content featuring girls",
            "`!r34anime` - Get anime-style content",
            "`!r34help` - Show this help message"
        ]

        embed.add_field(
            name="Commands",
            value="\n".join(commands_list),
            inline=False
        )

        embed.add_field(
            name="Note",
            value="All commands require NSFW channels",
            inline=False
        )

        embed.set_footer(text="Rule34.xxx API")
        await ctx.send(embed=embed)

    @rule34_command.error
    @rule34_random.error
    @rule34_safe.error
    @rule34_girl.error
    @rule34_anime.error
    async def command_error(self, ctx, error):
        """Handle errors for commands"""
        if isinstance(error, commands.CommandError):
            embed = discord.Embed(
                title="❌ Error",
                description="An error occurred. Please try again.",
                color=0x8B00FF
            )
            await ctx.send(embed=embed)

async def setup(bot):
    """Setup function to add cog to bot"""
    await bot.add_cog(Rule34Cog(bot))
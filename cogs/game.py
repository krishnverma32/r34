import discord
from discord.ext import commands
from discord import app_commands
import aiohttp
import asyncio
import os
import random
import logging
import re
import json
from typing import List, Dict, Optional, Literal
from datetime import datetime

# Enhanced logging setup
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("NSFWGames")

class GameResult:
    """Data class for game results"""
    def __init__(self, title: str, url: str, description: str, rating: str = "N/A", 
                 price: str = "Free", tags: List[str] = None, image_url: str = None):
        self.title = title
        self.url = url
        self.description = description
        self.rating = rating
        self.price = price
        self.tags = tags or []
        self.image_url = image_url

class NSFWGames(commands.Cog):
    """🔥 Advanced NSFW Games Discovery Bot 🎮"""

    def __init__(self, bot):
        self.bot = bot
        self.session = None
        self.itch_key = os.getenv("ITCH_API_KEY")
        self.cache = {}  # Simple caching system
        self.cache_timeout = 300  # 5 minutes

        # Creative game categories and emojis
        self.game_categories = {
            "visual_novel": {"emoji": "📖", "tags": ["visual-novel", "story-rich"]},
            "action": {"emoji": "⚔️", "tags": ["action", "combat"]},
            "puzzle": {"emoji": "🧩", "tags": ["puzzle", "strategy"]},
            "simulation": {"emoji": "🏠", "tags": ["simulation", "life-sim"]},
            "rpg": {"emoji": "🗡️", "tags": ["rpg", "adventure"]},
            "horror": {"emoji": "👻", "tags": ["horror", "thriller"]},
            "romance": {"emoji": "💕", "tags": ["romance", "dating"]},
            "fantasy": {"emoji": "🧙", "tags": ["fantasy", "magic"]}
        }

        # Fun loading messages
        self.loading_messages = [
            "🔍 Searching the depths of the internet...",
            "🎮 Discovering hidden gems...",
            "🔥 Finding spicy content...",
            "✨ Conjuring magical experiences...",
            "🚀 Launching into adult gaming space...",
            "🎯 Targeting your interests...",
            "💎 Mining for quality content...",
            "🌟 Curating exceptional experiences..."
        ]

    async def cog_load(self):
        """Initialize aiohttp session when cog loads"""
        self.session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=15),
            headers={'User-Agent': 'NSFWGames Discord Bot 1.0'}
        )
        logger.info("NSFWGames cog loaded successfully! 🎮")

    async def cog_unload(self):
        """Clean up session when cog unloads"""
        if self.session:
            await self.session.close()
        logger.info("NSFWGames cog unloaded. Session closed.")

    def _is_cache_valid(self, cache_key: str) -> bool:
        """Check if cache entry is still valid"""
        if cache_key not in self.cache:
            return False
        return (datetime.now() - self.cache[cache_key]['timestamp']).seconds < self.cache_timeout

    def _get_from_cache(self, cache_key: str) -> Optional[List[GameResult]]:
        """Get data from cache if valid"""
        if self._is_cache_valid(cache_key):
            return self.cache[cache_key]['data']
        return None

    def _store_in_cache(self, cache_key: str, data: List[GameResult]):
        """Store data in cache"""
        self.cache[cache_key] = {
            'data': data,
            'timestamp': datetime.now()
        }

    async def _safe_fetch(self, url: str, return_json: bool = True, headers: Dict = None) -> Optional[any]:
        """Enhanced fetch with better error handling and retries"""
        if not self.session:
            await self.cog_load()

        for attempt in range(3):
            try:
                async with self.session.get(url, headers=headers) as resp:
                    if resp.status == 200:
                        return await resp.json() if return_json else await resp.text()
                    elif resp.status == 429:  # Rate limited
                        wait_time = 2 ** attempt
                        logger.warning(f"Rate limited. Waiting {wait_time}s before retry...")
                        await asyncio.sleep(wait_time)
                    else:
                        logger.warning(f"HTTP {resp.status} for {url}")

            except asyncio.TimeoutError:
                logger.warning(f"Timeout on {url} (attempt {attempt + 1}/3)")
                await asyncio.sleep(1)
            except Exception as e:
                logger.error(f"Error fetching {url}: {e}")
                if attempt == 2:  # Last attempt
                    return None
                await asyncio.sleep(1)

        return None

    async def _fetch_itch_games(self, tags: List[str], page: int = 1) -> List[GameResult]:
        """Fetch games from Itch.io with enhanced data"""
        cache_key = f"itch_{','.join(tags)}_{page}"
        cached = self._get_from_cache(cache_key)
        if cached:
            return cached

        if not self.itch_key:
            logger.warning("No Itch.io API key found. Using fallback method.")
            return await self._fetch_itch_fallback(tags, page)

        url = f"https://itch.io/api/1/{self.itch_key}/search/games"
        params = {
            'tags': ','.join(tags),
            'page': page,
            'format': 'json'
        }

        # Build URL with parameters
        param_str = '&'.join([f"{k}={v}" for k, v in params.items()])
        full_url = f"{url}?{param_str}"

        data = await self._safe_fetch(full_url)
        if not data or 'games' not in data:
            return []

        games = []
        for game_data in data.get('games', [])[:10]:  # Limit to 10 results
            game = GameResult(
                title=game_data.get('title', 'Unknown Title'),
                url=game_data.get('url', ''),
                description=self._clean_description(game_data.get('short_text', 'No description available.')),
                rating=f"⭐ {game_data.get('rating', 'N/A')}",
                price=game_data.get('price_text', 'Free'),
                tags=game_data.get('tags', []),
                image_url=game_data.get('cover_url')
            )
            games.append(game)

        self._store_in_cache(cache_key, games)
        return games

    async def _fetch_itch_fallback(self, tags: List[str], page: int = 1) -> List[GameResult]:
        """Fallback method for Itch.io when API key is not available"""
        tag_str = '+'.join(tags)
        url = f"https://itch.io/games/tag-{tag_str}?format=json&page={page}"

        html = await self._safe_fetch(url, return_json=False)
        if not html:
            return []

        # Parse HTML for game links (simplified approach)
        game_pattern = r'<a[^>]+href="([^"]+)"[^>]*class="[^"]*game_link[^"]*"[^>]*>([^<]+)</a>'
        matches = re.findall(game_pattern, html, re.IGNORECASE)

        games = []
        for url, title in matches[:8]:  # Limit results
            if url.startswith('/'):
                url = f"https://itch.io{url}"

            game = GameResult(
                title=title.strip(),
                url=url,
                description="Adult game from Itch.io",
                rating="N/A",
                price="Varies"
            )
            games.append(game)

        return games

    async def _fetch_f95_games(self, tag: str = None, page: int = 1) -> List[GameResult]:
        """Enhanced F95Zone scraping with better parsing"""
        cache_key = f"f95_{tag}_{page}"
        cached = self._get_from_cache(cache_key)
        if cached:
            return cached

        base_url = "https://f95zone.to/latest/"
        if tag:
            base_url += f"?tags={tag}"

        html = await self._safe_fetch(base_url, return_json=False)
        if not html:
            return []

        # Enhanced regex for better game extraction
        pattern = r'<a href="(/threads/[^"]+)"[^>]*>(?:<[^>]*>)*([^<]+?)(?:\s*\[[^\]]+\])?</a>'
        matches = re.findall(pattern, html, re.DOTALL)

        games = []
        start_idx = (page - 1) * 6
        end_idx = start_idx + 6

        for link, title in matches[start_idx:end_idx]:
            clean_title = re.sub(r'\s+', ' ', title).strip()
            if len(clean_title) < 3:  # Skip very short titles
                continue

            game = GameResult(
                title=clean_title,
                url=f"https://f95zone.to{link}",
                description="🔞 Adult game discussion from F95Zone community",
                rating="Community Rated",
                price="Varies",
                tags=["adult", "community"]
            )
            games.append(game)

        self._store_in_cache(cache_key, games)
        return games

    async def _fetch_dlsite_games(self, category: str = None, page: int = 1) -> List[GameResult]:
        """Enhanced DLSite integration with better data"""
        cache_key = f"dlsite_{category}_{page}"
        cached = self._get_from_cache(cache_key)
        if cached:
            return cached

        # Mock data for demonstration (replace with actual DLSite API if available)
        mock_games = [
            GameResult(
                title="Fantasy Adventure RPG",
                url="https://www.dlsite.com/maniax/work/=/product_id/RJ123456.html",
                description="🏰 Epic fantasy adventure with mature themes",
                rating="⭐ 4.5/5",
                price="¥1,200",
                tags=["rpg", "fantasy", "adult"]
            ),
            GameResult(
                title="Visual Novel Romance",
                url="https://www.dlsite.com/maniax/work/=/product_id/RJ789012.html",
                description="💕 Romantic story with multiple endings",
                rating="⭐ 4.2/5",
                price="¥800",
                tags=["visual-novel", "romance"]
            ),
            GameResult(
                title="Action Platformer",
                url="https://www.dlsite.com/maniax/work/=/product_id/RJ345678.html",
                description="⚔️ Fast-paced action with adult content",
                rating="⭐ 4.0/5",
                price="¥1,500",
                tags=["action", "platformer"]
            )
        ]

        # Simulate pagination
        start_idx = (page - 1) * 3
        end_idx = start_idx + 3
        games = mock_games[start_idx:end_idx] if start_idx < len(mock_games) else []

        self._store_in_cache(cache_key, games)
        return games

    def _clean_description(self, description: str) -> str:
        """Clean and enhance game descriptions"""
        if not description or description.lower() in ['no description', 'no description.', '']:
            return "🎮 Exciting adult gaming experience awaits!"

        # Remove HTML tags
        clean_desc = re.sub(r'<[^>]+>', '', description)

        # Limit length and add emoji
        if len(clean_desc) > 100:
            clean_desc = clean_desc[:97] + "..."

        return f"🎯 {clean_desc}"

    def _create_game_embed(self, game: GameResult, site: str) -> discord.Embed:
        """Create enhanced embed for game display"""
        # Choose color based on site
        colors = {
            'itch': discord.Color.orange(),
            'f95': discord.Color.purple(),
            'dlsite': discord.Color.blue()
        }

        embed = discord.Embed(
            title=f"🎮 {game.title}",
            url=game.url,
            description=game.description,
            color=colors.get(site, discord.Color.red()),
            timestamp=datetime.now()
        )

        # Add fields with enhanced information
        embed.add_field(name="💰 Price", value=game.price, inline=True)
        embed.add_field(name="📊 Rating", value=game.rating, inline=True)
        embed.add_field(name="🏷️ Source", value=site.upper(), inline=True)

        if game.tags:
            tags_str = " • ".join([f"`{tag}`" for tag in game.tags[:5]])
            embed.add_field(name="🔖 Tags", value=tags_str, inline=False)

        # Add thumbnail if available
        if game.image_url:
            embed.set_thumbnail(url=game.image_url)

        # Add footer with helpful info
        embed.set_footer(
            text=f"🔞 NSFW Content • Use reactions to get more games",
            icon_url=self.bot.user.avatar.url if self.bot.user.avatar else None
        )

        return embed

    # ===================
    # SLASH COMMANDS
    # ===================

    @app_commands.command(name="game", description="🎮 Get a random NSFW game from various sites")
    @app_commands.describe(
        site="Choose the gaming site to search",
        tag="Optional: Filter by game tag/category"
    )
    @app_commands.choices(site=[
        app_commands.Choice(name="🍃 Itch.io", value="itch"),
        app_commands.Choice(name="🟣 F95Zone", value="f95"),
        app_commands.Choice(name="🟦 DLSite", value="dlsite")
    ])
    async def slash_game(self, interaction: discord.Interaction, 
                        site: app_commands.Choice[str], 
                        tag: str = None):
        """Slash command for getting a single random game"""
        await interaction.response.defer()

        # Check NSFW channel
        if not interaction.channel.is_nsfw():
            embed = discord.Embed(
                title="🚫 NSFW Channel Required",
                description="This command only works in NSFW channels for safety!",
                color=discord.Color.red()
            )
            return await interaction.followup.send(embed=embed, ephemeral=True)

        await self._handle_slash_game_request(interaction, site.value, tag, single=True)

    @app_commands.command(name="gamelist", description="📋 List NSFW games with pagination")
    @app_commands.describe(
        site="Choose the gaming site to search",
        page="Page number (default: 1)",
        tag="Optional: Filter by game tag/category"
    )
    @app_commands.choices(site=[
        app_commands.Choice(name="🍃 Itch.io", value="itch"),
        app_commands.Choice(name="🟣 F95Zone", value="f95"),
        app_commands.Choice(name="🟦 DLSite", value="dlsite")
    ])
    async def slash_gamelist(self, interaction: discord.Interaction, 
                           site: app_commands.Choice[str], 
                           page: int = 1,
                           tag: str = None):
        """Slash command for getting a list of games"""
        await interaction.response.defer()

        # Check NSFW channel
        if not interaction.channel.is_nsfw():
            embed = discord.Embed(
                title="🚫 NSFW Channel Required",
                description="This command only works in NSFW channels for safety!",
                color=discord.Color.red()
            )
            return await interaction.followup.send(embed=embed, ephemeral=True)

        if page < 1:
            page = 1

        await self._handle_slash_game_request(interaction, site.value, tag, single=False, page=page)

    @app_commands.command(name="categories", description="🏷️ Show available game categories and tags")
    async def slash_categories(self, interaction: discord.Interaction):
        """Slash command to show game categories"""
        embed = discord.Embed(
            title="🎮 Game Categories & Tags",
            description="Choose from these exciting categories!",
            color=discord.Color.blurple()
        )

        for category, info in self.game_categories.items():
            tags = " • ".join([f"`{tag}`" for tag in info["tags"]])
            embed.add_field(
                name=f"{info['emoji']} {category.replace('_', ' ').title()}",
                value=tags,
                inline=True
            )

        embed.set_footer(text="Use these tags with /game or /gamelist commands")
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="gamehelp", description="📖 Show detailed help for NSFW games commands")
    async def slash_game_help(self, interaction: discord.Interaction):
        """Slash command for detailed help"""
        embed = discord.Embed(
            title="🎮 NSFW Games Bot - Complete Guide",
            description="Your gateway to adult gaming discoveries!",
            color=discord.Color.gold()
        )

        embed.add_field(
            name="🎯 Slash Commands",
            value=(
                "`/game [site] [tag]` - Get random game\n"
                "`/gamelist [site] [page] [tag]` - List games\n"
                "`/gamehelp` - Show this help\n"
                "`/categories` - Show game categories"
            ),
            inline=False
        )

        embed.add_field(
            name="🎯 Text Commands",
            value=(
                "`!nsfwgame [site] [tag]` - Get random game\n"
                "`!nsfwlist [site] [page] [tag]` - List games\n"
                "`!gamehelp` - Show this help\n"
                "`!categories` - Show game categories"
            ),
            inline=False
        )

        embed.add_field(
            name="🌐 Supported Sites",
            value=(
                "**itch** - Itch.io indie games\n"
                "**f95** - F95Zone community\n"
                "**dlsite** - Japanese adult content"
            ),
            inline=False
        )

        embed.add_field(
            name="🏷️ Popular Tags",
            value="`visual-novel`, `rpg`, `action`, `puzzle`, `romance`, `fantasy`, `horror`",
            inline=False
        )

        embed.add_field(
            name="⚠️ Important Notes",
            value=(
                "• Only works in NSFW channels\n"
                "• Content is 18+ only\n"
                "• Respect community guidelines\n"
                "• Use responsibly"
            ),
            inline=False
        )

        embed.set_footer(text="Made with ❤️ for adult gaming enthusiasts")
        await interaction.response.send_message(embed=embed)

    # Tag autocomplete for slash commands
    @slash_game.autocomplete('tag')
    @slash_gamelist.autocomplete('tag')
    async def tag_autocomplete(self, interaction: discord.Interaction, current: str) -> List[app_commands.Choice[str]]:
        """Provide autocomplete suggestions for tags"""
        # Common tags to suggest
        common_tags = [
            "visual-novel", "rpg", "action", "puzzle", "simulation", 
            "romance", "fantasy", "horror", "adventure", "strategy",
            "platformer", "indie", "2d", "3d", "anime"
        ]

        # Add category names
        category_names = list(self.game_categories.keys())
        all_suggestions = common_tags + category_names

        # Filter suggestions based on current input
        if current:
            filtered = [tag for tag in all_suggestions if current.lower() in tag.lower()]
        else:
            filtered = all_suggestions[:25]  # Discord limit

        return [
            app_commands.Choice(name=f"🏷️ {tag}", value=tag) 
            for tag in filtered[:25]
        ]

    # ===================
    # TEXT COMMANDS (Existing)
    # ===================

    @commands.command(name="nsfwgame", aliases=["adultgame", "game18"])
    async def nsfwgame_command(self, ctx, site: str = "itch", *, tag: str = None):
        """🎮 Get a random NSFW game from various sites!

        Usage: !nsfwgame [site] [tag]
        Sites: itch, f95, dlsite
        Tags: visual-novel, rpg, action, etc.
        """
        await self._handle_game_request(ctx, site, tag, single=True)

    @commands.command(name="nsfwlist", aliases=["gamelist", "adultlist"])
    async def nsfwlist_command(self, ctx, site: str = "itch", page: int = 1, *, tag: str = None):
        """📋 List NSFW games with pagination!

        Usage: !nsfwlist [site] [page] [tag]
        Sites: itch, f95, dlsite
        Page: 1, 2, 3, etc.
        """
        await self._handle_game_request(ctx, site, tag, single=False, page=page)

    @commands.command(name="gamehelp", aliases=["adulthelp"])
    async def game_help(self, ctx):
        """📖 Show detailed help for NSFW games commands"""
        embed = discord.Embed(
            title="🎮 NSFW Games Bot - Complete Guide",
            description="Your gateway to adult gaming discoveries!",
            color=discord.Color.gold()
        )

        embed.add_field(
            name="🎯 Slash Commands",
            value=(
                "`/game [site] [tag]` - Get random game\n"
                "`/gamelist [site] [page] [tag]` - List games\n"
                "`/gamehelp` - Show this help\n"
                "`/categories` - Show game categories"
            ),
            inline=False
        )

        embed.add_field(
            name="🎯 Text Commands",
            value=(
                "`!nsfwgame [site] [tag]` - Get random game\n"
                "`!nsfwlist [site] [page] [tag]` - List games\n"
                "`!gamehelp` - Show this help\n"
                "`!categories` - Show game categories"
            ),
            inline=False
        )

        embed.add_field(
            name="🌐 Supported Sites",
            value=(
                "**itch** - Itch.io indie games\n"
                "**f95** - F95Zone community\n"
                "**dlsite** - Japanese adult content"
            ),
            inline=False
        )

        embed.add_field(
            name="🏷️ Popular Tags",
            value="`visual-novel`, `rpg`, `action`, `puzzle`, `romance`, `fantasy`, `horror`",
            inline=False
        )

        embed.add_field(
            name="⚠️ Important Notes",
            value=(
                "• Only works in NSFW channels\n"
                "• Content is 18+ only\n"
                "• Respect community guidelines\n"
                "• Use responsibly"
            ),
            inline=False
        )

        embed.set_footer(text="Made with ❤️ for adult gaming enthusiasts")
        await ctx.send(embed=embed)

    @commands.command(name="categories")
    async def show_categories(self, ctx):
        """🏷️ Show available game categories with emojis"""
        embed = discord.Embed(
            title="🎮 Game Categories & Tags",
            description="Choose from these exciting categories!",
            color=discord.Color.blurple()
        )

        for category, info in self.game_categories.items():
            tags = " • ".join([f"`{tag}`" for tag in info["tags"]])
            embed.add_field(
                name=f"{info['emoji']} {category.replace('_', ' ').title()}",
                value=tags,
                inline=True
            )

        embed.set_footer(text="Use these tags with !nsfwgame or !nsfwlist commands")
        await ctx.send(embed=embed)

    # ===================
    # SHARED HANDLERS
    # ===================

    async def _handle_slash_game_request(self, interaction: discord.Interaction, site: str, tag: str, single: bool = True, page: int = 1):
        """Enhanced unified handler for slash command game requests"""
        # Validate site
        site = site.lower()
        valid_sites = ["itch", "f95", "dlsite"]
        if site not in valid_sites:
            embed = discord.Embed(
                title="❌ Invalid Site",
                description=f"Please choose from: `{', '.join(valid_sites)}`",
                color=discord.Color.red()
            )
            return await interaction.followup.send(embed=embed, ephemeral=True)

        # Show loading message
        loading_msg = random.choice(self.loading_messages)
        embed = discord.Embed(
            title="🔄 Searching...",
            description=loading_msg,
            color=discord.Color.blue()
        )
        await interaction.followup.send(embed=embed)

        try:
            # Fetch games based on site
            games = []
            if site == "itch":
                tags = ["adult"]
                if tag:
                    # Check if tag matches a category
                    if tag.lower() in self.game_categories:
                        tags.extend(self.game_categories[tag.lower()]["tags"])
                    else:
                        tags.append(tag.lower())
                games = await self._fetch_itch_games(tags, page)

            elif site == "f95":
                games = await self._fetch_f95_games(tag, page)

            elif site == "dlsite":
                games = await self._fetch_dlsite_games(tag, page)

            if not games:
                embed = discord.Embed(
                    title="😔 No Results Found",
                    description=f"No games found on {site.upper()} with your criteria.\nTry different tags or check back later!",
                    color=discord.Color.orange()
                )
                embed.set_footer(text="Tip: Use /categories to see available tags")
                return await interaction.edit_original_response(embed=embed)

            if single:
                # Send single random game
                game = random.choice(games)
                embed = self._create_game_embed(game, site)
                await interaction.edit_original_response(embed=embed)

            else:
                # Send list of games
                embed = discord.Embed(
                    title=f"🎮 {site.upper()} Games (Page {page})",
                    description=f"Found {len(games)} games" + (f" with tag: `{tag}`" if tag else ""),
                    color=discord.Color.purple()
                )

                for i, game in enumerate(games, 1):
                    embed.add_field(
                        name=f"{i}. {game.title}",
                        value=f"[🔗 Play Now]({game.url})\n{game.description[:50]}...",
                        inline=False
                    )

                embed.set_footer(text=f"Page {page} • Use /gamelist {site} {page + 1} for next page")
                await interaction.edit_original_response(embed=embed)

        except Exception as e:
            logger.error(f"Error in slash game request: {e}")

            embed = discord.Embed(
                title="💥 Oops! Something Went Wrong",
                description="There was an error fetching games. Please try again later!",
                color=discord.Color.red()
            )
            embed.set_footer(text="If this persists, contact the bot administrator")
            await interaction.edit_original_response(embed=embed)

    async def _handle_game_request(self, ctx, site: str, tag: str, single: bool = True, page: int = 1):
        """Enhanced unified handler for text command game requests"""
        # Check if channel is NSFW
        if not ctx.channel.is_nsfw():
            embed = discord.Embed(
                title="🚫 NSFW Channel Required",
                description="This command only works in NSFW channels for safety!",
                color=discord.Color.red()
            )
            return await ctx.send(embed=embed, delete_after=10)

        # Validate site
        site = site.lower()
        valid_sites = ["itch", "f95", "dlsite"]
        if site not in valid_sites:
            embed = discord.Embed(
                title="❌ Invalid Site",
                description=f"Please choose from: `{', '.join(valid_sites)}`",
                color=discord.Color.red()
            )
            return await ctx.send(embed=embed, delete_after=10)

        # Show loading message
        loading_msg = random.choice(self.loading_messages)
        loading_embed = discord.Embed(
            title="🔄 Searching...",
            description=loading_msg,
            color=discord.Color.blue()
        )
        loading_message = await ctx.send(embed=loading_embed)
        try:
            # Fetch games based on site
            games = []
            if site == "itch":
                tags = ["adult"]
                if tag:
                    # Check if tag matches a category
                    if tag.lower() in self.game_categories:
                        tags.extend(self.game_categories[tag.lower()]["tags"])
                    else:
                        tags.append(tag.lower())
                games = await self._fetch_itch_games(tags, page)

            elif site == "f95":
                games = await self._fetch_f95_games(tag, page)

            elif site == "dlsite":
                games = await self._fetch_dlsite_games(tag, page)

        except Exception as e:
            self.logger.error(f"[GameFetcher] Error while fetching from {site}: {e}")
            games = []   # fallback if error happens


    
async def setup(bot):
    """Setup function to add cog to bot"""
    await bot.add_cog(NSFWGames(bot))
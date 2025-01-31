import os
import requests
from datetime import datetime, timezone
from rich.console import Console
from rich.table import Table
import yaml
from pathlib import Path
import orjson
import feedparser
from dateutil import parser as date_parser
import re
from concurrent.futures import ThreadPoolExecutor
from personalization import Personalization

class DevPostsFetcher:
    def __init__(self):
        self.console = Console()
        # API endpoints
        self.devto_api = "https://dev.to/api/articles"
        self.freecodecamp_rss = "https://www.freecodecamp.org/news/rss/"
        self.css_tricks_rss = "https://css-tricks.com/feed/"
        self.hackernoon_rss = "https://hackernoon.com/feed"
        self.stackoverflow_rss = "https://stackoverflow.blog/feed/"
        
        self.config_file = "config.yaml"
        self.load_config()
        self.personalization = Personalization(self.config['save_directory'])

    def load_config(self):
        """Load configuration from YAML file or create default if not exists."""
        try:
            config_path = Path(self.config_file)
            if not config_path.exists():
                self.console.print("[yellow]Config file not found, creating default config...[/yellow]")
                default_config = {
                    'tags': ['python', 'javascript', 'webdev', 'programming'],
                    'max_posts_per_source': 10,
                    'save_directory': 'saved_posts'
                }
                config_path.write_text(yaml.dump(default_config, default_flow_style=False))
                self.config = default_config
            else:
                self.console.print(f"[green]Loading config from {config_path.absolute()}[/green]")
                self.config = yaml.safe_load(config_path.read_text())
                self.console.print(f"[blue]Loaded config:[/blue] {self.config}")
        except Exception as e:
            self.console.print(f"[red]Error loading config: {str(e)}[/red]")
            raise

    def fetch_devto_posts(self):
        """Fetch posts from Dev.to"""
        self.console.print("\n[bold blue]Fetching posts from Dev.to...[/bold blue]")
        try:
            params = {
                'per_page': self.config['max_posts_per_source'],
                'tag': self.config['tags'][0]  # Dev.to only supports one tag at a time
            }
            response = requests.get(self.devto_api, params=params)
            response.raise_for_status()
            posts = response.json()
            self.console.print(f"[green]Successfully fetched {len(posts)} posts from Dev.to[/green]")
            return posts
        except requests.exceptions.RequestException as e:
            self.console.print(f"[red]Error making request to Dev.to API: {str(e)}[/red]")
            return []

    def process_rss_feed(self, feed_url, source_name):
        """Generic RSS feed processor"""
        try:
            feed = feedparser.parse(feed_url)
            
            if hasattr(feed, 'status') and feed.status != 200:
                raise requests.exceptions.RequestException(f"RSS feed returned status {feed.status}")
            
            posts = []
            for entry in feed.entries[:self.config['max_posts_per_source']]:
                # Extract tags from categories or tags
                tags = []
                if 'tags' in entry:
                    tags.extend(tag.term.lower() for tag in entry.tags)
                elif 'categories' in entry:
                    if isinstance(entry.categories[0], tuple):
                        tags.extend(cat[1].lower() for cat in entry.categories)
                    else:
                        tags.extend(cat.lower() for cat in entry.categories)
                
                # Extract reading time from content
                reading_time = 5  # default
                content = ''
                if 'content' in entry:
                    content = entry.content[0].value
                elif 'summary' in entry:
                    content = entry.summary
                
                time_match = re.search(r'(\d+)\s*min(ute)?s?\s*read', content, re.IGNORECASE)
                if time_match:
                    reading_time = int(time_match.group(1))
                else:
                    # Estimate reading time based on word count (average reading speed: 200 words/minute)
                    words = len(re.findall(r'\w+', content))
                    reading_time = max(1, round(words / 200))
                
                # Get author information
                author = entry.get('author', 'Unknown')
                
                # Parse and format the date with timezone
                try:
                    pub_date = date_parser.parse(entry.published)
                    if pub_date.tzinfo is None:
                        pub_date = pub_date.replace(tzinfo=timezone.utc)
                    published_at = pub_date.isoformat()
                except (ValueError, AttributeError):
                    published_at = datetime.now(timezone.utc).isoformat()
                
                post = {
                    'title': entry.title,
                    'description': entry.get('summary', ''),
                    'published_at': published_at,
                    'url': entry.link,
                    'user': {
                        'username': author,
                        'name': author
                    },
                    'tags': tags,
                    'public_reactions_count': 0,  # Not available in RSS
                    'comments_count': 0,  # Not available in RSS
                    'reading_time_minutes': reading_time,
                    'source': source_name
                }
                posts.append(post)
            
            self.console.print(f"[green]Successfully fetched {len(posts)} posts from {source_name}[/green]")
            return posts
        except Exception as e:
            self.console.print(f"[red]Error fetching {source_name} posts: {str(e)}[/red]")
            return []

    def fetch_css_tricks_posts(self):
        """Fetch posts from CSS-Tricks"""
        self.console.print("\n[bold green]Fetching posts from CSS-Tricks...[/bold green]")
        return self.process_rss_feed(self.css_tricks_rss, "CSS-Tricks")

    def fetch_hackernoon_posts(self):
        """Fetch posts from HackerNoon"""
        self.console.print("\n[bold magenta]Fetching posts from HackerNoon...[/bold magenta]")
        return self.process_rss_feed(self.hackernoon_rss, "HackerNoon")

    def fetch_stackoverflow_posts(self):
        """Fetch posts from Stack Overflow Blog"""
        self.console.print("\n[bold orange]Fetching posts from Stack Overflow Blog...[/bold orange]")
        return self.process_rss_feed(self.stackoverflow_rss, "Stack Overflow")

    def fetch_freecodecamp_posts(self):
        """Fetch posts from freeCodeCamp"""
        self.console.print("\n[bold green]Fetching posts from freeCodeCamp...[/bold green]")
        return self.process_rss_feed(self.freecodecamp_rss, "freeCodeCamp")

    def save_posts(self, posts, source):
        """Save posts to a JSON file in source-specific directory"""
        if not posts:
            return
            
        # Create save directory
        save_dir = Path(self.config['save_directory'])
        save_dir.mkdir(exist_ok=True)
        
        # Create source-specific directory
        source_dir = save_dir / source.lower().replace(' ', '-')
        source_dir.mkdir(exist_ok=True)
        
        # Save posts with timestamp
        timestamp = datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')
        filename = source_dir / f"posts_{timestamp}.json"
        
        # Add source to posts if not present
        for post in posts:
            if 'source' not in post:
                post['source'] = source
        
        with open(filename, 'wb') as f:
            f.write(orjson.dumps(posts, option=orjson.OPT_INDENT_2))
        
        self.console.print(f"[bold cyan]Saved {len(posts)} posts from {source} to {filename}[/bold cyan]")
        
        # Also save a latest.json file for quick access
        latest_file = source_dir / "latest.json"
        with open(latest_file, 'wb') as f:
            f.write(orjson.dumps(posts, option=orjson.OPT_INDENT_2))

    def display_posts(self, posts, source):
        """Display posts in a nice table format"""
        if not posts:
            return
            
        table = Table(title=f"{source} Posts")
        table.add_column("Title", style="cyan", no_wrap=False)
        table.add_column("Author", style="magenta")
        table.add_column("Date", style="green")
        table.add_column("Reading Time", style="yellow")
        
        for post in posts:
            table.add_row(
                post['title'],
                post['user']['username'],
                post['published_at'][:10],
                f"{post['reading_time_minutes']} min"
            )
        
        self.console.print(table)

    def fetch_and_process(self, fetch_func, source):
        """Helper function to fetch and process posts from a source"""
        try:
            posts = fetch_func()
            if posts:
                self.display_posts(posts, source)
                self.save_posts(posts, source)
            else:
                self.console.print(f"[yellow]No posts found from {source}[/yellow]")
            return posts
        except Exception as e:
            self.console.print(f"[red]Error processing {source} posts: {str(e)}[/red]")
            return []

    def run(self):
        """Main method to fetch and display posts"""
        self.console.print("[bold yellow]Starting Dev Posts Fetcher[/bold yellow]")
        
        # Define sources
        sources = [
            (self.fetch_devto_posts, "Dev.to"),
            (self.fetch_freecodecamp_posts, "freeCodeCamp"),
            (self.fetch_css_tricks_posts, "CSS-Tricks"),
            (self.fetch_hackernoon_posts, "HackerNoon"),
            (self.fetch_stackoverflow_posts, "Stack Overflow")
        ]
        
        # Fetch posts from all sources concurrently
        all_posts = []
        with ThreadPoolExecutor(max_workers=5) as executor:
            futures = [executor.submit(self.fetch_and_process, func, source) for func, source in sources]
            for future in futures:
                posts = future.result()
                all_posts.extend(posts)
        
        # Filter and deduplicate posts
        filtered_posts = self.personalization.filter_posts(all_posts)
        
        # Display filtered posts
        if filtered_posts:
            self.console.print("\n[bold cyan]Filtered and Personalized Posts[/bold cyan]")
            self.display_posts(filtered_posts, "All Sources")
            
            # Save filtered posts
            timestamp = datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')
            filtered_file = Path(self.config['save_directory']) / f"filtered_posts_{timestamp}.json"
            with open(filtered_file, 'wb') as f:
                f.write(orjson.dumps(filtered_posts, option=orjson.OPT_INDENT_2))
            self.console.print(f"[bold green]Saved {len(filtered_posts)} filtered posts to {filtered_file}[/bold green]")
        else:
            self.console.print("[yellow]No posts found after filtering[/yellow]")

if __name__ == "__main__":
    fetcher = DevPostsFetcher()
    fetcher.run()

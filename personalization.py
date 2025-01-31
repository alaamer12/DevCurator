from datetime import datetime, timedelta
import orjson
from pathlib import Path
from typing import Dict, List, Set
import re
from difflib import SequenceMatcher
from dateutil import tz

class Personalization:
    def __init__(self, save_directory: str = 'saved_posts'):
        self.save_directory = Path(save_directory)
        self.save_directory.mkdir(exist_ok=True)
        self.post_history_file = self.save_directory / 'post_history.json'
        self.user_preferences_file = self.save_directory / 'user_preferences.json'
        self.post_history = self._load_post_history()
        self.user_preferences = self._load_user_preferences()
        
    def _load_post_history(self) -> Dict:
        """Load post history from file or create if not exists"""
        if self.post_history_file.exists():
            try:
                with open(self.post_history_file, 'rb') as f:
                    data = orjson.loads(f.read())
                    # Convert lists back to sets
                    data['liked_posts'] = set(data.get('liked_posts', []))
                    data['dismissed_posts'] = set(data.get('dismissed_posts', []))
                    data['read_later'] = set(data.get('read_later', []))
                    return data
            except Exception as e:
                print(f"Error loading post history: {e}")
        
        # Return default history if file doesn't exist or has error
        return {
            'seen_posts': {},  # url -> timestamp
            'liked_posts': set(),  # urls
            'dismissed_posts': set(),  # urls
            'read_later': set(),  # urls
        }
    
    def _load_user_preferences(self) -> Dict:
        """Load user preferences from file or create if not exists"""
        if self.user_preferences_file.exists():
            with open(self.user_preferences_file, 'rb') as f:
                return orjson.loads(f.read())
        return {
            'favorite_tags': [],
            'blocked_tags': [],
            'favorite_authors': [],
            'blocked_authors': [],
            'preferred_sources': [],
            'min_reading_time': 0,
            'max_reading_time': 60,
            'similarity_threshold': 0.85  # for duplicate detection
        }
    
    def _save_post_history(self):
        """Save post history to file"""
        try:
            # Convert sets to lists for JSON serialization
            data = {
                'seen_posts': self.post_history['seen_posts'],
                'liked_posts': list(self.post_history['liked_posts']),
                'dismissed_posts': list(self.post_history['dismissed_posts']),
                'read_later': list(self.post_history['read_later'])
            }
            with open(self.post_history_file, 'wb') as f:
                f.write(orjson.dumps(data))
        except Exception as e:
            print(f"Error saving post history: {e}")
    
    def _save_user_preferences(self):
        """Save user preferences to file"""
        with open(self.user_preferences_file, 'wb') as f:
            f.write(orjson.dumps(self.user_preferences))
    
    def _calculate_text_similarity(self, text1: str, text2: str) -> float:
        """Calculate similarity between two texts using SequenceMatcher"""
        # Clean and normalize texts
        def clean_text(text):
            text = text.lower()
            text = re.sub(r'[^\w\s]', '', text)
            return ' '.join(text.split())
        
        text1 = clean_text(text1)
        text2 = clean_text(text2)
        return SequenceMatcher(None, text1, text2).ratio()
    
    def is_duplicate(self, new_post: Dict, existing_posts: List[Dict]) -> bool:
        """
        Check if a post is a duplicate using a sophisticated comparison algorithm
        that considers multiple factors:
        1. Exact URL match
        2. Title similarity
        3. Content similarity
        4. Author + date combination
        """
        # Check URL first (fastest check)
        if new_post['url'] in self.post_history['seen_posts']:
            return True
            
        for post in existing_posts:
            # Skip if posts are from different authors
            if post['user']['username'] != new_post['user']['username']:
                continue
                
            # Check title similarity
            title_similarity = self._calculate_text_similarity(
                post['title'], new_post['title']
            )
            
            # Check content similarity
            content_similarity = self._calculate_text_similarity(
                post['description'], new_post['description']
            )
            
            # Post is considered duplicate if either:
            # 1. Titles are very similar (>85%)
            # 2. Both title and content have moderate similarity (>70%)
            if (title_similarity > self.user_preferences['similarity_threshold'] or
                (title_similarity > 0.7 and content_similarity > 0.7)):
                return True
        
        return False
    
    def filter_posts(self, posts: List[Dict]) -> List[Dict]:
        """
        Filter posts based on user preferences and duplicate detection.
        Returns unique posts that match user preferences.
        """
        filtered_posts = []
        seen_urls = set()
        
        for post in posts:
            # Skip if URL already seen
            if post['url'] in seen_urls:
                continue
                
            # Skip if post is in dismissed list
            if post['url'] in self.post_history['dismissed_posts']:
                continue
                
            # Skip if reading time outside preferences
            reading_time = post['reading_time_minutes']
            if not (self.user_preferences['min_reading_time'] <= reading_time <= 
                   self.user_preferences['max_reading_time']):
                continue
                
            # Skip if author is blocked
            if post['user']['username'] in self.user_preferences['blocked_authors']:
                continue
                
            # Skip if has blocked tags
            if any(tag in self.user_preferences['blocked_tags'] 
                   for tag in post['tags']):
                continue
                
            # Skip if duplicate
            if not self.is_duplicate(post, filtered_posts):
                seen_urls.add(post['url'])
                # Store current time with timezone
                self.post_history['seen_posts'][post['url']] = datetime.now(tz.tzutc()).isoformat()
                filtered_posts.append(post)
        
        try:
            # Sort posts by relevance score
            scored_posts = [(self._calculate_post_score(post), post) 
                           for post in filtered_posts]
            scored_posts.sort(reverse=True)
            filtered_posts = [post for score, post in scored_posts]
        except Exception as e:
            print(f"Warning: Error during post scoring: {str(e)}. Using original order.")
        
        # Save updated history
        self._save_post_history()
        
        return filtered_posts
    
    def _calculate_post_score(self, post: Dict) -> float:
        """Calculate a relevance score for a post based on user preferences"""
        score = 1.0
        
        # Boost score for favorite authors
        if post['user']['username'] in self.user_preferences['favorite_authors']:
            score *= 1.5
            
        # Boost score for favorite tags
        favorite_tags = set(self.user_preferences['favorite_tags'])
        post_tags = set(post['tags'])
        matching_tags = favorite_tags & post_tags
        if matching_tags:
            score *= (1 + 0.2 * len(matching_tags))
            
        # Boost score for preferred sources
        if post.get('source') in self.user_preferences['preferred_sources']:
            score *= 1.3
            
        # Decay score based on age
        try:
            pub_date = datetime.fromisoformat(post['published_at'])
            if pub_date.tzinfo is None:
                # If the date has no timezone, assume UTC
                pub_date = pub_date.replace(tzinfo=tz.tzutc())
            current_time = datetime.now(tz.tzutc())
            age_days = (current_time - pub_date).days
            age_factor = max(0.5, 1 - (age_days / 30))  # 50% decay after 30 days
            score *= age_factor
        except (ValueError, TypeError):
            # If there's any issue with date parsing, don't modify the score
            pass
        
        return score
    
    def update_preferences(self, preferences: Dict):
        """Update user preferences"""
        self.user_preferences.update(preferences)
        self._save_user_preferences()
    
    def mark_post_action(self, url: str, action: str):
        """Mark a post as liked, dismissed, or read later"""
        if action == 'like':
            self.post_history['liked_posts'].add(url)
            if url in self.post_history['dismissed_posts']:
                self.post_history['dismissed_posts'].remove(url)
        elif action == 'dismiss':
            self.post_history['dismissed_posts'].add(url)
            if url in self.post_history['liked_posts']:
                self.post_history['liked_posts'].remove(url)
        elif action == 'read_later':
            self.post_history['read_later'].add(url)
        
        self._save_post_history()
    
    def get_reading_list(self) -> List[Dict]:
        """Get posts marked for reading later"""
        return [post for post in self.post_history['read_later']]
    
    def get_liked_posts(self) -> List[Dict]:
        """Get liked posts"""
        return [post for post in self.post_history['liked_posts']]
    
    def like_post(self, post):
        """Mark a post as liked"""
        post_url = post.get('url', '')
        if post_url:
            self.post_history['liked_posts'].add(post_url)
            self._save_post_history()
    
    def unlike_post(self, post):
        """Remove a post from liked posts"""
        url = post.get('url')
        if url:
            self.post_history['liked_posts'].discard(url)
            self._save_post_history()

    def undismiss_post(self, post):
        """Remove a post from dismissed posts"""
        url = post.get('url')
        if url:
            self.post_history['dismissed_posts'].discard(url)
            self._save_post_history()

    def dismiss_post(self, post):
        """Mark a post as dismissed"""
        post_url = post.get('url', '')
        if post_url:
            self.post_history['dismissed_posts'].add(post_url)
            self._save_post_history()
    
    def save_for_later(self, post):
        """Mark a post for reading later"""
        post_url = post.get('url', '')
        if post_url:
            self.post_history['read_later'].add(post_url)
            self._save_post_history()
    
    def remove_from_read_later(self, post):
        """Remove a post from read later list"""
        post_url = post.get('url', '')
        if post_url and post_url in self.post_history['read_later']:
            self.post_history['read_later'].remove(post_url)
            self._save_post_history()

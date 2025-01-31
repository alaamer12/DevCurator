import streamlit as st
import orjson
from pathlib import Path
import re
from datetime import datetime
import json
import yaml
from dev_posts_fetcher import DevPostsFetcher
from personalization import Personalization
import pandas as pd

# Initialize session state
if 'personalization' not in st.session_state:
    st.session_state.personalization = Personalization('saved_posts')
if 'posts' not in st.session_state:
    st.session_state.posts = []
if 'filtered_posts' not in st.session_state:
    st.session_state.filtered_posts = []
if 'selected_sources' not in st.session_state:
    st.session_state.selected_sources = []
if 'min_reading_time' not in st.session_state:
    st.session_state.min_reading_time = 0
if 'max_reading_time' not in st.session_state:
    st.session_state.max_reading_time = 60
if 'search' not in st.session_state:
    st.session_state.search = ''
if 'current_view' not in st.session_state:
    st.session_state.current_view = "all"
if 'current_page' not in st.session_state:
    st.session_state.current_page = 1
if 'posts_per_page' not in st.session_state:
    st.session_state.posts_per_page = 10
if 'sort_by' not in st.session_state:
    st.session_state.sort_by = 'newest'

def load_config():
    """Load configuration from YAML file"""
    config_path = Path("config.yaml")
    if config_path.exists():
        return yaml.safe_load(config_path.read_text())
    return {
        'tags': ['python', 'javascript', 'webdev', 'programming'],
        'max_posts_per_source': 10,
        'save_directory': 'saved_posts'
    }

def load_latest_posts():
    """Load posts from the unified filtered posts file"""
    save_dir = Path('saved_posts')
    filtered_file = save_dir / "filtered_posts.json"
    
    if not filtered_file.exists():
        return []
    
    try:
        with open(filtered_file, 'rb') as f:
            posts = orjson.loads(f.read())
            st.write(f"Debug: Loaded {len(posts)} posts from filtered_posts.json")
            return posts
    except Exception as e:
        st.error(f"Error loading posts: {str(e)}")
        return []

def get_latest_posts_from_sources():
    """Get the latest posts from all source directories"""
    save_dir = Path('saved_posts')
    all_posts = []
    
    # Get all source directories (excluding __pycache__ and filtered posts)
    source_dirs = [d for d in save_dir.iterdir() 
                  if d.is_dir() and d.name not in ['__pycache__']]
    
    for source_dir in source_dirs:
        post_files = list(source_dir.glob("posts_*.json"))
        if post_files:
            # Get the most recent file for this source
            latest_file = max(post_files, key=lambda x: x.stat().st_mtime)
            try:
                with open(latest_file, 'rb') as f:
                    posts = orjson.loads(f.read())
                    if isinstance(posts, list):
                        source_name = source_dir.name.replace('-', ' ').title()
                        for post in posts:
                            if 'source' not in post:
                                post['source'] = source_name
                        all_posts.extend(posts)
                        st.write(f"Debug: Loaded {len(posts)} posts from {source_name}")
            except Exception as e:
                st.error(f"Error loading {latest_file}: {str(e)}")
    
    return all_posts

def read_filtered_posts():
    """Read filtered posts from latest file"""
    if not Path('saved_posts/filtered_posts.json').exists():
        return []
    with open('saved_posts/filtered_posts.json', 'rb') as f:
        return orjson.loads(f.read())

def save_filtered_posts(posts):
    """Save filtered posts with current timestamp"""
    if not posts:
        return False
        
    save_dir = Path('saved_posts')
    save_dir.mkdir(exist_ok=True)
    
    old_filtered_file_data = read_filtered_posts()
    filtered_file = save_dir / f"filtered_posts.json"
    combined_posts = old_filtered_file_data + posts
    
    try:
        with open(filtered_file, 'wb') as f:
            f.write(orjson.dumps(combined_posts, option=orjson.OPT_INDENT_2))
        return filtered_file
    except Exception as e:
        st.error(f"Error saving filtered posts: {str(e)}")
        return None

def fetch_new_posts():
    """Fetch new posts using DevPostsFetcher"""
    with st.spinner("Fetching new posts..."):
        try:
            # Create and run the fetcher to get new posts
            fetcher = DevPostsFetcher()
            fetcher.run()
            
            # Combine latest posts from all sources
            new_posts = get_latest_posts_from_sources()
            
            if not new_posts:
                st.error("No posts were fetched. Please try again.")
                return
            
            # Save to unified filtered posts file
            if not save_filtered_posts(new_posts):
                st.error("Failed to save filtered posts.")
                return
            
            # Update session state
            st.session_state.posts = new_posts
            st.session_state.current_page = 1  # Reset to first page
            
            # Apply filters to update filtered_posts
            apply_filters()
            
            st.success(f"Successfully fetched and combined {len(new_posts)} posts from all sources!")
            st.rerun()  # Rerun the app to show new posts
            
        except Exception as e:
            st.error(f"Error fetching posts: {str(e)}")

def apply_filters():
    """Apply filters and update displayed posts"""
    if not st.session_state.posts:
        return
    
    # Start with all posts
    filtered = st.session_state.posts
    
    # Filter based on current view
    if st.session_state.current_view == "liked":
        liked_urls = st.session_state.personalization.post_history['liked_posts']
        filtered = [post for post in filtered if get_post_url(post) in liked_urls]
    elif st.session_state.current_view == "saved":
        saved_urls = st.session_state.personalization.post_history['read_later']
        filtered = [post for post in filtered if get_post_url(post) in saved_urls]
    else:  # all posts view
        # Apply search filter if needed
        search_term = st.session_state.get('search', '').lower()
        if search_term:
            filtered = [
                post for post in filtered
                if search_term in post.get('title', '').lower() or
                   search_term in post.get('description', '').lower() or
                   any(search_term in str(tag).lower() for tag in get_post_tags(post))
            ]
        
        # Apply source filter if selected
        if st.session_state.selected_sources:
            filtered = [
                post for post in filtered
                if get_post_source(post) in st.session_state.selected_sources
            ]
    
    # Sort posts
    filtered = sort_posts(filtered, st.session_state.get('sort_by', 'newest'))
    
    # Update filtered posts
    st.session_state.filtered_posts = filtered

def parse_post_date(post):
    """Parse post date with error handling"""
    try:
        date_str = post.get('date', '')
        if not date_str:
            return datetime.min
        return datetime.strptime(date_str, '%Y-%m-%d')
    except (ValueError, TypeError):
        return datetime.min

def sort_posts(posts, sort_by='newest'):
    """Sort posts by the specified criteria"""
    if sort_by == 'newest':
        return sorted(posts, key=parse_post_date, reverse=True)
    elif sort_by == 'oldest':
        return sorted(posts, key=parse_post_date)
    return posts

def get_post_source(post):
    """Get the source of a post, handling different post structures"""
    if 'source' in post:
        return post['source']
    elif 'type_of' in post:  # Dev.to posts
        return 'Dev.to'
    elif 'url' in post:
        url = post['url'].lower()
        if 'freecodecamp.org' in url:
            return 'freeCodeCamp'
        elif 'css-tricks.com' in url:
            return 'CSS-Tricks'
        elif 'hackernoon.com' in url:
            return 'HackerNoon'
        elif 'stackoverflow.blog' in url:
            return 'Stack Overflow'
    return 'Unknown'

def get_post_url(post):
    """Get the URL of a post, handling different post structures"""
    if 'url' in post:
        return post['url']
    elif 'path' in post:  # Dev.to posts
        return f"https://dev.to{post['path']}"
    return "#"

def get_post_date(post):
    """Get the publication date of a post, handling different formats"""
    if 'published_at' in post:
        return datetime.fromisoformat(post['published_at'].replace('Z', '+00:00')).strftime('%Y-%m-%d')
    elif 'readable_publish_date' in post:
        return post['readable_publish_date']
    return "Unknown date"

def get_post_tags(post):
    """Get tags from a post, handling different structures"""
    if 'tags' in post and isinstance(post['tags'], list):
        return post['tags']
    elif 'tag_list' in post and isinstance(post['tag_list'], list):
        return post['tag_list']
    return []

def render_post_card(post):
    """Render a post card with consistent styling"""
    try:
        with st.container():
            st.markdown("---")
            
            # Title and source
            col1, col2 = st.columns([4, 1])
            with col1:
                title = post.get('title', 'Untitled Post')
                url = get_post_url(post)
                st.markdown(f"### [{title}]({url})")
            with col2:
                source = get_post_source(post)
                st.markdown(f"**Source:** {source}")
            
            # Description
            desc = post.get('description', '')
            if desc:
                # Clean up HTML tags if present
                desc = re.sub('<[^<]+?>', '', desc)
                st.markdown(desc[:300] + "..." if len(desc) > 300 else desc)
            
            # Metadata
            col1, col2 = st.columns([1, 2])
            with col1:
                st.markdown(f"📅 {get_post_date(post)}")
            with col2:
                tags = get_post_tags(post)
                if tags:
                    st.markdown("🏷️ " + ", ".join(f"`{tag}`" for tag in tags[:3]))
            
            # Custom CSS for buttons
            st.markdown("""
            <style>
            .stButton button {
                width: 100%;
                padding: 10px 15px;
                margin: 5px 0;
                border-radius: 8px;
                font-size: 16px;
                transition: all 0.3s ease;
            }
            .stButton button:hover {
                transform: translateY(-2px);
                box-shadow: 0 2px 5px rgba(0,0,0,0.2);
            }
            div[data-testid="stHorizontalBlock"] > div[data-testid="column"] {
                text-align: center;
            }
            </style>
            """, unsafe_allow_html=True)
            
            # Action buttons row
            button_cols = st.columns(3)
            post_id = str(post.get('id', '')) or post.get('url', '')
            post_url = get_post_url(post)
            
            # Check post status
            is_liked = post_url in st.session_state.personalization.post_history['liked_posts']
            is_dismissed = post_url in st.session_state.personalization.post_history['dismissed_posts']
            is_saved = post_url in st.session_state.personalization.post_history['read_later']
            
            # Like button
            with button_cols[0]:
                if is_liked:
                    if st.button("❤️ Liked", 
                               key=f"unlike_{post_id}",
                               help="Click to unlike",
                               type="primary"):
                        st.session_state.personalization.unlike_post(post)
                        st.rerun()
                else:
                    if st.button("👍 Like", 
                               key=f"like_{post_id}",
                               help="Add to liked posts"):
                        st.session_state.personalization.like_post(post)
                        st.rerun()
            
            # Dismiss button
            with button_cols[1]:
                if is_dismissed:
                    if st.button("🚫 Dismissed", 
                               key=f"undismiss_{post_id}",
                               help="Click to un-dismiss",
                               type="secondary"):
                        st.session_state.personalization.undismiss_post(post)
                        st.rerun()
                else:
                    if st.button("👎 Dismiss", 
                               key=f"dismiss_{post_id}",
                               help="Hide this post"):
                        st.session_state.personalization.dismiss_post(post)
                        st.rerun()
            
            # Save button
            with button_cols[2]:
                if is_saved:
                    if st.button("📌 Saved", 
                               key=f"unsave_{post_id}",
                               help="Click to unsave",
                               type="primary"):
                        st.session_state.personalization.remove_from_read_later(post)
                        st.rerun()
                else:
                    if st.button("📑 Save", 
                               key=f"save_{post_id}",
                               help="Save for later"):
                        st.session_state.personalization.save_for_later(post)
                        st.rerun()
            
    except Exception as e:
        st.error(f"Error rendering post: {str(e)}")

def paginate_posts(posts, page_size=5):
    """Split posts into pages"""
    if 'current_page' not in st.session_state:
        st.session_state.current_page = 1
    
    total_posts = len(posts)
    total_pages = (total_posts + page_size - 1) // page_size
    
    # Ensure current page is valid
    st.session_state.current_page = max(1, min(st.session_state.current_page, total_pages))
    
    # Calculate start and end indices
    start_idx = (st.session_state.current_page - 1) * page_size
    end_idx = min(start_idx + page_size, total_posts)
    
    return posts[start_idx:end_idx], total_pages

def render_pagination_controls(total_pages):
    """Render pagination controls"""
    if total_pages <= 1:
        return

    st.markdown("""
    <style>
    .pagination {
        display: flex;
        justify-content: center;
        align-items: center;
        gap: 10px;
        margin: 20px 0;
    }
    .page-info {
        margin: 0 15px;
    }
    </style>
    """, unsafe_allow_html=True)

    col1, col2, col3, col4, col5 = st.columns([1, 1, 2, 1, 1])
    
    with col1:
        if st.button("⏮️ First", disabled=st.session_state.current_page == 1):
            st.session_state.current_page = 1
            st.rerun()
    
    with col2:
        if st.button("◀️ Prev", disabled=st.session_state.current_page == 1):
            st.session_state.current_page -= 1
            st.rerun()
    
    with col3:
        st.markdown(f"<div style='text-align: center'>Page {st.session_state.current_page} of {total_pages}</div>", 
                   unsafe_allow_html=True)
    
    with col4:
        if st.button("Next ▶️", disabled=st.session_state.current_page == total_pages):
            st.session_state.current_page += 1
            st.rerun()
    
    with col5:
        if st.button("Last ⏭️", disabled=st.session_state.current_page == total_pages):
            st.session_state.current_page = total_pages
            st.rerun()

def show_statistics():
    """Show statistics about the loaded posts"""
    if not st.session_state.posts:
        return
    
    # Convert posts to DataFrame for analysis
    posts_df = pd.DataFrame(st.session_state.posts)
    
    # Add source column if not present
    if 'source' not in posts_df.columns:
        posts_df['source'] = posts_df.apply(get_post_source, axis=1)
    
    # Display statistics in columns
    col1, col2, col3 = st.columns(3)
    
    with col1:
        st.metric("Total Posts", len(posts_df))
    
    with col2:
        st.metric("Sources", len(posts_df['source'].unique()))
    
    with col3:
        # Calculate average reading time if available
        if 'reading_time' in posts_df.columns:
            avg_time = posts_df['reading_time'].mean()
            st.metric("Avg. Reading Time", f"{avg_time:.0f} min")
    
    # Show source distribution
    st.subheader("Posts by Source")
    source_counts = posts_df['source'].value_counts()
    st.bar_chart(source_counts)

def show_debug_info():
    """Show debug information in the sidebar"""
    st.sidebar.markdown("---")
    st.sidebar.subheader("Debug Info")
    
    save_dir = Path('saved_posts')
    if save_dir.exists():
        # Show filtered posts info
        filtered_file = save_dir / "filtered_posts.json"
        if filtered_file.exists():
            st.sidebar.markdown("**Filtered Posts**")
            try:
                with open(filtered_file, 'rb') as f:
                    posts = orjson.loads(f.read())
                    st.sidebar.write(f"- Latest: {len(posts)} posts")
            except Exception:
                st.sidebar.write("- Error reading filtered posts")
        
        # Show source directories info
        source_dirs = [d for d in save_dir.iterdir() if d.is_dir() and d.name not in ['__pycache__']]
        st.sidebar.write(f"\nFound {len(source_dirs)} source directories:")
        
        for source_dir in source_dirs:
            st.sidebar.markdown(f"**{source_dir.name}**")
            post_files = list(source_dir.glob("posts_*.json"))
            if post_files:
                latest_file = max(post_files, key=lambda x: x.stat().st_mtime)
                try:
                    with open(latest_file, 'rb') as f:
                        posts = orjson.loads(f.read())
                        st.sidebar.write(f"- Latest posts: {len(posts)}")
                except Exception:
                    st.sidebar.write("- Error reading latest posts")
            st.sidebar.write(f"- Historical files: {len(post_files)}")
    else:
        st.sidebar.warning(f"Save directory not found: {save_dir}")


def count_json_objects(file_path):
    with open(file_path, 'rb') as f:
        data = orjson.loads(f.read())
    return len(data)

def show_preferences_sidebar():
    """Show and manage user preferences in the sidebar"""
    st.sidebar.title("Preferences")
    
    # View selector
    st.sidebar.subheader("View")
    view_options = {
        "All Posts": "all",
        "👍 Liked Posts": "liked",
        "📌 Saved Posts": "saved"
    }
    selected_view = st.sidebar.radio(
        "Select View",
        options=list(view_options.keys()),
        key="view_selector"
    )
    st.session_state.current_view = view_options[selected_view]
    
    # Sort selector
    st.sidebar.subheader("Sort")
    sort_options = {
        "Newest First": "newest",
        "Oldest First": "oldest"
    }
    selected_sort = st.sidebar.radio(
        "Sort Posts",
        options=list(sort_options.keys()),
        key="sort_selector",
        index=0
    )
    if st.session_state.get('sort_by') != sort_options[selected_sort]:
        st.session_state.sort_by = sort_options[selected_sort]
        st.session_state.current_page = 1  # Reset to first page when sorting changes
    
    # Posts per page selector
    st.sidebar.subheader("Display")
    posts_per_page = st.sidebar.select_slider(
        "Posts per page",
        options=[5, 10, 15, 20, 25, 30],
        value=st.session_state.get('posts_per_page', 10)
    )
    st.session_state.posts_per_page = posts_per_page
    
    # Show stats for current view
    total_posts = count_json_objects('saved_posts/filtered_posts.json')
    liked_posts = len(st.session_state.personalization.post_history['liked_posts'])
    saved_posts = len(st.session_state.personalization.post_history['read_later'])
    
    st.sidebar.markdown("---")
    st.sidebar.caption(f"📊 Stats")
    st.sidebar.caption(f"Total Posts: {total_posts}")
    st.sidebar.caption(f"Liked Posts: {liked_posts}")
    st.sidebar.caption(f"Saved Posts: {saved_posts}")
    
    # Only show filters for all posts view
    if st.session_state.current_view == "all":
        # Reading time preferences
        st.sidebar.markdown("---")
        st.sidebar.subheader("Reading Time")
        min_time = st.sidebar.slider("Minimum (minutes)", 0, 30, 
                                   st.session_state.min_reading_time)
        max_time = st.sidebar.slider("Maximum (minutes)", min_time, 60, 
                                   st.session_state.max_reading_time)
        
        # Source preferences
        st.sidebar.subheader("Sources")
        if st.session_state.posts:
            available_sources = sorted(set(get_post_source(post) 
                                        for post in st.session_state.posts))
            selected_sources = st.sidebar.multiselect(
                "Preferred Sources",
                available_sources,
                default=available_sources
            )
        else:
            selected_sources = []
        
        # Update session state
        st.session_state.min_reading_time = min_time
        st.session_state.max_reading_time = max_time
        st.session_state.selected_sources = selected_sources
    
    # Fetch new posts button
    st.sidebar.markdown("---")
    if st.sidebar.button("🔄 Fetch New Posts"):
        fetch_new_posts()

def main():
    st.title("Dev Posts Aggregator")
    
    # Show preferences in sidebar
    show_preferences_sidebar()
    
    # Main content area
    st.markdown("""
    Welcome to Dev Posts Aggregator! This app fetches and aggregates developer blog posts 
    from multiple sources including Dev.to, freeCodeCamp, CSS-Tricks, HackerNoon, and Stack Overflow Blog.
    """)
    
    # Search box (only show for all posts view)
    if st.session_state.current_view == "all":
        search = st.text_input("🔍 Search posts by title, description, or tags", 
                             value=st.session_state.search,
                             key="search")
    
    # Load posts if not already loaded
    if not st.session_state.posts:
        st.session_state.posts = load_latest_posts()
        if st.session_state.posts:
            st.success(f"Loaded {len(st.session_state.posts)} posts!")
            apply_filters()
    
    # Apply filters
    apply_filters()
    
    # Display view-specific headers
    if st.session_state.current_view == "liked":
        st.subheader("👍 Your Liked Posts")
    elif st.session_state.current_view == "saved":
        st.subheader("📌 Your Saved Posts")
    
    # Display posts with pagination
    if st.session_state.filtered_posts:
        st.caption(f"Showing {len(st.session_state.filtered_posts)} posts")
        
        # Paginate posts
        page_posts, total_pages = paginate_posts(
            st.session_state.filtered_posts,
            st.session_state.posts_per_page
        )
        
        # Display current page posts
        for post in page_posts:
            render_post_card(post)
        
        # Show pagination controls
        render_pagination_controls(total_pages)
        
    else:
        if st.session_state.current_view == "liked":
            st.info("You haven't liked any posts yet. Find posts you like and click the 👍 button!")
        elif st.session_state.current_view == "saved":
            st.info("You haven't saved any posts yet. Find interesting posts and click the 📌 button!")
        elif st.session_state.posts:
            st.info("No posts match your current filters. Try adjusting your search or preferences.")
        else:
            st.info("No posts found. Try fetching new posts using the button in the sidebar!")

if __name__ == "__main__":
    config = load_config()
    main()

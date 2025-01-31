# Dev Posts Fetcher

A Python script that aggregates developer blog posts from various platforms including Dev.to and Hashnode.

## Features

- Fetches latest posts from Dev.to and Hashnode
- Configurable tags and number of posts to fetch
- Beautiful console output using Rich
- Saves posts to JSON files for later reference
- Customizable through YAML configuration

## Setup

1. Install the required dependencies:
```bash
pip install -r requirements.txt
```

2. Run the script:
```bash
python dev_posts_fetcher.py
```

## Configuration

The script uses a `config.yaml` file for configuration. If not present, it will create one with default values:

```yaml
tags:
  - python
  - javascript
  - webdev
  - programming
max_posts_per_source: 10
save_directory: saved_posts
```

You can modify these values to customize:
- `tags`: List of tags to filter posts
- `max_posts_per_source`: Maximum number of posts to fetch from each source
- `save_directory`: Directory where posts will be saved as JSON files

## Output

The script will:
1. Display fetched posts in a nicely formatted table in the console
2. Save the posts to JSON files in the specified save directory
3. Each file is timestamped for easy tracking

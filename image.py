import anthropic
import base64
import httpx
from serpapi import GoogleSearch
from PIL import Image
from io import BytesIO
from concurrent.futures import ThreadPoolExecutor
import threading
import concurrent.futures
import sqlite3
import datetime
import os

class TweetImageEvaluator:
    def __init__(self, db_path='recipe_tweets.db'):
        self.client = anthropic.Anthropic(api_key=os.getenv('ANTHROPIC_API_KEY'))
        self.model = "claude-3-5-sonnet-20241022"
        self.db_path = db_path
        self.init_database()

    def init_database(self) -> None:
        """Initialize SQLite database with posts table"""
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute('''CREATE TABLE IF NOT EXISTS posts
                    (id INTEGER PRIMARY KEY AUTOINCREMENT,
                    content TEXT,
                    image_url TEXT,
                    scheduled_time TIMESTAMP,
                    is_published BOOLEAN DEFAULT FALSE,
                    is_canceled BOOLEAN DEFAULT FALSE,
                    is_draft BOOLEAN DEFAULT FALSE,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    engagement_score INTEGER DEFAULT 0,
                    publish_to_twitter BOOLEAN DEFAULT TRUE,
                    publish_to_instagram BOOLEAN DEFAULT FALSE,
                    publish_to_facebook BOOLEAN DEFAULT FALSE,
                    publish_to_pinterest BOOLEAN DEFAULT FALSE,
                    twitter_post_id TEXT,
                    instagram_post_id TEXT,
                    facebook_post_id TEXT,
                    pinterest_post_id TEXT)''')
        conn.commit()
        conn.close()

    def is_image_url_used(self, image_url: str) -> bool:
        """Check if an image URL already exists in the database"""
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute('SELECT COUNT(*) FROM posts WHERE image_url = ?', (image_url,))
        count = c.fetchone()[0]
        conn.close()
        return count > 0

    def save_tweet_with_image(self, tweet_text: str, image_url: str, score: int) -> None:
        """Save tweet and associated image URL to database"""
        timestamp = datetime.datetime.now().isoformat()
        
        conn = sqlite3.connect(self.db_path)
        try:
            c = conn.cursor()
            c.execute('''INSERT INTO posts 
                        (content, image_url, created_at, updated_at, engagement_score) 
                        VALUES (?, ?, datetime(?), datetime(?), ?)''',
                    (tweet_text, image_url, timestamp, timestamp, score))
            conn.commit()
            
            # Verify the save
            c.execute('SELECT * FROM posts ORDER BY id DESC LIMIT 1')
            last_tweet = c.fetchone()
            if last_tweet:
                print(f"\n✅ Tweet and image successfully saved to database with ID: {last_tweet[0]}")
                print(f"Tweet text: {last_tweet[1]}")
                print(f"Image URL: {last_tweet[2]}")
                print(f"Created at: {last_tweet[6]}")
                print(f"Engagement Score: {last_tweet[8]}")
            else:
                print("\n❌ Failed to verify tweet save")
                
        except sqlite3.Error as e:
            print(f"\n❌ Database error: {e}")
        finally:
            conn.close()

    def compress_image(self, image_data):
        """Compress image to max 1000x1000 while maintaining aspect ratio"""
        image = Image.open(BytesIO(image_data))
        
        if image.mode == 'RGBA':
            image = image.convert('RGB')
            
        max_size = 1000
        ratio = min(max_size/float(image.size[0]), max_size/float(image.size[1]))
        if ratio < 1:
            new_size = (int(image.size[0]*ratio), int(image.size[1]*ratio))
            image = image.resize(new_size, Image.Resampling.LANCZOS)
        
        buffer = BytesIO()
        image.save(buffer, format="JPEG", quality=85)
        return buffer.getvalue()

    def generate_search_queries(self, tweet):
        response = self.client.messages.create(
            model=self.model,
            max_tokens=1024,
            tools=[{
                "name": "generate_queries",
                "description": "Generate 3 specific search queries that would find images matching the tweet's content",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "queries": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "List of 3 specific search queries"
                        }
                    },
                    "required": ["queries"]
                }
            }],
            messages=[{
                "role": "user",
                "content": f"Generate 3 specific search queries to find images that would match this tweet: {tweet}"
            }]
        )
        
        tool_outputs = [msg for msg in response.content if msg.type == 'tool_use']
        if tool_outputs:
            return tool_outputs[0].input["queries"]
        return []

    def get_top_4_image_urls(self, query):
        params = {
            "api_key":  os.getenv('SERP_API_KEY'),
            "engine": "google_images",
            "google_domain": "google.com",
            "q": query,
            "hl": "en",
            "gl": "us",
            "tbs": "sur:cl"
        }
        
        try:
            search = GoogleSearch(params)
            results = search.get_dict()
            
            if 'images_results' not in results:
                return []
            
            image_urls = []
            for image in results['images_results']:
                if 'original' in image:
                    url = image['original']
                    # Add check for "stockcake" in URL
                    if not self.is_image_url_used(url) and "stockcake" not in url.lower():
                        image_urls.append(url)
                    if len(image_urls) >= 4:  # Stop once we have 4 valid URLs
                        break
            
            return image_urls
            
        except Exception as e:
            print(f"Error occurred: {e}")
            return []

    def evaluate_image_tweet_pair(self, image_url, tweet):
        try:
            response = httpx.get(image_url)
            if response.status_code != 200:
                raise Exception(f"Failed to download image: {response.status_code}")
            
            compressed_image = self.compress_image(response.content)
            image_base64 = base64.b64encode(compressed_image).decode('utf-8')
            
            response = self.client.messages.create(
                model=self.model,
                max_tokens=1024,
                tools=[{
                    "name": "rate_match",
                    "description": "Rate how well the image matches the tweet on a scale of 1-10",
                    "input_schema": {
                        "type": "object",
                        "properties": {
                            "score": {
                                "type": "integer",
                                "minimum": 1,
                                "maximum": 10
                            },
                            "explanation": {
                                "type": "string"
                            }
                        },
                        "required": ["score", "explanation"]
                    }
                }],
                messages=[{
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": "image/jpeg",
                                "data": image_base64
                            }
                        },
                        {
                            "type": "text",
                            "text": f"Rate how well this image matches the tweet: '{tweet}' on a scale of 1-10, where 10 is perfect match."
                        }
                    ]
                }]
            )
            
            tool_outputs = [msg for msg in response.content if msg.type == 'tool_use']
            if tool_outputs:
                return tool_outputs[0].input
            return {"score": 0, "explanation": "Failed to evaluate"}
            
        except Exception as e:
            print(f"Error evaluating image: {e}")
            return {"score": 0, "explanation": str(e)}

    def evaluate_images_in_parallel(self, tweet, image_urls):
        results = []
        
        print_lock = threading.Lock()
        def safe_print(*args):
            with print_lock:
                print(*args)
        
        def evaluate_single_image(url):
            safe_print(f"\nEvaluating: {url}")
            result = self.evaluate_image_tweet_pair(url, tweet)
            safe_print(f"Score: {result['score']}/10")
            safe_print(f"Explanation: {result['explanation']}")
            return {'url': url, **result}
        
        with ThreadPoolExecutor(max_workers=4) as executor:
            future_to_url = {executor.submit(evaluate_single_image, url): url 
                           for url in image_urls}
            
            for future in concurrent.futures.as_completed(future_to_url):
                try:
                    result = future.result()
                    results.append(result)
                except Exception as e:
                    safe_print(f"Error processing {future_to_url[future]}: {e}")
        
        return results
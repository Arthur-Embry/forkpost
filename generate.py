import sqlite3
from serpapi import GoogleSearch
from anthropic import Anthropic
import json
import datetime
from typing import List, Dict
import os
import importlib.util
import jinja2

class TwitterRecipeBot:
    def __init__(self, db_path, anthropic_key=os.getenv('ANTHROPIC_API_KEY'), guidance_path="guidance.py"):
        self.db_path = db_path
        self.client = Anthropic(api_key=anthropic_key)
        self.serp_api_key = os.getenv('SERP_API_KEY')
        self.conversation = []
        self.init_database()
        
        # Import guidance templates from external file
        self.guidance = self._load_guidance(guidance_path)
        
        # Initialize Jinja2 environment with min function
        self.jinja_env = jinja2.Environment(autoescape=False)
        self.jinja_env.globals.update(min=min)  # Add min function to Jinja env

    def _load_guidance(self, guidance_path):
        """Load guidance templates from external Python file with fallback to default"""
        try:
            spec = importlib.util.spec_from_file_location("guidance", guidance_path)
            guidance = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(guidance)
            return guidance
        except Exception as e:
            print(f"Warning: Error loading guidance file '{guidance_path}': {e}")
            print("Attempting to load default guidance file 'guidance-default.py'...")
            
            try:
                # Try to load the default guidance file
                default_path = "guidance-default.py"
                spec = importlib.util.spec_from_file_location("guidance_default", default_path)
                guidance_default = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(guidance_default)
                print("Successfully loaded default guidance file.")
                return guidance_default
            except Exception as default_error:
                print(f"Error loading default guidance file: {default_error}")
                # Final fallback to empty templates if both imports fail
                print("Using empty guidance templates as fallback.")
                return type('obj', (object,), {
                    'brand_guidelines': "",
                    'review': "",
                    'refactor': "",
                    'timing': ""
                })

    def init_database(self) -> None:
        """Initialize SQLite database with posts table"""
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        # Use the same schema as in the FastAPI app
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

    def populate_example_tweets(self, example_tweets=None, count: int = 5) -> None:
        """Populate the database with example tweets for testing
        
        Args:
            example_tweets: Optional list of tweet dictionaries to use instead of defaults
            count: Maximum number of tweets to insert (will be ignored if example_tweets is provided)
        """
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        
        # Check if we already have tweets
        c.execute('SELECT COUNT(*) FROM posts')
        existing_count = c.fetchone()[0]
        
        if existing_count > 0:
            print(f"Database already contains {existing_count} tweets. Skipping example population.")
            conn.close()
            return
        
        # Use provided tweets if available, otherwise don't populate
        if example_tweets is None:
            print("No example tweets provided. Skipping population.")
            conn.close()
            return
        
        # Current timestamp
        now = datetime.datetime.now().isoformat()
        
        # Insert example tweets
        for i, tweet in enumerate(example_tweets):
            # Set defaults for optional fields
            content = tweet.get("content", f"Example tweet #{i+1}")
            image_url = tweet.get("image_url", "")
            scheduled_time = tweet.get("scheduled_time", None)
            is_published = tweet.get("is_published", False)
            is_canceled = tweet.get("is_canceled", False)
            is_draft = tweet.get("is_draft", False)
            engagement_score = tweet.get("engagement_score", 0)
            
            # Calculate a created_at timestamp in the past (older for higher indices)
            days_ago = tweet.get("days_ago", i * 2)  # Each example is 2 days apart by default
            created_at = tweet.get("created_at", (datetime.datetime.now() - datetime.timedelta(days=days_ago)).isoformat())
            
            c.execute('''
                INSERT INTO posts 
                (content, image_url, scheduled_time, is_published, is_canceled, is_draft, 
                created_at, updated_at, engagement_score)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (content, image_url, scheduled_time, is_published, is_canceled, 
                is_draft, created_at, now, engagement_score))
        
        conn.commit()
        print(f"Successfully populated database with {len(example_tweets)} example tweets")
        conn.close()

        
    def get_trending_searches(self) -> List[Dict]:
        """Get top 20 trending searches from Google Trends"""
        params = {
            "api_key": self.serp_api_key,
            "engine": "google_trends_trending_now",
            "geo": "US"
        }
        
        try:
            search = GoogleSearch(params)
            results = search.get_dict()
            
            if 'trending_searches' not in results:
                return []
            
            trends = []
            for trend in results['trending_searches'][:20]:
                trend_info = {
                    'query': trend['query'],
                    'categories': [cat['name'] for cat in trend.get('categories', [])]
                }
                trends.append(trend_info)
            
            return trends
            
        except Exception as e:
            print(f"Error getting trends: {e}")
            return []

    def get_recipe_trends(self) -> List[str]:
        """Get trending recipe searches"""
        recipe_trends = []
        
        for query in ["recipe", "recipes"]:
            params = {
                "engine": "google_trends",
                "q": query,
                "data_type": "RELATED_QUERIES",
                "date": "now 1-d",
                "api_key": self.serp_api_key
            }
            
            try:
                search = GoogleSearch(params)
                results = search.get_dict()
                if "related_queries" in results:
                    recipe_trends.extend([q['query'] for q in results["related_queries"].get('rising', [])])
                    recipe_trends.extend([q['query'] for q in results["related_queries"].get('top', [])])
            except Exception as e:
                print(f"Error getting recipe trends: {e}")
                
        return list(set(recipe_trends))  # Remove duplicates

    def get_previous_tweets(self, limit: int = 10) -> List[dict]:
        """Get recent tweets from database with comprehensive information"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row  # This allows accessing columns by name
        c = conn.cursor()
        c.execute('''
            SELECT id, content, image_url, scheduled_time, is_published, 
                is_canceled, is_draft, created_at, updated_at, engagement_score 
            FROM posts 
            ORDER BY created_at DESC 
            LIMIT ?
        ''', (limit,))
        
        tweets = []
        for row in c.fetchall():
            # Convert row to dict and format dates for readability
            tweet = dict(row)
            if tweet['scheduled_time']:
                # Format the scheduled time for better readability
                dt = datetime.datetime.fromisoformat(tweet['scheduled_time'].replace('Z', '+00:00'))
                tweet['scheduled_time_formatted'] = dt.strftime("%b %d, %Y at %I:%M %p")
            
            tweets.append(tweet)
        
        conn.close()
        return tweets

    def start_conversation(self) -> str:
        """Initialize the conversation with context and generate initial tweets"""
        trends = self.get_trending_searches()
        recipe_trends = self.get_recipe_trends()
        previous_tweets = self.get_previous_tweets()
        
        # Create a Jinja2 template from the string
        template = self.jinja_env.from_string(self.guidance.brand_guidelines)
        
        # Render the template with context data
        formatted_guidelines = template.render(
            trends=trends,
            recipe_trends=recipe_trends,
            previous_tweets=previous_tweets
        )

        initial_prompt = {
            "role": "user",
            "content": formatted_guidelines
        }
        
        self.conversation.append(initial_prompt)
        
        response = self.client.messages.create(
            model="claude-3-5-sonnet-20241022",
            max_tokens=1024,
            temperature=0.9,
            messages=[initial_prompt]
        )
        
        self.conversation.append({
            "role": "assistant",
            "content": response.content[0].text
        })
        
        return response.content[0].text

    def evaluate_tweets(self, generated_content: str) -> str:
        """Have Claude evaluate the generated tweets and pick the best one"""
        evaluation_prompt = {
            "role": "user",
            "content": self.guidance.review
        }
        
        self.conversation.append(evaluation_prompt)
        
        response = self.client.messages.create(
            model="claude-3-5-sonnet-20241022",
            max_tokens=1024,
            messages=self.conversation
        )
        
        self.conversation.append({
            "role": "assistant",
            "content": response.content[0].text
        })
        
        return response.content[0].text

    def refine_best_tweet(self, evaluation: str) -> str:
        """Optional refinement of the chosen tweet"""
        refinement_prompt = {
            "role": "user",
            "content": self.guidance.refactor
        }
        
        self.conversation.append(refinement_prompt)
        
        response = self.client.messages.create(
            model="claude-3-5-sonnet-20241022",
            max_tokens=1024,
            messages=self.conversation
        )
        
        self.conversation.append({
            "role": "assistant",
            "content": response.content[0].text
        })
        
        return response.content[0].text

    def extract_tweet(self, refined_content: str) -> dict:
        """Extract the final tweet content and reasoning using a tool call"""
        response = self.client.messages.create(
            model="claude-3-5-sonnet-20241022",
            max_tokens=1024,
            tools=[{
                "name": "extract_tweet",
                "description": "Extract the final tweet and reasoning from the conversation",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "tweet_text": {
                            "type": "string",
                            "description": "The final optimized tweet content"
                        },
                        "reasoning": {
                            "type": "string",
                            "description": "Explanation of why this version was chosen"
                        }
                    },
                    "required": ["tweet_text", "reasoning"]
                }
            }],
            messages=[{
                "role": "user",
                "content": f"Extract the final optimized tweet and reasoning from this conversation: {refined_content}"
            }]
        )
        
        tool_outputs = [msg for msg in response.content if msg.type == 'tool_use']
        if tool_outputs:
            return tool_outputs[0].input
        return {"tweet_text": "", "reasoning": "Failed to extract tweet"}

    def save_tweet(self, tweet_text: str) -> None:
        """Save tweet to database with proper timestamp handling"""
        # Extract just the tweet text if it contains analysis
        # Look for common patterns in the refined output
        if "Here's the optimized version:" in tweet_text:
            # Split and get the content after this marker
            tweet_text = tweet_text.split("Here's the optimized version:")[1].strip()
        elif "Final refined tweet:" in tweet_text:
            tweet_text = tweet_text.split("Final refined tweet:")[1].strip()
        
        # Clean up any remaining analysis markers
        tweet_text = tweet_text.split("Key improvements:")[0].strip()
        tweet_text = tweet_text.split("Improvements:")[0].strip()
        
        # Get current timestamp
        timestamp = datetime.datetime.now().isoformat()
        
        conn = sqlite3.connect(self.db_path)
        try:
            c = conn.cursor()
            c.execute('''INSERT INTO posts 
                        (content, created_at, updated_at) 
                        VALUES (?, datetime(?), datetime(?))''',
                    (tweet_text, timestamp, timestamp))
            conn.commit()
            
            # Verify the save
            c.execute('SELECT * FROM posts ORDER BY id DESC LIMIT 1')
            last_tweet = c.fetchone()
            if last_tweet:
                print(f"\n✅ Tweet successfully saved to database with ID: {last_tweet[0]}")
                print(f"Saved tweet text: {last_tweet[1]}")
                print(f"Image URL: {last_tweet[2] or 'None'}")
                print(f"Created at: {last_tweet[6]}")
            else:
                print("\n❌ Failed to verify tweet save")
                
        except sqlite3.Error as e:
            print(f"\n❌ Database error: {e}")
        finally:
            conn.close()

    def log_conversation(self, filename: str) -> None:
        """Save the entire conversation to a file"""
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        with open(f"{filename}_{timestamp}.txt", "w", encoding="utf-8") as f:
            for message in self.conversation:
                f.write(f"\n{'='*50}\n")
                f.write(f"Role: {message['role']}\n")
                f.write(f"Content:\n{message['content']}\n")
                
    def predict_optimal_posting_time(self, tweet_content: str) -> dict:
        """Predict the optimal posting time for a tweet based on its content and context"""
        
        # Create a Jinja2 template from the string
        template = self.jinja_env.from_string(self.guidance.timing)
        
        # Render the template with context data
        formatted_timing_prompt = template.render(
            tweet_content=tweet_content
        )
        
        time_prediction_prompt = {
            "role": "user",
            "content": formatted_timing_prompt
        }
        
        self.conversation.append(time_prediction_prompt)
        
        response = self.client.messages.create(
            model="claude-3-5-sonnet-20241022",
            max_tokens=1024,
            tools=[{
                "name": "predict_posting_time",
                "description": "Predict the optimal posting hour and reasoning",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "optimal_hour": {
                            "type": "integer",
                            "description": "The recommended posting hour in 24-hour format (0-23)",
                            "minimum": 0,
                            "maximum": 23
                        },
                        "reasoning": {
                            "type": "string",
                            "description": "Explanation for the recommended posting time"
                        }
                    },
                    "required": ["optimal_hour", "reasoning"]
                }
            }],
            messages=self.conversation
        )
        
        tool_outputs = [msg for msg in response.content if msg.type == 'tool_use']
        if tool_outputs:
            return tool_outputs[0].input
        return {"optimal_hour": None, "reasoning": "Failed to predict optimal posting time"}
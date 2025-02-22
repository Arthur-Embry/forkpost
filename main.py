import asyncio
import json
import sqlite3
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from fastapi import FastAPI, HTTPException, Query
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi.responses import StreamingResponse, FileResponse
from pydantic import BaseModel
from typing import Optional, List
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Import your actual implementations
from generate import TwitterRecipeBot
from image import TweetImageEvaluator
from post import SocialMediaPoster

app = FastAPI()

# Initialize the scheduler
scheduler = AsyncIOScheduler()

# Example tweets that you can customize
import importlib

try:
    # Try to import from guidance.py
    guidance = importlib.import_module('guidance')
    example_tweets = guidance.example_tweets
except ImportError:
    # If that fails, use the default template
    guidance = importlib.import_module('guidance-default')
    example_tweets = guidance.example_tweets

# Add this as part of the startup event
@app.on_event("startup")
async def start_scheduler():
    scheduler.add_job(publish_due_tweets, 'interval', minutes=1)
    scheduler.start()
    
    # Populate the database with example tweets on startup
    recipe_bot.populate_example_tweets(example_tweets)


@app.on_event("shutdown")
async def shutdown_scheduler():
    scheduler.shutdown()

# Initialize services
recipe_bot = TwitterRecipeBot('recipe_tweets.db')
image_evaluator = TweetImageEvaluator()

# Pydantic models
class PostBase(BaseModel):
    content: Optional[str] = None
    image_url: Optional[str] = None
    scheduled_time: Optional[datetime] = None
    publish_to_twitter: Optional[bool] = True
    publish_to_instagram: Optional[bool] = False
    publish_to_facebook: Optional[bool] = False
    publish_to_pinterest: Optional[bool] = False

class PostResponse(PostBase):
    id: int
    is_published: bool
    is_canceled: bool
    is_draft: bool
    created_at: datetime
    updated_at: datetime
    engagement_score: int
    twitter_post_id: Optional[str] = None
    instagram_post_id: Optional[str] = None
    facebook_post_id: Optional[str] = None
    pinterest_post_id: Optional[str] = None

class PostCreate(PostBase):
    pass

class GenerateImageRequest(BaseModel):
    tweet_text: str

# Database helper functions
def get_db():
    conn = sqlite3.connect('recipe_tweets.db')
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    c = conn.cursor()
    # Modified schema definition
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

init_db()

# Serve index.html
@app.get("/")
async def read_index():
    return FileResponse('index.html')

# Utility: Convert a datetime string (from DB) to CST ISO format.
def to_cst(dt_str):
    if dt_str is None:
        # Return a default datetime if None
        return (datetime.now(ZoneInfo("America/Chicago")) + timedelta(days=1)).isoformat()
        
    if not isinstance(dt_str, str):
        # Convert non-string to string if needed
        dt_str = str(dt_str)
        
    dt = datetime.fromisoformat(dt_str)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=ZoneInfo("America/Chicago"))
    else:
        dt = dt.astimezone(ZoneInfo("America/Chicago"))
    return dt.isoformat()

# ---------------------------
# API Endpoints
# ---------------------------

@app.post("/generate/text")
async def generate_post_text():
    try:
        generated_content = await asyncio.to_thread(recipe_bot.start_conversation)
        evaluation = await asyncio.to_thread(recipe_bot.evaluate_tweets, generated_content)
        final_tweet_response = await asyncio.to_thread(recipe_bot.refine_best_tweet, evaluation)
        extracted_tweet = await asyncio.to_thread(recipe_bot.extract_tweet, final_tweet_response)
        prediction = await asyncio.to_thread(recipe_bot.predict_optimal_posting_time, extracted_tweet["tweet_text"])
        return {
            "tweet_text": extracted_tweet["tweet_text"],
            "reasoning": extracted_tweet["reasoning"],
            "optimal_hour": prediction["optimal_hour"],
            "timing_reasoning": prediction["reasoning"]
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/generate/image")
async def generate_post_image(request: GenerateImageRequest):
    try:
        queries = await asyncio.to_thread(image_evaluator.generate_search_queries, request.tweet_text)
        all_results = []
        for query in queries:
            image_urls = await asyncio.to_thread(image_evaluator.get_top_4_image_urls, query)
            results = await asyncio.to_thread(image_evaluator.evaluate_images_in_parallel, request.tweet_text, image_urls)
            all_results.extend(results)
        if not all_results:
            raise HTTPException(status_code=404, detail="No suitable images found")
        best_matches = sorted(all_results, key=lambda x: (-x['score'], len(x['explanation'])))
        best_match = best_matches[0]
        if best_match['score'] < 7:
            raise HTTPException(status_code=400, detail="No images met quality threshold")
        return {
            "image_url": best_match['url'],
            "score": best_match['score'],
            "explanation": best_match['explanation']
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# --------------------
# Post Endpoints
# --------------------

@app.post("/posts/", response_model=PostResponse)
async def create_scheduled_post(post: PostCreate):
    if not post.scheduled_time:
        raise HTTPException(status_code=400, detail="Scheduled time is required")
        
    scheduled_cst = post.scheduled_time.replace(tzinfo=ZoneInfo("America/Chicago"))
    now_cst = datetime.now(ZoneInfo("America/Chicago"))
    if scheduled_cst <= now_cst:
        raise HTTPException(status_code=400, detail="Scheduled time must be in the future (CST)")
    
    if not post.content:
        generated = await generate_post_text()
        post.content = generated["tweet_text"]
    
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute('''
            INSERT INTO posts (
                content, image_url, scheduled_time, is_draft,
                publish_to_twitter, publish_to_instagram, 
                publish_to_facebook, publish_to_pinterest
            )
            VALUES (?, ?, ?, 0, ?, ?, ?, ?)
        ''', (
            post.content, post.image_url, scheduled_cst.isoformat(),
            post.publish_to_twitter, post.publish_to_instagram,
            post.publish_to_facebook, post.publish_to_pinterest
        ))
        post_id = cursor.lastrowid
        conn.commit()
        cursor.execute('SELECT * FROM posts WHERE id = ?', (post_id,))
        db_post = dict(cursor.fetchone())
        db_post["scheduled_time"] = to_cst(db_post["scheduled_time"])
        return db_post
    finally:
        conn.close()

@app.get("/posts/", response_model=List[PostResponse])
def get_scheduled_posts(skip: int = 0, limit: int = 100, include_published: bool = False):
    conn = get_db()
    cursor = conn.cursor()
    try:
        if include_published:
            # All non-draft posts
            cursor.execute('SELECT * FROM posts WHERE is_draft = 0 ORDER BY scheduled_time LIMIT ? OFFSET ?', (limit, skip))
        else:
            # Only non-draft, non-published, non-canceled posts
            cursor.execute('SELECT * FROM posts WHERE is_published = 0 AND is_canceled = 0 AND is_draft = 0 ORDER BY scheduled_time LIMIT ? OFFSET ?', (limit, skip))
        
        posts = [dict(row) for row in cursor.fetchall()]
        for post in posts:
            if post["scheduled_time"] is not None:
                post["scheduled_time"] = to_cst(post["scheduled_time"])
            else:
                default_time = datetime.now(ZoneInfo("America/Chicago")) + timedelta(days=1)
                post["scheduled_time"] = default_time.isoformat()
        return posts
    finally:
        conn.close()

@app.get("/posts/{post_id}", response_model=PostResponse)
async def get_post(post_id: int):
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute('SELECT * FROM posts WHERE id = ?', (post_id,))
        post = cursor.fetchone()
        if not post:
            raise HTTPException(status_code=404, detail="Post not found")
        post = dict(post)
        if post["scheduled_time"] is not None:
            post["scheduled_time"] = to_cst(post["scheduled_time"])
        else:
            default_time = datetime.now(ZoneInfo("America/Chicago")) + timedelta(days=1)
            post["scheduled_time"] = default_time.isoformat()
        return post
    finally:
        conn.close()

@app.put("/posts/{post_id}", response_model=PostResponse)
async def update_post(post_id: int, post: PostCreate):
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute('SELECT * FROM posts WHERE id = ?', (post_id,))
        existing_post = cursor.fetchone()
        if not existing_post:
            raise HTTPException(status_code=404, detail="Post not found")
            
        scheduled_time = None
        if post.scheduled_time:
            scheduled_time = post.scheduled_time.replace(tzinfo=ZoneInfo("America/Chicago")).isoformat()
            
        cursor.execute('''
            UPDATE posts 
            SET content = ?, 
                image_url = ?, 
                scheduled_time = ?, 
                updated_at = CURRENT_TIMESTAMP,
                publish_to_twitter = ?,
                publish_to_instagram = ?,
                publish_to_facebook = ?,
                publish_to_pinterest = ?
            WHERE id = ?
        ''', (
            post.content or '', 
            post.image_url or '', 
            scheduled_time,
            post.publish_to_twitter,
            post.publish_to_instagram,
            post.publish_to_facebook,
            post.publish_to_pinterest,
            post_id
        ))
        conn.commit()
        cursor.execute('SELECT * FROM posts WHERE id = ?', (post_id,))
        updated_post = dict(cursor.fetchone())
        if updated_post["scheduled_time"] is not None:
            updated_post["scheduled_time"] = to_cst(updated_post["scheduled_time"])
        else:
            default_time = datetime.now(ZoneInfo("America/Chicago")) + timedelta(days=1)
            updated_post["scheduled_time"] = default_time.isoformat()
        return updated_post
    finally:
        conn.close()

@app.post("/posts/{post_id}/publish")
async def publish_post(post_id: int):
    conn = get_db()
    cursor = conn.cursor()
    social_media_poster = SocialMediaPoster()
    
    try:
        cursor.execute('SELECT * FROM posts WHERE id = ?', (post_id,))
        post = cursor.fetchone()
        if not post:
            raise HTTPException(status_code=404, detail="Post not found")
        post = dict(post)
        
        if post['is_published']:
            raise HTTPException(status_code=400, detail="Post is already published")
            
        # For drafts being directly published
        if post['is_draft']:
            cursor.execute('UPDATE posts SET is_draft = 0 WHERE id = ?', (post_id,))
            conn.commit()
            
        # For scheduled posts, verify time
        elif post["scheduled_time"]:
            now_cst = datetime.now(ZoneInfo("America/Chicago"))
            scheduled_cst = datetime.fromisoformat(post["scheduled_time"]).replace(tzinfo=ZoneInfo("America/Chicago"))
            if scheduled_cst > now_cst:
                raise HTTPException(status_code=400, detail="Post is scheduled for future publication")
                
        # Post to selected platforms
        platforms = {
            'twitter': post['publish_to_twitter'],
            'instagram': post['publish_to_instagram'],
            'facebook': post['publish_to_facebook'],
            'pinterest': post['publish_to_pinterest']
        }
        
        post_results = await social_media_poster.post_to_platforms(
            post['content'], 
            post['image_url'],
            platforms
        )
        
        # Update post with platform-specific post IDs
        cursor.execute('''
            UPDATE posts 
            SET is_published = 1, 
                updated_at = CURRENT_TIMESTAMP,
                twitter_post_id = ?,
                instagram_post_id = ?,
                facebook_post_id = ?,
                pinterest_post_id = ?
            WHERE id = ?
        ''', (
            post_results.get('twitter_post_id'),
            post_results.get('instagram_post_id'),
            post_results.get('facebook_post_id'),
            post_results.get('pinterest_post_id'),
            post_id
        ))
        conn.commit()
        
        return {"message": "Post published successfully", "post": post, "platform_results": post_results}
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to publish post: {str(e)}")
    finally:
        conn.close()

@app.delete("/posts/{post_id}")
def delete_post(post_id: int):
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute('SELECT * FROM posts WHERE id = ?', (post_id,))
        post = cursor.fetchone()
        if not post:
            raise HTTPException(status_code=404, detail="Post not found")
        cursor.execute('DELETE FROM posts WHERE id = ?', (post_id,))
        conn.commit()
        return {"message": "Post deleted successfully"}
    finally:
        conn.close()

@app.post("/posts/{post_id}/cancel")
def cancel_post(post_id: int):
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute('SELECT * FROM posts WHERE id = ?', (post_id,))
        post = cursor.fetchone()
        if not post:
            raise HTTPException(status_code=404, detail="Post not found")
        cursor.execute('UPDATE posts SET is_canceled = 1, updated_at = CURRENT_TIMESTAMP WHERE id = ?', (post_id,))
        conn.commit()
        return {"message": "Post canceled successfully"}
    finally:
        conn.close()

@app.delete("/posts/{post_id}/cancel")
def uncancel_post(post_id: int):
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute('SELECT * FROM posts WHERE id = ?', (post_id,))
        post = cursor.fetchone()
        if not post:
            raise HTTPException(status_code=404, detail="Post not found")
        cursor.execute('UPDATE posts SET is_canceled = 0, updated_at = CURRENT_TIMESTAMP WHERE id = ?', (post_id,))
        conn.commit()
        return {"message": "Post unscheduled (uncanceled) successfully"}
    finally:
        conn.close()

# --------------------
# Draft Endpoints
# --------------------

@app.get("/drafts/", response_model=List[PostResponse])
def get_drafts(skip: int = 0, limit: int = 100):
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute('SELECT * FROM posts WHERE is_draft = 1 ORDER BY updated_at DESC LIMIT ? OFFSET ?', (limit, skip))
        drafts = [dict(row) for row in cursor.fetchall()]
        for draft in drafts:
            if draft["scheduled_time"] is not None:
                draft["scheduled_time"] = to_cst(draft["scheduled_time"])
            else:
                # Use default time for UI display purposes
                default_time = datetime.now(ZoneInfo("America/Chicago")) + timedelta(days=1)
                draft["scheduled_time"] = default_time.isoformat()
        return drafts
    finally:
        conn.close()

@app.post("/drafts/", response_model=PostResponse)
async def create_draft(post: PostCreate):
    conn = get_db()
    cursor = conn.cursor()
    try:
        scheduled_time = None
        if post.scheduled_time:
            scheduled_time = post.scheduled_time.replace(tzinfo=ZoneInfo("America/Chicago")).isoformat()
            
        cursor.execute('''
            INSERT INTO posts (content, image_url, scheduled_time, is_draft, updated_at)
            VALUES (?, ?, ?, 1, CURRENT_TIMESTAMP)
        ''', (post.content or '', post.image_url or '', scheduled_time))
        
        post_id = cursor.lastrowid
        conn.commit()
        cursor.execute('SELECT * FROM posts WHERE id = ?', (post_id,))
        db_post = dict(cursor.fetchone())
        
        if db_post["scheduled_time"] is not None:
            db_post["scheduled_time"] = to_cst(db_post["scheduled_time"])
        else:
            # Use a future date as placeholder
            default_time = datetime.now(ZoneInfo("America/Chicago")) + timedelta(days=1)
            db_post["scheduled_time"] = default_time.isoformat()
            
        return db_post
    finally:
        conn.close()

@app.put("/drafts/{post_id}", response_model=PostResponse)
async def update_draft(post_id: int, post: PostCreate):
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute('SELECT * FROM posts WHERE id = ?', (post_id,))
        existing_post = cursor.fetchone()
        if not existing_post:
            raise HTTPException(status_code=404, detail="Draft not found")
        
        scheduled_time = None
        if post.scheduled_time:
            scheduled_time = post.scheduled_time.replace(tzinfo=ZoneInfo("America/Chicago")).isoformat()
            
        cursor.execute('''
            UPDATE posts 
            SET content = ?, image_url = ?, scheduled_time = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        ''', (post.content or '', post.image_url or '', scheduled_time, post_id))
        conn.commit()
        cursor.execute('SELECT * FROM posts WHERE id = ?', (post_id,))
        updated_post = dict(cursor.fetchone())
        
        if updated_post["scheduled_time"] is not None:
            updated_post["scheduled_time"] = to_cst(updated_post["scheduled_time"])
        else:
            default_time = datetime.now(ZoneInfo("America/Chicago")) + timedelta(days=1)
            updated_post["scheduled_time"] = default_time.isoformat()
            
        return updated_post
    finally:
        conn.close()

@app.post("/posts/{post_id}/schedule")
async def schedule_post(post_id: int, scheduled_data: dict):
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute('SELECT * FROM posts WHERE id = ?', (post_id,))
        post = cursor.fetchone()
        if not post:
            raise HTTPException(status_code=404, detail="Post not found")
        
        scheduled_time = scheduled_data.get("scheduled_time")
        if not scheduled_time:
            raise HTTPException(status_code=400, detail="Scheduled time is required")
            
        # Parse the scheduled time and ensure it's in the future
        try:
            scheduled_dt = datetime.fromisoformat(scheduled_time.replace('Z', '+00:00'))
            scheduled_cst = scheduled_dt.astimezone(ZoneInfo("America/Chicago"))
            now_cst = datetime.now(ZoneInfo("America/Chicago"))
            
            if scheduled_cst <= now_cst:
                raise HTTPException(status_code=400, detail="Scheduled time must be in the future (CST)")
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid datetime format")
        
        cursor.execute('''
            UPDATE posts 
            SET scheduled_time = ?, is_draft = 0, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        ''', (scheduled_cst.isoformat(), post_id))
        conn.commit()
        
        cursor.execute('SELECT * FROM posts WHERE id = ?', (post_id,))
        updated_post = dict(cursor.fetchone())
        if updated_post["scheduled_time"]:
            updated_post["scheduled_time"] = to_cst(updated_post["scheduled_time"])
        
        return {"message": "Post scheduled successfully", "post": updated_post}
    finally:
        conn.close()

# ----------------------------------
# Health Check
# ----------------------------------
@app.get("/health")
def health_check():
    return {
        "status": "healthy",
        "timestamp": datetime.now(ZoneInfo("America/Chicago")).isoformat(),
        "services": {
            "recipe_bot": "initialized",
            "image_evaluator": "initialized",
            "image_poster": "initialized"
        }
    }

# ----------------------------------
# SSE Streaming Endpoints
# ----------------------------------
@app.get("/stream/generate/text")
async def sse_generate_text():
    async def event_generator():
        try:
            yield "data: Starting conversation...\n\n"
            conversation = await asyncio.to_thread(recipe_bot.start_conversation)
            yield "data: Conversation complete.\n\n"
            
            yield "data: Evaluating tweet drafts...\n\n"
            evaluation = await asyncio.to_thread(recipe_bot.evaluate_tweets, conversation)
            yield "data: Evaluation complete.\n\n"
            
            yield "data: Refining best tweet...\n\n"
            refined = await asyncio.to_thread(recipe_bot.refine_best_tweet, evaluation)
            yield "data: Refinement complete.\n\n"
            
            yield "data: Extracting tweet...\n\n"
            extracted = await asyncio.to_thread(recipe_bot.extract_tweet, refined)
            yield "data: Extraction complete.\n\n"
            
            yield "data: Predicting optimal posting time...\n\n"
            prediction = await asyncio.to_thread(recipe_bot.predict_optimal_posting_time, extracted["tweet_text"])
            final_result = {
                "tweet_text": extracted["tweet_text"],
                "reasoning": extracted["reasoning"],
                "optimal_hour": prediction["optimal_hour"],
                "timing_reasoning": prediction["reasoning"]
            }
            yield "data: " + json.dumps(final_result) + "\n\n"
        except Exception as e:
            yield "data: Error: " + str(e) + "\n\n"
    return StreamingResponse(event_generator(), media_type="text/event-stream")

@app.get("/stream/generate/image")
async def sse_generate_image(tweet_text: str = Query(...)):
    async def event_generator():
        try:
            yield "data: Starting image search...\n\n"
            queries = await asyncio.to_thread(image_evaluator.generate_search_queries, tweet_text)
            yield "data: Generated image queries.\n\n"
            all_results = []
            for query in queries:
                yield "data: Fetching image URLs for query: " + query + "\n\n"
                image_urls = await asyncio.to_thread(image_evaluator.get_top_4_image_urls, query)
                yield "data: Evaluating images for query: " + query + "\n\n"
                results = await asyncio.to_thread(image_evaluator.evaluate_images_in_parallel, tweet_text, image_urls)
                all_results.extend(results)
            if not all_results:
                yield "data: No suitable images found.\n\n"
                return
            best_matches = sorted(all_results, key=lambda x: (-x['score'], len(x['explanation'])))
            best_match = best_matches[0]
            if best_match['score'] < 7:
                yield "data: No images met quality threshold.\n\n"
                return
            final_result = {
                "image_url": best_match['url'],
                "score": best_match['score'],
                "explanation": best_match['explanation']
            }
            yield "data: " + json.dumps(final_result) + "\n\n"
        except Exception as e:
            yield "data: Error: " + str(e) + "\n\n"
    return StreamingResponse(event_generator(), media_type="text/event-stream")

# ----------------------------------
# Scheduled Tweet Publisher
# ----------------------------------
async def publish_due_tweets():
    """Check and publish tweets that are due"""
    conn = get_db()
    cursor = conn.cursor()
    now_cst = datetime.now(ZoneInfo("America/Chicago"))
    social_media_poster = SocialMediaPoster()
    
    try:
        # Get all unpublished, uncanceled tweets that are due
        cursor.execute('''
            SELECT id, content, image_url, 
                   publish_to_twitter, publish_to_instagram,
                   publish_to_facebook, publish_to_pinterest
            FROM posts 
            WHERE scheduled_time <= ? 
            AND is_published = 0 
            AND is_canceled = 0
            AND is_draft = 0
        ''', (now_cst.isoformat(),))
        
        due_posts = cursor.fetchall()
        
        for post in due_posts:
            try:
                post_id = post[0]
                content = post[1]
                image_url = post[2]
                
                platforms = {
                    'twitter': post[3],
                    'instagram': post[4],
                    'facebook': post[5],
                    'pinterest': post[6]
                }
                
                post_results = await social_media_poster.post_to_platforms(
                    content,
                    image_url,
                    platforms
                )
                
                # Update post with platform-specific post IDs
                cursor.execute('''
                    UPDATE posts 
                    SET is_published = 1,
                        updated_at = CURRENT_TIMESTAMP,
                        twitter_post_id = ?,
                        instagram_post_id = ?,
                        facebook_post_id = ?,
                        pinterest_post_id = ?
                    WHERE id = ?
                ''', (
                    post_results.get('twitter_post_id'),
                    post_results.get('instagram_post_id'),
                    post_results.get('facebook_post_id'),
                    post_results.get('pinterest_post_id'),
                    post_id
                ))
                conn.commit()
                
                print(f"Successfully published scheduled post {post_id}")
                
            except Exception as e:
                print(f"Error publishing post {post_id}: {str(e)}")
                continue
                
    finally:
        conn.close()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)

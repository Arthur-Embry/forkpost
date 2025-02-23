import requests
from requests_oauthlib import OAuth1
import os
import json
import time
import asyncio

# API Credentials
# Twitter/X
TWITTER_API_KEY = os.getenv('TWITTER_API_KEY')
TWITTER_API_SECRET = os.getenv('TWITTER_API_SECRET')
TWITTER_ACCESS_TOKEN = os.getenv('TWITTER_ACCESS_TOKEN')
TWITTER_ACCESS_TOKEN_SECRET = os.getenv('TWITTER_ACCESS_TOKEN_SECRET')

# Instagram
INSTAGRAM_ACCOUNT_ID = os.getenv('INSTAGRAM_ACCOUNT_ID')
INSTAGRAM_ACCESS_TOKEN = os.getenv('INSTAGRAM_ACCESS_TOKEN')

# Facebook
FACEBOOK_PAGE_ID = os.getenv('FACEBOOK_PAGE_ID')
FACEBOOK_ACCESS_TOKEN = os.getenv('FACEBOOK_ACCESS_TOKEN')

# Pinterest
PINTEREST_ACCESS_TOKEN = os.getenv('PINTEREST_ACCESS_TOKEN')
PINTEREST_BOARD_ID = os.getenv('PINTEREST_BOARD_ID')

class TwitterImagePoster:
    # API URLs
    MEDIA_UPLOAD_URL = 'https://upload.twitter.com/1.1/media/upload.json'
    TWEET_URL = 'https://api.twitter.com/2/tweets'

    def __init__(self):
        self.oauth = OAuth1(
            TWITTER_API_KEY,
            client_secret=TWITTER_API_SECRET,
            resource_owner_key=TWITTER_ACCESS_TOKEN,
            resource_owner_secret=TWITTER_ACCESS_TOKEN_SECRET
        )

    def download_image(self, url, local_filename):
        """Download image from URL and save to local file"""
        print(f"Downloading image from {url}")
        response = requests.get(url)
        response.raise_for_status()
        with open(local_filename, 'wb') as f:
            f.write(response.content)
        print(f"Image saved to {local_filename}")
        return local_filename

    def tweet_with_image(self, text, image_path):
        """Post a tweet with an image"""
        print(f"Reading image file: {image_path}")
        with open(image_path, 'rb') as image_file:
            files = {'media': image_file}
            print("Uploading image to Twitter...")
            upload_response = requests.post(
                self.MEDIA_UPLOAD_URL,
                auth=self.oauth,
                files=files
            )
            
            print(f"Upload response status code: {upload_response.status_code}")
            print(f"Upload response text: {upload_response.text}")
            
            if upload_response.status_code != 200:
                raise Exception(f"Failed to upload image: {upload_response.text}")
            
            media_id = upload_response.json()['media_id_string']
            print(f"Media ID received: {media_id}")

        tweet_data = {
            "text": text,
            "media": {
                "media_ids": [media_id]
            }
        }
        
        print("Posting tweet...")
        tweet_response = requests.post(
            self.TWEET_URL,
            auth=self.oauth,
            json=tweet_data
        )
        
        print(f"Tweet response status code: {tweet_response.status_code}")
        print(f"Tweet response text: {tweet_response.text}")
        
        if tweet_response.status_code != 201:
            raise Exception(f"Failed to post tweet: {tweet_response.text}")
        
        return tweet_response.json()

    def post_image_from_url(self, tweet_text, image_url):
        """Download image from URL and post tweet with it"""
        local_filename = "temp_image.png"
        try:
            self.download_image(image_url, local_filename)
            tweet = self.tweet_with_image(tweet_text, local_filename)
            print(f"Tweet posted successfully! Response: {json.dumps(tweet, indent=2)}")
            return tweet
            
        except requests.exceptions.RequestException as e:
            print(f"Network error occurred: {str(e)}")
            raise
        except Exception as e:
            print(f"Error: {str(e)}")
            raise
            
        finally:
            if os.path.exists(local_filename):
                print(f"Cleaning up: removing {local_filename}")
                os.remove(local_filename)

class InstagramImagePoster:
    def __init__(self):
        self.graph_url = "https://graph.facebook.com/v22.0"
        self.account_id = INSTAGRAM_ACCOUNT_ID
        self.access_token = INSTAGRAM_ACCESS_TOKEN
    
    def create_container(self, image_url, caption=None):
        """Create a media container for the Instagram post"""
        url = f"{self.graph_url}/{self.account_id}/media"
        params = {
            "image_url": image_url,
            "access_token": self.access_token
        }
        
        if caption:
            params["caption"] = caption

        try:
            print(f"Creating Instagram container with image: {image_url}")
            print(f"Caption: {caption}")
            
            response = requests.post(url, params=params)
            print(f"Container creation response status: {response.status_code}")
            print(f"Container creation response: {response.text}")
            
            response.raise_for_status()
            container_id = response.json().get("id")
            
            if container_id:
                print(f"Container created successfully with ID: {container_id}")
                return container_id
            else:
                raise Exception("No container ID returned")
                
        except requests.exceptions.RequestException as e:
            print(f"Error creating container: {str(e)}")
            if 'response' in locals():
                print(f"Response content: {response.text}")
            raise
    
    def check_container_status(self, container_id):
        """Check the status of a container"""
        url = f"{self.graph_url}/{container_id}"
        params = {
            "fields": "status_code",
            "access_token": self.access_token
        }

        try:
            response = requests.get(url, params=params)
            response.raise_for_status()
            status = response.json().get("status_code")
            print(f"Container status: {status}")
            return status
        except requests.exceptions.RequestException as e:
            print(f"Error checking container status: {str(e)}")
            raise
    
    def publish_container(self, container_id):
        """Publish the container to Instagram"""
        url = f"{self.graph_url}/{self.account_id}/media_publish"
        params = {
            "creation_id": container_id,
            "access_token": self.access_token
        }

        try:
            print(f"Publishing container {container_id}")
            response = requests.post(url, params=params)
            print(f"Publish response status: {response.status_code}")
            print(f"Publish response: {response.text}")
            
            response.raise_for_status()
            media_id = response.json().get("id")
            
            if media_id:
                print(f"Post published successfully with ID: {media_id}")
                return media_id
            else:
                raise Exception("No media ID returned")
                
        except requests.exceptions.RequestException as e:
            print(f"Error publishing container: {str(e)}")
            raise
    
    def post_image_from_url(self, image_url, caption):
        """Post an image to Instagram from a URL"""
        try:
            # Create container
            container_id = self.create_container(image_url, caption)
            
            # Wait for container to be ready
            max_attempts = 5
            attempt = 0
            while attempt < max_attempts:
                status = self.check_container_status(container_id)
                if status == "FINISHED":
                    break
                elif status in ["ERROR", "EXPIRED"]:
                    raise Exception(f"Container failed with status: {status}")
                
                print(f"Waiting for container to be ready (attempt {attempt+1}/{max_attempts})...")
                time.sleep(5)  # Wait 5 seconds between checks
                attempt += 1
            
            if status != "FINISHED":
                raise Exception("Container not ready after maximum attempts")
            
            # Publish container
            media_id = self.publish_container(container_id)
            print(f"Successfully posted to Instagram with media ID: {media_id}")
            return media_id
            
        except Exception as e:
            print(f"Error posting to Instagram: {str(e)}")
            raise

class FacebookImagePoster:
    def __init__(self):
        self.graph_url = "https://graph.facebook.com/v17.0"
        # Set default Page ID and token
        self.page_id = FACEBOOK_PAGE_ID
        self.access_token = FACEBOOK_ACCESS_TOKEN
        
    def get_page_info(self):
        """Try to get information about the page"""
        page_url = f"{self.graph_url}/{self.page_id}"
        params = {
            "fields": "id,name,access_token",
            "access_token": self.access_token
        }
        
        try:
            print(f"Getting info for Page ID: {self.page_id}")
            response = requests.get(page_url, params=params)
            print(f"Page info response status: {response.status_code}")
            print(f"Page info response: {response.text}")
            
            if response.status_code == 200:
                page_data = response.json()
                print(f"Successfully accessed Page: {page_data.get('name', 'Unknown')}")
                
                # If we got a page-specific token, use it
                if 'access_token' in page_data:
                    self.access_token = page_data['access_token']
                    print("Using page-specific access token")
                    
                return page_data
            else:
                print("Failed to get page info")
                return None
                
        except Exception as e:
            print(f"Error getting page info: {str(e)}")
            return None
    
    def post_image_to_page(self, image_url, caption):
        """Post an image to the business Page"""
        # Try to get page info first (optional but helpful)
        self.get_page_info()
            
        local_filename = "temp_facebook_image.jpg"
        try:
            # Download image
            print(f"Downloading image from {image_url}")
            response = requests.get(image_url)
            response.raise_for_status()
            with open(local_filename, 'wb') as f:
                f.write(response.content)
            
            # Upload to page photos
            photos_url = f"{self.graph_url}/{self.page_id}/photos"
            
            with open(local_filename, 'rb') as image_file:
                files = {'source': image_file}
                params = {
                    "message": caption,
                    "access_token": self.access_token
                }
                
                print(f"Uploading photo to Page {self.page_id}...")
                response = requests.post(photos_url, params=params, files=files)
                print(f"Photo upload response status: {response.status_code}")
                print(f"Photo upload response: {response.text}")
                
                response.raise_for_status()
                photo_id = response.json().get("id") or response.json().get("post_id")
                
                if photo_id:
                    print(f"Photo uploaded successfully to Page with ID: {photo_id}")
                    return photo_id
                else:
                    raise Exception("No photo ID returned")
                    
        except Exception as e:
            print(f"Error: {str(e)}")
            raise
        finally:
            if os.path.exists(local_filename):
                print(f"Cleaning up: removing {local_filename}")
                os.remove(local_filename)
    
    def post_image_from_url(self, image_url, caption):
        """Post an image to Facebook (compatible with existing code)"""
        try:
            return self.post_image_to_page(image_url, caption)
        except Exception as e:
            print(f"Failed to post to Facebook: {str(e)}")
            raise


class PinterestImagePoster:
    def __init__(self):
        self.api_url = "https://api.pinterest.com/v5"
        self.access_token = PINTEREST_ACCESS_TOKEN
        self.board_id = PINTEREST_BOARD_ID
    
    def download_image(self, url, local_filename):
        """Download image from URL and save to local file"""
        print(f"Downloading image from {url}")
        response = requests.get(url)
        response.raise_for_status()
        with open(local_filename, 'wb') as f:
            f.write(response.content)
        print(f"Image saved to {local_filename}")
        return local_filename
    
    def upload_media(self, image_path):
        """Upload media to Pinterest and get media ID"""
        upload_url = f"{self.api_url}/media"
        headers = {
            "Authorization": f"Bearer {self.access_token}"
        }
        
        print(f"Reading image file: {image_path}")
        with open(image_path, 'rb') as image_file:
            files = {"image": image_file}
            
            print("Uploading image to Pinterest...")
            upload_response = requests.post(
                upload_url,
                headers=headers,
                files=files
            )
            
            print(f"Upload response status code: {upload_response.status_code}")
            print(f"Upload response text: {upload_response.text}")
            
            if upload_response.status_code != 201:
                raise Exception(f"Failed to upload image: {upload_response.text}")
            
            media_id = upload_response.json()['id']
            print(f"Media ID received: {media_id}")
            return media_id
    
    def create_pin(self, title, description, media_id, link=None):
        """Create a pin with the uploaded media"""
        pins_url = f"{self.api_url}/pins"
        headers = {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json"
        }
        
        pin_data = {
            "board_id": self.board_id,
            "media_source": {
                "media_id": media_id
            },
            "title": title,
            "description": description
        }
        
        if link:
            pin_data["link"] = link
        
        print("Creating Pinterest pin...")
        pin_response = requests.post(
            pins_url,
            headers=headers,
            json=pin_data
        )
        
        print(f"Pin creation response status code: {pin_response.status_code}")
        print(f"Pin creation response text: {pin_response.text}")
        
        if pin_response.status_code != 201:
            raise Exception(f"Failed to create pin: {pin_response.text}")
        
        pin_id = pin_response.json()['id']
        print(f"Pin created with ID: {pin_id}")
        return pin_response.json()
    
    def post_image_from_url(self, image_url, title, description=None, link=None):
        """Download image from URL and post to Pinterest"""
        local_filename = "temp_pinterest_image.jpg"
        try:
            # Download the image
            self.download_image(image_url, local_filename)
            
            # Upload the media
            media_id = self.upload_media(local_filename)
            
            # Create the pin
            result = self.create_pin(
                title=title,
                description=description or title,
                media_id=media_id,
                link=link
            )
            
            print(f"Pin posted successfully! Response: {json.dumps(result, indent=2)}")
            return result
            
        except requests.exceptions.RequestException as e:
            print(f"Network error occurred: {str(e)}")
            raise
        except Exception as e:
            print(f"Error: {str(e)}")
            raise
            
        finally:
            if os.path.exists(local_filename):
                print(f"Cleaning up: removing {local_filename}")
                os.remove(local_filename)


class SocialMediaPoster:
    def __init__(self):
        self.twitter_poster = TwitterImagePoster()
        self.instagram_poster = InstagramImagePoster()
        self.facebook_poster = FacebookImagePoster()
        self.pinterest_poster = PinterestImagePoster()

    async def post_to_platforms(self, content, image_url, platforms):
        results = {}
        
        # Ensure platforms is a dict with boolean values
        platforms = {
            'twitter': bool(platforms.get('publish_to_twitter', False)),
            'instagram': bool(platforms.get('publish_to_instagram', False)),
            'facebook': bool(platforms.get('publish_to_facebook', False)),
            'pinterest': bool(platforms.get('publish_to_pinterest', False))
        }

        if platforms['twitter']:
            try:
                result = await asyncio.to_thread(
                    self.twitter_poster.post_image_from_url, 
                    content, 
                    image_url
                )
                results['twitter_post_id'] = result.get('id')
            except Exception as e:
                print(f"Twitter posting error: {e}")
                results['twitter_post_id'] = None

        if platforms['instagram']:
            try:
                result = await asyncio.to_thread(
                    self.instagram_poster.post_image_from_url, 
                    image_url, 
                    content
                )
                results['instagram_post_id'] = result
            except Exception as e:
                print(f"Instagram posting error: {e}")
                results['instagram_post_id'] = None

        if platforms['facebook']:
            try:
                result = await asyncio.to_thread(
                    self.facebook_poster.post_image_from_url, 
                    image_url, 
                    content
                )
                results['facebook_post_id'] = result
            except Exception as e:
                print(f"Facebook posting error: {e}")
                results['facebook_post_id'] = None

        if platforms['pinterest']:
            try:
                result = await asyncio.to_thread(
                    self.pinterest_poster.post_image_from_url, 
                    image_url, 
                    content,  # Used as title
                    content   # Used as description
                )
                results['pinterest_post_id'] = result.get('id')
            except Exception as e:
                print(f"Pinterest posting error: {e}")
                results['pinterest_post_id'] = None

        return results
from dotenv import load_dotenv
load_dotenv()

from post import TwitterImagePoster, InstagramImagePoster, FacebookImagePoster, PinterestImagePoster

def main():
    # Test image and caption
    test_image = "https://upload.wikimedia.org/wikipedia/commons/thumb/4/47/PNG_transparency_demonstration_1.png/280px-PNG_transparency_demonstration_1.png"
    test_caption = "Test post"
    
    # Create instances of all three posters
    twitter_poster = TwitterImagePoster()
    instagram_poster = InstagramImagePoster()
    facebook_poster = FacebookImagePoster()
    pinterest_poster = PinterestImagePoster()
    """# Post to Twitter
    try:
        tweet = twitter_poster.post_image_from_url(test_caption, test_image)
        print(f"Successfully posted to Twitter! Tweet ID: {tweet.get('data', {}).get('id')}")
    except Exception as e:
        print(f"Failed to post to Twitter: {str(e)}")
    
    # Post to Instagram
    try:
        media_id = instagram_poster.post_image_from_url(test_image, test_caption)
        print(f"Successfully posted to Instagram! Media ID: {media_id}")
    except Exception as e:
        print(f"Failed to post to Instagram: {str(e)}")
    
    # Post to Facebook
    try:
        post_id = facebook_poster.post_image_from_url(test_image, test_caption)
        print(f"Successfully posted to Facebook! Post ID: {post_id}")
    except Exception as e:
        print(f"Failed to post to Facebook: {str(e)}")
    
    # Post to Pinterest
    try:
        post_id = pinterest_poster.post_image_from_url(test_image, test_caption)
        print(f"Successfully posted to Pinterest! Post ID: {post_id}")
    except Exception as e:
        print(f"Failed to post to Pinterest: {str(e)}")"""
        
if __name__ == "__main__":
    main()
# Replace with your API key
import requests
import re
import sys
import os
import time
import argparse
from datetime import datetime
from youtube_transcript_api import YouTubeTranscriptApi


# Your YOUTUBE API KEY - get it from https://console.cloud.google.com/?hl=de
API_KEY = "AIzaSyBUdEQ-NBQr_0WgWf-FLQw7W0mWyOLo3RI"



def sanitize_filename(name):
    """
    Sanitize the video title to be used as a filename by removing or replacing
    characters that are illegal in filenames.
    """
    # Remove invalid characters: <>:"/\\|?*
    sanitized = re.sub(r'[<>:"/\\|?*]', '', name)
    # Optionally, you can trim the filename length if it's too long
    return sanitized.strip()

def get_channel_id(query):
    """
    Searches for the channel by name or handle (query) and returns its unique channel ID.
    """
    search_url = (
        f"https://www.googleapis.com/youtube/v3/search?"
        f"part=snippet&type=channel&q={query}&key={API_KEY}"
    )
    response = requests.get(search_url)
    if response.status_code != 200:
        print("Error searching for channel:", response.text)
        sys.exit(1)
    data = response.json()
    if data.get("items"):
        # For channel search results, the channel ID is in the id.channelId field.
        return data["items"][0]["id"]["channelId"]
    else:
        print("No channel found for query:", query)
        sys.exit(1)

def get_uploads_playlist_id(channel_id):
    """
    Gets the uploads playlist ID for the given channel ID.
    """
    channel_details_url = (
        f"https://www.googleapis.com/youtube/v3/channels?"
        f"part=contentDetails&id={channel_id}&key={API_KEY}"
    )
    response = requests.get(channel_details_url)
    if response.status_code != 200:
        print("Error fetching channel details:", response.text)
        sys.exit(1)
    data = response.json()
    if data.get("items"):
        return data["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]
    else:
        print("No channel details found.")
        sys.exit(1)

def get_video_ids_from_playlist(playlist_id, after_date=None):
    """
    Gets all video IDs from the uploads playlist, optionally filtered by date.
    """
    video_data = []
    next_page_token = None
    
    while True:
        playlist_items_url = (
            f"https://www.googleapis.com/youtube/v3/playlistItems?"
            f"part=snippet&maxResults=50&playlistId={playlist_id}&key={API_KEY}"
        )
        if next_page_token:
            playlist_items_url += f"&pageToken={next_page_token}"
        
        response = requests.get(playlist_items_url)
        if response.status_code != 200:
            print("Error fetching playlist items:", response.text)
            sys.exit(1)
        data = response.json()
        
        for item in data.get("items", []):
            published_at = item["snippet"]["publishedAt"]
            video_id = item["snippet"]["resourceId"]["videoId"]
            
            # Parse the date
            video_date = datetime.fromisoformat(published_at.replace('Z', '+00:00'))
            
            # Filter by date if specified
            if after_date is None or video_date > after_date:
                video_data.append({
                    'id': video_id,
                    'date': video_date,
                    'title': item["snippet"]["title"]
                })
        
        next_page_token = data.get("nextPageToken")
        if not next_page_token:
            break
    
    return video_data

def get_video_details(video_ids):
    """
    Gets video details (title) for the given video IDs.
    """
    video_details = []
    # YouTube API allows up to 50 video IDs per request
    for i in range(0, len(video_ids), 50):
        chunk = video_ids[i:i+50]
        video_ids_str = ','.join(chunk)
        videos_url = (
            f"https://www.googleapis.com/youtube/v3/videos?"
            f"part=snippet&id={video_ids_str}&key={API_KEY}"
        )
        response = requests.get(videos_url)
        if response.status_code != 200:
            print("Error fetching video details:", response.text)
            continue
        data = response.json()
        for item in data.get("items", []):
            video_details.append({
                'id': item['id'],
                'title': item['snippet']['title']
            })
    return video_details

def download_transcript(video_id, title, output_dir="transcripts"):
    """
    Downloads the transcript for a given video ID and saves it to a file.
    """
    try:
        # Create API instance
        api = YouTubeTranscriptApi()
        
        # Try to get any available transcript
        transcript_list = api.list(video_id)
        
        # Try to get manually created transcript first, then auto-generated
        try:
            transcript = transcript_list.find_manually_created_transcript(['en']).fetch()
        except:
            try:
                transcript = transcript_list.find_generated_transcript(['en']).fetch()
            except:
                # Get any available transcript
                transcript = transcript_list.find_transcript(['en']).fetch()
        
        # Create the output directory if it doesn't exist
        if not os.path.exists(output_dir):
            os.makedirs(output_dir)
        
        # Combine transcript text
        full_text = '\n'.join([entry.text for entry in transcript])
        
        # Sanitize the title for filename
        filename = sanitize_filename(title)
        filepath = os.path.join(output_dir, f"{filename}.txt")
        
        # Save to file
        with open(filepath, 'w', encoding='utf-8') as file:
            file.write(full_text)
        
        return True
    except Exception as e:
        # Only show brief error message
        if "blocking requests" in str(e):
            print(f"    Rate limited - YouTube is blocking requests")
        elif "No transcripts" in str(e):
            print(f"    No transcript available")
        else:
            print(f"    Error: {str(e)[:100]}")
        return False

def main():
    parser = argparse.ArgumentParser(description='Download YouTube transcripts in bulk')
    parser.add_argument('--channel', type=str, help='YouTube channel name or handle (e.g., @ycombinator)')
    parser.add_argument('--video-ids', type=str, help='Comma-separated list of video IDs')
    parser.add_argument('--api-key', type=str, help='YouTube Data API v3 key')
    parser.add_argument('--after-date', type=str, help='Only download videos after this date (YYYY-MM-DD)')
    parser.add_argument('--output-dir', type=str, default='transcripts', help='Output directory for transcripts')
    parser.add_argument('--delay', type=float, default=3.0, help='Delay in seconds between transcript downloads (default: 3.0)')
    
    args = parser.parse_args()
    
    # Override API key if provided
    global API_KEY
    if args.api_key:
        API_KEY = args.api_key
    
    # Parse after_date if provided
    after_date = None
    if args.after_date:
        after_date = datetime.strptime(args.after_date, '%Y-%m-%d')
        after_date = after_date.replace(tzinfo=datetime.now().astimezone().tzinfo)
    
    # If video IDs are provided directly
    if args.video_ids:
        video_ids = [vid.strip() for vid in args.video_ids.split(',')]
        print(f"Downloading transcripts for {len(video_ids)} video(s)...")
        for video_id in video_ids:
            download_transcript(video_id, f"video_{video_id}", args.output_dir)
        return
    
    # If channel is provided
    if args.channel:
        channel_query = args.channel
    else:
        # Interactive mode
        channel_query = input("Enter the YouTube channel name or handle (e.g., @ycombinator): ").strip()
    
    if API_KEY == "YOUR_API_KEY_HERE":
        print("\n⚠️  WARNING: You haven't set up your YouTube API key!")
        print("To use the API features, please:")
        print("1. Get your API key from https://console.cloud.google.com/")
        print("2. Use --api-key parameter or replace 'YOUR_API_KEY_HERE' in the script\n")
        print("For now, you can manually enter video IDs to download transcripts.")
        
        # Alternative: Allow manual video ID input
        video_ids_input = input("Enter video IDs separated by commas (or press Enter to exit): ").strip()
        if not video_ids_input:
            print("Exiting...")
            sys.exit(0)
        
        video_ids = [vid.strip() for vid in video_ids_input.split(',')]
        
        # Download transcripts for manually entered video IDs
        for video_id in video_ids:
            download_transcript(video_id, f"video_{video_id}", args.output_dir)
    else:
        # Get channel ID from query
        print(f"Searching for channel: {channel_query}")
        channel_id = get_channel_id(channel_query)
        print(f"Found channel ID: {channel_id}")
        
        # Get uploads playlist ID
        uploads_playlist_id = get_uploads_playlist_id(channel_id)
        print(f"Uploads playlist ID: {uploads_playlist_id}")
        
        # Get all video IDs from the channel's uploads
        print("Fetching video IDs...")
        video_data = get_video_ids_from_playlist(uploads_playlist_id, after_date)
        
        if after_date:
            print(f"Found {len(video_data)} videos after {args.after_date}")
        else:
            print(f"Found {len(video_data)} videos")
        
        # Download transcripts for each video
        print(f"\nStarting transcript downloads for {len(video_data)} videos...")
        print(f"Using {args.delay} second delay between downloads to avoid rate limiting...")
        
        # TEMP: Test with just first 3 videos
        test_limit = min(3, len(video_data))
        print(f"TEST MODE: Only downloading first {test_limit} videos...")
        
        success_count = 0
        for i, video in enumerate(video_data[:test_limit], 1):
            print(f"\n[{i}/{test_limit}] Downloading: {video['title'][:60]}...")
            if download_transcript(video['id'], video['title'], args.output_dir):
                success_count += 1
                print(f"    ✓ Success")
            else:
                print(f"    ✗ Failed")
            
            # Add delay to avoid hitting rate limits (except for the last video)
            if i < test_limit:
                print(f"    Waiting {args.delay} seconds before next download...")
                time.sleep(args.delay)
        
        print(f"\n✅ Successfully downloaded {success_count} out of {test_limit} transcripts (test mode).")

if __name__ == "__main__":
    main()
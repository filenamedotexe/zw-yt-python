from flask import Flask, render_template, request, jsonify, send_file
from flask_cors import CORS
import os
import json
import threading
import queue
from datetime import datetime
import time
from youtube_transcript_api import YouTubeTranscriptApi
import requests
import re
import sys

app = Flask(__name__)
CORS(app)

# Global variables for tracking progress
download_progress = {}
download_queue = queue.Queue()

# Import functions from go.py
API_KEY = "AIzaSyBUdEQ-NBQr_0WgWf-FLQw7W0mWyOLo3RI"

def sanitize_filename(name):
    """Sanitize the video title to be used as a filename"""
    sanitized = re.sub(r'[<>:"/\\|?*]', '', name)
    return sanitized.strip()

def get_channel_id(query):
    """Searches for the channel by name or handle and returns its unique channel ID."""
    search_url = (
        f"https://www.googleapis.com/youtube/v3/search?"
        f"part=snippet&type=channel&q={query}&key={API_KEY}"
    )
    response = requests.get(search_url)
    if response.status_code != 200:
        raise Exception(f"Error searching for channel: {response.text}")
    data = response.json()
    if data.get("items"):
        return data["items"][0]["id"]["channelId"]
    else:
        raise Exception(f"No channel found for query: {query}")

def get_uploads_playlist_id(channel_id):
    """Gets the uploads playlist ID for the given channel ID."""
    channel_details_url = (
        f"https://www.googleapis.com/youtube/v3/channels?"
        f"part=contentDetails&id={channel_id}&key={API_KEY}"
    )
    response = requests.get(channel_details_url)
    if response.status_code != 200:
        raise Exception(f"Error fetching channel details: {response.text}")
    data = response.json()
    if data.get("items"):
        return data["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]
    else:
        raise Exception("No channel details found.")

def get_video_ids_from_playlist(playlist_id, after_date=None, limit=None):
    """Gets video IDs from the uploads playlist, optionally filtered by date."""
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
            raise Exception(f"Error fetching playlist items: {response.text}")
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
                    'date': video_date.isoformat(),
                    'title': item["snippet"]["title"]
                })
                
                # Check if we've reached the limit
                if limit and len(video_data) >= limit:
                    return video_data
        
        next_page_token = data.get("nextPageToken")
        if not next_page_token:
            break
    
    return video_data

def download_transcript(video_id, title, output_dir="transcripts"):
    """Downloads the transcript for a given video ID and saves it to a file."""
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
        
        return True, filepath
    except Exception as e:
        return False, str(e)

def background_download(task_id, config):
    """Background worker for downloading transcripts"""
    global download_progress
    
    try:
        download_progress[task_id] = {
            'status': 'running',
            'current': 0,
            'total': 0,
            'success': 0,
            'failed': 0,
            'videos': []
        }
        
        # Parse configuration
        channel = config.get('channel', '')
        video_ids = config.get('video_ids', '')
        after_date = config.get('after_date', '')
        output_dir = config.get('output_dir', 'transcripts')
        delay = float(config.get('delay', 3.0))
        limit = config.get('limit', None)
        
        if limit:
            limit = int(limit)
        
        # Parse after_date if provided
        after_date_obj = None
        if after_date:
            after_date_obj = datetime.strptime(after_date, '%Y-%m-%d')
            after_date_obj = after_date_obj.replace(tzinfo=datetime.now().astimezone().tzinfo)
        
        videos_to_download = []
        
        # Get videos to download
        if video_ids:
            # Direct video IDs provided
            ids = [v.strip() for v in video_ids.split(',')]
            videos_to_download = [{'id': vid, 'title': f'video_{vid}'} for vid in ids]
        elif channel:
            # Channel provided - fetch video list
            download_progress[task_id]['status'] = 'fetching_channel'
            channel_id = get_channel_id(channel)
            playlist_id = get_uploads_playlist_id(channel_id)
            videos_to_download = get_video_ids_from_playlist(playlist_id, after_date_obj, limit)
        
        # Update total count
        download_progress[task_id]['total'] = len(videos_to_download)
        download_progress[task_id]['videos'] = videos_to_download
        
        # Download each video
        for i, video in enumerate(videos_to_download):
            download_progress[task_id]['current'] = i + 1
            download_progress[task_id]['status'] = 'downloading'
            
            success, result = download_transcript(video['id'], video['title'], output_dir)
            
            if success:
                download_progress[task_id]['success'] += 1
                video['status'] = 'success'
                video['file'] = result
            else:
                download_progress[task_id]['failed'] += 1
                video['status'] = 'failed'
                video['error'] = result
            
            # Add delay between downloads (except for the last one)
            if i < len(videos_to_download) - 1:
                time.sleep(delay)
        
        download_progress[task_id]['status'] = 'completed'
        
    except Exception as e:
        download_progress[task_id]['status'] = 'error'
        download_progress[task_id]['error'] = str(e)

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/download', methods=['POST'])
def start_download():
    config = request.json
    task_id = f"task_{int(time.time() * 1000)}"
    
    # Start background download
    thread = threading.Thread(target=background_download, args=(task_id, config))
    thread.start()
    
    return jsonify({'task_id': task_id})

@app.route('/api/progress/<task_id>')
def get_progress(task_id):
    if task_id in download_progress:
        return jsonify(download_progress[task_id])
    else:
        return jsonify({'status': 'not_found'})

@app.route('/api/folders')
def list_folders():
    """List available transcript folders"""
    folders = []
    base_dir = 'transcripts'
    
    if os.path.exists(base_dir):
        for item in os.listdir(base_dir):
            path = os.path.join(base_dir, item)
            if os.path.isdir(path):
                # Count files in folder
                files = [f for f in os.listdir(path) if f.endswith('.txt')]
                folders.append({
                    'name': item,
                    'path': path,
                    'count': len(files)
                })
    
    # Also add the base transcripts folder
    if os.path.exists(base_dir):
        files = [f for f in os.listdir(base_dir) if f.endswith('.txt')]
        folders.insert(0, {
            'name': 'Main (transcripts)',
            'path': base_dir,
            'count': len(files)
        })
    
    return jsonify(folders)

@app.route('/api/config')
def get_config():
    """Get current configuration"""
    return jsonify({
        'api_key_set': API_KEY != "YOUR_API_KEY_HERE",
        'api_key_preview': API_KEY[:10] + '...' if API_KEY != "YOUR_API_KEY_HERE" else None
    })

if __name__ == '__main__':
    # Create templates directory if it doesn't exist
    if not os.path.exists('templates'):
        os.makedirs('templates')
    
    print("\n🚀 YouTube Transcript Downloader UI")
    print("📍 Open http://localhost:5555 in your browser")
    print("Press Ctrl+C to stop the server\n")
    
    app.run(debug=True, port=5555)
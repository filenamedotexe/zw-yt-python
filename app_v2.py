from flask import Flask, render_template, request, jsonify, session
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
import secrets
import hashlib
from github_storage import GitHubStorage
from download_service import DownloadService
from scheduler import JobScheduler

app = Flask(__name__)
CORS(app)
app.secret_key = os.environ.get('FLASK_SECRET_KEY', secrets.token_hex(32))

# Global variables for tracking progress
download_progress = {}
download_queue = queue.Queue()

# Initialize GitHub storage
storage = GitHubStorage()

# Initialize download service and scheduler (after function definitions)
download_service = None
scheduler = None

# API Key storage functions
def get_api_key_file():
    """Get the API key storage file path"""
    return os.path.join(os.path.dirname(__file__), '.api_key_storage')

def save_api_key_to_file(api_key):
    """Save API key securely to file"""
    try:
        # Simple encoding (not encryption, but better than plain text)
        encoded_key = hashlib.sha256(api_key.encode()).hexdigest()[:16] + api_key
        
        with open(get_api_key_file(), 'w') as f:
            f.write(encoded_key)
        return True
    except:
        return False

def load_api_key_from_file():
    """Load API key from file"""
    try:
        if os.path.exists(get_api_key_file()):
            with open(get_api_key_file(), 'r') as f:
                encoded_key = f.read().strip()
                # Extract the actual API key (skip the hash prefix)
                if len(encoded_key) > 16:
                    return encoded_key[16:]
    except:
        pass
    return None

def remove_api_key_file():
    """Remove API key file"""
    try:
        if os.path.exists(get_api_key_file()):
            os.remove(get_api_key_file())
        return True
    except:
        return False

def get_current_api_key():
    """Get current API key from session, file, or environment"""
    # Priority: session -> file -> environment
    if 'youtube_api_key' in session:
        return session['youtube_api_key']
    
    file_key = load_api_key_from_file()
    if file_key:
        return file_key
        
    return os.environ.get('YOUTUBE_API_KEY', '')

def sanitize_filename(name):
    """Sanitize the video title to be used as a filename"""
    sanitized = re.sub(r'[<>:"/\\|?*]', '', name)
    return sanitized.strip()

def get_channel_id(query, api_key):
    """Searches for the channel by name or handle and returns its unique channel ID."""
    search_url = (
        f"https://www.googleapis.com/youtube/v3/search?"
        f"part=snippet&type=channel&q={query}&key={api_key}"
    )
    response = requests.get(search_url)
    if response.status_code != 200:
        raise Exception(f"Error searching for channel: {response.text}")
    data = response.json()
    if data.get("items"):
        return data["items"][0]["id"]["channelId"]
    else:
        raise Exception(f"No channel found for query: {query}")

def get_channel_info(channel_id, api_key):
    """Get channel information including name"""
    url = (
        f"https://www.googleapis.com/youtube/v3/channels?"
        f"part=snippet&id={channel_id}&key={api_key}"
    )
    response = requests.get(url)
    if response.status_code == 200:
        data = response.json()
        if data.get("items"):
            return data["items"][0]["snippet"]["title"]
    return "Unknown Channel"

def get_uploads_playlist_id(channel_id, api_key):
    """Gets the uploads playlist ID for the given channel ID."""
    channel_details_url = (
        f"https://www.googleapis.com/youtube/v3/channels?"
        f"part=contentDetails&id={channel_id}&key={api_key}"
    )
    response = requests.get(channel_details_url)
    if response.status_code != 200:
        raise Exception(f"Error fetching channel details: {response.text}")
    data = response.json()
    if data.get("items"):
        return data["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]
    else:
        raise Exception("No channel details found.")

def get_video_ids_from_playlist(playlist_id, api_key, channel_id=None, after_date=None, limit=None):
    """Gets video IDs from the uploads playlist, optionally filtered by date."""
    video_data = []
    next_page_token = None
    
    while True:
        playlist_items_url = (
            f"https://www.googleapis.com/youtube/v3/playlistItems?"
            f"part=snippet&maxResults=50&playlistId={playlist_id}&key={api_key}"
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
                    'title': item["snippet"]["title"],
                    'channel': item["snippet"]["channelTitle"],
                    'channel_id': channel_id or item["snippet"].get("channelId", "")
                })
                
                # Check if we've reached the limit
                if limit and len(video_data) >= limit:
                    return video_data
        
        next_page_token = data.get("nextPageToken")
        if not next_page_token:
            break
    
    return video_data

def download_transcript(video_id, title, channel_name=None, channel_id=None, published_at=None):
    """Downloads the transcript for a given video ID and saves to GitHub."""
    try:
        # Check if already exists
        if storage.check_transcript_exists(video_id):
            return False, "Transcript already exists (duplicate)"
        
        # Create API instance
        api = YouTubeTranscriptApi()
        
        # Try to get any available transcript
        try:
            transcript_list = api.list(video_id)
        except Exception as e:
            error_msg = str(e)
            if "Could not retrieve" in error_msg:
                return False, f"No transcript available for this video (ID: {video_id})"
            elif "Too Many Requests" in error_msg:
                return False, "YouTube rate limit reached - please wait a few minutes"
            else:
                return False, f"Failed to fetch transcript: {error_msg[:200]}"
        
        # Try to get manually created transcript first, then auto-generated
        transcript = None
        transcript_type = "unknown"
        
        try:
            transcript = transcript_list.find_manually_created_transcript(['en']).fetch()
            transcript_type = "manual"
        except:
            try:
                transcript = transcript_list.find_generated_transcript(['en']).fetch()
                transcript_type = "auto-generated"
            except:
                try:
                    # Try to get any English transcript
                    transcript = transcript_list.find_transcript(['en']).fetch()
                except:
                    # Get first available transcript in any language
                    try:
                        available = list(transcript_list)
                        if available:
                            transcript = available[0].fetch()
                            transcript_type = f"auto ({available[0].language})"
                        else:
                            return False, "No transcripts available in any language"
                    except Exception as e:
                        return False, f"Cannot fetch transcript: {str(e)[:200]}"
        
        if not transcript:
            return False, "No transcript content found"
        
        # Combine transcript text
        full_text = '\n'.join([entry.text for entry in transcript])
        
        # If no channel name provided, use a default
        if not channel_name:
            channel_name = "Unknown_Channel"
        
        # Save to GitHub
        metadata = {
            "transcript_type": transcript_type,
            "duration": transcript[-1].start if transcript else 0,
            "channel_id": channel_id or "",
            "published_at": published_at or ""
        }
        
        result = storage.save_transcript(
            channel_name=channel_name,
            video_id=video_id,
            title=title,
            transcript_text=full_text,
            metadata=metadata
        )
        
        if result.get('duplicate'):
            return False, "Transcript already exists (duplicate)"
        elif result['success']:
            return True, result['url']
        else:
            error = result.get('error', 'Failed to save to GitHub')
            if "rate limit" in error.lower():
                return False, "GitHub API rate limit reached - please wait before retrying"
            else:
                return False, f"GitHub save failed: {error[:200]}"
            
    except Exception as e:
        error_msg = str(e)
        # Provide more specific error messages
        if "429" in error_msg or "rate" in error_msg.lower():
            return False, "Rate limited - please wait before retrying"
        elif "404" in error_msg:
            return False, f"Video not found (ID: {video_id})"
        elif "403" in error_msg:
            return False, "Access forbidden - video may be private or restricted"
        else:
            return False, f"Unexpected error: {error_msg[:200]}"

# Initialize services after function definitions
download_service = DownloadService(storage, get_current_api_key)
scheduler = JobScheduler(download_service, storage)

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
            'duplicates': 0,
            'errors': 0,
            'videos': []
        }
        
        # Get API key from current sources
        api_key = config.get('api_key') or get_current_api_key()
        
        if not api_key:
            raise Exception("No API key provided. Please set your YouTube API key.")
        
        # Parse configuration
        channel = config.get('channel', '')
        video_ids = config.get('video_ids', '')
        after_date = config.get('after_date', '')
        folder_name = config.get('folder', '')
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
        channel_name = folder_name  # Default to provided folder name
        
        # Get videos to download
        if video_ids:
            # Direct video IDs provided
            ids = [v.strip() for v in video_ids.split(',')]
            videos_to_download = [{'id': vid, 'title': f'video_{vid}', 'channel': folder_name or 'Direct_Downloads'} for vid in ids]
        elif channel:
            # Channel provided - fetch video list
            download_progress[task_id]['status'] = 'fetching_channel'
            channel_id = get_channel_id(channel, api_key)
            
            # Get actual channel name
            channel_name = get_channel_info(channel_id, api_key) or channel
            if not folder_name:
                folder_name = channel_name
            
            playlist_id = get_uploads_playlist_id(channel_id, api_key)
            videos_to_download = get_video_ids_from_playlist(playlist_id, api_key, channel_id, after_date_obj, limit)
            
            # Update channel name for all videos
            for video in videos_to_download:
                video['channel'] = folder_name
        
        # Update total count
        download_progress[task_id]['total'] = len(videos_to_download)
        download_progress[task_id]['videos'] = videos_to_download
        download_progress[task_id]['folder'] = folder_name
        
        # Download each video
        for i, video in enumerate(videos_to_download):
            download_progress[task_id]['current'] = i + 1
            download_progress[task_id]['status'] = 'downloading'
            
            success, result = download_transcript(
                video['id'], 
                video['title'],
                video.get('channel', folder_name),
                channel_id=video.get('channel_id'),
                published_at=video.get('date')
            )
            
            if success:
                download_progress[task_id]['success'] += 1
                video['status'] = 'success'
                video['url'] = result
            else:
                download_progress[task_id]['failed'] += 1
                video['status'] = 'failed'
                video['error'] = result
                
                # Track error types
                if 'duplicate' in result.lower():
                    video['error_type'] = 'duplicate'
                    download_progress[task_id]['duplicates'] += 1
                else:
                    video['error_type'] = 'error'
                    download_progress[task_id]['errors'] += 1
            
            # Add delay between downloads (except for the last one)
            if i < len(videos_to_download) - 1:
                time.sleep(delay)
        
        download_progress[task_id]['status'] = 'completed'
        
    except Exception as e:
        download_progress[task_id]['status'] = 'error'
        download_progress[task_id]['error'] = str(e)

@app.route('/')
def index():
    return render_template('index_v3.html')

@app.route('/api/set_api_key', methods=['POST'])
def set_api_key():
    """Store API key persistently for all users"""
    data = request.json
    api_key = data.get('api_key', '')
    
    if api_key:
        # Save to file for persistence across all users
        if save_api_key_to_file(api_key):
            # Also save to session for immediate use
            session['youtube_api_key'] = api_key
            return jsonify({'success': True, 'message': 'API key saved for all users'})
        else:
            return jsonify({'success': False, 'message': 'Failed to save API key'}), 500
    else:
        return jsonify({'success': False, 'message': 'Invalid API key'}), 400

@app.route('/api/remove_api_key', methods=['POST'])
def remove_api_key():
    """Remove API key from both session and file"""
    # Remove from session
    session.pop('youtube_api_key', None)
    
    # Remove from file
    if remove_api_key_file():
        return jsonify({'success': True, 'message': 'API key removed for all users'})
    else:
        return jsonify({'success': True, 'message': 'API key removed from session'})

@app.route('/api/check_api_key')
def check_api_key():
    """Check if API key is set"""
    current_key = get_current_api_key()
    has_key = bool(current_key)
    
    # Determine source
    source = None
    if 'youtube_api_key' in session:
        source = 'session'
    elif load_api_key_from_file():
        source = 'persistent'  
    elif os.environ.get('YOUTUBE_API_KEY'):
        source = 'environment'
    
    return jsonify({
        'has_key': has_key,
        'source': source
    })

@app.route('/api/download', methods=['POST'])
def start_download():
    config = request.json
    
    # Add API key from current sources if not provided
    if 'api_key' not in config:
        config['api_key'] = get_current_api_key()
    
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

@app.route('/api/storage/channels')
def list_channels():
    """List all channels in storage"""
    try:
        channels = storage.list_channels()
        channel_details = []
        
        for channel in channels:
            transcripts = storage.list_transcripts(channel)
            channel_details.append({
                'name': channel,
                'transcript_count': len(transcripts),
                'transcripts': transcripts[:5]  # First 5 as preview
            })
        
        return jsonify({
            'success': True,
            'channels': channel_details
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/storage/transcripts')
def list_all_transcripts():
    """List all transcripts"""
    try:
        channel = request.args.get('channel')
        transcripts = storage.list_transcripts(channel)
        
        return jsonify({
            'success': True,
            'transcripts': transcripts,
            'total': len(transcripts)
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/storage/search')
def search_transcripts():
    """Search transcripts"""
    try:
        query = request.args.get('q', '')
        if not query:
            return jsonify({'success': False, 'error': 'Query parameter required'})
        
        results = storage.search_transcripts(query)
        
        return jsonify({
            'success': True,
            'results': results,
            'total': len(results)
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/storage/transcript/<channel>/<title>')
def get_transcript(channel, title):
    """Get a specific transcript"""
    try:
        transcript = storage.get_transcript(channel, title)
        
        if transcript:
            return jsonify({
                'success': True,
                'transcript': transcript
            })
        else:
            return jsonify({'success': False, 'error': 'Transcript not found'}), 404
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/storage/stats')
def get_storage_stats():
    """Get storage statistics"""
    try:
        stats = storage.get_statistics()
        return jsonify({
            'success': True,
            'stats': stats
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/storage/transcripts/detailed')
def get_all_transcripts_detailed():
    """Get all transcripts with full metadata for table view"""
    try:
        transcripts = storage.get_all_transcripts_detailed()
        return jsonify({
            'success': True,
            'transcripts': transcripts,
            'total': len(transcripts)
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/storage/transcripts/combine', methods=['POST'])
def combine_transcripts():
    """Combine multiple transcripts into one markdown document"""
    try:
        data = request.json
        paths = data.get('paths', [])
        
        if not paths:
            return jsonify({'success': False, 'error': 'No transcripts selected'})
        
        combined_markdown = "# Combined YouTube Transcripts\n\n"
        combined_markdown += f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
        combined_markdown += "---\n\n"
        
        for path in paths:
            # Extract channel and filename from path
            parts = path.split('/')
            if len(parts) >= 3:
                channel = parts[1]
                filename = parts[2].replace('.json', '')
                
                # Get the transcript content
                transcript_data = storage.get_transcript(channel, filename)
                
                if transcript_data:
                    # Add to markdown
                    combined_markdown += f"## {transcript_data['title']}\n\n"
                    combined_markdown += f"**Channel:** {transcript_data['channel']}  \n"
                    combined_markdown += f"**Video ID:** {transcript_data['video_id']}  \n"
                    if transcript_data.get('published_at'):
                        combined_markdown += f"**Published:** {transcript_data['published_at'][:10]}  \n"
                    combined_markdown += f"**Downloaded:** {transcript_data['downloaded_at'][:10]}  \n\n"
                    combined_markdown += "### Transcript\n\n"
                    combined_markdown += transcript_data['transcript']
                    combined_markdown += "\n\n---\n\n"
        
        return jsonify({
            'success': True,
            'markdown': combined_markdown,
            'count': len(paths)
        })
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/github/init', methods=['POST'])
def init_github_storage():
    """Initialize GitHub storage structure"""
    try:
        storage.create_initial_structure()
        return jsonify({'success': True, 'message': 'GitHub storage initialized'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

# Scheduler API endpoints
@app.route('/api/scheduler/jobs')
def get_scheduled_jobs():
    """Get all scheduled jobs"""
    try:
        jobs = scheduler.get_jobs()
        return jsonify({
            'success': True,
            'jobs': jobs,
            'total': len(jobs)
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/scheduler/jobs', methods=['POST'])
def create_scheduled_job():
    """Create a new scheduled job"""
    try:
        data = request.json
        name = data.get('name', '')
        channels = data.get('channels', [])
        frequency = data.get('frequency', 'daily')  # daily, weekly, monthly
        start_date = data.get('start_date', '')  # YYYY-MM-DD format
        folder_prefix = data.get('folder_prefix', '')
        
        if not name or not channels:
            return jsonify({'success': False, 'error': 'Name and channels are required'}), 400
        
        result = scheduler.add_scheduled_job(
            name=name,
            channels=channels,
            frequency=frequency,
            start_date=start_date,
            folder_prefix=folder_prefix
        )
        
        return jsonify(result)
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/scheduler/jobs/<job_id>', methods=['DELETE'])
def delete_scheduled_job(job_id):
    """Delete a scheduled job"""
    try:
        result = scheduler.remove_scheduled_job(job_id)
        return jsonify(result)
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/scheduler/jobs/<job_id>/run', methods=['POST'])
def run_job_now(job_id):
    """Manually trigger a job to run now"""
    try:
        jobs = scheduler.get_jobs()
        job = next((j for j in jobs if j['id'] == job_id), None)
        
        if not job:
            return jsonify({'success': False, 'error': 'Job not found'}), 404
        
        # Run the job in a background thread
        def run_job():
            scheduler._run_scheduled_download(job_id)
        
        thread = threading.Thread(target=run_job)
        thread.start()
        
        return jsonify({'success': True, 'message': 'Job started'})
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

if __name__ == '__main__':
    print("\n🚀 YouTube Transcript Downloader v2.0")
    print("📍 Open http://localhost:5555 in your browser")
    print("🗄️  Using GitHub as storage backend")
    print("⏰ Scheduler service enabled")
    print("Press Ctrl+C to stop the server\n")
    
    # Start the scheduler
    scheduler.start()
    
    try:
        app.run(debug=True, port=5555)
    finally:
        # Stop the scheduler when the app shuts down
        scheduler.stop()
import time
from datetime import datetime
from typing import Dict, List, Optional
from youtube_transcript_api import YouTubeTranscriptApi
import requests
import re

class DownloadService:
    """Service for downloading YouTube transcripts"""
    
    def __init__(self, storage, get_api_key_func):
        self.storage = storage
        self.get_api_key_func = get_api_key_func
    
    def run_download(self, config: Dict) -> Dict:
        """Run a download with given configuration"""
        try:
            # Get API key
            api_key = config.get('api_key') or self.get_api_key_func()
            if not api_key:
                return {'success': False, 'error': 'No API key available'}
            
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
            channel_name = folder_name
            
            # Get videos to download
            if video_ids:
                # Direct video IDs provided
                ids = [v.strip() for v in video_ids.split(',')]
                videos_to_download = [{'id': vid, 'title': f'video_{vid}', 'channel': folder_name or 'Direct_Downloads'} for vid in ids]
            elif channel:
                # Channel provided - fetch video list
                channel_id = self.get_channel_id(channel, api_key)
                
                # Get actual channel name
                channel_name = self.get_channel_info(channel_id, api_key) or channel
                if not folder_name:
                    folder_name = channel_name
                
                playlist_id = self.get_uploads_playlist_id(channel_id, api_key)
                videos_to_download = self.get_video_ids_from_playlist(playlist_id, api_key, channel_id, after_date_obj, limit)
                
                # Update channel name for all videos
                for video in videos_to_download:
                    video['channel'] = folder_name
            
            # Download each video
            success_count = 0
            failed_count = 0
            duplicate_count = 0
            
            results = []
            
            for i, video in enumerate(videos_to_download):
                success, result = self.download_transcript(
                    video['id'], 
                    video['title'],
                    video.get('channel', folder_name),
                    channel_id=video.get('channel_id'),
                    published_at=video.get('date')
                )
                
                video_result = {
                    'video_id': video['id'],
                    'title': video['title'],
                    'success': success,
                    'result': result
                }
                
                if success:
                    success_count += 1
                    video_result['url'] = result
                else:
                    failed_count += 1
                    video_result['error'] = result
                    
                    if 'duplicate' in result.lower():
                        duplicate_count += 1
                
                results.append(video_result)
                
                # Add delay between downloads (except for the last one)
                if i < len(videos_to_download) - 1:
                    time.sleep(delay)
            
            return {
                'success': True,
                'total_videos': len(videos_to_download),
                'total_downloads': success_count,
                'success_count': success_count,
                'failed_count': failed_count,
                'duplicate_count': duplicate_count,
                'folder': folder_name,
                'results': results
            }
            
        except Exception as e:
            return {'success': False, 'error': str(e)}
    
    def sanitize_filename(self, name):
        """Sanitize the video title to be used as a filename"""
        sanitized = re.sub(r'[<>:"/\\|?*]', '', name)
        return sanitized.strip()

    def get_channel_id(self, query, api_key):
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

    def get_channel_info(self, channel_id, api_key):
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

    def get_uploads_playlist_id(self, channel_id, api_key):
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

    def get_video_ids_from_playlist(self, playlist_id, api_key, channel_id=None, after_date=None, limit=None):
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

    def download_transcript(self, video_id, title, channel_name=None, channel_id=None, published_at=None):
        """Downloads the transcript for a given video ID and saves to GitHub."""
        try:
            # Check if already exists
            if self.storage.check_transcript_exists(video_id):
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
            
            result = self.storage.save_transcript(
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
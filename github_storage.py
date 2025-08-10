import os
import json
import base64
import requests
from datetime import datetime
from typing import Optional, List, Dict

class GitHubStorage:
    """GitHub-based storage for YouTube transcripts"""
    
    def __init__(self, repo_owner="filenamedotexe", repo_name="youtube-transcripts-db"):
        self.repo_owner = repo_owner
        self.repo_name = repo_name
        self.api_base = f"https://api.github.com/repos/{repo_owner}/{repo_name}"
        # GitHub token will be set from environment variable
        self.token = os.environ.get('GITHUB_TOKEN', '')
        self.headers = {
            'Accept': 'application/vnd.github.v3+json',
        }
        if self.token:
            self.headers['Authorization'] = f'token {self.token}'
    
    def check_transcript_exists(self, video_id: str) -> bool:
        """Check if a transcript with this video ID already exists"""
        try:
            # Search for the video ID in the repository
            search_response = requests.get(
                f"https://api.github.com/search/code",
                headers=self.headers,
                params={
                    'q': f'"video_id": "{video_id}" repo:{self.repo_owner}/{self.repo_name}',
                    'per_page': 1
                }
            )
            
            if search_response.status_code == 200:
                results = search_response.json().get('items', [])
                return len(results) > 0
        except:
            pass
        return False
    
    def save_transcript(self, channel_name: str, video_id: str, title: str, 
                       transcript_text: str, metadata: Dict = None) -> Dict:
        """Save a transcript to GitHub"""
        # Check for duplicates first
        if self.check_transcript_exists(video_id):
            return {
                "success": False,
                "error": "Transcript already exists",
                "duplicate": True
            }
        
        # Sanitize names for file paths
        safe_channel = self._sanitize_name(channel_name)
        safe_title = self._sanitize_name(title)
        
        # Create file path: channels/[channel_name]/[video_id]_[title].json
        # Include video_id in filename for uniqueness
        file_path = f"channels/{safe_channel}/{video_id}_{safe_title}.json"
        
        # Prepare content with metadata
        content = {
            "video_id": video_id,
            "channel_id": metadata.get('channel_id', ''),
            "title": title,
            "channel": channel_name,
            "published_at": metadata.get('published_at', ''),
            "downloaded_at": datetime.now().isoformat(),
            "transcript": transcript_text,
            "metadata": metadata or {}
        }
        
        # Convert to JSON and encode to base64
        json_content = json.dumps(content, indent=2, ensure_ascii=False)
        encoded_content = base64.b64encode(json_content.encode()).decode()
        
        # Check if file exists
        existing_sha = self._get_file_sha(file_path)
        
        # Prepare commit data
        commit_data = {
            "message": f"Add transcript: {title} from {channel_name}",
            "content": encoded_content,
            "branch": "main"
        }
        
        if existing_sha:
            commit_data["sha"] = existing_sha
            commit_data["message"] = f"Update transcript: {title} from {channel_name}"
        
        # Create or update file
        response = requests.put(
            f"{self.api_base}/contents/{file_path}",
            headers=self.headers,
            json=commit_data
        )
        
        if response.status_code in [201, 200]:
            return {
                "success": True,
                "path": file_path,
                "url": response.json().get('content', {}).get('html_url', '')
            }
        else:
            return {
                "success": False,
                "error": response.text
            }
    
    def get_transcript(self, channel_name: str, title: str) -> Optional[Dict]:
        """Retrieve a transcript from GitHub"""
        safe_channel = self._sanitize_name(channel_name)
        safe_title = self._sanitize_name(title)
        file_path = f"channels/{safe_channel}/{safe_title}.json"
        
        response = requests.get(
            f"{self.api_base}/contents/{file_path}",
            headers=self.headers
        )
        
        if response.status_code == 200:
            content = response.json()
            decoded = base64.b64decode(content['content']).decode()
            return json.loads(decoded)
        return None
    
    def list_channels(self) -> List[str]:
        """List all available channels"""
        response = requests.get(
            f"{self.api_base}/contents/channels",
            headers=self.headers
        )
        
        if response.status_code == 200:
            return [item['name'] for item in response.json() if item['type'] == 'dir']
        return []
    
    def list_transcripts(self, channel_name: str = None) -> List[Dict]:
        """List transcripts, optionally filtered by channel"""
        transcripts = []
        
        if channel_name:
            safe_channel = self._sanitize_name(channel_name)
            path = f"channels/{safe_channel}"
        else:
            path = "channels"
        
        response = requests.get(
            f"{self.api_base}/contents/{path}",
            headers=self.headers,
            params={'ref': 'main'}
        )
        
        if response.status_code == 200:
            items = response.json()
            
            if channel_name:
                # Direct channel listing
                for item in items:
                    if item['type'] == 'file' and item['name'].endswith('.json'):
                        transcripts.append({
                            'name': item['name'].replace('.json', ''),
                            'path': item['path'],
                            'channel': channel_name,
                            'size': item['size'],
                            'url': item['html_url'],
                            'download_url': item.get('download_url', '')
                        })
            else:
                # List all channels and their transcripts
                for channel_dir in items:
                    if channel_dir['type'] == 'dir':
                        channel_transcripts = self.list_transcripts(channel_dir['name'])
                        transcripts.extend(channel_transcripts)
        
        return transcripts
    
    def get_all_transcripts_detailed(self) -> List[Dict]:
        """Get all transcripts with full metadata"""
        detailed_transcripts = []
        
        # Get all channels
        channels = self.list_channels()
        
        for channel in channels:
            # Get transcripts for this channel
            transcripts = self.list_transcripts(channel)
            
            # For each transcript, fetch its content to get metadata
            for transcript in transcripts:
                # Try to get the full content
                if transcript.get('download_url'):
                    try:
                        content_response = requests.get(transcript['download_url'])
                        if content_response.status_code == 200:
                            data = content_response.json()
                            detailed_transcripts.append({
                                'video_id': data.get('video_id', ''),
                                'channel_id': data.get('channel_id', ''),
                                'title': data.get('title', ''),
                                'channel': data.get('channel', ''),
                                'published_at': data.get('published_at', ''),
                                'downloaded_at': data.get('downloaded_at', ''),
                                'url': transcript['url'],
                                'path': transcript['path']
                            })
                    except:
                        # If we can't get details, use basic info
                        detailed_transcripts.append({
                            'video_id': '',
                            'channel_id': '',
                            'title': transcript['name'],
                            'channel': channel,
                            'published_at': '',
                            'downloaded_at': '',
                            'url': transcript['url'],
                            'path': transcript['path']
                        })
        
        return detailed_transcripts
    
    def search_transcripts(self, query: str) -> List[Dict]:
        """Search transcripts using GitHub search API"""
        search_response = requests.get(
            f"https://api.github.com/search/code",
            headers=self.headers,
            params={
                'q': f'{query} repo:{self.repo_owner}/{self.repo_name}',
                'per_page': 30
            }
        )
        
        results = []
        if search_response.status_code == 200:
            for item in search_response.json().get('items', []):
                results.append({
                    'name': item['name'].replace('.json', ''),
                    'path': item['path'],
                    'url': item['html_url'],
                    'score': item['score']
                })
        
        return results
    
    def get_statistics(self) -> Dict:
        """Get storage statistics"""
        channels = self.list_channels()
        total_transcripts = 0
        
        for channel in channels:
            transcripts = self.list_transcripts(channel)
            total_transcripts += len(transcripts)
        
        return {
            'total_channels': len(channels),
            'total_transcripts': total_transcripts,
            'channels': channels
        }
    
    def _sanitize_name(self, name: str) -> str:
        """Sanitize names for file paths"""
        import re
        # Remove or replace invalid characters
        name = re.sub(r'[<>:"/\\|?*@]', '', name)
        name = name.replace(' ', '_')
        return name[:100]  # Limit length
    
    def _get_file_sha(self, file_path: str) -> Optional[str]:
        """Get SHA of existing file if it exists"""
        response = requests.get(
            f"{self.api_base}/contents/{file_path}",
            headers=self.headers
        )
        
        if response.status_code == 200:
            return response.json()['sha']
        return None
    
    def create_initial_structure(self):
        """Create initial repository structure"""
        # Create README
        readme_content = """# YouTube Transcripts Database

A public repository of YouTube video transcripts, automatically collected and organized by channel.

## Structure
```
channels/
├── [channel_name]/
│   ├── [video_title].json
│   └── ...
└── ...
```

## Usage
Each transcript is stored as a JSON file with the following structure:
- `video_id`: YouTube video ID
- `title`: Video title  
- `channel`: Channel name
- `downloaded_at`: Timestamp of download
- `transcript`: Full transcript text
- `metadata`: Additional metadata

## Contributing
This repository is automatically updated by the YouTube Transcript Downloader app.
"""
        
        encoded_readme = base64.b64encode(readme_content.encode()).decode()
        
        requests.put(
            f"{self.api_base}/contents/README.md",
            headers=self.headers,
            json={
                "message": "Initialize transcript database",
                "content": encoded_readme,
                "branch": "main"
            }
        )
        
        # Create channels directory with .gitkeep
        requests.put(
            f"{self.api_base}/contents/channels/.gitkeep",
            headers=self.headers,
            json={
                "message": "Create channels directory",
                "content": "",
                "branch": "main"
            }
        )
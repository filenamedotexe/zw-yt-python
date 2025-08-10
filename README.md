# YouTube Transcript Downloader

A powerful web-based tool for downloading YouTube transcripts in bulk, with support for channel downloads, date filtering, automated scheduling, and rate limit protection.

## Features

### Core Functionality
- 🎬 **Bulk Download**: Download transcripts from entire YouTube channels
- 📅 **Date Filtering**: Only download videos after a specific date
- 🎯 **Video ID Support**: Download specific videos by their IDs
- 🚦 **Rate Limit Protection**: Configurable delays to avoid YouTube blocking
- 📊 **Real-time Progress**: Track download progress with live updates
- 🎨 **Modern UI**: Beautiful web interface with intuitive controls
- 📁 **Folder Management**: Organize transcripts into custom folders
- 🔒 **Secure Storage**: Private cloud storage with duplicate detection

### Advanced Features
- ⏰ **Automated Scheduling**: Set up daily/weekly/monthly automatic downloads
- 🚀 **Smart Catch-up**: Download all missing videos from a start date on first run
- 📋 **Multi-select & Combine**: Select multiple transcripts and combine to markdown
- 🔍 **Advanced Search**: Search and filter your transcript database
- 🔑 **Persistent API Keys**: API keys stored securely for all users
- 📊 **Database View**: Table view with sortable columns and detailed metadata

## Setup

1. Clone the repository:
```bash
git clone https://github.com/zachwieder/zw-yt-python.git
cd zw-yt-python
```

2. Create a virtual environment:
```bash
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

3. Install dependencies:
```bash
pip install -r requirements.txt
```

4. Get a YouTube Data API v3 key:
   - Go to [Google Cloud Console](https://console.cloud.google.com/)
   - Create a new project or select existing
   - Enable YouTube Data API v3
   - Create credentials → API Key
   - Update `API_KEY` in `app.py` and `go.py`

## Usage

### Web Interface (Recommended)

1. Start the web server:
```bash
python app_v2.py
```

2. Open http://localhost:5555 in your browser

3. Use the interface to:
   - **Database Tab**: Browse, search, and manage your transcript collection
   - **Download Tab**: Manual downloads from channels or video IDs
   - **Scheduler Tab**: Set up automated daily/weekly/monthly downloads
   - **Settings Tab**: Manage API keys and view system information

#### Automated Scheduling

The scheduler allows you to set up automatic downloads that run in the background:

1. Go to the **Scheduler Tab**
2. Click **"+ Create New Job"**
3. Configure:
   - **Job Name**: e.g., "Alex Becker Daily Updates"
   - **Channels**: List channels to monitor (one per line)
   - **Frequency**: Daily, Weekly, or Monthly
   - **Start Date**: For catch-up downloads
   - **Folder Prefix**: Optional organization prefix
4. The system will automatically:
   - Download all videos from start date to now (catch-up)
   - Then run at your selected frequency
   - Skip duplicates and handle errors gracefully

### Command Line

```bash
# Download from a channel
python go.py --channel "@channelname" --after-date "2024-01-01" --output-dir "transcripts/channel"

# Download specific videos
python go.py --video-ids "VIDEO_ID1,VIDEO_ID2" --output-dir "transcripts"

# With custom delay (in seconds)
python go.py --channel "@channelname" --delay 5
```

## Command Line Options

- `--channel`: YouTube channel name or handle (e.g., @channelname)
- `--video-ids`: Comma-separated list of video IDs
- `--after-date`: Only download videos after this date (YYYY-MM-DD)
- `--output-dir`: Output directory for transcripts (default: transcripts)
- `--delay`: Delay in seconds between downloads (default: 3.0)
- `--api-key`: YouTube Data API v3 key (optional, can be set in code)

## File Structure

```
zw-yt-python/
├── app_v2.py              # Main Flask application with scheduler
├── go.py                  # Command-line script  
├── download_service.py    # Download logic service
├── scheduler.py           # Automated scheduling system
├── github_storage.py      # GitHub-based storage backend
├── templates/
│   └── index_v3.html     # Web interface with scheduler UI
├── requirements.txt       # Python dependencies
├── .api_key_storage      # Persistent API key storage (auto-created)
├── .scheduled_jobs.json  # Scheduler job definitions (auto-created)
└── README.md
```

## Rate Limiting & Error Handling

The system includes comprehensive error handling:
- **YouTube Transcript API**: IP-based rate limiting (changing API keys won't help)
- **YouTube Data API**: API key quota limits (5,000 units/day free)
- **GitHub API**: Rate limiting for storage operations
- **Smart retry logic** and **duplicate detection**
- **Detailed error categorization** and reporting

If you get blocked:
1. Wait 15-30 minutes for YouTube transcript rate limits
2. Use a VPN or different network for IP-based blocks  
3. Increase delays between downloads (3-5 seconds recommended)
4. Check API key quotas in Google Cloud Console

## Scheduler Details

**Scheduling Times:**
- **Daily**: Every day at midnight (12:00 AM)
- **Weekly**: Every Monday at midnight
- **Monthly**: Every 1st of the month at midnight

**Catch-up Behavior:**
- On first run, downloads ALL videos from your start date to current date
- Then continues with regular schedule
- Skips duplicates automatically
- Handles channel changes and errors gracefully

## Storage & Security

- **Private GitHub repository** for transcript storage
- **Encrypted API key storage** on server
- **No public exposure** of repository details
- **Unlimited storage capacity**
- **Automatic duplicate detection**

## License

MIT
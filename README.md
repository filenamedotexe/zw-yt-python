# YouTube Transcript Downloader

A powerful web-based tool for downloading YouTube transcripts in bulk, with support for channel downloads, date filtering, and rate limit protection.

## Features

- 🎬 **Bulk Download**: Download transcripts from entire YouTube channels
- 📅 **Date Filtering**: Only download videos after a specific date
- 🎯 **Video ID Support**: Download specific videos by their IDs
- 🚦 **Rate Limit Protection**: Configurable delays to avoid YouTube blocking
- 📊 **Real-time Progress**: Track download progress with live updates
- 🎨 **Modern UI**: Beautiful web interface with intuitive controls
- 📁 **Folder Management**: Organize transcripts into custom folders

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
python app.py
```

2. Open http://localhost:5555 in your browser

3. Use the interface to:
   - Download from YouTube channels
   - Filter by date
   - Set custom output folders
   - Configure download delays

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

## Rate Limiting

YouTube may block requests if too many are made quickly. The tool includes:
- Default 3-5 second delay between downloads
- Configurable delay settings
- Automatic error handling for rate limits

If you get blocked:
1. Wait 15-30 minutes
2. Increase the delay between downloads
3. Use a VPN or different network

## License

MIT
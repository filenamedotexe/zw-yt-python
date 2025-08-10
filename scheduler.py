import json
import os
import threading
import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
import hashlib

from download_service import DownloadService
from github_storage import GitHubStorage

class JobScheduler:
    """Manages scheduled YouTube transcript downloads"""
    
    def __init__(self, download_service: DownloadService, storage: GitHubStorage):
        self.download_service = download_service
        self.storage = storage
        self.scheduler = BackgroundScheduler()
        self.jobs_file = os.path.join(os.path.dirname(__file__), '.scheduled_jobs.json')
        self.jobs = self._load_jobs()
        self.running = False
    
    def start(self):
        """Start the scheduler"""
        if not self.running:
            self.scheduler.start()
            self.running = True
            # Add all saved jobs to scheduler
            self._restore_jobs()
    
    def stop(self):
        """Stop the scheduler"""
        if self.running:
            self.scheduler.shutdown()
            self.running = False
    
    def add_scheduled_job(self, name: str, channels: List[str], frequency: str, 
                         start_date: Optional[str] = None, folder_prefix: str = "") -> Dict:
        """Add a new scheduled job"""
        try:
            job_id = self._generate_job_id(name, channels, frequency)
            
            # Create job config
            job_config = {
                'id': job_id,
                'name': name,
                'channels': channels,
                'frequency': frequency,  # 'daily', 'weekly', 'monthly'
                'start_date': start_date or datetime.now().strftime('%Y-%m-%d'),
                'folder_prefix': folder_prefix,
                'created_at': datetime.now().isoformat(),
                'last_run': None,
                'status': 'active',
                'total_downloads': 0,
                'last_error': None
            }
            
            # Add to jobs list
            self.jobs[job_id] = job_config
            self._save_jobs()
            
            # Add to scheduler if running
            if self.running:
                self._add_job_to_scheduler(job_config)
            
            # Schedule catch-up run for new jobs
            self._schedule_catchup_run(job_config)
            
            return {'success': True, 'job_id': job_id, 'message': f'Scheduled job "{name}" created'}
            
        except Exception as e:
            return {'success': False, 'error': str(e)}
    
    def remove_scheduled_job(self, job_id: str) -> Dict:
        """Remove a scheduled job"""
        try:
            if job_id in self.jobs:
                # Remove from scheduler
                try:
                    self.scheduler.remove_job(job_id)
                except:
                    pass
                
                # Remove from jobs
                del self.jobs[job_id]
                self._save_jobs()
                
                return {'success': True, 'message': 'Job removed successfully'}
            else:
                return {'success': False, 'error': 'Job not found'}
                
        except Exception as e:
            return {'success': False, 'error': str(e)}
    
    def get_jobs(self) -> List[Dict]:
        """Get all scheduled jobs"""
        jobs_list = []
        for job_id, job_config in self.jobs.items():
            # Add next run time if job is in scheduler
            next_run = None
            if self.running:
                try:
                    scheduler_job = self.scheduler.get_job(job_id)
                    if scheduler_job:
                        next_run = scheduler_job.next_run_time.isoformat() if scheduler_job.next_run_time else None
                except:
                    pass
            
            job_info = job_config.copy()
            job_info['next_run'] = next_run
            jobs_list.append(job_info)
        
        return jobs_list
    
    def update_job_status(self, job_id: str, status: str, error: str = None):
        """Update job status after run"""
        if job_id in self.jobs:
            self.jobs[job_id]['status'] = status
            self.jobs[job_id]['last_run'] = datetime.now().isoformat()
            if error:
                self.jobs[job_id]['last_error'] = error
            else:
                self.jobs[job_id]['last_error'] = None
            self._save_jobs()
    
    def _generate_job_id(self, name: str, channels: List[str], frequency: str) -> str:
        """Generate unique job ID"""
        content = f"{name}_{','.join(channels)}_{frequency}_{datetime.now().isoformat()}"
        return hashlib.md5(content.encode()).hexdigest()[:12]
    
    def _get_cron_trigger(self, frequency: str) -> CronTrigger:
        """Get cron trigger for frequency"""
        if frequency == 'daily':
            return CronTrigger(hour=0, minute=0)  # Daily at midnight
        elif frequency == 'weekly':
            return CronTrigger(day_of_week=0, hour=0, minute=0)  # Monday at midnight
        elif frequency == 'monthly':
            return CronTrigger(day=1, hour=0, minute=0)  # 1st of month at midnight
        else:
            raise ValueError(f"Unsupported frequency: {frequency}")
    
    def _add_job_to_scheduler(self, job_config: Dict):
        """Add job to APScheduler"""
        trigger = self._get_cron_trigger(job_config['frequency'])
        
        self.scheduler.add_job(
            func=self._run_scheduled_download,
            trigger=trigger,
            id=job_config['id'],
            args=[job_config['id']],
            name=job_config['name'],
            replace_existing=True
        )
    
    def _restore_jobs(self):
        """Restore all jobs to scheduler"""
        for job_id, job_config in self.jobs.items():
            if job_config['status'] == 'active':
                self._add_job_to_scheduler(job_config)
    
    def _schedule_catchup_run(self, job_config: Dict):
        """Schedule immediate catch-up run for new jobs"""
        # Run catch-up in 30 seconds to allow UI to show the job was created
        catchup_job_id = f"catchup_{job_config['id']}"
        
        self.scheduler.add_job(
            func=self._run_catchup_download,
            trigger='date',
            run_date=datetime.now() + timedelta(seconds=30),
            id=catchup_job_id,
            args=[job_config['id']],
            name=f"Catchup: {job_config['name']}",
            replace_existing=True
        )
    
    def _run_scheduled_download(self, job_id: str):
        """Execute a scheduled download"""
        if job_id not in self.jobs:
            return
        
        job_config = self.jobs[job_id]
        print(f"🔄 Running scheduled job: {job_config['name']}")
        
        try:
            # Calculate date filter (since last successful run or start_date)
            last_run_date = job_config.get('last_run')
            if last_run_date:
                # Since last run
                after_date = datetime.fromisoformat(last_run_date).strftime('%Y-%m-%d')
            else:
                # Since job start date
                after_date = job_config['start_date']
            
            # Download from each channel
            total_downloads = 0
            for channel in job_config['channels']:
                folder_name = f"{job_config['folder_prefix']}{channel}" if job_config['folder_prefix'] else channel
                
                # Create download config
                download_config = {
                    'channel': channel,
                    'after_date': after_date,
                    'folder': folder_name,
                    'delay': 3.0,  # Use safe default
                    'api_key': None  # Will use current API key
                }
                
                # Run download
                result = self.download_service.run_download(download_config)
                if result.get('success'):
                    total_downloads += result.get('total_downloads', 0)
            
            # Update job stats
            self.jobs[job_id]['total_downloads'] += total_downloads
            self.update_job_status(job_id, 'completed')
            
            print(f"✅ Scheduled job '{job_config['name']}' completed: {total_downloads} new transcripts")
            
        except Exception as e:
            error_msg = str(e)
            self.update_job_status(job_id, 'failed', error_msg)
            print(f"❌ Scheduled job '{job_config['name']}' failed: {error_msg}")
    
    def _run_catchup_download(self, job_id: str):
        """Run initial catch-up download for a new job"""
        if job_id not in self.jobs:
            return
        
        job_config = self.jobs[job_id]
        print(f"🚀 Running catch-up for new job: {job_config['name']}")
        
        try:
            # For catch-up, download from start_date to now
            after_date = job_config['start_date']
            
            total_downloads = 0
            for channel in job_config['channels']:
                folder_name = f"{job_config['folder_prefix']}{channel}" if job_config['folder_prefix'] else channel
                
                download_config = {
                    'channel': channel,
                    'after_date': after_date,
                    'folder': folder_name,
                    'delay': 3.0,
                    'api_key': None
                }
                
                result = self.download_service.run_download(download_config)
                if result.get('success'):
                    total_downloads += result.get('total_downloads', 0)
            
            # Update job stats
            self.jobs[job_id]['total_downloads'] += total_downloads
            self.update_job_status(job_id, 'completed')
            
            print(f"✅ Catch-up for '{job_config['name']}' completed: {total_downloads} transcripts")
            
        except Exception as e:
            error_msg = str(e)
            self.update_job_status(job_id, 'failed', error_msg)
            print(f"❌ Catch-up for '{job_config['name']}' failed: {error_msg}")
    
    def _load_jobs(self) -> Dict:
        """Load jobs from file"""
        if os.path.exists(self.jobs_file):
            try:
                with open(self.jobs_file, 'r') as f:
                    return json.load(f)
            except:
                pass
        return {}
    
    def _save_jobs(self):
        """Save jobs to file"""
        try:
            with open(self.jobs_file, 'w') as f:
                json.dump(self.jobs, f, indent=2)
        except Exception as e:
            print(f"Failed to save jobs: {e}")
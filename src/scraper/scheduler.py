from flask_apscheduler import APScheduler
from datetime import datetime, timedelta
from ..models.database import db, ScraperJob
from ..todaytix.api import TodayTixAPI
from ..todaytix.scraper import EventScraper
import logging

logger = logging.getLogger(__name__)
scheduler = APScheduler()

class ScraperScheduler:
    @staticmethod
    def start_scraper(job_id: int, app):
        with app.app_context():
            job = ScraperJob.query.get(job_id)
            if not job or job.status not in ['running', 'completed']:
                logger.info(f"Job {job_id} is not running or completed. Current status: {job.status if job else 'None'}")
                return
            
            try:
                # Update job status
                job.last_run = datetime.now()
                job.next_run = job.last_run + timedelta(minutes=job.interval_minutes)
                db.session.commit()
                logger.info(f"Job {job_id} started. Next run scheduled at {job.next_run}")
                
                # Run scraper
                api = TodayTixAPI()
                scraper = EventScraper(api, app.config['OUTPUT_FILE_DIR'])
                scraper.run(job)
                
                # Schedule next run if still running
                job = ScraperJob.query.get(job_id)  # Refresh job status
                if job and job.status == 'running':
                    scheduler.add_job(
                        func=ScraperScheduler.start_scraper,
                        trigger='date',
                        run_date=job.next_run,
                        args=[job_id, app],
                        id=f'scraper_{job_id}_{datetime.now().strftime("%Y%m%d_%H%M%S")}'
                    )
                    logger.info(f"Next run for job {job_id} scheduled at {job.next_run}")
                
            except Exception as e:
                logger.error(f"Error in scraper job {job_id}: {str(e)}")
                job = ScraperJob.query.get(job_id)
                if job:
                    job.status = 'error'
                    job.next_run = None
                    db.session.commit()
                raise e
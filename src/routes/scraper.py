import os
from flask import Blueprint, jsonify, render_template, request, current_app
from datetime import datetime, timedelta

from flask_login import login_required
from src.scraper.scheduler import scheduler, ScraperScheduler
from ..todaytix.api import TodayTixAPI
from ..todaytix.scraper import EventScraper
from ..models.database import Event, ScraperJob, db

bp = Blueprint('scraper', __name__)

@bp.route('/scrape')
@login_required
def scrape_page():
    current_job = ScraperJob.query.order_by(ScraperJob.id.desc()).first()
    return render_template('scrape.html', current_job=current_job)

@bp.route('/api/scrape/start', methods=['POST'])
@login_required
def start_scrape():
    try:
        data = request.json
        interval_minutes = data.get('interval_minutes', 20)
        
        # Get events from database
        events = Event.query.all()
        if not events:
            return jsonify({
                "status": "error",
                "message": "No events found in database"
            }), 400

        # Create output directory if it doesn't exist
        os.makedirs(current_app.config['OUTPUT_FILE_DIR'], exist_ok=True)

        # Initialize API and scraper
        api = TodayTixAPI()
        scraper = EventScraper(api, current_app.config['OUTPUT_FILE_DIR'])
        
        # Get or create job record
        job = ScraperJob.query.order_by(ScraperJob.id.desc()).first()
        if not job:
            job = ScraperJob(
                status='running',
                interval_minutes=interval_minutes,
                events_processed=0,
                total_tickets_found=0,
                last_run=None,
                next_run=datetime.now()
            )
            db.session.add(job)
        else:
            job.status = 'running'
            job.interval_minutes = interval_minutes
            job.events_processed = 0  # Reset events processed
            job.total_tickets_found = 0  # Reset total tickets found
            job.next_run = datetime.now()
        
        db.session.commit()
        
        # Run scraper
        success = False
        output_file = None
        try:
            success, output_file = scraper.run(job)
        except Exception as e:
            success = False
            output_file = None
        
        # Update job status based on result
        if success and output_file:
            job.status = 'completed'
            job.last_run = datetime.now()
            job.next_run = job.last_run + timedelta(minutes=interval_minutes)
            db.session.commit()
            
            # Schedule next run
            scheduler.add_job(
                func=ScraperScheduler.start_scraper,
                trigger='date',
                run_date=job.next_run,
                args=[job.id, current_app._get_current_object()],
                id=f'scraper_{job.id}_{datetime.now().strftime("%Y%m%d_%H%M%S")}'
            )
            
            return jsonify({
                "status": "success",
                "message": f"Scraping completed. Output saved to {output_file}"
            })
        else:
            job.status = 'error'
            job.next_run = None
            db.session.commit()
            
            return jsonify({
                "status": "error",
                "message": "No data was collected during scraping"
            }), 400
            
    except Exception as e:
        if 'job' in locals():
            job.status = 'error'
            job.next_run = None
            db.session.commit()
            
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500

@bp.route('/api/scrape/stop', methods=['POST'])
@login_required
def stop_scrape():
    try:
        job = ScraperJob.query.filter(ScraperJob.status.in_(['running', 'completed'])).first()
        if job:
            job.status = 'stopped'
            job.next_run = None
            db.session.commit()
            return jsonify({
                "status": "success",
                "message": "Scraper stopped successfully"
            })
        else:
            return jsonify({
                "status": "error",
                "message": "No running or completed job found"
            }), 404
        
    except Exception as e:
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500

@bp.route('/api/scrape/status')
@login_required
def get_status():
    try:
        # Get the most recent job
        job = ScraperJob.query.order_by(ScraperJob.id.desc()).first()
        
        if job:
            return jsonify({
                "status": job.status,
                "last_run": job.last_run.isoformat() if job.last_run else None,
                "next_run": job.next_run.isoformat() if job.next_run else None,
                "events_processed": job.events_processed,
                "total_tickets_found": job.total_tickets_found
            })
        else:
            return jsonify({
                "status": "stopped",
                "last_run": None,
                "next_run": None,
                "events_processed": 0,
                "total_tickets_found": 0
            })
            
    except Exception as e:
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500
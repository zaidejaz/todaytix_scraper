import os
from flask import Blueprint, jsonify, render_template, request, current_app
from datetime import datetime, timedelta

from flask_login import login_required
from src.scraper.scheduler import scheduler, ScraperScheduler
from ..todaytix.api import TodayTixAPI
from ..todaytix.scraper import EventScraper
from ..models.database import Event, ScraperJob, db
from pathlib import Path
from werkzeug.utils import secure_filename
from flask import send_file

bp = Blueprint('scraper', __name__)

@bp.route('/scrape')
@login_required
def scrape_page():
    cleanup_old_files()
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
            
            cleanup_job_id = f'cleanup_{job.id}_{datetime.now().strftime("%Y%m%d_%H%M%S")}'
            scheduler.add_job(
                func=cleanup_old_files,
                trigger='date',
                run_date=datetime.now() + timedelta(hours=24),
                id=cleanup_job_id
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
    
def get_file_info(file_path):
    """Get file information including creation time and age"""
    stat = os.stat(file_path)
    created_time = datetime.fromtimestamp(stat.st_ctime)
    age_hours = (datetime.now() - created_time).total_seconds() / 3600
    return {
        'name': os.path.basename(file_path),
        'created_at': created_time.isoformat(),
        'size': stat.st_size,
        'age_hours': age_hours
    }

def get_output_dir():
    """Get absolute path to output directory"""
    base_dir = current_app.config.get('BASE_DIR', Path(__file__).resolve().parent.parent.parent)
    output_dir = current_app.config['OUTPUT_FILE_DIR']
    
    # If output_dir is relative, make it absolute relative to base_dir
    if not os.path.isabs(output_dir):
        output_dir = os.path.join(base_dir, output_dir)
        current_app.logger.debug(f"Output directory: {output_dir}")
    # Ensure directory exists
    os.makedirs(output_dir, exist_ok=True)
    return output_dir

@bp.route('/api/files', methods=['GET'])
@login_required
def list_files():
    try:
        output_dir = Path(get_output_dir())
        files = []
        
        current_app.logger.info(f"Scanning directory: {output_dir}")
        
        if not output_dir.exists():
            current_app.logger.error(f"Output directory does not exist: {output_dir}")
            return jsonify({
                "status": "error",
                "message": "Output directory not found"
            }), 500
            
        # Only look for .xlsx files
        for file_path in output_dir.glob('*.xlsx'):
            try:
                file_info = get_file_info(str(file_path))
                files.append(file_info)
            except Exception as e:
                current_app.logger.error(f"Error processing file {file_path}: {str(e)}")
                continue
        
        # Sort files by creation time, newest first
        files.sort(key=lambda x: x['created_at'], reverse=True)
        
        return jsonify({
            "status": "success",
            "files": files
        })
    except Exception as e:
        current_app.logger.error(f"Error listing files: {str(e)}")
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500

@bp.route('/api/files/<filename>', methods=['GET'])
@login_required
def download_file(filename):
    try:
        # Verify file extension
        if not filename.lower().endswith('.xlsx'):
            return jsonify({
                "status": "error",
                "message": "Only Excel (.xlsx) files can be downloaded"
            }), 400
            
        output_dir = get_output_dir()
        safe_filename = secure_filename(filename)
        file_path = os.path.join(output_dir, safe_filename)
        
        current_app.logger.info(f"Attempting to download file: {file_path}")
        
        if not os.path.exists(file_path):
            current_app.logger.error(f"File not found: {file_path}")
            return jsonify({
                "status": "error",
                "message": "File not found"
            }), 404
        
        return send_file(
            file_path,
            as_attachment=True,
            download_name=safe_filename,
            mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        )
    except Exception as e:
        current_app.logger.error(f"Error downloading file: {str(e)}")
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500

def cleanup_old_files():
    """Delete files older than 24 hours"""
    output_dir = Path(get_output_dir())
    current_app.logger.info(f"Running cleanup in: {output_dir}")
    
    for file_path in output_dir.glob('*'):
        if file_path.is_file():
            try:
                age_hours = (datetime.now() - datetime.fromtimestamp(file_path.stat().st_ctime)).total_seconds() / 3600
                if age_hours >= 24:
                    current_app.logger.info(f"Deleting old file: {file_path}")
                    file_path.unlink()
            except Exception as e:
                current_app.logger.error(f"Error deleting file {file_path}: {str(e)}")
# events.py
from datetime import datetime
from io import StringIO
from flask import Blueprint, jsonify, redirect, request, render_template, current_app, url_for
from flask_login import login_required
from werkzeug.utils import secure_filename
import csv
import os
from ..models.database import db, Event
from ..constants import CITY_URL_MAP

bp = Blueprint('events', __name__)

def get_city_id_by_name(city_name):
    """Get city ID from city name"""
    return CITY_URL_MAP.get(city_name.strip())

def get_city_name_by_id(city_id):
    """Get city name from city ID"""
    for city_name, cid in CITY_URL_MAP.items():
        if cid == city_id:
            return city_name
    return None

@bp.route('/')
@login_required
def index():
    return redirect(url_for('events.events_page'))

@bp.route('/events', methods=['GET'])
@login_required
def events_page():
    events = Event.query.all()
    # Create a reverse mapping for display purposes
    city_names = {cid: name for name, cid in CITY_URL_MAP.items()}
    return render_template('events.html', events=events, cities=CITY_URL_MAP, city_names=city_names)

@bp.route('/api/events', methods=['GET'])
@login_required
def get_events():
    events = Event.query.all()
    return jsonify([event.to_dict() for event in events])

@bp.route('/api/events', methods=['POST'])
@login_required
def create_event():
    try:
        data = request.json
        # Validate city_id
        city_id = int(data['city_id'])
        if city_id not in [cid for cid in CITY_URL_MAP.values()]:
            return jsonify({'error': 'Invalid city ID'}), 400

        event = Event(
            event_id=data['event_id'],
            event_name=data['event_name'],
            city_id=city_id,
            start_date=datetime.strptime(data['start_date'], '%Y-%m-%d').date(),
            end_date=datetime.strptime(data['end_date'], '%Y-%m-%d').date(),
            markup=float(data['markup'])
        )
        db.session.add(event)
        db.session.commit()
        return jsonify(event.to_dict()), 201
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@bp.route('/api/events/<int:id>', methods=['GET'])
@login_required
def get_event(id):
    event = Event.query.get_or_404(id)
    return jsonify(event.to_dict())

@bp.route('/api/events/<int:id>', methods=['PUT'])
@login_required
def update_event(id):
    try:
        event = Event.query.get_or_404(id)
        data = request.json
        
        # Validate city_id
        city_id = int(data['city_id'])
        if city_id not in [cid for cid in CITY_URL_MAP.values()]:
            return jsonify({'error': 'Invalid city ID'}), 400

        event.event_id = data['event_id']
        event.event_name = data['event_name']
        event.city_id = city_id
        event.start_date = datetime.strptime(data['start_date'], '%Y-%m-%d').date()
        event.end_date = datetime.strptime(data['end_date'], '%Y-%m-%d').date()
        event.markup = float(data['markup'])
        
        db.session.commit()
        return jsonify(event.to_dict())
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@bp.route('/api/events/<int:id>', methods=['DELETE'])
@login_required
def delete_event(id):
    event = Event.query.get_or_404(id)
    db.session.delete(event)
    db.session.commit()
    return '', 204

@bp.route('/api/events/import', methods=['POST'])
@login_required
def import_events():
    if 'file' not in request.files:
        return jsonify({'error': 'No file uploaded'}), 400
    
    file = request.files['file']
    if not file or file.filename == '':
        return jsonify({'error': 'No file selected'}), 400
    
    if not file.filename.endswith('.csv'):
        return jsonify({'error': 'Only CSV files are allowed'}), 400
    
    try:
        # Create temporary file to store the uploaded CSV
        filename = secure_filename(file.filename)
        temp_path = os.path.join(current_app.config['UPLOAD_FOLDER'], filename)
        os.makedirs(os.path.dirname(temp_path), exist_ok=True)
        file.save(temp_path)
        
        imported_count = 0
        errors = []
        
        with open(temp_path, 'r', encoding='utf-8') as csvfile:
            reader = csv.DictReader(csvfile)
            
            for row_num, row in enumerate(reader, start=2):  # Start from 2 to account for header row
                try:
                    # Get city ID from city name
                    city_id = get_city_id_by_name(row['city'])
                    if city_id is None:
                        errors.append(f"Row {row_num}: Invalid city name '{row['city']}'. Valid cities are: {', '.join(CITY_URL_MAP.keys())}")
                        continue
                    
                    # Create new event
                    event = Event(
                        event_id=row['event_id'].strip(),
                        event_name=row['event_name'].strip(),
                        city_id=city_id,
                        start_date=datetime.strptime(row['start_date'].strip(), '%Y-%m-%d').date(),
                        end_date=datetime.strptime(row['end_date'].strip(), '%Y-%m-%d').date(),
                        markup=float(row['markup'].strip())
                    )
                    
                    db.session.add(event)
                    imported_count += 1
                    
                except Exception as e:
                    errors.append(f"Row {row_num}: {str(e)}")
                    continue
            
            if imported_count > 0:
                db.session.commit()
        
        # Clean up temporary file
        os.remove(temp_path)
        
        response = {
            'success': True,
            'imported_count': imported_count,
            'errors': errors
        }
        
        if errors:
            response['status'] = 'partial'
        else:
            response['status'] = 'success'
            
        return jsonify(response)
        
    except Exception as e:
        if 'temp_path' in locals():
            os.remove(temp_path)
        return jsonify({'error': str(e)}), 500
    
@bp.route('/api/events/template', methods=['GET'])
@login_required
def download_template():
    # Create a CSV template file with headers
    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(['event_id', 'event_name', 'city', 'start_date', 'end_date', 'markup'])
    
    writer.writerow(['EVT001', 'Sample Event', 'New York', '2024-01-01', '2024-01-03', '1.6'])
    
    # Create the response
    output.seek(0)
    return current_app.response_class(
        output.getvalue(),
        mimetype='text/csv',
        headers={
            "Content-Disposition": "attachment;filename=event_template.csv"
        }
    )
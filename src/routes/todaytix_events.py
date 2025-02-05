from datetime import datetime
from flask import Blueprint, jsonify, render_template, request, current_app
from flask_login import login_required
import csv
from io import StringIO
from ..todaytix.api import TodayTixAPI
from ..constants import CITY_URL_MAP

bp = Blueprint('todaytix_events', __name__)

@bp.route('/todaytix-events')
@login_required
def todaytix_events_page():
    return render_template('todaytix_events.html', cities=CITY_URL_MAP)

@bp.route('/api/todaytix-events/search', methods=['POST'])
@login_required
def search_events():
    try:
        data = request.json
        event_name = data.get('event_name')
        city_id = int(data.get('city_id'))
        start_date = datetime.strptime(data.get('start_date'), '%Y-%m-%d').date()
        end_date = datetime.strptime(data.get('end_date'), '%Y-%m-%d').date()

        if not all([event_name, city_id, start_date, end_date]):
            return jsonify({
                'status': 'error',
                'message': 'All fields are required'
            }), 400

        # Initialize API
        api = TodayTixAPI()

        # Search for event
        event = api.search_event(event_name, city_id)
        if not event:
            return jsonify({
                'status': 'error',
                'message': f'Event "{event_name}" not found'
            }), 404

        event_id = event['id']

        # Get showtimes
        showtimes = api.get_showtimes(event_id)
        # Filter showtimes by date range
        filtered_showtimes = []
        for showtime in showtimes:
            show_date = datetime.strptime(showtime.local_date, '%Y-%m-%d').date()
            if start_date <= show_date <= end_date:
                filtered_showtimes.append({
                    'todaytix_id': showtime.id,
                    'event_name': event_name,
                    'city': next((name for name, id_ in CITY_URL_MAP.items() if id_ == city_id), 'Unknown'),
                    'date': showtime.local_date,
                    'time': showtime.local_time,
                })

        if not filtered_showtimes:
            return jsonify({
                'status': 'error',
                'message': 'No showtimes found in the specified date range'
            }), 404

        # Generate CSV
        output = StringIO()
        writer = csv.writer(output)
        writer.writerow(['TodayTix ID', 'Event Name', 'City', 'Date', 'Time'])
        
        for show in filtered_showtimes:
            writer.writerow([
                show['todaytix_id'],
                show['event_name'],
                show['city'],
                show['date'],
                show['time'],
            ])

        # Create the response
        output.seek(0)
        return current_app.response_class(
            output.getvalue(),
            mimetype='text/csv',
            headers={
                "Content-Disposition": f"attachment;filename=todaytix_events_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
            }
        )

    except Exception as e:
        current_app.logger.error(f"Error searching events: {str(e)}")
        return jsonify({
            'status': 'error',
            'message': str(e)
        }), 500
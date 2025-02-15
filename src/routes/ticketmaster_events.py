from datetime import datetime
from flask import Blueprint, jsonify, render_template, request, current_app
from flask_login import login_required
import csv
from io import StringIO
from ..ticketmaster.api import TicketmasterAPI

bp = Blueprint('ticketmaster_events', __name__)

@bp.route('/ticketmaster-events')
@login_required
def ticketmaster_events_page():
    return render_template('ticketmaster_events.html')

@bp.route('/api/ticketmaster-events/search', methods=['POST'])
@login_required
def search_events():
    try:
        data = request.json
        event_name = data.get('event_name')
        city = data.get('city')
        start_date = datetime.strptime(data.get('start_date'), '%Y-%m-%d').date()
        end_date = datetime.strptime(data.get('end_date'), '%Y-%m-%d').date()

        if not all([event_name, city, start_date, end_date]):
            return jsonify({
                'status': 'error',
                'message': 'All fields are required'
            }), 400

        api = TicketmasterAPI()
        events = api.search_events(
            event_name=event_name,
            location=city,
            start_date=data.get('start_date'),
            end_date=data.get('end_date')
        )

        if not events:
            return jsonify({
                'status': 'error',
                'message': f'No events found for "{event_name}" in {city}'
            }), 404

        # Generate CSV
        output = StringIO()
        writer = csv.writer(output)
        writer.writerow([
            'website', 'event_id', 'ticketmaster_event_id', 'event_name', 'city', 
            'event_date', 'event_time', 'venue_name', 'markup'
        ])
        
        for event in events:
            writer.writerow([
                event['website'],
                event['event_id'],
                event['ticketmaster_event_id'],
                event['event_name'],
                event['city'],
                event['event_date'],
                event['event_time'],
                event['venue_name'],
                event['markup']
            ])

        output.seek(0)
        return current_app.response_class(
            output.getvalue(),
            mimetype='text/csv',
            headers={
                "Content-Disposition": f"attachment;filename=ticketmaster_events_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
            }
        )
        
    except Exception as e:
        current_app.logger.error(f"Error searching events: {str(e)}")
        return jsonify({
            'status': 'error',
            'message': str(e)
        }), 500
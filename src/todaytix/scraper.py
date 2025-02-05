from flask import current_app
import pandas as pd
import logging
import time
import os
from datetime import datetime
from typing import List, Dict, Optional
from ..models.database import Event, ScraperJob, db
from concurrent.futures import ThreadPoolExecutor
from ..services import UploadService

logger = logging.getLogger(__name__)

class EventScraper:
    def __init__(self, api, output_dir: str):
        self.api = api
        self.output_dir = output_dir
        self.max_concurrent = int(os.getenv('MAX_CONCURRENT_REQUESTS', '5'))
        self.app = current_app._get_current_object() 
        
    def generate_inventory_id(self, event_name: str, date: str, time: str, row: str) -> str:
        """Generate a unique inventory ID."""
        event_code = ''.join([c.upper() for c in event_name if c.isalpha()][:5])
        event_numeric = ''.join(str(ord(c) - 64) for c in event_code)
        date_numeric = date.replace("/", "")
        time_numeric = time.replace(":", "")

        if row.isdigit():
            row_numeric = row
        else:
            row_numeric = ''.join(str(ord(c.upper()) - 64) for c in row)
        return f"{date_numeric}{event_numeric}{row_numeric}{time_numeric}"

    def get_show_id(self, event: Event) -> Optional[int]:
        """Get show ID using event name and city."""
        try:
            api_event = self.api.search_event(event.event_name, event.city_id)
            if api_event:
                return api_event['id']
            return None
        except Exception as e:
            logger.error(f"Error getting show ID for event {event.event_name}: {str(e)}")
            return None

    def process_event(self, event: Event) -> List[Dict]:
        """Process a single event using its TodayTix ID."""
        try:
            if not event.todaytix_id:
                logger.error(f"No TodayTix ID found for event: {event.event_name}")
                return []

            # Get show ID first
            show_id = self.get_show_id(event)
            if not show_id:
                logger.error(f"Could not find show ID for event: {event.event_name}")
                return []

            # Use stored todaytix_id as showtime_id
            showtime_id = int(event.todaytix_id)
            
            # Get seats directly using the IDs
            seats_data = self.api.get_seats(show_id, showtime_id)
            processed_data = []
            
            for seat in seats_data:
                # Format date based on event's date
                date_str = event.event_date.strftime('%m/%d/%Y')
                
                # Use event-specific markup
                unit_list_price = int(round(seat['price'] * event.markup))
                
                processed_data.append({
                    "inventory_id": self.generate_inventory_id(event.event_name, date_str, event.event_time, seat['row']),
                    "event_name": event.event_name,
                    "venue_name": seat['section'].split(' - ')[0] if ' - ' in seat['section'] else 'Unknown Venue',
                    "event_date": f"{event.event_date.strftime('%Y-%m-%d')}T{event.event_time}:00",
                    "event_id": event.event_id,
                    "quantity": 2,
                    "section": seat['section'],
                    "row": seat['row'],
                    "seats": seat['seats'],
                    "barcodes": "",
                    "internal_notes": "",
                    "public_notes": "",
                    "tags": "",
                    "list_price": unit_list_price,
                    "face_price": 0,
                    "taxed_cost": 0,
                    "cost": seat['price'],
                    "hide_seats": "Y",
                    "in_hand": "N",
                    "in_hand_date": date_str,
                    "instant_transfer": "N",
                    "files_available": "N",
                    "split_type": "NEVERLEAVEONE",
                    "custom_split": "",
                    "stock_type": "ELECTRONIC",
                    "zone": "N",
                    "shown_quantity": "",
                    "passthrough": "",
                })
            
            return processed_data
            
        except Exception as e:
            logger.error(f"Error processing event {event.event_name}: {str(e)}")
            return []

    def process_event_with_context(self, event: Event) -> List[Dict]:
        """Wrapper to handle Flask context in threads"""
        with self.app.app_context():
            return self.process_event(event)
        
    def run(self, job: ScraperJob):
        """Run the scraper with job tracking and concurrent processing."""
        try:
            logger.info("Starting scraper run")
            output_file = None
            
            # Get all events with TodayTix IDs
            events = Event.query.filter(
                Event.todaytix_id.isnot(None),
                Event.website == 'TodayTix'
            ).all()

            if not events:
                logger.warning("No TodayTix events found")
                return False, None
                
            all_seats_data = []
            
            # Process events sequentially to avoid rate limiting
            for event in events:
                try:
                    seats_data = self.process_event_with_context(event)
                    if seats_data:
                        all_seats_data.extend(seats_data)
                        job.total_tickets_found += len(seats_data)
                        job.events_processed += 1
                        db.session.commit()
                        logger.info(f"Found {len(seats_data)} seat pairs for {event.event_name}")
                    time.sleep(1)  # Add delay between events
                except Exception as e:
                    logger.error(f"Error processing event {event.event_name}: {str(e)}")
            
            if all_seats_data:
                # Generate output filename with timestamp
                timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
                output_file = os.path.join(self.output_dir, f'tickets_{timestamp}.xlsx')
                
                # Save to Excel
                output_df = pd.DataFrame(all_seats_data)
                output_df.to_excel(output_file, index=False)
                logger.info(f"Saved {len(output_df)} rows to {output_file}")
                
                # Upload the file
                upload_service = UploadService(
                    current_app.config['STORE_API_BASE_URL'],
                    current_app.config['STORE_API_KEY'],
                    current_app.config['COMPANY_ID']
                )
                success, message = upload_service.upload_csv(output_file)
                if success:
                    logger.info(f"File uploaded successfully: {message}")
                else:   
                    logger.error(f"File upload failed: {message}")
                
                return True, output_file
            else:
                logger.warning("No data collected")
                return False, None
                
        except Exception as e:
            logger.error(f"Error running scraper: {str(e)}")
            return False, None
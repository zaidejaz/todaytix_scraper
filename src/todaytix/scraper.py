from flask import current_app
import pandas as pd
import logging
import time
import os
from datetime import datetime
from typing import List, Dict
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
        
    def generate_inventory_id(self, event_name: str, date: str, time:str, row: str) -> str:
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

    def get_available_dates(self, event: Event) -> List[Dict]:
        """Get all available dates and times for an event."""
        try:
            location_id = event.city_id 
            api_event = self.api.search_event(event.event_name, location_id)
            if not api_event:
                logger.error(f"Event '{event.event_name}' not found")
                return []

            event_id = api_event['id']
            venue_name = api_event['venue']
            
            # Get all available showtimes
            showtimes = self.api.get_showtimes(event_id)
            return [{
                'event_id': event_id,
                'venue_name': venue_name,
                'showtime': st
            } for st in showtimes]
            
        except Exception as e:
            logger.error(f"Error getting dates for {event.event_name}: {str(e)}")
            return []

    def process_showtime(self, event: Event, showtime_data: Dict) -> List[Dict]:
        """Process a single showtime and return seat data."""
        try:
            event_id = showtime_data['event_id']
            venue_name = showtime_data['venue_name']
            showtime = showtime_data['showtime']
            
            # Get seats for this showtime
            seats_data = self.api.get_seats(event_id, showtime.id)
            processed_data = []
            
            for seat in seats_data:
                # Format date for inventory ID
                date_str = datetime.strptime(showtime.local_date, '%Y-%m-%d').strftime('%m/%d/%Y')
                
                # Use event-specific markup
                unit_list_price = int(round(seat['price'] * event.markup))
                
                processed_data.append({
                    "inventory_id": self.generate_inventory_id(event.event_name, date_str, showtime.local_time, seat['row']),
                    "event_name": event.event_name,
                    "venue_name": venue_name,
                    "event_date": f"{showtime.local_date}T{showtime.local_time}:00",
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
            logger.error(f"Error processing showtime: {str(e)}")
            return []

    def process_showtime_with_context(self, event: Event, date_data: Dict) -> List[Dict]:
        """Wrapper to handle Flask context in threads"""
        with self.app.app_context():
            return self.process_showtime(event, date_data)
        
    def run(self, job: ScraperJob):
        """Run the scraper with job tracking and concurrent processing."""
        try:
            logger.info("Starting scraper run")
            output_file = None
            
            # Get all events
            events = Event.query.all()
            if not events:
                logger.warning("No events found")
                return False, None
                
            all_seats_data = []
            
            for event in events:
                # Update job status
                job.events_processed += 1
                db.session.commit()
                
                logger.info(f"Getting available dates for: {event.event_name}")
                available_dates = self.get_available_dates(event)
                available_dates.sort(key=lambda x: x['showtime'].local_date)
                
                filtered_dates = [
                    date_data for date_data in available_dates
                    if event.start_date <= datetime.strptime(date_data['showtime'].local_date, '%Y-%m-%d').date() <= event.end_date
                ]

                # Process dates concurrently using ThreadPoolExecutor
                with ThreadPoolExecutor(max_workers=self.max_concurrent) as executor:
                    # Use the wrapper function that handles Flask context
                    futures = [
                        executor.submit(self.process_showtime_with_context, event, date_data)
                        for date_data in filtered_dates
                    ]
                    
                    # Process results as they complete
                    for future in futures:
                        try:
                            seats_data = future.result()
                            if seats_data:
                                all_seats_data.extend(seats_data)
                                job.total_tickets_found += len(seats_data)
                                db.session.commit()
                                logger.info(f"Found {len(seats_data)} seat pairs")
                        except Exception as e:
                            logger.error(f"Error processing showtime: {str(e)}")
                
                # Add a small delay between events
                time.sleep(0.5)
            
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
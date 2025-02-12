from concurrent import futures
import zlib
from flask import current_app
import pandas as pd
import logging
import time
import os
from datetime import datetime
from typing import List, Dict, Optional
from ..models.database import Event, ScraperJob, VenueMapping, db
from concurrent.futures import ThreadPoolExecutor
from ..services import UploadService

logger = logging.getLogger(__name__)

class EventScraper:
    def __init__(self, api, output_dir: str, concurrent_requests: int = 5, auto_upload: bool = False):
        self.api = api
        self.output_dir = output_dir
        self.max_concurrent = concurrent_requests
        self.auto_upload = auto_upload
        self.app = current_app._get_current_object()
        self._stop_requested = False
        self._executor = None
        
    def request_stop(self):
        """Signal the scraper to stop gracefully"""
        self._stop_requested = True
        if self._executor:
            self._executor.shutdown(wait=False)
            
    def should_stop(self) -> bool:
        """Check if stop has been requested"""
        with self.app.app_context():
            # Check both internal flag and job status
            job = ScraperJob.query.order_by(ScraperJob.id.desc()).first()
            return self._stop_requested or (job and job.status == 'stopped')

    def generate_section_hash(self, section_name: str) -> str:
        """Generate a 3-digit hash from section name."""
        return str(zlib.crc32(str(section_name).encode()) % 1000).zfill(3)
    
    def convert_row_to_number(self, row: str) -> str:
        """Convert row to 2-digit numeric format."""
        if str(row).isdigit():
            return str(row).zfill(2)
        return str(ord(str(row).upper()[0]) - ord('A') + 1).zfill(2)
    
    def get_first_seat(self, seats: str) -> str:
        """Extract first seat number from seats string."""
        try:
            first_seat = str(seats).split(',')[0].strip()
            return first_seat
        except:
            return "00"

    def generate_inventory_id(self, event_id: str, section: str, row: str, seats: str) -> str:
        """Generate a unique inventory ID following the new format."""
        section_hash = self.generate_section_hash(section)
        row_num = self.convert_row_to_number(row)
        first_seat = self.get_first_seat(seats)
        
        return f"{event_id}{section_hash}{row_num}{first_seat}"

    def process_seats(self, event: Event, seats_data: List[Dict]) -> List[Dict]:
        """Process seats data for an event."""
        if self.should_stop():
            return []
            
        processed_data = []
        date_str = event.event_date.strftime('%m/%d/%Y')
        date_parts = date_str.split('/')
        in_hand_date = f"{date_parts[2]}-{date_parts[0].zfill(2)}-{date_parts[1].zfill(2)}"

        for seat in seats_data:
            if self.should_stop():
                return processed_data
                
            unit_list_price = int(round(seat['price'] * event.markup))
            processed_data.append({
                "inventory_id": self.generate_inventory_id(
                    str(event.event_id),
                    seat['section'],
                    seat['row'],
                    seat['seats']
                ),
                "event_name": event.event_name,
                "venue_name": event.venue_name or 'Unknown Venue',
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
                "in_hand_date": event.in_hand_date or in_hand_date,
                "instant_transfer": "N",
                "files_available": "N",
                "split_type": "NEVERLEAVEONE",
                "custom_split": "",
                "stock_type": event.stock_type or "ELECTRONIC",
                "zone": "N",
                "shown_quantity": "",
                "passthrough": "",
            })
        return processed_data

    def process_event_with_context(self, event: Event) -> List[Dict]:
        """Wrapper to handle Flask context in threads"""
        if self.should_stop():
            return []
            
        with self.app.app_context():
            return self.process_event(event)

    def process_event(self, event: Event) -> List[Dict]:
        """Process a single event using stored IDs."""
        if self.should_stop():
            return []

        try:
            if not event.todaytix_event_id or not event.todaytix_show_id:
                logger.error(f"Missing TodayTix IDs for event: {event.event_name}")
                return []

            try:
                rules = {}
                for rule in event.rules:
                    rules[rule.rule_type] = rule.keyword
            except Exception as e:
                logger.error(f"Error fetching rules for event {event.event_name}: {str(e)}")
                rules = {}

            excluded_seats = VenueMapping.get_excluded_seats(event.event_name, event.venue_name)

            if self.should_stop():
                return []

            seats_data = self.api.get_seats(
                int(event.todaytix_show_id), 
                int(event.todaytix_event_id), 
                rules=rules,
                excluded_seats=excluded_seats
            )

            if seats_data:
                logger.info(f"Found {len(seats_data)} valid seats for event: {event.event_name}")
            else:
                logger.warning(f"No seats found for event: {event.event_name}")

            return self.process_seats(event, seats_data)

        except Exception as e:
            logger.error(f"Error processing event {event.event_name}: {str(e)}")
            return []

    def run(self, job: ScraperJob):
        """Run the scraper with job tracking and concurrent processing."""
        try:
            self._stop_requested = False
            logger.info("Starting scraper run")
            logger.info(f"Using max concurrent requests: {self.max_concurrent}")
            logger.info(f"Auto upload enabled: {self.auto_upload}")
            output_file = None

            events = Event.query.filter(
                Event.todaytix_event_id.isnot(None),
                Event.todaytix_show_id.isnot(None),
                Event.website == 'TodayTix'
            ).all()

            if not events:
                logger.warning("No TodayTix events found with required IDs")
                return False, None

            all_seats_data = []
            processed_events = 0

            # Process events concurrently
            with ThreadPoolExecutor(max_workers=self.max_concurrent) as executor:
                self._executor = executor  # Store executor for stop requests
                future_to_event = {
                    executor.submit(self.process_event_with_context, event): event 
                    for event in events
                }

                for future in futures.as_completed(future_to_event):
                    if self.should_stop():
                        logger.info("Stop requested, terminating scraper")
                        return False, None
                        
                    event = future_to_event[future]
                    try:
                        seats_data = future.result()
                        if seats_data:
                            all_seats_data.extend(seats_data)
                            job.total_tickets_found += len(seats_data)
                            logger.info(f"Found {len(seats_data)} seats for event: {event.event_name}")

                        processed_events += 1
                        job.events_processed = processed_events
                        db.session.commit()

                        progress = (processed_events / len(events)) * 100
                        logger.info(f"Progress: {progress:.1f}% ({processed_events}/{len(events)} events)")
                        
                    except Exception as e:
                        logger.error(f"Error processing event {event.event_name}: {str(e)}")

            if self.should_stop():
                logger.info("Stop requested, terminating scraper")
                return False, None

            if all_seats_data:
                # Save directly as CSV instead of Excel
                timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
                output_file = os.path.join(self.output_dir, f'tickets_{timestamp}.csv')

                # Save as CSV without BOM
                output_df = pd.DataFrame(all_seats_data)
                output_df.to_csv(output_file, index=False, encoding='utf-8')
                logger.info(f"Saved {len(output_df)} rows to {output_file}")

                # Upload the file if auto_upload is enabled
                if self.auto_upload:
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
        finally:
            self._executor = None
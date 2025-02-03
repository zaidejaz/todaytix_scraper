import requests
from typing import Dict, List, Optional, Union, Tuple
from dataclasses import dataclass
from datetime import datetime
import pandas as pd
import time
import re
import logging
import os

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# City mapping
CITY_URL_MAP = {
    "London": 2,
    "New York": 3,
    "Sydney": 4,
    "Los Angeles + OC": 5,
    "Brisbane": 6,
    "Chicago": 7,
    "Perth": 8,
    "SF Bay Area": 9,
    "Washington DC": 10,
    "Adelaide": 11,
    "Melbourne": 12
}

def generate_inventory_id(event_name: str, date: str, row: str) -> str:
    """Generate a unique inventory ID."""
    event_code = ''.join([c.upper() for c in event_name if c.isalpha()][:5])
    event_numeric = ''.join(str(ord(c) - 64) for c in event_code)
    date_numeric = date.replace("/", "")
    time_numeric = re.sub(r"\D", "", date)

    if row.isdigit():
        row_numeric = row
    else:
        row_numeric = ''.join(str(ord(c.upper()) - 64) for c in row)
    return f"{date_numeric}{event_numeric}{row_numeric}{time_numeric}"

@dataclass
class ShowTime:
    id: int
    datetime: str
    local_date: str
    local_time: str
    day_of_week: str

@dataclass
class Seat:
    section: str
    row: str
    seat_number: str
    price: float
    face_value: float
    is_restricted_view: bool
    seat_id: str
    fees: Dict[str, float]

class TodayTixAPI:
    BASE_URL = "https://api.todaytix.com/api/v2"
    
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            'Accept': 'application/json',
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })

    def search_event(self, event_name: str, location: int = 2) -> Optional[Dict]:
        """Search for an event and return its details."""
        try:
            params = {
                'fieldset': 'SHOW_SUMMARY',
                'query': event_name,
                'location': location,
                'limit': 5,
                'offset': 0,
                'includeAggregations': False
            }
            response = self.session.get(f"{self.BASE_URL}/shows", params=params)
            response.raise_for_status()
            data = response.json()
            
            for event in data['data']:
                if event['name'].lower() == event_name.lower():
                    return event
            return None
            
        except requests.RequestException as e:
            logger.error(f"Error searching for event: {str(e)}")
            return None

    def get_showtimes(self, show_id: int) -> List[ShowTime]:
        """Get all available showtimes for an event."""
        try:
            response = self.session.get(f"{self.BASE_URL}/shows/{show_id}/showtimes")
            response.raise_for_status()
            data = response.json()
            
            showtimes = []
            for show in data['data']:
                showtime = ShowTime(
                    id=show['id'],
                    datetime=show['datetime'],
                    local_date=show['localDate'],
                    local_time=show['localTime'],
                    day_of_week=show['dayOfWeek']
                )
                showtimes.append(showtime)
                
            return showtimes
            
        except requests.RequestException as e:
            logger.error(f"Error fetching showtimes: {str(e)}")
            return []

    def get_seats(self, show_id: int, showtime_id: int, quantity: int = 2) -> List[Dict]:
        """Get available seats for a specific showtime."""
        try:
            params = {
                'allowMultipleGaSections': True,
                'quantity': quantity,
                'groupSelectionBy': 'SAME_PROVIDER'
            }
            url = f"{self.BASE_URL}/shows/{show_id}/showtimes/{showtime_id}/sections"
            response = self.session.get(url, params=params)
            response.raise_for_status()
            data = response.json()
            
            seats_data = []
            for section in data['data']:
                section_name = section['name']
                for block in section['seatBlocks']:
                    seats = []
                    for seat in block['seats']:
                        seat_info = {
                            'section': section_name,
                            'row': block['row'],
                            'seat_number': seat['name'],
                            'price': block['salePrice']['value'],
                            'face_value': block['faceValue']['value'],
                            'is_restricted_view': seat['isRestrictedView'],
                            'seat_id': seat['id'],
                            'fees': {
                                'convenience': block['feeSummary']['convenience']['value'],
                                'concierge': block['feeSummary']['concierge']['value'],
                                'order': block['feeSummary']['orderFee']['value']
                            }
                        }
                        seats.append(seat_info)
                    
                    # Group seats by pairs
                    for i in range(0, len(seats), 2):
                        if i + 1 < len(seats):
                            seats_data.append({
                                'section': seats[i]['section'],
                                'row': seats[i]['row'],
                                'seats': f"{seats[i]['seat_number']},{seats[i+1]['seat_number']}",
                                'price': seats[i]['price'],
                                'face_value': seats[i]['face_value'],
                                'is_restricted_view': seats[i]['is_restricted_view'],
                                'fees': seats[i]['fees']
                            })
                        
            return seats_data
            
        except requests.RequestException as e:
            logger.error(f"Error fetching seats: {str(e)}")
            return []

class EventScraper:
    def __init__(self, api: TodayTixAPI, input_file: str, output_file: str):
        self.api = api
        self.input_file = input_file
        self.output_file = output_file

    def process_event(self, event_name: str, city: str, date: str, time_slot: str) -> List[Dict]:
        """Process a single event and return seat data."""
        try:
            location_id = CITY_URL_MAP.get(city, 2)
            event = self.api.search_event(event_name, location_id)
            if not event:
                logger.error(f"Event '{event_name}' not found")
                return []

            event_id = event['id']
            venue_name = event['venue']
            
            # Convert date formats
            new_date = datetime.strptime(date, '%m/%d/%Y').strftime('%Y-%m-%d')
            new_time = datetime.strptime(time_slot, '%H:%M:%S').strftime('%H:%M')
            
            # Get showtimes and find matching showtime
            showtimes = self.api.get_showtimes(event_id)
            matching_showtime = None
            for st in showtimes:
                if st.local_date == new_date and st.local_time == new_time:
                    matching_showtime = st
                    break
                    
            if not matching_showtime:
                logger.error(f"No matching showtime found for {new_date} {new_time}")
                return []
                
            # Get seats
            seats_data = self.api.get_seats(event_id, matching_showtime.id)
            processed_data = []
            
            for seat in seats_data:
                inventory_id = generate_inventory_id(event_name, date, seat['row'])
                
                # Calculate list price (60% increase)
                unit_list_price = int(round(seat['price'] * 1.6))
                
                processed_data.append({
                    "inventory_id": inventory_id,
                    "event_name": event_name,
                    "venue_name": venue_name,
                    "event_date": f"{new_date}T{new_time}:00",
                    "event_id": "",
                    "quantity": 2,
                    "section": seat['section'],
                    "row": seat['row'],
                    "seats": seat['seats'],
                    "barcodes": "",
                    "internal_notes": "",
                    "public_notes": "",
                    "tags": "",
                    "list_price": unit_list_price,
                    "face_price": seat['face_value'],
                    "taxed_cost": 0,
                    "cost": seat['price'],
                    "hide_seats": "Y",
                    "in_hand": "N",
                    "in_hand_date": date,
                    "instant_transfer": "",
                    "files_available": "N",
                    "split_type": "ANY",
                    "custom_split": "",
                    "stock_type": "ELECTRONIC",
                    "zone": "N",
                    "shown_quantity": "",
                    "passthrough": ""
                })
                
            return processed_data
            
        except Exception as e:
            logger.error(f"Error processing event {event_name}: {str(e)}")
            return []

    def run(self, days_limit: Optional[int] = None):
        """Run the scraper on all events from the input file."""
        try:
            # Read input file
            events_df = pd.read_excel(self.input_file)
            logger.info(f"Loaded {len(events_df)} events from input file")
            
            all_seats_data = []
            processed_dates = set()
            
            for _, event in events_df.iterrows():
                if days_limit and len(processed_dates) >= days_limit:
                    break
                    
                date = event['Date'].strftime('%m/%d/%Y')
                if days_limit and date in processed_dates:
                    continue
                    
                logger.info(f"Processing event: {event['Event Name']} on {date}")
                seats_data = self.process_event(
                    event['Event Name'],
                    event['City'],
                    date,
                    str(event['Time Slot'])
                )
                
                if seats_data:
                    all_seats_data.extend(seats_data)
                    processed_dates.add(date)
                    logger.info(f"Found {len(seats_data)} seat pairs")
                
                # Add delay between requests
                time.sleep(0.5)
            
            if all_seats_data:
                # Save to Excel
                output_df = pd.DataFrame(all_seats_data)
                output_df.to_excel(self.output_file, index=False)
                logger.info(f"Saved {len(output_df)} rows to {self.output_file}")
            else:
                logger.warning("No data collected")
                
        except Exception as e:
            logger.error(f"Error running scraper: {str(e)}")

def main():
    # File paths
    input_file = "eventss.xlsx"
    output_file = f"tickets_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
    
    # Initialize API and scraper
    api = TodayTixAPI()
    scraper = EventScraper(api, input_file, output_file)
    
    # Run scraper with optional day limit
    days_limit = 3  # Set to None for all days
    scraper.run(days_limit=days_limit)

if __name__ == "__main__":
    while True:
        start_time = time.time()
        main()
        elapsed_time = time.time() - start_time
        wait_time = max(0, 300 - elapsed_time)  # 5 minutes between runs
        logger.info(f"Waiting {wait_time/60:.2f} minutes before next run")
        time.sleep(wait_time)
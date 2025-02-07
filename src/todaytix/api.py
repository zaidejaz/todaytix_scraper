import requests
import logging
import os
import json
from typing import Dict, List, Optional
from .models import ShowTime, Seat

logger = logging.getLogger(__name__)

class TodayTixAPI:
    BASE_URL = "https://api.todaytix.com/api/v2"
    
    def __init__(self):
        self.proxy_url = os.getenv('PROXY_API_URL')
        self.proxy_api_key = os.getenv('PROXY_API_KEY')
        logger.info(f"Proxy URL: {self.proxy_url}")
        if not all([self.proxy_url, self.proxy_api_key]):
            raise ValueError("Missing proxy configuration in environment")
            
        self.session = requests.Session()
        self.session.headers.update({
            'Accept': 'application/json',
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'X-Api-Key': self.proxy_api_key
        })

    def _make_proxy_request(self, method: str, endpoint: str, params: Dict = None) -> Dict:
        """Make a request through the proxy service."""
        target_url = f"{self.BASE_URL}{endpoint}"
        proxy_params = {'url': target_url}
        
        if params:
            proxy_params.update(params)
        try:
            logger.info(f"Making proxy request to: {target_url}")
            response = self.session.request(
                method=method,
                url=f"{self.proxy_url}/api/proxy/request",
                params=proxy_params
            )
            response.raise_for_status()
            
            proxy_response = response.json()
            if not proxy_response.get('content'):
                logger.error("No content in proxy response")
                return None
                
            return json.loads(proxy_response['content'])
            
        except requests.RequestException as e:
            logger.error(f"Proxy request failed: {str(e)}")
            return None
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse response: {str(e)}")
            return None

    def search_event(self, event_name: str, location: int = 2) -> Optional[Dict]:
        """Search for an event and return its details."""
        params = {
            'fieldset': 'SHOW_SUMMARY',
            'query': event_name,
            'location': location,
            'limit': 5,
            'offset': 0,
            'includeAggregations': False,
        }
        
        data = self._make_proxy_request('GET', '/shows', params=params)
        if not data or 'data' not in data:
            return None
            
        for event in data['data']:
            if event['displayName'].lower() == event_name.lower():
                return event
        return None

    def get_showtimes(self, show_id: int) -> List[ShowTime]:
        """Get all available showtimes for an event."""
        data = self._make_proxy_request('GET', f'/shows/{show_id}/showtimes')
        if not data or 'data' not in data:
            return []
            
        return [
            ShowTime(
                id=show['id'],
                datetime=show['datetime'],
                local_date=show['localDate'],
                local_time=show['localTime'],
                day_of_week=show['dayOfWeek']
            )
            for show in data['data']
        ]

    def analyze_seat_pattern(self, seats):
        """
        Analyze if seats follow even, odd, or consecutive pattern
        Returns tuple of (pattern_type, seats_list) where pattern_type is 'even', 'odd', 'consecutive', or None
        """
        # Extract seat numbers
        seat_numbers = []
        for seat in seats:
            try:
                num = int(''.join(filter(str.isdigit, seat['name'])))
                seat_numbers.append((num, seat))
            except (ValueError, TypeError):
                continue

        if not seat_numbers:
            return None, []

        # Sort by seat number
        seat_numbers.sort(key=lambda x: x[0])

        # Check patterns
        numbers = [x[0] for x in seat_numbers]

        # Check even pattern
        if all(n % 2 == 0 for n in numbers):
            return 'even', [s[1] for s in seat_numbers]

        # Check odd pattern    
        if all(n % 2 == 1 for n in numbers):
            return 'odd', [s[1] for s in seat_numbers]

        # Check consecutive pattern
        consecutive_pairs = []
        for i in range(len(numbers)-1):
            if numbers[i+1] == numbers[i] + 1:
                consecutive_pairs.append((seat_numbers[i][1], seat_numbers[i+1][1]))

        if consecutive_pairs:
            return 'consecutive', [s for pair in consecutive_pairs for s in pair]

        return None, []

    def get_seats(self, show_id: int, showtime_id: int, rules: dict = None) -> List[Dict]:
        """
        Get available seats for a specific showtime with pattern matching and price optimization.

        Args:
            show_id: Show ID
            showtime_id: Showtime ID
            rules: Dict of rules with keywords for each pattern type {'even': 'keyword', 'odd': 'keyword', 'consecutive': 'keyword'}
        """
        params = {
            'allowMultipleGaSections': True,
            'quantity': 2,
            'groupSelectionBy': 'SAME_PROVIDER'
        }

        data = self._make_proxy_request(
            'GET',
            f'/shows/{show_id}/showtimes/{showtime_id}/sections',
            params=params
        )

        if not data or 'data' not in data:
            return []

        # Process each section
        seats_data = []
        processed_sections = set()  # Track processed section+row combinations

        for section in data['data']:
            base_section_name = section['name']

            # Process each block
            for block in section['seatBlocks']:
                row = block['row']

                # Get non-restricted seats
                non_restricted_seats = [
                    seat for seat in block['seats']
                    if not seat['isRestrictedView']
                ]

                # Analyze seat pattern
                pattern_type, pattern_seats = self.analyze_seat_pattern(non_restricted_seats)

                if pattern_type and pattern_seats and rules and pattern_type in rules:
                    # Create section name with rule keyword
                    section_name = f"{base_section_name} {rules[pattern_type]}"
                    section_key = f"{section_name}_{row}"

                    # Skip if we've already processed this section+row combination
                    if section_key in processed_sections:
                        continue

                    # Get consecutive pairs
                    pairs = []
                    for i in range(0, len(pattern_seats)-1, 2):
                        pairs.append(f"{pattern_seats[i]['name']},{pattern_seats[i+1]['name']}")

                    if pairs:
                        # Add to tracking set
                        processed_sections.add(section_key)

                        # Add the seat data
                        seats_data.append({
                            'section': section_name,
                            'row': row,
                            'seats': pairs[0],  # Take only first pair
                            'price': block['salePrice']['value'],
                            'face_value': block['faceValue']['value'],
                            'is_restricted_view': False,
                            'pattern_type': pattern_type,
                            'fees': {
                                'convenience': block['feeSummary']['convenience']['value'],
                                'concierge': block['feeSummary']['concierge']['value'],
                                'order': block['feeSummary']['orderFee']['value']
                            }
                        })

        return seats_data
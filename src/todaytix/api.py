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

    def get_seats(self, show_id: int, showtime_id: int, quantity: int = 2) -> List[Dict]:
        """Get available seats for a specific showtime."""
        params = {
            'allowMultipleGaSections': True,
            'quantity': quantity,
            'groupSelectionBy': 'SAME_PROVIDER'
        }
        
        data = self._make_proxy_request(
            'GET',
            f'/shows/{show_id}/showtimes/{showtime_id}/sections',
            params=params
        )
        if not data or 'data' not in data:
            return []
            
        seats_data = []
        for section in data['data']:
            section_name = section['name']
            for block in section['seatBlocks']:
                row = block['row']
                
                non_restricted_seats = [
                    seat for seat in block['seats']
                    if not seat['isRestrictedView']
                ]
                
                has_adjacent_pair = False
                for i in range(len(non_restricted_seats) - 1):
                    current_seat = non_restricted_seats[i]
                    next_seat = non_restricted_seats[i + 1]
                    
                    try:
                        current_num = int(''.join(filter(str.isdigit, current_seat['name'])))
                        next_num = int(''.join(filter(str.isdigit, next_seat['name'])))
                        
                        if next_num == current_num + 1:
                            has_adjacent_pair = True
                            break
                    except (ValueError, TypeError):
                        continue
                    
                if has_adjacent_pair:
                    seats_data.append({
                        'section': section_name,
                        'row': row,
                        'seats': "1,2", 
                        'price': block['salePrice']['value'],
                        'face_value': block['faceValue']['value'],
                        'is_restricted_view': False,
                        'fees': {
                            'convenience': block['feeSummary']['convenience']['value'],
                            'concierge': block['feeSummary']['concierge']['value'],
                            'order': block['feeSummary']['orderFee']['value']
                        }
                    })
        
        return seats_data
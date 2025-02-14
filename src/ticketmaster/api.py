import os
import requests
import logging
import uuid
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

class TicketmasterAPI:
    BASE_URL = 'https://services.ticketmaster.com/api/ismds'

    def __init__(self):
        self.api_key = os.getenv('TICKETMASTER_API_KEY')
        self.api_secret = os.getenv('TICKETMASTER_API_SECRET')
        if not all([self.api_key, self.api_secret]):
            raise ValueError("Missing Ticketmaster API configuration in environment")

        self.headers = {
            'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64; rv:133.0) Gecko/20100101 Firefox/133.0',
            'Accept': '*/*',
            'Accept-Language': 'en-US,en;q=0.5',
            'Accept-Encoding': 'gzip, deflate, br, zstd',
            'TMPS-Correlation-Id': str(uuid.uuid4()), 
            'Origin': 'https://www.ticketmaster.com',
            'Connection': 'keep-alive',
            'Referer': 'https://www.ticketmaster.com/',
            'Sec-Fetch-Dest': 'empty',
            'Sec-Fetch-Mode': 'cors',
            'Sec-Fetch-Site': 'same-site',
            'Pragma': 'no-cache',
            'Cache-Control': 'no-cache',
            'TE': 'trailers'
        }

    def get_seats(self, event_id: str) -> List[Dict]:
        """Get available seats for a specific event."""
        seats_data = []
        offset = 0
        limit = 40

        while True:
            try:
                base_url = f'{self.BASE_URL}/event/{event_id}/quickpicks'
                
                # Query parameters
                query_params = (
                    f'show=places+sections'
                    f'&mode=primary:ppsectionrow+resale:ga_areas+platinum:all'
                    f'&qty=2'
                    f"&q=not('accessible')"
                    f'&includeStandard=true'
                    f'&includeResale=false'
                    f'&includePlatinumInventoryType=false'
                    f'&ticketTypes=000000000001'
                    f'&embed=area&embed=offer&embed=description'
                    f'&apikey={self.api_key}'
                    f'&apisecret={self.api_secret}'
                    f'&resaleChannelId=internal.ecommerce.consumer.desktop.web.browser.ticketmaster.us'
                    f'&limit={limit}'
                    f'&offset={offset}'
                    f'&sort=listprice'
                )

                url = f"{base_url}?{query_params}"

                response = requests.get(url, headers=self.headers)
                response.raise_for_status()
                data = response.json()

                if not data.get('picks'):
                    break

                processed_seats = self._process_seats_data(data)
                seats_data.extend(processed_seats)

                if len(data['picks']) < limit:
                    break

                offset += limit

            except Exception as e:
                logger.error(f"Error fetching seats for event {event_id}: {str(e)}")
                if 'response' in locals() and hasattr(response, 'text'):
                    logger.error(f"Response content: {response.text}")
                break

        return seats_data

    def _process_seats_data(self, data: Dict) -> List[Dict]:
        """Process raw seats data into standardized format."""
        processed_seats = []
        offer_map = {offer['offerId']: offer for offer in data.get('_embedded', {}).get('offer', [])}

        for pick in data['picks']:
            if pick['selection'] != 'standard':
                continue

            # Handle GA event
            if pick['type'] == 'general-seating':
                offer_id = pick['offers'][0]
                offer = offer_map.get(offer_id, {})
                price = offer.get('listPrice', 0)
                face_value = offer.get('faceValue', 0)

                processed_seats.append({
                    'section': pick['section'],
                    'row': 'GA',
                    'seats': ','.join(map(str, range(20, 24))),  
                    'price': price,
                    'face_value': face_value,
                    'type': 'standard'
                })
                continue

            # Handle regular seats
            if pick['type'] == 'seat':
                for offer_group in pick['offerGroups']:
                    offer_id = offer_group['offers'][0]
                    offer = offer_map.get(offer_id, {})
                    
                    if not offer_group.get('seats'):
                        continue

                    price = offer.get('listPrice', 0)
                    face_value = offer.get('faceValue', 0)

                    processed_seats.append({
                        'section': pick['section'],
                        'row': pick['row'],
                        'seats': ','.join(map(str, offer_group['seats'])),
                        'price': price,
                        'face_value': face_value,
                        'type': 'standard'
                    })

        return processed_seats
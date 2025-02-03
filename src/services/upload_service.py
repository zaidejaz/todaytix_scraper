import requests
import logging
from typing import Dict, Optional, Tuple
import os

logger = logging.getLogger(__name__)

class UploadService:
    def __init__(self, api_base_url: str, api_key: str, company_id: str):
        self.api_base_url = api_base_url
        self.headers = {
            'X-Api-Token': api_key,
            'X-Company-Id': company_id,
            'accept': 'application/json',
            'Content-Type': 'application/json'
        }
    
    def request_upload(self) -> Tuple[bool, Dict]:
        """Request upload credentials from the API."""
        try:
            response = requests.post(
                f"{self.api_base_url}/sync/api/inventories/csv_upload_request",
                headers=self.headers
            )
            response.raise_for_status()
            return True, response.json()
        except Exception as e:
            logger.error(f"Error requesting upload: {str(e)}")
            return False, {"error": str(e)}
    
    def upload_to_s3(self, file_path: str, upload_data: Dict) -> Tuple[bool, str]:
        """Upload file to S3 using provided credentials."""
        try:
            if not os.path.exists(file_path):
                return False, "File does not exist"
                
            # Extract fields from upload data
            fields = upload_data['upload']['fields']
            url = upload_data['upload']['url']
            
            # Create form data in the exact order S3 expects
            form = {
                'key': fields['key'],
                'Policy': fields['Policy'],
                'X-Amz-Algorithm': fields['X-Amz-Algorithm'],
                'X-Amz-Credential': fields['X-Amz-Credential'],
                'X-Amz-Date': fields['X-Amz-Date'],
                'X-Amz-Signature': fields['X-Amz-Signature']
            }
            
            # Prepare the file
            with open(file_path, 'rb') as f:
                files = {
                    'file': (fields['key'], f, 'application/octet-stream')
                }
                
                # Make the upload request
                response = requests.post(
                    url,
                    data=form,
                    files=files
                )
                
                if response.status_code not in [200, 201, 204]:
                    logger.error(f"S3 upload failed with status {response.status_code}")
                    logger.error(f"Response content: {response.content}")
                    return False, f"Upload failed with status {response.status_code}"
                
                return True, "Upload successful"
                
        except Exception as e:
            error_msg = f"Error uploading to S3: {str(e)}"
            logger.error(error_msg)
            return False, error_msg
    
    def upload_csv(self, file_path: str) -> Tuple[bool, str]:
        """Complete upload process including requesting credentials and uploading."""
        # First request upload credentials
        success, upload_data = self.request_upload()
        if not success:
            return False, upload_data.get("error", "Failed to get upload credentials")
        
        # Then upload to S3
        return self.upload_to_s3(file_path, upload_data)
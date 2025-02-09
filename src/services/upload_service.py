import requests
import logging
from typing import Dict, Optional, Tuple
import os
import pandas as pd
import chardet

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

    def detect_file_encoding(self, file_path: str) -> Tuple[bool, str]:
        """Detect the encoding of a file."""
        try:
            with open(file_path, 'rb') as file:
                raw_data = file.read()
                result = chardet.detect(raw_data)
                encoding = result['encoding']
                confidence = result['confidence']
                
                logger.info(f"Detected encoding: {encoding} with confidence: {confidence}")
                return True, f"Encoding: {encoding} (confidence: {confidence})"
        except Exception as e:
            return False, f"Error detecting encoding: {str(e)}"

    def verify_utf8_encoding(self, file_path: str) -> Tuple[bool, str]:
        """Verify if file is UTF-8 encoded."""
        try:
            with open(file_path, 'rb') as file:
                content = file.read()
                # Try to decode as UTF-8
                content.decode('utf-8')
                return True, "File is UTF-8 encoded"
        except UnicodeDecodeError as e:
            return False, f"File is not UTF-8 encoded: {str(e)}"
        except Exception as e:
            return False, f"Error checking encoding: {str(e)}"

    def convert_excel_to_csv(self, file_path: str) -> Tuple[bool, str]:
        """Convert Excel file to UTF-8 CSV."""
        try:
            # Create temp CSV file path
            csv_path = f"{os.path.splitext(file_path)[0]}_utf8.csv"
            
            # Read Excel file
            df = pd.read_excel(file_path)
            
            # Save as UTF-8 CSV with BOM
            df.to_csv(csv_path, index=False, encoding='utf-8-sig')
            
            # Verify the encoding
            is_utf8, msg = self.verify_utf8_encoding(csv_path)
            if not is_utf8:
                return False, msg
                
            return True, csv_path
        except Exception as e:
            error_msg = f"Error converting Excel to CSV: {str(e)}"
            logger.error(error_msg)
            return False, error_msg

    def upload_to_s3(self, file_path: str, upload_data: Dict) -> Tuple[bool, str]:
        """Upload file to S3 using provided credentials."""
        csv_path = None
        try:
            if not os.path.exists(file_path):
                return False, "File does not exist"

            # Check original file encoding
            success, msg = self.detect_file_encoding(file_path)
            if success:
                logger.info(f"Original file: {msg}")

            # Convert Excel to CSV if needed
            if file_path.endswith(('.xlsx', '.xls')):
                success, result = self.convert_excel_to_csv(file_path)
                if not success:
                    return False, result
                csv_path = result
            else:
                # For CSV files, ensure UTF-8 encoding
                df = pd.read_csv(file_path)
                csv_path = f"{os.path.splitext(file_path)[0]}_utf8.csv"
                df.to_csv(csv_path, index=False, encoding='utf-8-sig')

            # Verify final file encoding
            is_utf8, msg = self.verify_utf8_encoding(csv_path)
            if not is_utf8:
                return False, msg
            logger.info(f"Final file encoding verification: {msg}")

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

            # Read and upload the file
            with open(csv_path, 'rb') as f:
                files = {
                    'file': (fields['key'], f, 'text/csv; charset=utf-8')
                }

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
        finally:
            # Clean up temporary CSV file
            if csv_path and os.path.exists(csv_path):
                try:
                    os.remove(csv_path)
                except Exception as e:
                    logger.error(f"Error removing temporary CSV file: {str(e)}")

    def upload_csv(self, file_path: str) -> Tuple[bool, str]:
        """Complete upload process including requesting credentials and uploading."""
        # First request upload credentials
        success, upload_data = self.request_upload()
        if not success:
            return False, upload_data.get("error", "Failed to get upload credentials")

        # Then upload to S3
        return self.upload_to_s3(file_path, upload_data)
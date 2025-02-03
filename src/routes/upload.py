from flask import Blueprint, jsonify, render_template, request, current_app
import os

from flask_login import login_required

from ..services import UploadService

bp = Blueprint('upload', __name__)

def get_upload_service():
    return UploadService(
        current_app.config['STORE_API_BASE_URL'],
        current_app.config['STORE_API_KEY'],
        current_app.config['COMPANY_ID']
    )

@bp.route('/upload')
@login_required
def upload_page():
    return render_template('upload.html')

@bp.route('/api/upload', methods=['POST'])
@login_required
def manual_upload():
    try:
        if 'file' not in request.files:
            return jsonify({
                "status": "error",
                "message": "No file provided"
            }), 400
            
        file = request.files['file']
        if not file.filename.endswith(('.csv', '.xlsx', '.xls')):
            return jsonify({
                "status": "error",
                "message": "Invalid file format"
            }), 400
            
        # Save file temporarily
        temp_path = os.path.join(current_app.config['OUTPUT_FILE_DIR'], file.filename)
        file.save(temp_path)
        
        # Upload file
        upload_service = get_upload_service()
        success, message = upload_service.upload_csv(temp_path)
        
        # Clean up temp file
        os.remove(temp_path)
        
        if success:
            return jsonify({
                "status": "success",
                "message": message
            })
        else:
            return jsonify({
                "status": "error",
                "message": message
            }), 400
            
    except Exception as e:
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500

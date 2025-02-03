# src/models/database.py
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.sql import func
from datetime import datetime

db = SQLAlchemy()

class Event(db.Model):
    __tablename__ = 'events'
    
    id = db.Column(db.Integer, primary_key=True)
    event_id = db.Column(db.String(255), nullable=False, unique=True)  # Add this line
    event_name = db.Column(db.String(255), nullable=False)
    city_id = db.Column(db.Integer, nullable=False)
    start_date = db.Column(db.Date, nullable=False)
    end_date = db.Column(db.Date, nullable=False)
    markup = db.Column(db.Float, nullable=False, default=1.6)
    created_at = db.Column(db.DateTime, server_default=func.now())
    updated_at = db.Column(db.DateTime, server_default=func.now(), onupdate=func.now())
    
    def to_dict(self):
        from ..constants import CITY_URL_MAP
        city_name = None
        for city, cid in CITY_URL_MAP.items():
            if cid == self.city_id:
                city_name = city
                break
                
        return {
            'id': self.id,
            'event_id': self.event_id,  # Add this line
            'event_name': self.event_name,
            'city_id': self.city_id,
            'city': city_name or 'Unknown',
            'start_date': self.start_date.isoformat() if self.start_date else None,
            'end_date': self.end_date.isoformat() if self.end_date else None,
            'markup': self.markup,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None
        }

    @property
    def city_name(self):
        """Helper property to get city name directly"""
        from ..constants import CITY_URL_MAP
        for city, cid in CITY_URL_MAP.items():
            if cid == self.city_id:
                return city
        return 'Unknown'
    
class ScraperJob(db.Model):
    __tablename__ = 'scraper_jobs'
    
    id = db.Column(db.Integer, primary_key=True)
    status = db.Column(db.String(50), nullable=False)
    interval_minutes = db.Column(db.Integer, nullable=False)
    last_run = db.Column(db.DateTime)
    next_run = db.Column(db.DateTime)
    events_processed = db.Column(db.Integer, default=0)
    total_tickets_found = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, server_default=func.now())
    updated_at = db.Column(db.DateTime, server_default=func.now(), onupdate=func.now())
    
    def to_dict(self):
        return {
            'id': self.id,
            'status': self.status,
            'interval_minutes': self.interval_minutes,
            'last_run': self.last_run.isoformat() if self.last_run else None,
            'next_run': self.next_run.isoformat() if self.next_run else None,
            'events_processed': self.events_processed,
            'total_tickets_found': self.total_tickets_found,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None
        }
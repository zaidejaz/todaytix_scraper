from flask import Blueprint, request, jsonify, render_template, redirect, url_for, flash
from ..models.database import db, Event, EventRule
from flask_login import login_required

rules_bp = Blueprint('rules', __name__)

VALID_RULE_TYPES = ['even', 'odd', 'consecutive']
RULE_DESCRIPTIONS = {
    'even': 'Keyword for selecting even-numbered seats',
    'odd': 'Keyword for selecting odd-numbered seats',
    'consecutive': 'Keyword for selecting consecutive seats'
}

@rules_bp.route('/events/<int:event_id>/rules')
@login_required
def event_rules(event_id):
    event = Event.query.get_or_404(event_id)
    rules = {rule_type: next((rule for rule in event.rules if rule.rule_type == rule_type), None)
            for rule_type in VALID_RULE_TYPES}
    return render_template('event_rules.html', 
                         event=event, 
                         rules=rules, 
                         descriptions=RULE_DESCRIPTIONS)

@rules_bp.route('/events/<int:event_id>/rules/<rule_type>', methods=['POST'])
@login_required
def manage_rule(event_id, rule_type):
    if rule_type not in VALID_RULE_TYPES:
        return jsonify({'error': 'Invalid rule type'}), 400
    
    event = Event.query.get_or_404(event_id)
    keyword = request.form.get('keyword', '').strip()
    
    if not keyword:
        return jsonify({'error': 'Keyword is required'}), 400
    
    rule = EventRule.query.filter_by(event_id=event_id, rule_type=rule_type).first()
    
    if rule:
        rule.keyword = keyword
    else:
        rule = EventRule(
            event_id=event_id,
            rule_type=rule_type,
            keyword=keyword
        )
        db.session.add(rule)
        
    try:
        db.session.commit()
        return jsonify({'success': True})
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500

@rules_bp.route('/events/<int:event_id>/rules/<rule_type>', methods=['DELETE'])
@login_required
def delete_rule(event_id, rule_type):
    if rule_type not in VALID_RULE_TYPES:
        return jsonify({'error': 'Invalid rule type'}), 400
    
    rule = EventRule.query.filter_by(event_id=event_id, rule_type=rule_type).first()
    if rule:
        try:
            db.session.delete(rule)
            db.session.commit()
            return jsonify({'success': True})
        except Exception as e:
            db.session.rollback()
            return jsonify({'error': str(e)}), 500
    
    return jsonify({'error': 'Rule not found'}), 404
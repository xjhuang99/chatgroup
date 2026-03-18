# 文件名: models.py
from datetime import datetime
from flask_login import UserMixin
from extensions import db  # 注意：是从 extensions 导入 db

# --- 数据库模型 ---

class SessionLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    session_code = db.Column(db.String(10), unique=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.now)
    admin_id = db.Column(db.String(50))

class ChatRecord(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    session_code = db.Column(db.String(10))
    match_id = db.Column(db.String(50))
    sender = db.Column(db.String(50))
    message = db.Column(db.Text)
    scope = db.Column(db.String(10))
    timestamp = db.Column(db.DateTime, default=datetime.now)

class GameResult(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    session_code = db.Column(db.String(10))
    match_id = db.Column(db.String(50))
    round_num = db.Column(db.Integer)
    team_a = db.Column(db.String(50))
    team_b = db.Column(db.String(50))
    move_a = db.Column(db.String(10))
    move_b = db.Column(db.String(10))
    score_a = db.Column(db.Float)
    score_b = db.Column(db.Float)
    timestamp = db.Column(db.DateTime, default=datetime.now)

# AdminUser 虽然不是数据库模型，但放在这里统一管理数据结构也很合适
class AdminUser(UserMixin):
    def __init__(self, id):
        self.id = id
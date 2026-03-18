# 文件名: extensions.py
from flask_sqlalchemy import SQLAlchemy

# 初始化数据库实例，但暂时不绑定 app
db = SQLAlchemy()
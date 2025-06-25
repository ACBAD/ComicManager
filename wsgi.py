import sys
import os

# 添加项目目录到 sys.path
sys.path.insert(0, '/var/www/comic')

# 导入 Flask 应用
from app import app as application


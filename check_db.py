# Run:  python check_db.py   -> prints every registered user
from app import app
from models import User

with app.app_context():
    users = User.query.all()
    if not users:
        print("No users yet.")
    for u in users:
        print(u.id, u.username, u.email)

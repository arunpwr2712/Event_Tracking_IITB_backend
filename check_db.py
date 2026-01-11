from database import SessionLocal
from models import Lab, Group, GroupLabAssignment

if __name__ == '__main__':
    db = SessionLocal()
    print('Labs:', db.query(Lab).count())
    print('Groups:', db.query(Group).count())
    print('Assignments:', db.query(GroupLabAssignment).count())
    db.close()
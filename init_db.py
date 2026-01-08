import os
from database import engine, SessionLocal
from models import Base, Lab, Group, GroupLabAssignment

# Remove old DB if present so schema changes take effect
if os.path.exists("./event.db"):
    os.remove("./event.db")

Base.metadata.create_all(bind=engine)

db = SessionLocal()

# Create 12 labs with names
for i in range(1, 13):
    db.add(Lab(lab_id=i, name=f"Lab {i}", status="FREE"))

# Create 20 groups (volunteers)
for i in range(1, 21):
    db.add(Group(group_id=i, volunteer_name=f"Volunteer {i}", state="WAITING"))

db.commit()

# By default assign all labs to all groups so behavior remains as before
labs = db.query(Lab).all()
groups = db.query(Group).all()
for g in groups:
    for lab in labs:
        db.add(GroupLabAssignment(group_id=g.group_id, lab_id=lab.lab_id))

db.commit()
db.close()

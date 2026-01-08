from sqlalchemy import Column, Integer, String, DateTime, ForeignKey
from database import Base

class Lab(Base):
    __tablename__ = "labs"

    lab_id = Column(Integer, primary_key=True)
    name = Column(String, default=None)
    status = Column(String)
    occupied_by = Column(Integer, nullable=True)

class Group(Base):
    __tablename__ = "groups"

    group_id = Column(Integer, primary_key=True)
    volunteer_name = Column(String, default=None)
    state = Column(String)
    current_lab = Column(Integer, nullable=True)
    entered_at = Column(DateTime, nullable=True)
    expected_exit_at = Column(DateTime, nullable=True)
    alarm_8_sent = Column(Integer, default=0)
    alarm_10_sent = Column(Integer, default=0)

class GroupLabAssignment(Base):
    __tablename__ = "group_lab_assignments"

    id = Column(Integer, primary_key=True)
    group_id = Column(Integer, ForeignKey("groups.group_id"))
    lab_id = Column(Integer, ForeignKey("labs.lab_id"))

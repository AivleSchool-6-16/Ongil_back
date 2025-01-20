from sqlalchemy import Column, String
from app.db.database import Base

class User(Base):
    __tablename__ = "user" 

    email = Column(String, primary_key=True, index=True)
    password = Column(String, nullable=False)
    name = Column(String, nullable=False)
    department = Column(String, nullable=False)
    mgmt_area = Column(String, nullable=False)
    

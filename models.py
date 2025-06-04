from sqlalchemy.orm import declarative_base, relationship
from sqlalchemy import Column, Integer, String, BigInteger, ForeignKey, Text, DateTime
from sqlalchemy.sql import func

Base = declarative_base()


class ProcessingStyle(Base):
    __tablename__ = 'processing_styles'
    id = Column(Integer, primary_key=True)
    style_name = Column(String(100), unique=True, nullable=False)
    description = Column(Text)

    def __repr__(self):
        return f"<ProcessingStyle(id={self.id}, name='{self.style_name}')>"


class TaskStatus(Base):
    __tablename__ = 'task_statuses'
    id = Column(Integer, primary_key=True)
    status_name = Column(String(50), unique=True, nullable=False)
    display_order = Column(Integer, default=0)  

    def __repr__(self):
        return f"<TaskStatus(id={self.id}, name='{self.status_name}')>"

class User(Base):
    __tablename__ = 'users'
    id = Column(Integer, primary_key=True)
    telegram_id = Column(BigInteger, unique=True)
    username = Column(String(255))
    first_name = Column(String(255))
    last_name = Column(String(255))
    created_at = Column(DateTime, server_default=func.now())

    uploads = relationship("Upload", back_populates="user", cascade="all, delete")
    tasks = relationship("VideoTask", back_populates="user", cascade="all, delete")

class Upload(Base):
    __tablename__ = 'uploads'
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'))
    file_id = Column(String(512), nullable=False)
    upload_time = Column(DateTime, server_default=func.now())
    is_photo = Column(String(255))

    user = relationship("User", back_populates="uploads")
    task_images = relationship("TaskImage", back_populates="upload")

class VideoTask(Base):
    __tablename__ = 'video_tasks'
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'))
    status_id = Column(Integer, ForeignKey('task_statuses.id'))
    style_id = Column(Integer, ForeignKey('processing_styles.id'))
    created_at = Column(DateTime, server_default=func.now())
    completed_at = Column(DateTime)
    result_path = Column(String(512))

    user = relationship("User", back_populates="tasks")
    status = relationship("TaskStatus")
    style = relationship("ProcessingStyle")
    images = relationship("TaskImage", back_populates="task")

class TaskImage(Base):
    __tablename__ = 'task_images'
    id = Column(Integer, primary_key=True)
    task_id = Column(Integer, ForeignKey('video_tasks.id'))
    upload_id = Column(Integer, ForeignKey('uploads.id'))
    order_index = Column(Integer, nullable=False)

    task = relationship("VideoTask", back_populates="images")
    upload = relationship("Upload", back_populates="task_images")

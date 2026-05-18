from datetime import datetime
from sqlalchemy import ForeignKey, String, Float, DateTime, Integer
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from typing import List


class Base(DeclarativeBase):
    pass


class Teacher(Base):
    __tablename__ = "teachers"

    id: Mapped[int] = mapped_column(primary_key=True)
    teacher_id: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    department: Mapped[str] = mapped_column(String(100), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    courses: Mapped[List["CourseOffering"]] = relationship(back_populates="teacher")

    def __repr__(self) -> str:
        return f"<Teacher(id={self.id}, name={self.name})>"


class Student(Base):
    __tablename__ = "students"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    student_id: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)
    enrollment_date: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    enrollments: Mapped[List["Enrollment"]] = relationship(back_populates="student")

    def __repr__(self) -> str:
        return f"<Student(id={self.id}, name={self.name})>"


class Course(Base):
    __tablename__ = "courses"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(String(1000), nullable=True)
    credits: Mapped[int] = mapped_column(Integer, nullable=False)

    offerings: Mapped[List["CourseOffering"]] = relationship(back_populates="course")

    def __repr__(self) -> str:
        return f"<Course(id={self.id}, code={self.code})>"


class CourseOffering(Base):
    __tablename__ = "course_offerings"

    id: Mapped[int] = mapped_column(primary_key=True)
    course_id: Mapped[int] = mapped_column(ForeignKey("courses.id"), nullable=False)
    teacher_id: Mapped[int] = mapped_column(ForeignKey("teachers.id"), nullable=False)
    semester: Mapped[str] = mapped_column(String(20), nullable=False)
    year: Mapped[int] = mapped_column(Integer, nullable=False)
    max_students: Mapped[int] = mapped_column(Integer, nullable=False)

    course: Mapped["Course"] = relationship(back_populates="offerings")
    teacher: Mapped["Teacher"] = relationship(back_populates="courses")
    enrollments: Mapped[List["Enrollment"]] = relationship(back_populates="course_offering")

    def __repr__(self) -> str:
        return f"<CourseOffering(id={self.id}, semester={self.semester}, year={self.year})>"


class Enrollment(Base):
    __tablename__ = "enrollments"

    id: Mapped[int] = mapped_column(primary_key=True)
    student_id: Mapped[int] = mapped_column(ForeignKey("students.id"), nullable=False)
    course_offering_id: Mapped[int] = mapped_column(
        ForeignKey("course_offerings.id"), nullable=False
    )
    grade: Mapped[float] = mapped_column(Float, nullable=True)
    enrollment_date: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    student: Mapped["Student"] = relationship(back_populates="enrollments")
    course_offering: Mapped["CourseOffering"] = relationship(back_populates="enrollments")

    def __repr__(self) -> str:
        return f"<Enrollment(student_id={self.student_id}, grade={self.grade})>"

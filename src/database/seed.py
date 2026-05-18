from sqlalchemy.orm import Session
from datetime import datetime
from .models import Teacher, Student, Course, CourseOffering, Enrollment


def seed_database(session: Session, force_reseed: bool = False) -> None:
    """Populate database with sample data.

    Args:
        session: Database session
        force_reseed: If True, clear existing data and reseed (use when changing seed.py)
    """

    if session.query(Teacher).first() is not None and not force_reseed:
        return

    if force_reseed:
        session.query(Enrollment).delete()
        session.query(CourseOffering).delete()
        session.query(Course).delete()
        session.query(Student).delete()
        session.query(Teacher).delete()
        session.commit()

    teachers = [
        Teacher(teacher_id="T001", name="Dr. Alice Johnson", email="alice.johnson@university.edu", department="Computer Science"),
        Teacher(teacher_id="T002", name="Dr. Bob Smith", email="bob.smith@university.edu", department="Computer Science"),
        Teacher(teacher_id="T003", name="Dr. Eve Thompson", email="eve.thompson@university.edu", department="Computer Science"),
        Teacher(teacher_id="T004", name="Dr. Carol Davis", email="carol.davis@university.edu", department="Mathematics"),
        Teacher(teacher_id="T005", name="Dr. David Wilson", email="david.wilson@university.edu", department="Physics"),
    ]

    students = [
        Student(name="Emma Brown", email="emma.brown@student.edu", student_id="S001"),
        Student(name="Frank Garcia", email="frank.garcia@student.edu", student_id="S002"),
        Student(name="Grace Lee", email="grace.lee@student.edu", student_id="S003"),
        Student(name="Henry Chen", email="henry.chen@student.edu", student_id="S004"),
        Student(name="Iris Martinez", email="iris.martinez@student.edu", student_id="S005"),
    ]

    courses = [
        Course(
            code="CS101",
            title="Introduction to Programming",
            description="Learn programming fundamentals with Python",
            credits=3,
        ),
        Course(
            code="CS201",
            title="Algorithms",
            description="Algorithm design",
            credits=4,
        ),
        Course(
            code="MATH101",
            title="Calculus I",
            description="Differential calculus and applications",
            credits=4,
        ),
        Course(
            code="PHYS101",
            title="Physics I",
            description="Mechanics and waves",
            credits=4,
        ),
    ]

    session.add_all(teachers)
    session.add_all(students)
    session.add_all(courses)
    session.flush()

    offerings = [
        CourseOffering(id=1, course_id=1, teacher_id=1, semester="Fall", year=2024, max_students=30),
        CourseOffering(id=2, course_id=1, teacher_id=1, semester="Spring", year=2025, max_students=30),
        CourseOffering(id=3, course_id=2, teacher_id=2, semester="Fall", year=2024, max_students=25),
        CourseOffering(id=4, course_id=3, teacher_id=3, semester="Fall", year=2024, max_students=35),
        CourseOffering(id=5, course_id=4, teacher_id=4, semester="Spring", year=2025, max_students=30),
    ]

    session.add_all(offerings)
    session.flush()

    enrollments = [
        Enrollment(student_id=1, course_offering_id=1, grade=85.5),#
        Enrollment(student_id=1, course_offering_id=3, grade=92.0),
        Enrollment(student_id=2, course_offering_id=1, grade=78.5),#
        Enrollment(student_id=2, course_offering_id=4, grade=88.0),
        Enrollment(student_id=3, course_offering_id=1, grade=95.0),#
        Enrollment(student_id=3, course_offering_id=2, grade=91.5),#
        Enrollment(student_id=4, course_offering_id=3, grade=76.0),
        Enrollment(student_id=4, course_offering_id=4, grade=82.5),
        Enrollment(student_id=5, course_offering_id=2, grade=89.0),#
        Enrollment(student_id=5, course_offering_id=5, grade=87.5),
    ]

    session.add_all(enrollments)
    session.commit()

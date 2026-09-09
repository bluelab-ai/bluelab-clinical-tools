import tempfile
import unittest
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models import Project, User
from app.routers.projects import UpdateTablesRequest, update_tables


class UpdateTablesCompletedProjectTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        self.session = sessionmaker(bind=engine)()

        self.user = User(username="table-update-user", password_hash="unused")
        self.session.add(self.user)
        self.session.flush()

        self.output_dir = Path(self.temp_dir.name) / "project-output"
        self.output_dir.mkdir()
        self.project = Project(
            user_id=self.user.id,
            name="已完成项目",
            sap_filename="sap.pdf",
            sap_path="/tmp/sap.pdf",
            output_dir=str(self.output_dir),
            status="completed",
            phase="completed",
            tables_count=1,
        )
        self.session.add(self.project)
        self.session.commit()

    def tearDown(self):
        self.session.close()
        self.temp_dir.cleanup()

    def test_saving_catalog_does_not_downgrade_completed_project(self):
        update_tables(
            self.project.id,
            UpdateTablesRequest(tables=[]),
            self.session,
            self.user,
        )

        self.session.refresh(self.project)

        self.assertEqual(self.project.status, "completed")
        self.assertEqual(self.project.phase, "completed")

    def test_saving_catalog_keeps_existing_transition_for_unfinished_project(self):
        self.project.phase = "review"
        self.project.status = "running"
        self.session.commit()

        update_tables(
            self.project.id,
            UpdateTablesRequest(tables=[]),
            self.session,
            self.user,
        )

        self.session.refresh(self.project)

        self.assertEqual(self.project.status, "completed")
        self.assertEqual(self.project.phase, "catalog")


if __name__ == "__main__":
    unittest.main()

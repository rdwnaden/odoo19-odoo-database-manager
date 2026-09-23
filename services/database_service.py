import logging
import os
import tempfile

from odoo.service import db


_logger = logging.getLogger(__name__)


class DatabaseService:
    """
    Service wrapper around Odoo native database backup.

    Backup dibuat sebagai temporary file agar tidak menampung
    seluruh file backup di memory/RAM.
    """

    # ==========================================================
    # CREATE BACKUP
    # ==========================================================

    @staticmethod
    def backup_database(
        database_name,
        include_filestore=True,
    ):
        """
        Create an Odoo native database backup.

        Return:
            temporary backup file path

        Example:
            C:\\Users\\...\\Temp\\main_xxxxx.zip
        """

        if not database_name:
            raise ValueError(
                "Database name is required."
            )

        _logger.info(
            "Starting native Odoo database backup: %s",
            database_name,
        )

        temp_file = None

        try:

            # --------------------------------------------------
            # Create temporary file
            # --------------------------------------------------

            fd, temp_file = tempfile.mkstemp(
                prefix=f"{database_name}_",
                suffix=".zip",
            )

            # Close OS handle first.
            # Odoo will open/write the file itself.
            os.close(fd)

            _logger.info(
                "Temporary backup file created: %s",
                temp_file,
            )

            # --------------------------------------------------
            # Create native Odoo backup
            # --------------------------------------------------

            with open(
                temp_file,
                "wb",
            ) as stream:

                db.dump_db(
                    database_name,
                    stream,
                    backup_format="zip",
                    with_filestore=include_filestore,
                )

            # --------------------------------------------------
            # Verify
            # --------------------------------------------------

            if not os.path.isfile(temp_file):

                raise IOError(
                    "Odoo backup file was not created."
                )

            file_size = os.path.getsize(
                temp_file
            )

            if file_size <= 0:

                raise IOError(
                    "Odoo returned an empty backup file."
                )

            _logger.info(
                "Native Odoo database backup completed: "
                "%s (%.2f MB)",
                database_name,
                file_size / (1024 * 1024),
            )

            return temp_file

        except Exception:

            _logger.exception(
                "Native Odoo database backup failed: %s",
                database_name,
            )

            # --------------------------------------------------
            # Cleanup temporary file
            # --------------------------------------------------

            if temp_file and os.path.exists(
                temp_file
            ):

                try:
                    os.remove(temp_file)

                except Exception:

                    _logger.warning(
                        "Unable to remove temporary "
                        "backup file: %s",
                        temp_file,
                    )

            raise

    # ==========================================================
    # REMOVE TEMP FILE
    # ==========================================================

    @staticmethod
    def cleanup_backup(
        file_path,
    ):
        """
        Remove temporary backup file.
        """

        if not file_path:
            return

        try:

            if os.path.exists(
                file_path
            ):

                os.remove(
                    file_path
                )

                _logger.info(
                    "Temporary backup removed: %s",
                    file_path,
                )

        except Exception:

            _logger.warning(
                "Unable to remove temporary backup: %s",
                file_path,
                exc_info=True,
            )
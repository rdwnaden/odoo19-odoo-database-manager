import logging
import os
from calendar import monthrange
from datetime import timedelta

from odoo import api, fields, models

from ..services.database_service import DatabaseService
from ..services.storage_service import StorageService


_logger = logging.getLogger(__name__)


class DatabaseBackup(models.Model):
    _name = 'odoo.database.backup'
    _description = 'Odoo Database Backup'
    _inherit = ["mail.thread","mail.activity.mixin"]
    _order = 'create_date desc'

    name = fields.Char(string='Backup Job', required=True, default='New Backup', tracking=True)
    database_name = fields.Char(string='Database', tracking=True, required=True, default=lambda self: self.env.cr.dbname)
    active = fields.Boolean(string='Active', default=True)
    include_filestore = fields.Boolean(string='Include Filestore', default=True, tracking=True)
    storage_id = fields.Many2one('odoo.database.storage', string='Service', required=True, tracking=True, ondelete='restrict', domain=[('active', '=', True)])
    schedule_type = fields.Selection(
        selection=[
            ('manual', 'Manual'),
            ('3_minutes', 'Every 3 Minutes'),
            ('hourly', 'Hourly'),
            ('daily', 'Daily'),
            ('weekly', 'Weekly'),
            ('monthly', 'Monthly'),
        ],
        string='Schedule',
        default='manual',
        required=True,
        tracking=True,
    )

    schedule_hour = fields.Integer(string='Hour', default=0, help='Hour of execution, from 0 to 23.')
    schedule_minute = fields.Integer(string='Minute', default=0, help='Minute of execution, from 0 to 59.')
    schedule_weekday = fields.Selection(
        selection=[
            ('0', 'Monday'),
            ('1', 'Tuesday'),
            ('2', 'Wednesday'),
            ('3', 'Thursday'),
            ('4', 'Friday'),
            ('5', 'Saturday'),
            ('6', 'Sunday'),
        ],
        string='Weekday',
        default='0',
    )

    schedule_day = fields.Integer(string='Day of Month', default=1, help='Day of month from 1 to 31.')
    last_run = fields.Datetime(string='Last Run', readonly=True)
    next_run = fields.Datetime(string='Next Run', readonly=True)
    state = fields.Selection(
        selection=[
            ('draft', 'Draft'),
            ('queued', 'Queued'),
            ('running', 'Running'),
            ('done', 'Done'),
            ('failed', 'Failed'),
        ],
        string='Status',
        default='draft',
        required=True,
    )

    backup_date = fields.Datetime(string='Last Backup', readonly=True)
    error_message = fields.Text(string='Error', readonly=True)
    backup_file_ids = fields.One2many('odoo.database.backup.file', 'backup_id', string='Backup Files')
    backup_count = fields.Integer(string='Backup Count', compute='_compute_backup_count')

    @api.depends('backup_file_ids')
    def _compute_backup_count(self):
        for record in self:
            record.backup_count = len(
                record.backup_file_ids
            )

    @api.constrains(
        'schedule_hour',
        'schedule_minute',
        'schedule_day',
    )
    def _check_schedule_values(self):
        for record in self:

            if not 0 <= record.schedule_hour <= 23:
                raise ValueError(
                    'Hour must be between 0 and 23.'
                )

            if not 0 <= record.schedule_minute <= 59:
                raise ValueError(
                    'Minute must be between 0 and 59.'
                )

            if not 1 <= record.schedule_day <= 31:
                raise ValueError(
                    'Day of Month must be between 1 and 31.'
                )

    # ==========================================================
    # MANUAL START
    # ==========================================================

    def action_start(self):
        """
        Queue backup for background processing.

        The actual backup and upload are handled
        by the Odoo cron process.
        """

        self.ensure_one()

        if self.state in (
            'queued',
            'running',
        ):

            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Backup Already Running',
                    'message': (
                        'This backup job is already queued '
                        'or running.'
                    ),
                    'type': 'warning',
                    'sticky': False,
                },
            }

        if not self.database_name:

            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Backup Error',
                    'message': (
                        'Database name is required.'
                    ),
                    'type': 'danger',
                    'sticky': True,
                },
            }

        if not self.storage_id:

            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Backup Error',
                    'message': (
                        'Please select a storage service.'
                    ),
                    'type': 'danger',
                    'sticky': True,
                },
            }

        # ------------------------------------------------------
        # Queue job
        # ------------------------------------------------------

        self.write({
            'state': 'queued',
            'error_message': False,
        })

        self.env.cr.commit()

        _logger.info(
            'Manual backup queued. '
            'Job=%s ID=%s Database=%s Storage=%s',
            self.name,
            self.id,
            self.database_name,
            self.storage_id.name,
        )

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Backup Queued',
                'message': (
                    'Backup has been queued and will be '
                    'processed in the background.'
                ),
                'type': 'success',
                'sticky': False,
            },
        }

    # ==========================================================
    # EXECUTE BACKUP
    # ==========================================================

    def _execute_backup(self):
        """
        Execute backup in background.

        IMPORTANT:

        - DatabaseService creates the backup as a filesystem file.
        - The file is streamed directly to storage.
        - The ZIP is NEVER loaded into PostgreSQL/base64.
        - Temporary backup is deleted after upload.
        """

        self.ensure_one()

        database_name = self.database_name
        backup_path = None
        filename = None

        # ------------------------------------------------------
        # Prevent duplicate execution
        # ------------------------------------------------------

        if self.state == 'running':

            _logger.warning(
                'Backup already running. '
                'Skipping duplicate execution. '
                'Job=%s ID=%s',
                self.name,
                self.id,
            )

            return False

        # ------------------------------------------------------
        # Mark running
        # ------------------------------------------------------

        self.write({
            'state': 'running',
            'error_message': False,
        })

        self.env.cr.commit()

        try:

            # ==================================================
            # VALIDATION
            # ==================================================

            if not database_name:

                raise ValueError(
                    'Database name is required.'
                )

            if not self.storage_id:

                raise ValueError(
                    'Please select a storage service.'
                )

            _logger.info(
                'Starting background backup. '
                'Job=%s ID=%s Database=%s Storage=%s',
                self.name,
                self.id,
                database_name,
                self.storage_id.name,
            )

            # ==================================================
            # 1. CREATE NATIVE ODOO BACKUP
            # ==================================================

            _logger.info(
                'Creating native Odoo database backup. '
                'Database=%s IncludeFilestore=%s',
                database_name,
                self.include_filestore,
            )

            backup_result = (
                DatabaseService.backup_database(
                    database_name=database_name,
                    include_filestore=self.include_filestore,
                )
            )

            _logger.info(
                'DatabaseService returned type: %s',
                type(backup_result).__name__,
            )

            # ==================================================
            # 2. RESOLVE BACKUP PATH
            # ==================================================

            if isinstance(
                backup_result,
                (str, os.PathLike),
            ):

                backup_path = os.fspath(
                    backup_result
                )

            elif hasattr(
                backup_result,
                'name',
            ):

                backup_path = backup_result.name

                try:

                    backup_result.close()

                except Exception:

                    pass

            else:

                raise TypeError(
                    'DatabaseService must return a '
                    'filesystem path for large backups. '
                    f'Received: '
                    f'{type(backup_result).__name__}'
                )

            _logger.info(
                'Backup path: %s',
                backup_path,
            )

            # ==================================================
            # 3. VERIFY BACKUP FILE
            # ==================================================

            if not backup_path:

                raise ValueError(
                    'DatabaseService returned an empty '
                    'backup path.'
                )

            if not os.path.isfile(
                backup_path
            ):

                raise FileNotFoundError(
                    'Backup file does not exist: '
                    f'{backup_path}'
                )

            backup_size = os.path.getsize(
                backup_path
            )

            if backup_size <= 0:

                raise ValueError(
                    'Backup file is empty: '
                    f'{backup_path}'
                )

            file_size_mb = (
                backup_size
                / (1024 * 1024)
            )

            file_size_gb = (
                backup_size
                / (1024 * 1024 * 1024)
            )

            _logger.info(
                'Native Odoo backup completed. '
                'Path=%s Size=%.2f MB (%.2f GB)',
                backup_path,
                file_size_mb,
                file_size_gb,
            )

            # ==================================================
            # 4. CREATE FINAL FILENAME
            # ==================================================

            timestamp = (
                fields.Datetime.now()
                .strftime('%Y%m%d_%H%M%S')
            )

            filename = (
                f'{database_name}_{timestamp}.zip'
            )

            _logger.info(
                'Final backup filename: %s',
                filename,
            )

            # ==================================================
            # 5. UPLOAD TO STORAGE
            # ==================================================

            _logger.info(
                'Starting storage upload. '
                'Storage=%s Type=%s '
                'File=%s Size=%.2f MB',
                self.storage_id.name,
                self.storage_id.service_type,
                backup_path,
                file_size_mb,
            )

            # --------------------------------------------------
            # IMPORTANT
            #
            # StorageService handles streaming.
            #
            # The entire 1+ GB ZIP is NOT loaded into RAM.
            # --------------------------------------------------

            upload_result = StorageService.upload(
                storage=self.storage_id,
                filename=filename,
                file_path=backup_path,
            )

            if upload_result is not True:

                raise IOError(
                    'Storage upload did not return '
                    'a successful result.'
                )

            _logger.info(
                'Storage upload completed successfully. '
                'Filename=%s',
                filename,
            )

            # ==================================================
            # 6. CREATE LIGHTWEIGHT BACKUP LOG
            # ==================================================

            self.env[
                'odoo.database.backup.file'
            ].create({
                'backup_id': self.id,
                'backup_filename': filename,
                'file_size': file_size_mb,
                'media': self.storage_id.service_type,
                'state': 'success',
            })

            _logger.info(
                'Backup log created. '
                'Job=%s Filename=%s Size=%.2f MB',
                self.id,
                filename,
                file_size_mb,
            )

            # ==================================================
            # 7. UPDATE JOB
            # ==================================================

            now = fields.Datetime.now()

            self.write({
                'state': 'done',
                'backup_date': now,
                'last_run': now,
                'error_message': False,
            })

            self._calculate_next_run(
                from_datetime=now
            )

            self.env.cr.commit()

            _logger.info(
                'Background backup completed successfully. '
                'Job=%s ID=%s Database=%s '
                'Filename=%s Size=%.2f MB',
                self.name,
                self.id,
                database_name,
                filename,
                file_size_mb,
            )

            return True

        except Exception as error:

            _logger.exception(
                'Background backup failed. '
                'Job=%s ID=%s Database=%s',
                self.name,
                self.id,
                database_name,
            )

            now = fields.Datetime.now()

            try:

                self.write({
                    'state': 'failed',
                    'error_message': str(error),
                    'backup_date': now,
                    'last_run': now,
                })

                self._calculate_next_run(
                    from_datetime=now
                )

                self.env.cr.commit()

            except Exception:

                _logger.exception(
                    'Failed to update backup job '
                    'after backup error. '
                    'Job=%s ID=%s',
                    self.name,
                    self.id,
                )

            return False

        finally:

            # ==================================================
            # DELETE TEMPORARY BACKUP
            # ==================================================

            if backup_path:

                try:

                    if os.path.isfile(
                        backup_path
                    ):

                        temp_size = os.path.getsize(
                            backup_path
                        )

                        os.remove(
                            backup_path
                        )

                        _logger.info(
                            'Temporary backup file deleted. '
                            'Path=%s Size=%.2f MB',
                            backup_path,
                            temp_size / (1024 * 1024),
                        )

                except Exception:

                    _logger.exception(
                        'Failed to delete temporary '
                        'backup file: %s',
                        backup_path,
                    )

    # ==========================================================
    # GLOBAL SCHEDULER
    # ==========================================================

    @api.model
    def _cron_process_scheduled_backups(self):
        """
        Global backup scheduler.

        Cron should run every minute.

        Handles:

        1. Manually queued backups.
        2. Scheduled backups.
        """

        now = fields.Datetime.now()

        BackupModel = self.sudo()

        _logger.info(
            'Database Backup Scheduler started.'
        )

        # ======================================================
        # 1. PROCESS MANUAL QUEUED JOBS
        # ======================================================

        queued_jobs = BackupModel.search(
            [
                ('state', '=', 'queued'),
                ('active', '=', True),
            ],
            order='create_date asc',
        )

        _logger.info(
            'Queued backup jobs found: %s',
            len(queued_jobs),
        )

        for job in queued_jobs:

            try:

                _logger.info(
                    'Processing queued backup. '
                    'Job=%s ID=%s Database=%s',
                    job.name,
                    job.id,
                    job.database_name,
                )

                job._execute_backup()

            except Exception:

                _logger.exception(
                    'Queued backup failed unexpectedly. '
                    'Job=%s ID=%s',
                    job.name,
                    job.id,
                )

        # ======================================================
        # 2. PROCESS SCHEDULED JOBS
        # ======================================================

        jobs = BackupModel.search(
            [
                ('active', '=', True),
                ('schedule_type', '!=', 'manual'),
                (
                    'state',
                    'not in',
                    ['queued', 'running'],
                ),
            ]
        )

        _logger.info(
            'Scheduled backup jobs found: %s',
            len(jobs),
        )

        for job in jobs:

            try:

                due = job._is_backup_due(
                    now
                )

                _logger.info(
                    'Backup due check. '
                    'Job=%s ID=%s Schedule=%s '
                    'LastRun=%s NextRun=%s Due=%s',
                    job.name,
                    job.id,
                    job.schedule_type,
                    job.last_run,
                    job.next_run,
                    due,
                )

                if not due:

                    continue

                _logger.info(
                    'Scheduled backup triggered. '
                    'Job=%s ID=%s Database=%s '
                    'Storage=%s',
                    job.name,
                    job.id,
                    job.database_name,
                    job.storage_id.name
                    if job.storage_id
                    else 'None',
                )

                job._execute_backup()

            except Exception:

                _logger.exception(
                    'Scheduled backup failed. '
                    'Job=%s ID=%s Database=%s',
                    job.name,
                    job.id,
                    job.database_name,
                )

        _logger.info(
            'Database Backup Scheduler finished.'
        )

        return True

    # ==========================================================
    # CHECK WHETHER BACKUP IS DUE
    # ==========================================================

    def _is_backup_due(self, now):

        self.ensure_one()

        if not self.active:

            return False

        if self.schedule_type == 'manual':

            return False

        if self.state in (
            'queued',
            'running',
        ):

            return False

        # ======================================================
        # EVERY 3 MINUTES
        # ======================================================

        if self.schedule_type == '3_minutes':

            if not self.last_run:

                return True

            elapsed = (
                now - self.last_run
            ).total_seconds()

            return elapsed >= 180

        # ======================================================
        # HOURLY
        # ======================================================

        if self.schedule_type == 'hourly':

            if not self.last_run:

                return True

            elapsed = (
                now - self.last_run
            ).total_seconds()

            return elapsed >= 3600

        # ======================================================
        # DAILY
        # ======================================================

        if self.schedule_type == 'daily':

            if not self.last_run:

                return (
                    now.hour == self.schedule_hour
                    and now.minute
                    >= self.schedule_minute
                )

            if now.date() == self.last_run.date():

                return False

            return (
                now.hour == self.schedule_hour
                and now.minute
                >= self.schedule_minute
            )

        # ======================================================
        # WEEKLY
        # ======================================================

        if self.schedule_type == 'weekly':

            if (
                str(now.weekday())
                != self.schedule_weekday
            ):

                return False

            if not self.last_run:

                return (
                    now.hour == self.schedule_hour
                    and now.minute
                    >= self.schedule_minute
                )

            if now.date() == self.last_run.date():

                return False

            return (
                now.hour == self.schedule_hour
                and now.minute
                >= self.schedule_minute
            )

        # ======================================================
        # MONTHLY
        # ======================================================

        if self.schedule_type == 'monthly':

            target_day = min(
                self.schedule_day,
                monthrange(
                    now.year,
                    now.month,
                )[1],
            )

            if now.day != target_day:

                return False

            if not self.last_run:

                return (
                    now.hour == self.schedule_hour
                    and now.minute
                    >= self.schedule_minute
                )

            if (
                now.year == self.last_run.year
                and now.month == self.last_run.month
            ):

                return False

            return (
                now.hour == self.schedule_hour
                and now.minute
                >= self.schedule_minute
            )

        return False

    # ==========================================================
    # CALCULATE NEXT RUN
    # ==========================================================

    def _calculate_next_run(
        self,
        from_datetime=None,
    ):

        self.ensure_one()

        if self.schedule_type == 'manual':

            self.write({
                'next_run': False,
            })

            return False

        if from_datetime is None:

            from_datetime = (
                fields.Datetime.now()
            )

        # ======================================================
        # EVERY 3 MINUTES
        # ======================================================

        if self.schedule_type == '3_minutes':

            next_run = (
                from_datetime
                + timedelta(minutes=3)
            )

        # ======================================================
        # HOURLY
        # ======================================================

        elif self.schedule_type == 'hourly':

            next_run = (
                from_datetime
                + timedelta(hours=1)
            )

        # ======================================================
        # DAILY
        # ======================================================

        elif self.schedule_type == 'daily':

            next_run = (
                from_datetime
                + timedelta(days=1)
            ).replace(
                hour=self.schedule_hour,
                minute=self.schedule_minute,
                second=0,
                microsecond=0,
            )

        # ======================================================
        # WEEKLY
        # ======================================================

        elif self.schedule_type == 'weekly':

            target_weekday = int(
                self.schedule_weekday
            )

            days_ahead = (
                target_weekday
                - from_datetime.weekday()
            ) % 7

            if days_ahead == 0:

                days_ahead = 7

            next_run = (
                from_datetime
                + timedelta(days=days_ahead)
            ).replace(
                hour=self.schedule_hour,
                minute=self.schedule_minute,
                second=0,
                microsecond=0,
            )

        # ======================================================
        # MONTHLY
        # ======================================================

        elif self.schedule_type == 'monthly':

            year = from_datetime.year
            month = from_datetime.month + 1

            if month > 12:

                month = 1
                year += 1

            max_day = monthrange(
                year,
                month,
            )[1]

            day = min(
                self.schedule_day,
                max_day,
            )

            next_run = from_datetime.replace(
                year=year,
                month=month,
                day=day,
                hour=self.schedule_hour,
                minute=self.schedule_minute,
                second=0,
                microsecond=0,
            )

        else:

            next_run = False

        if next_run:

            self.write({
                'next_run': next_run,
            })

        return next_run

    # ==========================================================
    # ONCHANGE SCHEDULE
    # ==========================================================

    @api.onchange(
        'active',
        'schedule_type',
        'schedule_hour',
        'schedule_minute',
        'schedule_weekday',
        'schedule_day',
    )
    def _onchange_schedule(self):

        for record in self:

            if (
                not record.active
                or record.schedule_type == 'manual'
            ):

                record.next_run = False

                continue

            now = fields.Datetime.now()

            # --------------------------------------------------
            # EVERY 3 MINUTES
            # --------------------------------------------------

            if record.schedule_type == '3_minutes':

                record.next_run = (
                    now + timedelta(minutes=3)
                )

            # --------------------------------------------------
            # HOURLY
            # --------------------------------------------------

            elif record.schedule_type == 'hourly':

                record.next_run = (
                    now + timedelta(hours=1)
                )

            # --------------------------------------------------
            # DAILY
            # --------------------------------------------------

            elif record.schedule_type == 'daily':

                record.next_run = (
                    now + timedelta(days=1)
                ).replace(
                    hour=record.schedule_hour,
                    minute=record.schedule_minute,
                    second=0,
                    microsecond=0,
                )

            # --------------------------------------------------
            # WEEKLY
            # --------------------------------------------------

            elif record.schedule_type == 'weekly':

                target_weekday = int(
                    record.schedule_weekday
                )

                days_ahead = (
                    target_weekday
                    - now.weekday()
                ) % 7

                if days_ahead == 0:

                    days_ahead = 7

                record.next_run = (
                    now + timedelta(days=days_ahead)
                ).replace(
                    hour=record.schedule_hour,
                    minute=record.schedule_minute,
                    second=0,
                    microsecond=0,
                )

            # --------------------------------------------------
            # MONTHLY
            # --------------------------------------------------

            elif record.schedule_type == 'monthly':

                year = now.year
                month = now.month + 1

                if month > 12:

                    month = 1
                    year += 1

                max_day = monthrange(
                    year,
                    month,
                )[1]

                day = min(
                    record.schedule_day,
                    max_day,
                )

                record.next_run = now.replace(
                    year=year,
                    month=month,
                    day=day,
                    hour=record.schedule_hour,
                    minute=record.schedule_minute,
                    second=0,
                    microsecond=0,
                )
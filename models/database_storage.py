import logging

from odoo import api, fields, models


_logger = logging.getLogger(__name__)


class DatabaseStorage(models.Model):
    _name = 'odoo.database.storage'
    _description = 'Database Storage Service'
    _inherit = ["mail.thread","mail.activity.mixin"]
    _order = 'name asc'

    name = fields.Char(string='Name', required=True)
    service_type = fields.Selection(
        selection=[
            ('local', 'Local'),
            ('sftp', 'SFTP'),
            ('ftp', 'FTP'),
            ('nas', 'NAS'),
        ],
        string='Service Type',
        required=True,
        default='local',
        tracking=True,
    )

    active = fields.Boolean(string='Active', default=True)

    # ==========================================================
    # CONNECTION
    # ==========================================================

    host = fields.Char(string='Host', help='Hostname or IP address of the storage server.', tracking=True)
    port = fields.Integer(string='Port', tracking=True)
    username = fields.Char(string='Username', tracking=True)
    password = fields.Char(string='Password')
    remote_path = fields.Char(string='Remote Path', help='Destination directory on the remote server.', tracking=True)
    local_path = fields.Char(string='Local Path', help='Local or network path used for NAS/Local storage.', tracking=True)

    # ==========================================================
    # CONNECTION STATUS
    # ==========================================================

    connection_status = fields.Selection(
        selection=[
            ('unknown', 'Not Tested'),
            ('success', 'Connected'),
            ('failed', 'Failed'),
        ],
        string='Connection Status',
        default='unknown',
        readonly=True,
    )

    connection_message = fields.Text(string='Connection Message', readonly=True)
    last_test_date = fields.Datetime(string='Last Test', readonly=True)

    # ==========================================================
    # DEFAULT PORT
    # ==========================================================

    @api.onchange('service_type')
    def _onchange_service_type(self):
        for record in self:

            if record.service_type == 'sftp':
                record.port = 22

            elif record.service_type == 'ftp':
                record.port = 21

            elif record.service_type == 'local':
                record.port = False

            elif record.service_type == 'nas':
                record.port = False

    # ==========================================================
    # TEST CONNECTION
    # ==========================================================

    def action_test_connection(self):
        self.ensure_one()

        _logger.info(
            'Testing storage connection. '
            'Name=%s Type=%s Host=%s Port=%s',
            self.name,
            self.service_type,
            self.host,
            self.port,
        )

        try:

            # --------------------------------------------------
            # LOCAL
            # --------------------------------------------------

            if self.service_type == 'local':

                if not self.local_path:
                    raise ValueError(
                        'Local Path is required.'
                    )

                import os

                if not os.path.exists(self.local_path):
                    raise ValueError(
                        f'Path does not exist: '
                        f'{self.local_path}'
                    )

                if not os.path.isdir(self.local_path):
                    raise ValueError(
                        f'Path is not a directory: '
                        f'{self.local_path}'
                    )

                message = (
                    'Local storage connection successful.'
                )

            # --------------------------------------------------
            # SFTP
            # --------------------------------------------------

            elif self.service_type == 'sftp':

                if not self.host:
                    raise ValueError(
                        'Host is required.'
                    )

                if not self.port:
                    self.port = 22

                if not self.username:
                    raise ValueError(
                        'Username is required.'
                    )

                if not self.password:
                    raise ValueError(
                        'Password is required.'
                    )

                import paramiko

                ssh = paramiko.SSHClient()

                ssh.set_missing_host_key_policy(
                    paramiko.AutoAddPolicy()
                )

                ssh.connect(
                    hostname=self.host,
                    port=self.port,
                    username=self.username,
                    password=self.password,
                    timeout=10,
                )

                sftp = ssh.open_sftp()

                if self.remote_path:
                    try:
                        sftp.stat(self.remote_path)
                    except IOError:
                        raise ValueError(
                            f'Remote path does not exist: '
                            f'{self.remote_path}'
                        )

                sftp.close()
                ssh.close()

                message = (
                    'SFTP connection successful.'
                )

            # --------------------------------------------------
            # FTP
            # --------------------------------------------------

            elif self.service_type == 'ftp':

                if not self.host:
                    raise ValueError(
                        'Host is required.'
                    )

                if not self.port:
                    self.port = 21

                if not self.username:
                    raise ValueError(
                        'Username is required.'
                    )

                if not self.password:
                    raise ValueError(
                        'Password is required.'
                    )

                from ftplib import FTP

                ftp = FTP()

                ftp.connect(
                    self.host,
                    self.port,
                    timeout=10,
                )

                ftp.login(
                    self.username,
                    self.password,
                )

                if self.remote_path:
                    ftp.cwd(self.remote_path)

                ftp.quit()

                message = (
                    'FTP connection successful.'
                )

            # --------------------------------------------------
            # NAS
            # --------------------------------------------------

            elif self.service_type == 'nas':

                if not self.local_path:
                    raise ValueError(
                        'NAS Path is required.'
                    )

                import os

                if not os.path.exists(self.local_path):
                    raise ValueError(
                        f'NAS path does not exist: '
                        f'{self.local_path}'
                    )

                if not os.path.isdir(self.local_path):
                    raise ValueError(
                        f'NAS path is not a directory: '
                        f'{self.local_path}'
                    )

                message = (
                    'NAS connection successful.'
                )

            else:
                raise ValueError(
                    'Unsupported storage service.'
                )

            # --------------------------------------------------
            # SUCCESS
            # --------------------------------------------------

            self.write({
                'connection_status': 'success',
                'connection_message': message,
                'last_test_date': fields.Datetime.now(),
            })

            _logger.info(
                'Storage connection successful: %s',
                self.name,
            )

            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Connection Successful',
                    'message': message,
                    'type': 'success',
                    'sticky': False,
                },
            }

        except Exception as error:

            message = str(error)

            self.write({
                'connection_status': 'failed',
                'connection_message': message,
                'last_test_date': fields.Datetime.now(),
            })

            _logger.exception(
                'Storage connection failed: %s',
                self.name,
            )

            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Connection Failed',
                    'message': message,
                    'type': 'danger',
                    'sticky': True,
                },
            }
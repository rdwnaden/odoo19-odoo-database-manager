import logging

from odoo import fields, models


_logger = logging.getLogger(__name__)


class DatabaseBackupFile(models.Model):
    _name = 'odoo.database.backup.file'
    _description = 'Database Backup File'
    _order = 'backup_date desc, create_date desc'


    backup_id = fields.Many2one('odoo.database.backup', string='Backup Job', required=True, ondelete='cascade', index=True)
    database_name = fields.Char(string='Database', related='backup_id.database_name', store=True, readonly=True, index=True)
    backup_file = fields.Binary(string='Backup File', attachment=True, readonly=True)
    backup_filename = fields.Char(string='Backup File Name', readonly=True)
    file_size = fields.Float(string='Size (MB)', digits=(16, 2), readonly=True)
    media = fields.Selection(
        selection=[
            ('local', 'Local'),
            ('ftp', 'FTP'),
            ('sftp', 'SFTP'),
            ('nas', 'NAS'),
        ],
        string='Media',
        default='local',
        required=True,
        readonly=True,
    )

    state = fields.Selection(
        selection=[
            ('success', 'Success'),
            ('failed', 'Failed'),
        ],
        string='Status',
        default='success',
        required=True,
        readonly=True,
    )

    backup_date = fields.Datetime(string='Backup Date', readonly=True, default=fields.Datetime.now)
    error_message = fields.Text(string='Error', readonly=True)
    display_name = fields.Char(string='Display Name', compute='_compute_display_name')

    def _compute_display_name(self):
        for record in self:
            record.display_name = (
                record.backup_filename
                or record.database_name
                or 'Backup File'
            )

    def action_download(self):
        self.ensure_one()

        if not self.backup_file:
            return False

        return {
            'type': 'ir.actions.act_url',
            'url': (
                '/odoo_database_manager/backup/download/'
                f'{self.id}'
            ),
            'target': 'self',
        }
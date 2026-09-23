import base64

from odoo import http
from odoo.http import request


class DatabaseBackupDownloadController(http.Controller):

    @http.route(
        '/odoo_database_manager/backup/download/<int:backup_file_id>',
        type='http',
        auth='user',
        methods=['GET'],
    )
    def download_backup(
        self,
        backup_file_id,
        **kwargs,
    ):

        backup_file = request.env[
            'odoo.database.backup.file'
        ].browse(
            backup_file_id
        )

        if not backup_file.exists():
            return request.not_found()

        if not backup_file.backup_file:
            return request.not_found()

        # ------------------------------------------------------
        # Security
        # ------------------------------------------------------

        if not request.env.user.has_group(
            'base.group_system'
        ):
            return request.not_found()

        # ------------------------------------------------------
        # Decode binary
        # ------------------------------------------------------

        file_data = base64.b64decode(
            backup_file.backup_file
        )

        filename = (
            backup_file.backup_filename
            or 'odoo_backup.zip'
        )

        headers = [
            (
                'Content-Type',
                'application/zip',
            ),
            (
                'Content-Disposition',
                f'attachment; filename="{filename}"',
            ),
            (
                'Content-Length',
                str(len(file_data)),
            ),
        ]

        return request.make_response(
            file_data,
            headers=headers,
        )
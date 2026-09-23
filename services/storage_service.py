import logging
import os
import shutil
import socket
from ftplib import FTP


_logger = logging.getLogger(__name__)


class StorageService:
    """
    Handle uploading backup files to configured storage services.

    Supported:
        - Local
        - SFTP
        - FTP
        - NAS

    IMPORTANT:
        Large backup files are always streamed from filesystem.
        The backup ZIP is NEVER loaded entirely into Python memory.
    """

    # ==========================================================
    # CONFIGURATION
    # ==========================================================

    # Progress log interval for large file uploads.
    # 100 MB is useful for monitoring without flooding the log.
    SFTP_PROGRESS_INTERVAL = 100 * 1024 * 1024

    # Connection timeout.
    SFTP_CONNECT_TIMEOUT = 30

    # Socket timeout while transferring large files.
    SFTP_SOCKET_TIMEOUT = 300

    FTP_CONNECT_TIMEOUT = 30

    # ==========================================================
    # MAIN UPLOAD METHOD
    # ==========================================================

    @staticmethod
    def upload(
        storage,
        filename,
        file_path,
    ):
        """
        Upload backup file to configured storage.

        :param storage:
            odoo.database.storage record

        :param filename:
            destination backup filename

        :param file_path:
            local temporary backup file

        :return:
            True
        """

        if not storage:
            raise ValueError(
                "Storage configuration is required."
            )

        if not file_path:
            raise ValueError(
                "Backup file path is required."
            )

        if not os.path.isfile(file_path):
            raise FileNotFoundError(
                f"Backup file not found: {file_path}"
            )

        service_type = storage.service_type

        file_size = os.path.getsize(file_path)

        file_size_mb = (
            file_size / (1024 * 1024)
        )

        _logger.info(
            "Uploading backup. "
            "Storage=%s Type=%s Filename=%s "
            "File=%s Size=%.2f MB",
            storage.name,
            service_type,
            filename,
            file_path,
            file_size_mb,
        )

        # ------------------------------------------------------
        # LOCAL
        # ------------------------------------------------------

        if service_type == "local":

            return StorageService._upload_local(
                storage,
                filename,
                file_path,
            )

        # ------------------------------------------------------
        # SFTP
        # ------------------------------------------------------

        if service_type == "sftp":

            return StorageService._upload_sftp(
                storage,
                filename,
                file_path,
            )

        # ------------------------------------------------------
        # FTP
        # ------------------------------------------------------

        if service_type == "ftp":

            return StorageService._upload_ftp(
                storage,
                filename,
                file_path,
            )

        # ------------------------------------------------------
        # NAS
        # ------------------------------------------------------

        if service_type == "nas":

            return StorageService._upload_nas(
                storage,
                filename,
                file_path,
            )

        raise ValueError(
            f"Unsupported storage service: {service_type}"
        )

    # ==========================================================
    # LOCAL
    # ==========================================================

    @staticmethod
    def _upload_local(
        storage,
        filename,
        file_path,
    ):
        """
        Copy backup to local filesystem.

        This uses shutil.copy2(), which streams the file through
        the operating system and does not load the entire backup
        into Python memory.
        """

        if not storage.local_path:
            raise ValueError(
                "Local Path is required."
            )

        folder = os.path.abspath(
            os.path.expanduser(
                storage.local_path
            )
        )

        os.makedirs(
            folder,
            exist_ok=True,
        )

        destination = os.path.join(
            folder,
            filename,
        )

        _logger.info(
            "Copying backup to local path: %s",
            destination,
        )

        shutil.copy2(
            file_path,
            destination,
        )

        if not os.path.isfile(
            destination
        ):
            raise IOError(
                "Backup file was not created: "
                f"{destination}"
            )

        local_size = os.path.getsize(
            file_path
        )

        remote_size = os.path.getsize(
            destination
        )

        if local_size != remote_size:
            raise IOError(
                "Local upload verification failed. "
                f"Local size={local_size}, "
                f"Destination size={remote_size}"
            )

        _logger.info(
            "Local backup uploaded successfully: %s "
            "Size=%.2f MB",
            destination,
            remote_size / (1024 * 1024),
        )

        return True

    # ==========================================================
    # NAS
    # ==========================================================

    @staticmethod
    def _upload_nas(
        storage,
        filename,
        file_path,
    ):
        """
        Copy backup to mounted NAS filesystem.

        The NAS path must already be mounted and accessible
        from the operating system.
        """

        if not storage.local_path:
            raise ValueError(
                "NAS Path is required."
            )

        folder = os.path.abspath(
            os.path.expanduser(
                storage.local_path
            )
        )

        if not os.path.exists(
            folder
        ):
            raise ValueError(
                f"NAS path does not exist: {folder}"
            )

        if not os.path.isdir(
            folder
        ):
            raise ValueError(
                f"NAS path is not a directory: {folder}"
            )

        destination = os.path.join(
            folder,
            filename,
        )

        _logger.info(
            "Copying backup to NAS: %s",
            destination,
        )

        shutil.copy2(
            file_path,
            destination,
        )

        if not os.path.isfile(
            destination
        ):
            raise IOError(
                "NAS backup file was not created: "
                f"{destination}"
            )

        local_size = os.path.getsize(
            file_path
        )

        remote_size = os.path.getsize(
            destination
        )

        if local_size != remote_size:
            raise IOError(
                "NAS upload verification failed. "
                f"Local size={local_size}, "
                f"Destination size={remote_size}"
            )

        _logger.info(
            "NAS backup uploaded successfully: %s "
            "Size=%.2f MB",
            destination,
            remote_size / (1024 * 1024),
        )

        return True

    # ==========================================================
    # SFTP
    # ==========================================================

    @staticmethod
    def _upload_sftp(
        storage,
        filename,
        file_path,
    ):
        """
        Upload large backup file to SFTP.

        IMPORTANT:
            The file is streamed directly from disk.

            We DO NOT do:
                file_data = open(...).read()

            We DO:
                open(file_path, "rb")
                sftp.putfo(...)

        This prevents a 1+ GB backup from being loaded into
        Python memory.
        """

        if not storage.host:
            raise ValueError(
                "SFTP Host is required."
            )

        if not storage.username:
            raise ValueError(
                "SFTP Username is required."
            )

        if not storage.password:
            raise ValueError(
                "SFTP Password is required."
            )

        port = storage.port or 22

        remote_path = (
            storage.remote_path or "/"
        )

        import paramiko

        ssh = None
        sftp = None

        local_size = os.path.getsize(
            file_path
        )

        local_size_mb = (
            local_size / (1024 * 1024)
        )

        _logger.info(
            "Preparing SFTP upload. "
            "Host=%s Port=%s "
            "Filename=%s Size=%.2f MB",
            storage.host,
            port,
            filename,
            local_size_mb,
        )

        try:

            # ==================================================
            # CONNECT SSH
            # ==================================================

            _logger.info(
                "Connecting to SFTP %s:%s",
                storage.host,
                port,
            )

            ssh = paramiko.SSHClient()

            ssh.set_missing_host_key_policy(
                paramiko.AutoAddPolicy()
            )

            ssh.connect(
                hostname=storage.host,
                port=port,
                username=storage.username,
                password=storage.password,
                timeout=StorageService.SFTP_CONNECT_TIMEOUT,
                banner_timeout=StorageService.SFTP_CONNECT_TIMEOUT,
                auth_timeout=StorageService.SFTP_CONNECT_TIMEOUT,
                look_for_keys=False,
                allow_agent=False,
            )

            # ==================================================
            # CONFIGURE SOCKET TIMEOUT
            # ==================================================

            try:

                transport = ssh.get_transport()

                if transport:

                    sock = transport.sock

                    if sock:

                        sock.settimeout(
                            StorageService.SFTP_SOCKET_TIMEOUT
                        )

                        _logger.info(
                            "SFTP socket timeout set to %s seconds.",
                            StorageService.SFTP_SOCKET_TIMEOUT,
                        )

            except Exception as timeout_error:

                _logger.warning(
                    "Could not configure SFTP socket timeout: %s",
                    timeout_error,
                )

            # ==================================================
            # OPEN SFTP
            # ==================================================

            sftp = ssh.open_sftp()

            _logger.info(
                "SFTP connection established. "
                "Server=%s:%s",
                storage.host,
                port,
            )

            # ==================================================
            # ENSURE REMOTE DIRECTORY
            # ==================================================

            StorageService._ensure_sftp_directory(
                sftp,
                remote_path,
            )

            remote_file = (
                remote_path.rstrip("/")
                + "/"
                + filename
            )

            _logger.info(
                "Uploading to SFTP: %s",
                remote_file,
            )

            # ==================================================
            # STREAM FILE FROM DISK
            # ==================================================

            uploaded_last_logged = 0

            def progress_callback(
                transferred,
                total,
            ):
                nonlocal uploaded_last_logged

                # Avoid excessive logging.
                if (
                    transferred - uploaded_last_logged
                    < StorageService.SFTP_PROGRESS_INTERVAL
                    and transferred < total
                ):
                    return

                uploaded_last_logged = transferred

                transferred_mb = (
                    transferred / (1024 * 1024)
                )

                total_mb = (
                    total / (1024 * 1024)
                )

                percentage = (
                    (transferred / total) * 100
                    if total
                    else 0
                )

                _logger.info(
                    "SFTP upload progress: "
                    "%.2f / %.2f MB (%.1f%%)",
                    transferred_mb,
                    total_mb,
                    percentage,
                )

            with open(
                file_path,
                "rb",
            ) as file_stream:

                # --------------------------------------------------
                # IMPORTANT
                #
                # putfo() streams the file.
                #
                # file_size tells Paramiko the expected size
                # and avoids unnecessary file handling.
                # --------------------------------------------------

                sftp.putfo(
                    file_stream,
                    remote_file,
                    file_size=local_size,
                    callback=progress_callback,
                    confirm=True,
                )

            _logger.info(
                "SFTP file transfer completed. "
                "Filename=%s Size=%.2f MB",
                filename,
                local_size_mb,
            )

            # ==================================================
            # VERIFY REMOTE FILE
            # ==================================================

            remote_stat = sftp.stat(
                remote_file
            )

            remote_size = remote_stat.st_size

            _logger.info(
                "SFTP upload verification. "
                "Local=%d bytes Remote=%d bytes",
                local_size,
                remote_size,
            )

            if remote_size != local_size:

                raise IOError(
                    "SFTP upload verification failed. "
                    f"Local size={local_size}, "
                    f"Remote size={remote_size}"
                )

            _logger.info(
                "SFTP upload successful: %s "
                "Size=%.2f MB",
                remote_file,
                remote_size / (1024 * 1024),
            )

            return True

        except Exception as error:

            _logger.exception(
                "SFTP upload failed. "
                "Host=%s Port=%s "
                "Filename=%s File=%s Error=%s",
                storage.host,
                port,
                filename,
                file_path,
                error,
            )

            raise

        finally:

            # ==================================================
            # CLOSE SFTP
            # ==================================================

            if sftp:

                try:
                    sftp.close()

                    _logger.info(
                        "SFTP connection closed."
                    )

                except Exception as close_error:

                    _logger.warning(
                        "Failed to close SFTP connection: %s",
                        close_error,
                    )

            # ==================================================
            # CLOSE SSH
            # ==================================================

            if ssh:

                try:
                    ssh.close()

                    _logger.info(
                        "SSH connection closed."
                    )

                except Exception as close_error:

                    _logger.warning(
                        "Failed to close SSH connection: %s",
                        close_error,
                    )

    # ==========================================================
    # SFTP DIRECTORY
    # ==========================================================

    @staticmethod
    def _ensure_sftp_directory(
        sftp,
        remote_path,
    ):
        """
        Ensure that the remote SFTP directory exists.

        Example:

            /Folder Sharing/IT/Backup/Database/Odoo
        """

        if not remote_path:
            return

        remote_path = remote_path.replace(
            "\\",
            "/",
        )

        if remote_path == "/":
            return

        parts = remote_path.strip(
            "/"
        ).split("/")

        current = ""

        if remote_path.startswith("/"):
            current = "/"

        for part in parts:

            if not part:
                continue

            if current == "/":

                current = "/" + part

            elif current:

                current = (
                    current
                    + "/"
                    + part
                )

            else:

                current = part

            try:

                sftp.stat(
                    current
                )

            except IOError:

                _logger.info(
                    "Creating SFTP directory: %s",
                    current,
                )

                sftp.mkdir(
                    current
                )

    # ==========================================================
    # FTP
    # ==========================================================

    @staticmethod
    def _upload_ftp(
        storage,
        filename,
        file_path,
    ):
        """
        Upload backup to FTP.

        The file is streamed from disk using storbinary().
        """

        if not storage.host:
            raise ValueError(
                "FTP Host is required."
            )

        if not storage.username:
            raise ValueError(
                "FTP Username is required."
            )

        if not storage.password:
            raise ValueError(
                "FTP Password is required."
            )

        port = storage.port or 21

        local_size = os.path.getsize(
            file_path
        )

        ftp = FTP()

        try:

            _logger.info(
                "Connecting to FTP %s:%s",
                storage.host,
                port,
            )

            ftp.connect(
                storage.host,
                port,
                timeout=StorageService.FTP_CONNECT_TIMEOUT,
            )

            ftp.login(
                storage.username,
                storage.password,
            )

            if storage.remote_path:

                ftp.cwd(
                    storage.remote_path
                )

            _logger.info(
                "Uploading to FTP: %s Size=%.2f MB",
                filename,
                local_size / (1024 * 1024),
            )

            with open(
                file_path,
                "rb",
            ) as file_stream:

                ftp.storbinary(
                    f"STOR {filename}",
                    file_stream,
                    blocksize=64 * 1024,
                )

            # ==================================================
            # VERIFY
            # ==================================================

            try:

                remote_size = ftp.size(
                    filename
                )

                if remote_size != local_size:

                    raise IOError(
                        "FTP upload verification failed. "
                        f"Local size={local_size}, "
                        f"Remote size={remote_size}"
                    )

                _logger.info(
                    "FTP upload verification successful. "
                    "Size=%.2f MB",
                    remote_size / (1024 * 1024),
                )

            except Exception as verify_error:

                _logger.warning(
                    "FTP verification warning: %s",
                    verify_error,
                )

            _logger.info(
                "FTP upload successful: %s",
                filename,
            )

            return True

        except Exception as error:

            _logger.exception(
                "FTP upload failed. "
                "Host=%s Port=%s "
                "Filename=%s Error=%s",
                storage.host,
                port,
                filename,
                error,
            )

            raise

        finally:

            try:

                ftp.quit()

            except Exception:

                try:
                    ftp.close()

                except Exception:
                    pass
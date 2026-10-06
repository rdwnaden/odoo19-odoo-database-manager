import logging
import os
import shutil
from ftplib import FTP


_logger = logging.getLogger(__name__)


class StorageService:
    """
    Handle uploading and deleting backup files
    from configured storage services.

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

        file_size = os.path.getsize(
            file_path
        )

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
    # DELETE BACKUP FILE
    # ==========================================================

    @staticmethod
    def delete(
        storage,
        filename,
    ):
        """
        Delete backup file from configured storage.

        Supported:
            - Local
            - NAS
            - SFTP
            - FTP

        IMPORTANT:
            The physical backup file is deleted first.

            The database backup log should only be deleted
            after this method returns True.
        """

        if not storage:
            raise ValueError(
                "Storage configuration is required."
            )

        if not filename:
            raise ValueError(
                "Backup filename is required."
            )

        service_type = storage.service_type

        _logger.info(
            "Deleting backup file. "
            "Storage=%s Type=%s Filename=%s",
            storage.name,
            service_type,
            filename,
        )

        # ------------------------------------------------------
        # LOCAL
        # ------------------------------------------------------

        if service_type == "local":

            return StorageService._delete_local(
                storage,
                filename,
            )

        # ------------------------------------------------------
        # NAS
        # ------------------------------------------------------

        if service_type == "nas":

            return StorageService._delete_nas(
                storage,
                filename,
            )

        # ------------------------------------------------------
        # SFTP
        # ------------------------------------------------------

        if service_type == "sftp":

            return StorageService._delete_sftp(
                storage,
                filename,
            )

        # ------------------------------------------------------
        # FTP
        # ------------------------------------------------------

        if service_type == "ftp":

            return StorageService._delete_ftp(
                storage,
                filename,
            )

        raise ValueError(
            f"Unsupported storage service: {service_type}"
        )

    # ==========================================================
    # LOCAL UPLOAD
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
    # LOCAL DELETE
    # ==========================================================

    @staticmethod
    def _delete_local(
        storage,
        filename,
    ):
        """
        Delete backup file from local filesystem.
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

        file_path = os.path.join(
            folder,
            filename,
        )

        # ------------------------------------------------------
        # File already does not exist
        # ------------------------------------------------------

        if not os.path.isfile(
            file_path
        ):

            _logger.warning(
                "Local backup file does not exist. "
                "Filename=%s Path=%s",
                filename,
                file_path,
            )

            # Already deleted = success.
            return True

        try:

            file_size = os.path.getsize(
                file_path
            )

            _logger.info(
                "Deleting local backup. "
                "Path=%s Size=%.2f MB",
                file_path,
                file_size / (1024 * 1024),
            )

            os.remove(
                file_path
            )

            # --------------------------------------------------
            # VERIFY DELETION
            # --------------------------------------------------

            if os.path.exists(
                file_path
            ):

                raise IOError(
                    "Local backup file still exists "
                    f"after deletion: {file_path}"
                )

            _logger.info(
                "Local backup deleted successfully. "
                "Filename=%s Size=%.2f MB",
                filename,
                file_size / (1024 * 1024),
            )

            return True

        except Exception:

            _logger.exception(
                "Failed to delete local backup. "
                "Filename=%s Path=%s",
                filename,
                file_path,
            )

            raise

    # ==========================================================
    # NAS UPLOAD
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
    # NAS DELETE
    # ==========================================================

    @staticmethod
    def _delete_nas(
        storage,
        filename,
    ):
        """
        Delete backup file from mounted NAS filesystem.
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

        file_path = os.path.join(
            folder,
            filename,
        )

        # ------------------------------------------------------
        # File already does not exist
        # ------------------------------------------------------

        if not os.path.isfile(
            file_path
        ):

            _logger.warning(
                "NAS backup file does not exist. "
                "Filename=%s Path=%s",
                filename,
                file_path,
            )

            # Already deleted = success.
            return True

        try:

            file_size = os.path.getsize(
                file_path
            )

            _logger.info(
                "Deleting NAS backup. "
                "Path=%s Size=%.2f MB",
                file_path,
                file_size / (1024 * 1024),
            )

            os.remove(
                file_path
            )

            # --------------------------------------------------
            # VERIFY DELETION
            # --------------------------------------------------

            if os.path.exists(
                file_path
            ):

                raise IOError(
                    "NAS backup file still exists "
                    f"after deletion: {file_path}"
                )

            _logger.info(
                "NAS backup deleted successfully. "
                "Filename=%s Size=%.2f MB",
                filename,
                file_size / (1024 * 1024),
            )

            return True

        except Exception:

            _logger.exception(
                "Failed to delete NAS backup. "
                "Filename=%s Path=%s",
                filename,
                file_path,
            )

            raise

    # ==========================================================
    # SFTP UPLOAD
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

                except Exception as close_error:

                    _logger.warning(
                        "Failed to close SSH connection: %s",
                        close_error,
                    )

    # ==========================================================
    # SFTP DELETE
    # ==========================================================

    @staticmethod
    def _delete_sftp(
        storage,
        filename,
    ):
        """
        Delete backup file from SFTP server.
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

        remote_file = (
            remote_path.rstrip("/")
            + "/"
            + filename
        )

        try:

            _logger.info(
                "Connecting to SFTP for deletion. "
                "Host=%s Port=%s",
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
            # SOCKET TIMEOUT
            # ==================================================

            try:

                transport = ssh.get_transport()

                if transport:

                    sock = transport.sock

                    if sock:

                        sock.settimeout(
                            StorageService.SFTP_SOCKET_TIMEOUT
                        )

            except Exception as timeout_error:

                _logger.warning(
                    "Could not configure SFTP socket timeout "
                    "for deletion: %s",
                    timeout_error,
                )

            # ==================================================
            # OPEN SFTP
            # ==================================================

            sftp = ssh.open_sftp()

            # ==================================================
            # CHECK FILE
            # ==================================================

            try:

                remote_stat = sftp.stat(
                    remote_file
                )

                remote_size = remote_stat.st_size

            except IOError:

                _logger.warning(
                    "SFTP backup file does not exist. "
                    "Remote=%s",
                    remote_file,
                )

                # Already deleted = success.
                return True

            # ==================================================
            # DELETE
            # ==================================================

            _logger.info(
                "Deleting SFTP backup. "
                "Remote=%s Size=%.2f MB",
                remote_file,
                remote_size / (1024 * 1024),
            )

            sftp.remove(
                remote_file
            )

            # ==================================================
            # VERIFY DELETION
            # ==================================================

            try:

                sftp.stat(
                    remote_file
                )

            except IOError:

                # Expected:
                # File no longer exists.
                pass

            else:

                raise IOError(
                    "SFTP backup file still exists "
                    f"after deletion: {remote_file}"
                )

            _logger.info(
                "SFTP backup deleted successfully. "
                "Remote=%s Size=%.2f MB",
                remote_file,
                remote_size / (1024 * 1024),
            )

            return True

        except Exception:

            _logger.exception(
                "Failed to delete SFTP backup. "
                "Host=%s Port=%s Remote=%s",
                storage.host,
                port,
                remote_file,
            )

            raise

        finally:

            # ==================================================
            # CLOSE SFTP
            # ==================================================

            if sftp:
                try:
                    sftp.close()
                except Exception:
                    pass

            # ==================================================
            # CLOSE SSH
            # ==================================================

            if ssh:
                try:
                    ssh.close()
                except Exception:
                    pass

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
    # FTP UPLOAD
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

    # ==========================================================
    # FTP DELETE
    # ==========================================================

    @staticmethod
    def _delete_ftp(
        storage,
        filename,
    ):
        """
        Delete backup file from FTP server.
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

        ftp = FTP()

        try:

            _logger.info(
                "Connecting to FTP for deletion. "
                "Host=%s Port=%s",
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

            # ==================================================
            # CHECK FILE
            # ==================================================

            try:

                remote_size = ftp.size(
                    filename
                )

            except Exception:

                _logger.warning(
                    "FTP backup file does not exist. "
                    "Filename=%s",
                    filename,
                )

                # Already deleted = success.
                return True

            # ==================================================
            # DELETE
            # ==================================================

            _logger.info(
                "Deleting FTP backup. "
                "Filename=%s Size=%.2f MB",
                filename,
                remote_size / (1024 * 1024),
            )

            ftp.delete(
                filename
            )

            _logger.info(
                "FTP backup deleted successfully. "
                "Filename=%s",
                filename,
            )

            return True

        except Exception:

            _logger.exception(
                "Failed to delete FTP backup. "
                "Host=%s Port=%s Filename=%s",
                storage.host,
                port,
                filename,
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
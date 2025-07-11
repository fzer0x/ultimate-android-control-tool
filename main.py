import sys
import os
import subprocess
import re
import time
import threading
from datetime import datetime
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
    QTabWidget, QPushButton, QLabel, QLineEdit, QTextEdit, 
    QComboBox, QCheckBox, QGroupBox, QScrollArea, QFileDialog,
    QMessageBox, QProgressBar, QListWidget, QTreeWidget, QInputDialog, 
    QTreeWidgetItem, QSplitter, QFrame, QMenu, QSystemTrayIcon, QGridLayout, QSpinBox,
    QFormLayout, QStatusBar, QDialog)
from PyQt6.QtGui import (QIcon, QFont, QPixmap, QColor, QPalette, QAction, 
                         QTextCursor, QStandardItemModel, QStandardItem)
from PyQt6.QtCore import (Qt, QSize, QTimer, QProcess, QSettings, QThread, 
                          pyqtSignal, QObject, QByteArray)
from functools import partial
import webbrowser
import json
import zipfile
import tempfile
import requests
import shutil
import xml.etree.ElementTree as ET
from packaging import version

# Constants
VERSION = "1.0.0"
APP_NAME = "Ultimate Android Control Tool"
DEVELOPER = "fzer0x"
SUPPORTED_ANDROID_VERSIONS = ["4.0", "5.0", "6.0", "7.0", "8.0", "9.0", "10", "11", "12", "13", "14"]
DEFAULT_ADB_PATH = "adb"  # Will search in PATH if not found
DEFAULT_FASTBOOT_PATH = "fastboot"  # Will search in PATH if not found

# Global settings
settings = QSettings("AndroidToolMaster", "UACT")

class CommandWorker(QObject):
    command_output = pyqtSignal(str)
    command_finished = pyqtSignal(int)
    progress_update = pyqtSignal(int, str)

    def __init__(self):
        super().__init__()
        self.process = None
        self.is_running = False

    def run_command(self, command, cwd=None):
        self.is_running = True
        try:
            self.process = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                stdin=subprocess.PIPE,
                shell=True,
                cwd=cwd,
                universal_newlines=True
            )

            while self.is_running:
                output = self.process.stdout.readline()
                if output == '' and self.process.poll() is not None:
                    break
                if output:
                    self.command_output.emit(output.strip())
            
            return_code = self.process.poll()
            self.command_finished.emit(return_code)
        except Exception as e:
            self.command_output.emit(f"Error executing command: {str(e)}")
            self.command_finished.emit(-1)
        finally:
            self.is_running = False

    def stop(self):
        self.is_running = False
        if self.process:
            try:
                self.process.terminate()
            except:
                pass

class DeviceManager(QObject):
    devices_updated = pyqtSignal(list)
    device_details_updated = pyqtSignal(dict)
    connection_status_changed = pyqtSignal(bool)

    def __init__(self):
        super().__init__()
        self.adb_path = settings.value("adb_path", DEFAULT_ADB_PATH)
        self.fastboot_path = settings.value("fastboot_path", DEFAULT_FASTBOOT_PATH)
        self.connected_devices = []
        self.current_device = None
        self.device_details = {}
        self.timer = QTimer()
        self.timer.timeout.connect(self.update_devices)
        self.timer.start(3000)  # Check every 3 seconds

    def update_devices(self):
        try:
            # Check ADB devices
            result = subprocess.run([self.adb_path, "devices"], capture_output=True, text=True)
            lines = result.stdout.splitlines()
            adb_devices = []
            
            for line in lines[1:]:
                if line.strip() and "offline" not in line:
                    device_id = line.split("\t")[0]
                    adb_devices.append({"id": device_id, "type": "adb", "status": "device"})

            # Check Fastboot devices
            result = subprocess.run([self.fastboot_path, "devices"], capture_output=True, text=True)
            lines = result.stdout.splitlines()
            fastboot_devices = []
            
            for line in lines:
                if line.strip():
                    device_id = line.split("\t")[0]
                    fastboot_devices.append({"id": device_id, "type": "fastboot", "status": "fastboot"})

            new_devices = adb_devices + fastboot_devices
            if new_devices != self.connected_devices:
                self.connected_devices = new_devices
                self.devices_updated.emit(self.connected_devices)
                
                if self.connected_devices:
                    self.connection_status_changed.emit(True)
                    if not self.current_device and self.connected_devices:
                        self.set_current_device(self.connected_devices[0]["id"])
                else:
                    self.connection_status_changed.emit(False)
                    self.current_device = None
                    self.device_details = {}
                    self.device_details_updated.emit({})
        except Exception as e:
            print(f"Error updating devices: {str(e)}")

    def set_current_device(self, device_id):
        self.current_device = device_id
        self.update_device_details()

    def update_device_details(self):
        if not self.current_device:
            return

        details = {}
        device_type = next((d["type"] for d in self.connected_devices if d["id"] == self.current_device), None)

        if device_type == "adb":
            # Get basic info
            details["serial"] = self.current_device
            details["type"] = "adb"
            
            # Get device model
            result = subprocess.run([self.adb_path, "-s", self.current_device, "shell", "getprop", "ro.product.model"], 
                                  capture_output=True, text=True)
            details["model"] = result.stdout.strip()
            
            # Get device brand
            result = subprocess.run([self.adb_path, "-s", self.current_device, "shell", "getprop", "ro.product.brand"], 
                                  capture_output=True, text=True)
            details["brand"] = result.stdout.strip()
            
            # Get Android version
            result = subprocess.run([self.adb_path, "-s", self.current_device, "shell", "getprop", "ro.build.version.release"], 
                                  capture_output=True, text=True)
            details["android_version"] = result.stdout.strip()
            
            # Get build number
            result = subprocess.run([self.adb_path, "-s", self.current_device, "shell", "getprop", "ro.build.display.id"], 
                                  capture_output=True, text=True)
            details["build_number"] = result.stdout.strip()
            
            # Get root status
            result = subprocess.run([self.adb_path, "-s", self.current_device, "shell", "su", "-c", "whoami"], 
                                  capture_output=True, text=True)
            details["root"] = "root" in result.stdout.strip().lower()
            
            # Get device state
            result = subprocess.run([self.adb_path, "-s", self.current_device, "get-state"], 
                                  capture_output=True, text=True)
            details["state"] = result.stdout.strip()
            
            # Get battery info
            result = subprocess.run([self.adb_path, "-s", self.current_device, "shell", "dumpsys", "battery"], 
                                  capture_output=True, text=True)
            battery_info = result.stdout.strip()
            details["battery_level"] = "Unknown"
            if "level:" in battery_info:
                match = re.search(r"level:\s*(\d+)", battery_info)
                if match:
                    details["battery_level"] = f"{match.group(1)}%"
            
            # Get storage info
            result = subprocess.run([self.adb_path, "-s", self.current_device, "shell", "df", "/data"], 
                                  capture_output=True, text=True)
            storage_info = result.stdout.strip()
            if len(storage_info.splitlines()) > 1:
                parts = storage_info.splitlines()[1].split()
                if len(parts) >= 5:
                    details["storage_total"] = parts[1]
                    details["storage_used"] = parts[2]
                    details["storage_available"] = parts[3]
                    details["storage_percent"] = parts[4]

        elif device_type == "fastboot":
            details["serial"] = self.current_device
            details["type"] = "fastboot"
            
            # Get fastboot variables
            variables = [
                "product", "variant", "secure", "unlocked", "version-baseband", 
                "version-bootloader", "version", "serialno"
            ]
            
            for var in variables:
                result = subprocess.run([self.fastboot_path, "-s", self.current_device, "getvar", var], 
                                       capture_output=True, text=True)
                output = result.stdout.strip()
                if ":" in output:
                    key, value = output.split(":", 1)
                    details[key.strip()] = value.strip().split("\n")[0].strip()
            
            # Check if device is unlocked
            details["unlocked"] = details.get("unlocked", "no").lower() == "yes"

        self.device_details = details
        self.device_details_updated.emit(details)

    def execute_adb_command(self, command, device_specific=True):
        if not self.current_device:
            return None, "No device selected"
        
        full_command = [self.adb_path]
        if device_specific:
            full_command.extend(["-s", self.current_device])
        full_command.extend(command.split())
        
        try:
            result = subprocess.run(full_command, capture_output=True, text=True)
            return result.returncode, result.stdout
        except Exception as e:
            return -1, str(e)

    def execute_fastboot_command(self, command, device_specific=True):
        if not self.current_device:
            return None, "No device selected"
        
        full_command = [self.fastboot_path]
        if device_specific:
            full_command.extend(["-s", self.current_device])
        full_command.extend(command.split())
        
        try:
            result = subprocess.run(full_command, capture_output=True, text=True)
            return result.returncode, result.stdout
        except Exception as e:
            return -1, str(e)

    def reboot_device(self, mode="system"):
        if not self.current_device:
            return False, "No device selected"
        
        device_type = next((d["type"] for d in self.connected_devices if d["id"] == self.current_device), None)
        
        if device_type == "adb":
            if mode.lower() in ["recovery", "bootloader", "sideload", "download"]:
                cmd = f"reboot {mode.lower()}"
            else:
                cmd = "reboot"
            
            return_code, output = self.execute_adb_command(cmd)
            return return_code == 0, output
        elif device_type == "fastboot":
            if mode.lower() in ["recovery", "bootloader", "system"]:
                cmd = f"reboot-{mode.lower()}"
            else:
                cmd = "reboot"
            
            return_code, output = self.execute_fastboot_command(cmd)
            return return_code == 0, output
        else:
            return False, "Unknown device type"

class FileManager(QObject):
    file_transfer_progress = pyqtSignal(int, str)
    file_operation_complete = pyqtSignal(bool, str)
    
    def __init__(self, device_manager):
        super().__init__()
        self.device_manager = device_manager
    
    def push_file(self, local_path, remote_path):
        if not self.device_manager.current_device:
            self.file_operation_complete.emit(False, "No device selected")
            return
        
        def run_push():
            try:
                command = [self.device_manager.adb_path, "-s", self.device_manager.current_device, "push", local_path, remote_path]
                process = subprocess.Popen(
                    command,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    universal_newlines=True
                )
                
                total_size = os.path.getsize(local_path)
                transferred = 0
                last_progress = 0
                
                while True:
                    output = process.stdout.readline()
                    if output == '' and process.poll() is not None:
                        break
                    
                    if output:
                        # Parse progress from ADB output (format: [xx%] or xx%)
                        match = re.search(r'(\d+)%', output)
                        if match:
                            progress = int(match.group(1))
                            if progress != last_progress:
                                self.file_transfer_progress.emit(progress, f"Uploading: {progress}%")
                                last_progress = progress
                
                return_code = process.poll()
                success = return_code == 0
                message = "File transfer completed" if success else "File transfer failed"
                self.file_operation_complete.emit(success, message)
            except Exception as e:
                self.file_operation_complete.emit(False, f"Error: {str(e)}")
        
        thread = threading.Thread(target=run_push, daemon=True)
        thread.start()
    
    def pull_file(self, remote_path, local_path):
        if not self.device_manager.current_device:
            self.file_operation_complete.emit(False, "No device selected")
            return
        
        def run_pull():
            try:
                command = [self.device_manager.adb_path, "-s", self.device_manager.current_device, "pull", remote_path, local_path]
                process = subprocess.Popen(
                    command,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    universal_newlines=True
                )
                
                # ADB pull doesn't provide progress output, so we'll simulate it
                # First get the remote file size
                size_cmd = [self.device_manager.adb_path, "-s", self.device_manager.current_device, "shell", "stat", "-c", "%s", remote_path]
                size_result = subprocess.run(size_cmd, capture_output=True, text=True)
                
                total_size = 0
                try:
                    total_size = int(size_result.stdout.strip())
                except:
                    pass
                
                start_time = time.time()
                last_update = start_time
                last_size = 0
                
                while True:
                    if not os.path.exists(local_path):
                        time.sleep(0.1)
                        continue
                    
                    current_size = os.path.getsize(local_path)
                    now = time.time()
                    
                    if now - last_update > 0.5:  # Update every 0.5 seconds
                        if total_size > 0:
                            progress = int((current_size / total_size) * 100)
                            self.file_transfer_progress.emit(progress, f"Downloading: {progress}%")
                        
                        last_update = now
                        last_size = current_size
                    
                    if process.poll() is not None:
                        break
                    
                    time.sleep(0.1)
                
                return_code = process.poll()
                success = return_code == 0
                message = "File transfer completed" if success else "File transfer failed"
                self.file_operation_complete.emit(success, message)
            except Exception as e:
                self.file_operation_complete.emit(False, f"Error: {str(e)}")
        
        thread = threading.Thread(target=run_pull, daemon=True)
        thread.start()

class PackageManager(QObject):
    package_operation_complete = pyqtSignal(bool, str)
    package_list_updated = pyqtSignal(list)
    
    def __init__(self, device_manager):
        super().__init__()
        self.device_manager = device_manager
    
    def get_installed_packages(self, system_only=False, third_party_only=False, enabled_only=False, disabled_only=False):
        if not self.device_manager.current_device:
            self.package_operation_complete.emit(False, "No device selected")
            return
        
        try:
            command = [self.device_manager.adb_path, "-s", self.device_manager.current_device, "shell", "pm", "list", "packages"]
            
            if system_only:
                command.append("-s")
            elif third_party_only:
                command.append("-3")
            
            if enabled_only:
                command.extend(["-e"])
            elif disabled_only:
                command.extend(["-d"])
            
            result = subprocess.run(command, capture_output=True, text=True)
            packages = []
            
            for line in result.stdout.splitlines():
                if line.startswith("package:"):
                    package_name = line[8:].strip()
                    packages.append(package_name)
            
            self.package_list_updated.emit(packages)
            return True, "Package list retrieved"
        except Exception as e:
            self.package_operation_complete.emit(False, f"Error: {str(e)}")
            return False, str(e)
    
    def get_package_info(self, package_name):
        if not self.device_manager.current_device:
            return None, "No device selected"
        
        try:
            # Get basic package info
            command = [self.device_manager.adb_path, "-s", self.device_manager.current_device, "shell", "dumpsys", "package", package_name]
            result = subprocess.run(command, capture_output=True, text=True)
            output = result.stdout
            
            info = {
                "name": package_name,
                "version": "Unknown",
                "uid": "Unknown",
                "path": "Unknown",
                "enabled": True,
                "permissions": []
            }
            
            # Parse version
            version_match = re.search(r"versionName=([^\s]+)", output)
            if version_match:
                info["version"] = version_match.group(1)
            
            # Parse UID
            uid_match = re.search(r"userId=(\d+)", output)
            if uid_match:
                info["uid"] = uid_match.group(1)
            
            # Parse path
            path_match = re.search(r"codePath=([^\s]+)", output)
            if path_match:
                info["path"] = path_match.group(1)
            
            # Parse enabled status
            enabled_match = re.search(r"enabled=(\d+)", output)
            if enabled_match:
                info["enabled"] = enabled_match.group(1) == "1"
            
            # Parse permissions
            permissions_section = re.search(r"requested permissions:(.*?)install permissions:", output, re.DOTALL)
            if permissions_section:
                permissions = re.findall(r"(\w+): granted=(\w+)", permissions_section.group(1))
                info["permissions"] = [f"{p[0]} ({'granted' if p[1] == 'true' else 'denied'})" for p in permissions]
            
            return True, info
        except Exception as e:
            return False, str(e)
    
    def install_package(self, apk_path, replace_existing=False, grant_all_permissions=False, test_only=False):
        if not self.device_manager.current_device:
            self.package_operation_complete.emit(False, "No device selected")
            return
        
        try:
            command = [self.device_manager.adb_path, "-s", self.device_manager.current_device, "install"]
            
            if replace_existing:
                command.append("-r")
            
            if grant_all_permissions:
                command.append("-g")
            
            if test_only:
                command.append("-t")
            
            command.append(apk_path)
            
            result = subprocess.run(command, capture_output=True, text=True)
            
            success = "Success" in result.stdout
            message = result.stdout.strip()
            
            self.package_operation_complete.emit(success, message)
            return success, message
        except Exception as e:
            self.package_operation_complete.emit(False, f"Error: {str(e)}")
            return False, str(e)
    
    def uninstall_package(self, package_name, keep_data=False):
        if not self.device_manager.current_device:
            self.package_operation_complete.emit(False, "No device selected")
            return
        
        try:
            command = [self.device_manager.adb_path, "-s", self.device_manager.current_device, "uninstall"]
            
            if keep_data:
                command.append("-k")
            
            command.append(package_name)
            
            result = subprocess.run(command, capture_output=True, text=True)
            
            success = "Success" in result.stdout
            message = result.stdout.strip()
            
            self.package_operation_complete.emit(success, message)
            return success, message
        except Exception as e:
            self.package_operation_complete.emit(False, f"Error: {str(e)}")
            return False, str(e)
    
    def clear_package_data(self, package_name):
        if not self.device_manager.current_device:
            self.package_operation_complete.emit(False, "No device selected")
            return
        
        try:
            command = [self.device_manager.adb_path, "-s", self.device_manager.current_device, "shell", "pm", "clear", package_name]
            result = subprocess.run(command, capture_output=True, text=True)
            
            success = "Success" in result.stdout
            message = result.stdout.strip()
            
            self.package_operation_complete.emit(success, message)
            return success, message
        except Exception as e:
            self.package_operation_complete.emit(False, f"Error: {str(e)}")
            return False, str(e)
    
    def enable_package(self, package_name):
        if not self.device_manager.current_device:
            self.package_operation_complete.emit(False, "No device selected")
            return
        
        try:
            command = [self.device_manager.adb_path, "-s", self.device_manager.current_device, "shell", "pm", "enable", package_name]
            result = subprocess.run(command, capture_output=True, text=True)
            
            success = result.returncode == 0
            message = "Package enabled" if success else "Failed to enable package"
            
            self.package_operation_complete.emit(success, message)
            return success, message
        except Exception as e:
            self.package_operation_complete.emit(False, f"Error: {str(e)}")
            return False, str(e)
    
    def disable_package(self, package_name):
        if not self.device_manager.current_device:
            self.package_operation_complete.emit(False, "No device selected")
            return
        
        try:
            command = [self.device_manager.adb_path, "-s", self.device_manager.current_device, "shell", "pm", "disable", package_name]
            result = subprocess.run(command, capture_output=True, text=True)
            
            success = result.returncode == 0
            message = "Package disabled" if success else "Failed to disable package"
            
            self.package_operation_complete.emit(success, message)
            return success, message
        except Exception as e:
            self.package_operation_complete.emit(False, f"Error: {str(e)}")
            return False, str(e)

class BackupManager(QObject):
    backup_progress = pyqtSignal(int, str)
    backup_complete = pyqtSignal(bool, str)
    
    def __init__(self, device_manager):
        super().__init__()
        self.device_manager = device_manager
    
    def create_backup(self, backup_path, include_apks=False, include_shared=False, include_system=False, all_apps=False, packages=None):
        if not self.device_manager.current_device:
            self.backup_complete.emit(False, "No device selected")
            return
        
        if not packages and not all_apps:
            self.backup_complete.emit(False, "No packages selected and 'all apps' not checked")
            return
        
        def run_backup():
            try:
                command = [self.device_manager.adb_path, "-s", self.device_manager.current_device, "backup"]
                
                if include_apks:
                    command.append("-apk")
                
                if include_shared:
                    command.append("-shared")
                
                if include_system:
                    command.append("-system")
                
                if all_apps:
                    command.append("-all")
                elif packages:
                    command.append("-f")
                    command.append(backup_path)
                    command.extend(packages)
                
                process = subprocess.Popen(
                    command,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    stdin=subprocess.PIPE,
                    universal_newlines=True
                )
                
                # ADB backup requires confirmation on the device
                # We can't automate this, so we'll just wait for completion
                while True:
                    output = process.stdout.readline()
                    if output == '' and process.poll() is not None:
                        break
                    
                    if output:
                        # Try to parse progress if available
                        if "%" in output:
                            match = re.search(r'(\d+)%', output)
                            if match:
                                progress = int(match.group(1))
                                self.backup_progress.emit(progress, f"Backup progress: {progress}%")
                
                return_code = process.poll()
                success = return_code == 0
                message = "Backup completed successfully" if success else "Backup failed"
                self.backup_complete.emit(success, message)
            except Exception as e:
                self.backup_complete.emit(False, f"Error: {str(e)}")
        
        thread = threading.Thread(target=run_backup, daemon=True)
        thread.start()
    
    def restore_backup(self, backup_path):
        if not self.device_manager.current_device:
            self.backup_complete.emit(False, "No device selected")
            return
        
        def run_restore():
            try:
                command = [self.device_manager.adb_path, "-s", self.device_manager.current_device, "restore", backup_path]
                process = subprocess.Popen(
                    command,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    stdin=subprocess.PIPE,
                    universal_newlines=True
                )
                
                # ADB restore requires confirmation on the device
                # We can't automate this, so we'll just wait for completion
                while True:
                    output = process.stdout.readline()
                    if output == '' and process.poll() is not None:
                        break
                    
                    if output:
                        # Try to parse progress if available
                        if "%" in output:
                            match = re.search(r'(\d+)%', output)
                            if match:
                                progress = int(match.group(1))
                                self.backup_progress.emit(progress, f"Restore progress: {progress}%")
                
                return_code = process.poll()
                success = return_code == 0
                message = "Restore completed successfully" if success else "Restore failed"
                self.backup_complete.emit(success, message)
            except Exception as e:
                self.backup_complete.emit(False, f"Error: {str(e)}")
        
        thread = threading.Thread(target=run_restore, daemon=True)
        thread.start()

class LogcatManager(QObject):
    log_received = pyqtSignal(str)
    log_cleared = pyqtSignal(bool)
    
    def __init__(self, device_manager):
        super().__init__()
        self.device_manager = device_manager
        self.process = None
        self.is_running = False
    
    def start_logcat(self, filters=None, clear_first=True):
        if not self.device_manager.current_device:
            self.log_received.emit("Error: No device selected")
            return
        
        if self.is_running:
            self.log_received.emit("Error: Logcat already running")
            return
        
        if clear_first:
            self.clear_logcat()
        
        def run_logcat():
            try:
                command = [self.device_manager.adb_path, "-s", self.device_manager.current_device, "logcat"]
                
                if filters:
                    command.extend(filters.split())
                
                self.process = subprocess.Popen(
                    command,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    universal_newlines=True
                )
                
                self.is_running = True
                
                while self.is_running:
                    output = self.process.stdout.readline()
                    if output == '' and self.process.poll() is not None:
                        break
                    if output:
                        self.log_received.emit(output.strip())
                
                self.is_running = False
            except Exception as e:
                self.log_received.emit(f"Error: {str(e)}")
                self.is_running = False
        
        thread = threading.Thread(target=run_logcat, daemon=True)
        thread.start()
    
    def stop_logcat(self):
        self.is_running = False
        if self.process:
            try:
                self.process.terminate()
            except:
                pass
    
    def clear_logcat(self):
        if not self.device_manager.current_device:
            self.log_cleared.emit(False)
            return
        
        try:
            command = [self.device_manager.adb_path, "-s", self.device_manager.current_device, "logcat", "-c"]
            result = subprocess.run(command, capture_output=True, text=True)
            
            success = result.returncode == 0
            self.log_cleared.emit(success)
            return success
        except Exception as e:
            self.log_cleared.emit(False)
            return False
    
    def save_logcat(self, file_path, filters=None):
        if not self.device_manager.current_device:
            return False, "No device selected"
        
        try:
            command = [self.device_manager.adb_path, "-s", self.device_manager.current_device, "logcat", "-d"]
            
            if filters:
                command.extend(filters.split())
            
            result = subprocess.run(command, capture_output=True, text=True)
            
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(result.stdout)
            
            return True, "Logcat saved successfully"
        except Exception as e:
            return False, str(e)

class DeviceControlTab(QWidget):
    def __init__(self, device_manager):
        super().__init__()
        self.device_manager = device_manager
        self.init_ui()
        
        # Connect signals
        self.device_manager.device_details_updated.connect(self.update_device_info)
        self.device_manager.connection_status_changed.connect(self.update_connection_status)
    
    def init_ui(self):
        layout = QVBoxLayout()
        
        # Device Info Group
        device_info_group = QGroupBox("Device Information")
        device_info_layout = QFormLayout()
        
        self.device_model_label = QLabel("Unknown")
        self.device_brand_label = QLabel("Unknown")
        self.android_version_label = QLabel("Unknown")
        self.build_number_label = QLabel("Unknown")
        self.root_status_label = QLabel("Unknown")
        self.battery_level_label = QLabel("Unknown")
        self.storage_info_label = QLabel("Unknown")
        
        device_info_layout.addRow("Model:", self.device_model_label)
        device_info_layout.addRow("Brand:", self.device_brand_label)
        device_info_layout.addRow("Android Version:", self.android_version_label)
        device_info_layout.addRow("Build Number:", self.build_number_label)
        device_info_layout.addRow("Root Status:", self.root_status_label)
        device_info_layout.addRow("Battery Level:", self.battery_level_label)
        device_info_layout.addRow("Storage Info:", self.storage_info_label)
        
        device_info_group.setLayout(device_info_layout)
        
        # Reboot Control Group
        reboot_group = QGroupBox("Device Control")
        reboot_layout = QHBoxLayout()
        
        self.reboot_system_btn = QPushButton("Reboot System")
        self.reboot_recovery_btn = QPushButton("Reboot Recovery")
        self.reboot_bootloader_btn = QPushButton("Reboot Bootloader")
        self.reboot_sideload_btn = QPushButton("Reboot Sideload")
        self.reboot_download_btn = QPushButton("Reboot Download")
        
        self.reboot_system_btn.clicked.connect(lambda: self.device_manager.reboot_device("system"))
        self.reboot_recovery_btn.clicked.connect(lambda: self.device_manager.reboot_device("recovery"))
        self.reboot_bootloader_btn.clicked.connect(lambda: self.device_manager.reboot_device("bootloader"))
        self.reboot_sideload_btn.clicked.connect(lambda: self.device_manager.reboot_device("sideload"))
        self.reboot_download_btn.clicked.connect(lambda: self.device_manager.reboot_device("download"))
        
        reboot_layout.addWidget(self.reboot_system_btn)
        reboot_layout.addWidget(self.reboot_recovery_btn)
        reboot_layout.addWidget(self.reboot_bootloader_btn)
        reboot_layout.addWidget(self.reboot_sideload_btn)
        reboot_layout.addWidget(self.reboot_download_btn)
        
        reboot_group.setLayout(reboot_layout)
        
        # Power Options Group
        power_group = QGroupBox("Power Options")
        power_layout = QHBoxLayout()
        
        self.power_off_btn = QPushButton("Power Off")
        self.screen_on_btn = QPushButton("Turn Screen On")
        self.screen_off_btn = QPushButton("Turn Screen Off")
        
        self.power_off_btn.clicked.connect(self.power_off_device)
        self.screen_on_btn.clicked.connect(self.turn_screen_on)
        self.screen_off_btn.clicked.connect(self.turn_screen_off)
        
        power_layout.addWidget(self.power_off_btn)
        power_layout.addWidget(self.screen_on_btn)
        power_layout.addWidget(self.screen_off_btn)
        
        power_group.setLayout(power_layout)
        
        # Advanced Controls Group
        advanced_group = QGroupBox("Advanced Controls")
        advanced_layout = QVBoxLayout()
        
        # Root access controls
        root_layout = QHBoxLayout()
        self.root_check_btn = QPushButton("Check Root Access")
        self.root_grant_btn = QPushButton("Grant Root Access")
        self.root_revoke_btn = QPushButton("Revoke Root Access")
        
        self.root_check_btn.clicked.connect(self.check_root_access)
        self.root_grant_btn.clicked.connect(self.grant_root_access)
        self.root_revoke_btn.clicked.connect(self.revoke_root_access)
        
        root_layout.addWidget(self.root_check_btn)
        root_layout.addWidget(self.root_grant_btn)
        root_layout.addWidget(self.root_revoke_btn)
        
        # ADB over WiFi
        wifi_layout = QHBoxLayout()
        self.wifi_enable_btn = QPushButton("Enable ADB over WiFi")
        self.wifi_disable_btn = QPushButton("Disable ADB over WiFi")
        self.wifi_connect_btn = QPushButton("Connect via WiFi")
        
        self.wifi_enable_btn.clicked.connect(self.enable_adb_over_wifi)
        self.wifi_disable_btn.clicked.connect(self.disable_adb_over_wifi)
        self.wifi_connect_btn.clicked.connect(self.connect_via_wifi)
        
        wifi_layout.addWidget(self.wifi_enable_btn)
        wifi_layout.addWidget(self.wifi_disable_btn)
        wifi_layout.addWidget(self.wifi_connect_btn)
        
        # Add to advanced layout
        advanced_layout.addLayout(root_layout)
        advanced_layout.addLayout(wifi_layout)
        advanced_group.setLayout(advanced_layout)
        
        # Add all groups to main layout
        layout.addWidget(device_info_group)
        layout.addWidget(reboot_group)
        layout.addWidget(power_group)
        layout.addWidget(advanced_group)
        layout.addStretch()
        
        self.setLayout(layout)
    
    def update_device_info(self, details):
        self.device_model_label.setText(details.get("model", "Unknown"))
        self.device_brand_label.setText(details.get("brand", "Unknown"))
        self.android_version_label.setText(details.get("android_version", "Unknown"))
        self.build_number_label.setText(details.get("build_number", "Unknown"))
        
        root_status = details.get("root", False)
        self.root_status_label.setText("Rooted" if root_status else "Not Rooted")
        
        self.battery_level_label.setText(details.get("battery_level", "Unknown"))
        
        storage_text = ""
        if "storage_total" in details:
            storage_text = f"Total: {details['storage_total']}, Used: {details['storage_used']}, "
            storage_text += f"Free: {details['storage_available']} ({details['storage_percent']} used)"
        else:
            storage_text = "Unknown"
        self.storage_info_label.setText(storage_text)
    
    def update_connection_status(self, connected):
        for btn in [
            self.reboot_system_btn, self.reboot_recovery_btn, self.reboot_bootloader_btn,
            self.reboot_sideload_btn, self.reboot_download_btn, self.power_off_btn,
            self.screen_on_btn, self.screen_off_btn, self.root_check_btn,
            self.root_grant_btn, self.root_revoke_btn, self.wifi_enable_btn,
            self.wifi_disable_btn, self.wifi_connect_btn
        ]:
            btn.setEnabled(connected)
    
    def power_off_device(self):
        return_code, output = self.device_manager.execute_adb_command("shell reboot -p")
        if return_code == 0:
            QMessageBox.information(self, "Success", "Device is powering off")
        else:
            QMessageBox.warning(self, "Error", f"Failed to power off device: {output}")
    
    def turn_screen_on(self):
        return_code, output = self.device_manager.execute_adb_command("shell input keyevent KEYCODE_POWER")
        if return_code == 0:
            QMessageBox.information(self, "Success", "Screen turned on")
        else:
            QMessageBox.warning(self, "Error", f"Failed to turn screen on: {output}")
    
    def turn_screen_off(self):
        return_code, output = self.device_manager.execute_adb_command("shell input keyevent KEYCODE_POWER")
        if return_code == 0:
            QMessageBox.information(self, "Success", "Screen turned off")
        else:
            QMessageBox.warning(self, "Error", f"Failed to turn screen off: {output}")
    
    def check_root_access(self):
        return_code, output = self.device_manager.execute_adb_command("shell su -c 'echo Root check'")
        if return_code == 0 and "Root check" in output:
            QMessageBox.information(self, "Root Access", "Device has root access")
        else:
            QMessageBox.warning(self, "Root Access", "Device does NOT have root access")
    
    def grant_root_access(self):
        return_code, output = self.device_manager.execute_adb_command("root")
        if return_code == 0:
            QMessageBox.information(self, "Success", "Root access granted. Device may reboot.")
        else:
            QMessageBox.warning(self, "Error", f"Failed to grant root access: {output}")
    
    def revoke_root_access(self):
        return_code, output = self.device_manager.execute_adb_command("unroot")
        if return_code == 0:
            QMessageBox.information(self, "Success", "Root access revoked")
        else:
            QMessageBox.warning(self, "Error", f"Failed to revoke root access: {output}")
    
    def enable_adb_over_wifi(self):
        # Set port to 5555
        return_code, output = self.device_manager.execute_adb_command("shell setprop service.adb.tcp.port 5555")
        if return_code != 0:
            QMessageBox.warning(self, "Error", f"Failed to set ADB port: {output}")
            return
        
        # Restart ADB
        return_code, output = self.device_manager.execute_adb_command("shell stop adbd")
        return_code, output = self.device_manager.execute_adb_command("shell start adbd")
        
        # Get device IP
        return_code, output = self.device_manager.execute_adb_command("shell ip -f inet addr show wlan0")
        ip_match = re.search(r'inet (\d+\.\d+\.\d+\.\d+)', output)
        
        if ip_match:
            ip_address = ip_match.group(1)
            QMessageBox.information(
                self, "ADB over WiFi", 
                f"ADB over WiFi enabled. Connect using:\n\nadb connect {ip_address}:5555"
            )
        else:
            QMessageBox.information(
                self, "ADB over WiFi", 
                "ADB over WiFi enabled but couldn't determine IP address. "
                "Make sure WiFi is connected on the device."
            )
    
    def disable_adb_over_wifi(self):
        # Disable TCP/IP
        return_code, output = self.device_manager.execute_adb_command("shell setprop service.adb.tcp.port -1")
        if return_code != 0:
            QMessageBox.warning(self, "Error", f"Failed to disable ADB over WiFi: {output}")
            return
        
        # Restart ADB
        return_code, output = self.device_manager.execute_adb_command("shell stop adbd")
        return_code, output = self.device_manager.execute_adb_command("shell start adbd")
        
        QMessageBox.information(self, "Success", "ADB over WiFi disabled")
    
    def connect_via_wifi(self):
        # Get device IP
        return_code, output = self.device_manager.execute_adb_command("shell ip -f inet addr show wlan0")
        ip_match = re.search(r'inet (\d+\.\d+\.\d+\.\d+)', output)
        
        if ip_match:
            ip_address = ip_match.group(1)
            return_code, output = self.device_manager.execute_adb_command(f"tcpip 5555", device_specific=False)
            return_code, output = self.device_manager.execute_adb_command(f"connect {ip_address}:5555", device_specific=False)
            
            if return_code == 0:
                QMessageBox.information(self, "Success", f"Connected to {ip_address}:5555")
            else:
                QMessageBox.warning(self, "Error", f"Failed to connect: {output}")
        else:
            QMessageBox.warning(self, "Error", "Could not determine device IP address. Make sure WiFi is connected.")

class FileExplorerTab(QWidget):
    def __init__(self, device_manager, file_manager):
        super().__init__()
        self.device_manager = device_manager
        self.file_manager = file_manager
        self.current_remote_path = "/"
        self.current_local_path = os.path.expanduser("~")
        self.init_ui()
        
        # Connect signals
        self.file_manager.file_transfer_progress.connect(self.update_progress)
        self.file_manager.file_operation_complete.connect(self.file_operation_completed)
        
        # Load initial directories
        self.refresh_remote_directory()
        self.refresh_local_directory()
    
    def init_ui(self):
        main_layout = QHBoxLayout()
        splitter = QSplitter(Qt.Orientation.Horizontal)
        
        # Remote (Device) File System
        remote_group = QGroupBox("Device File System")
        remote_layout = QVBoxLayout()
        
        self.remote_path_edit = QLineEdit(self.current_remote_path)
        self.remote_path_edit.returnPressed.connect(self.navigate_remote)
        
        self.remote_up_btn = QPushButton("Up")
        self.remote_up_btn.clicked.connect(self.remote_up)
        
        path_layout = QHBoxLayout()
        path_layout.addWidget(self.remote_path_edit)
        path_layout.addWidget(self.remote_up_btn)
        
        self.remote_files_tree = QTreeWidget()
        self.remote_files_tree.setHeaderLabels(["Name", "Size", "Permissions", "Owner"])
        self.remote_files_tree.setColumnWidth(0, 250)
        self.remote_files_tree.itemDoubleClicked.connect(self.remote_item_double_clicked)
        
        remote_btn_layout = QHBoxLayout()
        self.remote_refresh_btn = QPushButton("Refresh")
        self.remote_refresh_btn.clicked.connect(self.refresh_remote_directory)
        self.remote_pull_btn = QPushButton("Pull")
        self.remote_pull_btn.clicked.connect(self.pull_file)
        self.remote_delete_btn = QPushButton("Delete")
        self.remote_delete_btn.clicked.connect(self.delete_remote_file)
        
        remote_btn_layout.addWidget(self.remote_refresh_btn)
        remote_btn_layout.addWidget(self.remote_pull_btn)
        remote_btn_layout.addWidget(self.remote_delete_btn)
        
        remote_layout.addLayout(path_layout)
        remote_layout.addWidget(self.remote_files_tree)
        remote_layout.addLayout(remote_btn_layout)
        remote_group.setLayout(remote_layout)
        
        # Local File System
        local_group = QGroupBox("Local File System")
        local_layout = QVBoxLayout()
        
        self.local_path_edit = QLineEdit(self.current_local_path)
        self.local_path_edit.returnPressed.connect(self.navigate_local)
        
        self.local_up_btn = QPushButton("Up")
        self.local_up_btn.clicked.connect(self.local_up)
        
        local_path_layout = QHBoxLayout()
        local_path_layout.addWidget(self.local_path_edit)
        local_path_layout.addWidget(self.local_up_btn)
        
        self.local_files_tree = QTreeWidget()
        self.local_files_tree.setHeaderLabels(["Name", "Size", "Type", "Modified"])
        self.local_files_tree.setColumnWidth(0, 250)
        self.local_files_tree.itemDoubleClicked.connect(self.local_item_double_clicked)
        
        local_btn_layout = QHBoxLayout()
        self.local_refresh_btn = QPushButton("Refresh")
        self.local_refresh_btn.clicked.connect(self.refresh_local_directory)
        self.local_push_btn = QPushButton("Push")
        self.local_push_btn.clicked.connect(self.push_file)
        self.local_delete_btn = QPushButton("Delete")
        self.local_delete_btn.clicked.connect(self.delete_local_file)
        
        local_btn_layout.addWidget(self.local_refresh_btn)
        local_btn_layout.addWidget(self.local_push_btn)
        local_btn_layout.addWidget(self.local_delete_btn)
        
        local_layout.addLayout(local_path_layout)
        local_layout.addWidget(self.local_files_tree)
        local_layout.addLayout(local_btn_layout)
        local_group.setLayout(local_layout)
        
        # Progress bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        self.progress_label = QLabel()
        self.progress_label.setVisible(False)
        
        # Add to splitter
        splitter.addWidget(remote_group)
        splitter.addWidget(local_group)
        
        # Main layout
        main_layout.addWidget(splitter)
        
        # Overall layout
        overall_layout = QVBoxLayout()
        overall_layout.addLayout(main_layout)
        overall_layout.addWidget(self.progress_label)
        overall_layout.addWidget(self.progress_bar)
        
        self.setLayout(overall_layout)
        
        # Context menus
        self.remote_files_tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.remote_files_tree.customContextMenuRequested.connect(self.show_remote_context_menu)
        
        self.local_files_tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.local_files_tree.customContextMenuRequested.connect(self.show_local_context_menu)
    
    def refresh_remote_directory(self):
        if not self.device_manager.current_device:
            QMessageBox.warning(self, "Error", "No device selected")
            return
        
        self.remote_files_tree.clear()
        
        try:
            # List directory contents
            return_code, output = self.device_manager.execute_adb_command(f"shell ls -la {self.current_remote_path}")
            
            if return_code != 0:
                QMessageBox.warning(self, "Error", f"Failed to list directory: {output}")
                return
            
            # Parse ls output
            lines = output.splitlines()
            for line in lines:
                parts = line.split()
                if len(parts) >= 7:  # Typical ls -la output has at least 7 parts
                    permissions = parts[0]
                    owner = parts[2]
                    group = parts[3]
                    size = parts[4]
                    date = " ".join(parts[5:7])
                    name = " ".join(parts[7:])
                    
                    if name in [".", ".."]:
                        continue
                    
                    item = QTreeWidgetItem()
                    item.setText(0, name)
                    item.setText(1, size)
                    item.setText(2, permissions)
                    item.setText(3, f"{owner}/{group}")
                    
                    # Set icon based on type
                    if permissions.startswith("d"):
                        item.setIcon(0, QIcon.fromTheme("folder"))
                    else:
                        item.setIcon(0, QIcon.fromTheme("text-x-generic"))
                    
                    self.remote_files_tree.addTopLevelItem(item)
        except Exception as e:
            QMessageBox.warning(self, "Error", f"Failed to refresh remote directory: {str(e)}")
    
    def refresh_local_directory(self):
        self.local_files_tree.clear()
        
        try:
            for entry in os.listdir(self.current_local_path):
                full_path = os.path.join(self.current_local_path, entry)
                stat = os.stat(full_path)
                
                item = QTreeWidgetItem()
                item.setText(0, entry)
                
                if os.path.isdir(full_path):
                    item.setText(1, "")
                    item.setText(2, "Folder")
                    item.setIcon(0, QIcon.fromTheme("folder"))
                else:
                    size = stat.st_size
                    item.setText(1, self.format_size(size))
                    item.setText(2, os.path.splitext(entry)[1][1:].upper() + " File" if os.path.splitext(entry)[1] else "File")
                    item.setIcon(0, QIcon.fromTheme("text-x-generic"))
                
                item.setText(3, datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S"))
                self.local_files_tree.addTopLevelItem(item)
        except Exception as e:
            QMessageBox.warning(self, "Error", f"Failed to refresh local directory: {str(e)}")
    
    def format_size(self, size):
        for unit in ['B', 'KB', 'MB', 'GB']:
            if size < 1024.0:
                return f"{size:.2f} {unit}"
            size /= 1024.0
        return f"{size:.2f} TB"
    
    def navigate_remote(self):
        new_path = self.remote_path_edit.text()
        self.current_remote_path = new_path
        self.refresh_remote_directory()
    
    def navigate_local(self):
        new_path = self.local_path_edit.text()
        if os.path.isdir(new_path):
            self.current_local_path = new_path
            self.refresh_local_directory()
        else:
            QMessageBox.warning(self, "Error", "Invalid directory path")
            self.local_path_edit.setText(self.current_local_path)
    
    def remote_up(self):
        if self.current_remote_path == "/":
            return
        
        self.current_remote_path = os.path.dirname(self.current_remote_path.rstrip("/")) or "/"
        self.remote_path_edit.setText(self.current_remote_path)
        self.refresh_remote_directory()
    
    def local_up(self):
        parent = os.path.dirname(self.current_local_path)
        if parent != self.current_local_path:  # Prevent infinite loop at root
            self.current_local_path = parent
            self.local_path_edit.setText(self.current_local_path)
            self.refresh_local_directory()
    
    def remote_item_double_clicked(self, item, column):
        name = item.text(0)
        if item.text(2).startswith("d"):  # It's a directory
            new_path = os.path.join(self.current_remote_path, name).replace("\\", "/")
            self.current_remote_path = new_path
            self.remote_path_edit.setText(new_path)
            self.refresh_remote_directory()
    
    def local_item_double_clicked(self, item, column):
        name = item.text(0)
        full_path = os.path.join(self.current_local_path, name)
        
        if os.path.isdir(full_path):
            self.current_local_path = full_path
            self.local_path_edit.setText(full_path)
            self.refresh_local_directory()
    
    def pull_file(self):
        selected_items = self.remote_files_tree.selectedItems()
        if not selected_items:
            QMessageBox.warning(self, "Error", "No file selected")
            return
        
        item = selected_items[0]
        if item.text(2).startswith("d"):
            QMessageBox.warning(self, "Error", "Cannot pull a directory (use ADB pull manually)")
            return
        
        remote_file = os.path.join(self.current_remote_path, item.text(0)).replace("\\", "/")
        local_file = os.path.join(self.current_local_path, item.text(0))
        
        # Ask for destination
        file_path, _ = QFileDialog.getSaveFileName(
            self, "Save File", local_file, "All Files (*)"
        )
        
        if file_path:
            self.progress_bar.setValue(0)
            self.progress_bar.setVisible(True)
            self.progress_label.setText(f"Pulling {remote_file}...")
            self.progress_label.setVisible(True)
            
            self.file_manager.pull_file(remote_file, file_path)
    
    def push_file(self):
        selected_items = self.local_files_tree.selectedItems()
        if not selected_items:
            QMessageBox.warning(self, "Error", "No file selected")
            return
        
        item = selected_items[0]
        if item.text(2) == "Folder":
            QMessageBox.warning(self, "Error", "Cannot push a directory (use ADB push manually)")
            return
        
        local_file = os.path.join(self.current_local_path, item.text(0))
        remote_file = os.path.join(self.current_remote_path, item.text(0)).replace("\\", "/")
        
        self.progress_bar.setValue(0)
        self.progress_bar.setVisible(True)
        self.progress_label.setText(f"Pushing {local_file}...")
        self.progress_label.setVisible(True)
        
        self.file_manager.push_file(local_file, remote_file)
    
    def delete_remote_file(self):
        selected_items = self.remote_files_tree.selectedItems()
        if not selected_items:
            QMessageBox.warning(self, "Error", "No file selected")
            return
        
        item = selected_items[0]
        name = item.text(0)
        path = os.path.join(self.current_remote_path, name).replace("\\", "/")
        
        confirm = QMessageBox.question(
            self, "Confirm Delete", 
            f"Are you sure you want to delete {path} from the device?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        
        if confirm == QMessageBox.StandardButton.Yes:
            if item.text(2).startswith("d"):
                return_code, output = self.device_manager.execute_adb_command(f"shell rm -r {path}")
            else:
                return_code, output = self.device_manager.execute_adb_command(f"shell rm {path}")
            
            if return_code == 0:
                QMessageBox.information(self, "Success", f"Deleted {path}")
                self.refresh_remote_directory()
            else:
                QMessageBox.warning(self, "Error", f"Failed to delete: {output}")
    
    def delete_local_file(self):
        selected_items = self.local_files_tree.selectedItems()
        if not selected_items:
            QMessageBox.warning(self, "Error", "No file selected")
            return
        
        item = selected_items[0]
        name = item.text(0)
        path = os.path.join(self.current_local_path, name)
        
        confirm = QMessageBox.question(
            self, "Confirm Delete", 
            f"Are you sure you want to delete {path}?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        
        if confirm == QMessageBox.StandardButton.Yes:
            try:
                if item.text(2) == "Folder":
                    shutil.rmtree(path)
                else:
                    os.remove(path)
                
                QMessageBox.information(self, "Success", f"Deleted {path}")
                self.refresh_local_directory()
            except Exception as e:
                QMessageBox.warning(self, "Error", f"Failed to delete: {str(e)}")
    
    def update_progress(self, progress, message):
        self.progress_bar.setValue(progress)
        self.progress_label.setText(message)
    
    def file_operation_completed(self, success, message):
        self.progress_bar.setVisible(False)
        self.progress_label.setVisible(False)
        
        if success:
            QMessageBox.information(self, "Success", message)
            self.refresh_remote_directory()
            self.refresh_local_directory()
        else:
            QMessageBox.warning(self, "Error", message)
    
    def show_remote_context_menu(self, position):
        item = self.remote_files_tree.itemAt(position)
        if not item:
            return
        
        menu = QMenu()
        
        name = item.text(0)
        path = os.path.join(self.current_remote_path, name).replace("\\", "/")
        is_dir = item.text(2).startswith("d")
        
        if is_dir:
            open_action = menu.addAction("Open Directory")
            open_action.triggered.connect(lambda: self.remote_item_double_clicked(item, 0))
        else:
            open_action = menu.addAction("View File")
            open_action.triggered.connect(lambda: self.view_remote_file(path))
        
        pull_action = menu.addAction("Pull to Local")
        pull_action.triggered.connect(self.pull_file)
        
        delete_action = menu.addAction("Delete")
        delete_action.triggered.connect(self.delete_remote_file)
        
        if not is_dir:
            prop_action = menu.addAction("Properties")
            prop_action.triggered.connect(lambda: self.show_remote_file_properties(item))
        
        menu.exec(self.remote_files_tree.viewport().mapToGlobal(position))
    
    def show_local_context_menu(self, position):
        item = self.local_files_tree.itemAt(position)
        if not item:
            return
        
        menu = QMenu()
        
        name = item.text(0)
        path = os.path.join(self.current_local_path, name)
        is_dir = item.text(2) == "Folder"
        
        if is_dir:
            open_action = menu.addAction("Open Directory")
            open_action.triggered.connect(lambda: self.local_item_double_clicked(item, 0))
        else:
            open_action = menu.addAction("Open File")
            open_action.triggered.connect(lambda: self.open_local_file(path))
        
        push_action = menu.addAction("Push to Device")
        push_action.triggered.connect(self.push_file)
        
        delete_action = menu.addAction("Delete")
        delete_action.triggered.connect(self.delete_local_file)
        
        if not is_dir:
            prop_action = menu.addAction("Properties")
            prop_action.triggered.connect(lambda: self.show_local_file_properties(item))
        
        menu.exec(self.local_files_tree.viewport().mapToGlobal(position))
    
    def view_remote_file(self, path):
        # Create a temporary file
        temp_dir = tempfile.gettempdir()
        temp_file = os.path.join(temp_dir, os.path.basename(path))
        
        self.progress_bar.setValue(0)
        self.progress_bar.setVisible(True)
        self.progress_label.setText(f"Downloading {path} for viewing...")
        self.progress_label.setVisible(True)
        
        # Pull the file to temp location
        self.file_manager.pull_file(path, temp_file)
        
        # Open the file with default application (handled in file_operation_completed)
    
    def open_local_file(self, path):
        try:
            if sys.platform == "win32":
                os.startfile(path)
            elif sys.platform == "darwin":
                subprocess.run(["open", path])
            else:
                subprocess.run(["xdg-open", path])
        except Exception as e:
            QMessageBox.warning(self, "Error", f"Failed to open file: {str(e)}")
    
    def show_remote_file_properties(self, item):
        name = item.text(0)
        size = item.text(1)
        permissions = item.text(2)
        owner = item.text(3)
    
        # Zuerst den Pfad erstellen und formatieren
        file_path = os.path.join(self.current_remote_path, name).replace("\\", "/")
    
        msg = QMessageBox()
        msg.setWindowTitle("File Properties")
        msg.setText(f"""
        <b>Name:</b> {name}<br>
        <b>Size:</b> {size}<br>
        <b>Permissions:</b> {permissions}<br>
        <b>Owner/Group:</b> {owner}<br>
        <b>Path:</b> {file_path}
        """)
        msg.exec()
    
    def show_local_file_properties(self, item):
        name = item.text(0)
        size = item.text(1)
        file_type = item.text(2)
        modified = item.text(3)
        path = os.path.join(self.current_local_path, name)
        
        try:
            stat = os.stat(path)
            created = datetime.fromtimestamp(stat.st_ctime).strftime("%Y-%m-%d %H:%M:%S")
        except:
            created = "Unknown"
        
        msg = QMessageBox()
        msg.setWindowTitle("File Properties")
        msg.setText(f"""
        <b>Name:</b> {name}<br>
        <b>Size:</b> {size}<br>
        <b>Type:</b> {file_type}<br>
        <b>Modified:</b> {modified}<br>
        <b>Created:</b> {created}<br>
        <b>Path:</b> {path}
        """)
        msg.exec()

class PackageManagerTab(QWidget):
    def __init__(self, device_manager, package_manager):
        super().__init__()
        self.device_manager = device_manager
        self.package_manager = package_manager
        self.init_ui()
        
        # Connect signals
        self.package_manager.package_list_updated.connect(self.update_package_list)
        self.package_manager.package_operation_complete.connect(self.package_operation_result)
        
        # Load initial package list
        self.refresh_packages()
    
    def init_ui(self):
        layout = QVBoxLayout()
        
        # Package Filter Group
        filter_group = QGroupBox("Package Filter")
        filter_layout = QHBoxLayout()
        
        self.filter_edit = QLineEdit()
        self.filter_edit.setPlaceholderText("Filter packages...")
        self.filter_edit.textChanged.connect(self.filter_packages)
        
        self.system_check = QCheckBox("System")
        self.third_party_check = QCheckBox("Third Party")
        self.enabled_check = QCheckBox("Enabled")
        self.disabled_check = QCheckBox("Disabled")
        
        filter_layout.addWidget(QLabel("Filter:"))
        filter_layout.addWidget(self.filter_edit)
        filter_layout.addWidget(self.system_check)
        filter_layout.addWidget(self.third_party_check)
        filter_layout.addWidget(self.enabled_check)
        filter_layout.addWidget(self.disabled_check)
        
        filter_group.setLayout(filter_layout)
        
        # Package List Group
        package_group = QGroupBox("Packages")
        package_layout = QVBoxLayout()
        
        self.package_list = QListWidget()
        self.package_list.setSelectionMode(QListWidget.SelectionMode.MultiSelection)
        
        package_btn_layout = QHBoxLayout()
        self.refresh_btn = QPushButton("Refresh")
        self.install_btn = QPushButton("Install APK")
        self.uninstall_btn = QPushButton("Uninstall")
        self.clear_data_btn = QPushButton("Clear Data")
        self.enable_btn = QPushButton("Enable")
        self.disable_btn = QPushButton("Disable")
        self.info_btn = QPushButton("Info")
        
        self.refresh_btn.clicked.connect(self.refresh_packages)
        self.install_btn.clicked.connect(self.install_package)
        self.uninstall_btn.clicked.connect(self.uninstall_package)
        self.clear_data_btn.clicked.connect(self.clear_package_data)
        self.enable_btn.clicked.connect(self.enable_package)
        self.disable_btn.clicked.connect(self.disable_package)
        self.info_btn.clicked.connect(self.show_package_info)
        
        package_btn_layout.addWidget(self.refresh_btn)
        package_btn_layout.addWidget(self.install_btn)
        package_btn_layout.addWidget(self.uninstall_btn)
        package_btn_layout.addWidget(self.clear_data_btn)
        package_btn_layout.addWidget(self.enable_btn)
        package_btn_layout.addWidget(self.disable_btn)
        package_btn_layout.addWidget(self.info_btn)
        
        package_layout.addWidget(self.package_list)
        package_layout.addLayout(package_btn_layout)
        package_group.setLayout(package_layout)
        
        # Package Info Group
        info_group = QGroupBox("Package Information")
        info_layout = QVBoxLayout()
        
        self.info_text = QTextEdit()
        self.info_text.setReadOnly(True)
        
        info_layout.addWidget(self.info_text)
        info_group.setLayout(info_layout)
        
        # Add all groups to main layout
        layout.addWidget(filter_group)
        layout.addWidget(package_group)
        layout.addWidget(info_group)
        
        self.setLayout(layout)
        
        # Context menu
        self.package_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.package_list.customContextMenuRequested.connect(self.show_package_context_menu)
    
    def refresh_packages(self):
        system_only = self.system_check.isChecked()
        third_party_only = self.third_party_check.isChecked()
        enabled_only = self.enabled_check.isChecked()
        disabled_only = self.disabled_check.isChecked()
        
        self.package_manager.get_installed_packages(
            system_only=system_only,
            third_party_only=third_party_only,
            enabled_only=enabled_only,
            disabled_only=disabled_only
        )
    
    def update_package_list(self, packages):
        self.package_list.clear()
        self.package_list.addItems(packages)
        self.filter_packages()
    
    def filter_packages(self):
        filter_text = self.filter_edit.text().lower()
        
        for i in range(self.package_list.count()):
            item = self.package_list.item(i)
            item.setHidden(filter_text not in item.text().lower())
    
    def install_package(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Select APK File", "", "APK Files (*.apk);;All Files (*)"
        )
        
        if file_path:
            options = QMessageBox()
            options.setWindowTitle("Install Options")
            options.setText("Select install options:")
            
            replace_existing = QCheckBox("Replace existing")
            grant_permissions = QCheckBox("Grant all permissions")
            test_only = QCheckBox("Test only (don't actually install)")
            
            layout = options.layout()
            if layout is not None:
                layout.addWidget(replace_existing, 1, 0, 1, 2)
                layout.addWidget(grant_permissions, 2, 0, 1, 2)
                layout.addWidget(test_only, 3, 0, 1, 2)
            
            options.addButton("Install", QMessageBox.ButtonRole.AcceptRole)
            options.addButton("Cancel", QMessageBox.ButtonRole.RejectRole)
            
            options.exec()
            
            if options.clickedButton().text() == "Install":
                self.package_manager.install_package(
                    file_path,
                    replace_existing=replace_existing.isChecked(),
                    grant_all_permissions=grant_permissions.isChecked(),
                    test_only=test_only.isChecked()
                )
    
    def uninstall_package(self):
        selected_items = self.package_list.selectedItems()
        if not selected_items:
            QMessageBox.warning(self, "Error", "No packages selected")
            return
        
        package_names = [item.text() for item in selected_items]
        
        confirm = QMessageBox.question(
            self, "Confirm Uninstall", 
            f"Are you sure you want to uninstall {len(package_names)} package(s)?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        
        if confirm == QMessageBox.StandardButton.Yes:
            options = QMessageBox()
            options.setWindowTitle("Uninstall Options")
            options.setText("Select uninstall options:")
            
            keep_data = QCheckBox("Keep data and cache")
            
            layout = options.layout()
            if layout is not None:
                layout.addWidget(keep_data, 1, 0, 1, 2)
            
            options.addButton("Uninstall", QMessageBox.ButtonRole.AcceptRole)
            options.addButton("Cancel", QMessageBox.ButtonRole.RejectRole)
            
            options.exec()
            
            if options.clickedButton().text() == "Uninstall":
                for package in package_names:
                    self.package_manager.uninstall_package(package, keep_data=keep_data.isChecked())
    
    def clear_package_data(self):
        selected_items = self.package_list.selectedItems()
        if not selected_items:
            QMessageBox.warning(self, "Error", "No packages selected")
            return
        
        package_names = [item.text() for item in selected_items]
        
        confirm = QMessageBox.question(
            self, "Confirm Clear Data", 
            f"Are you sure you want to clear data for {len(package_names)} package(s)?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        
        if confirm == QMessageBox.StandardButton.Yes:
            for package in package_names:
                self.package_manager.clear_package_data(package)
    
    def enable_package(self):
        selected_items = self.package_list.selectedItems()
        if not selected_items:
            QMessageBox.warning(self, "Error", "No packages selected")
            return
        
        for item in selected_items:
            self.package_manager.enable_package(item.text())
    
    def disable_package(self):
        selected_items = self.package_list.selectedItems()
        if not selected_items:
            QMessageBox.warning(self, "Error", "No packages selected")
            return
        
        for item in selected_items:
            self.package_manager.disable_package(item.text())
    
    def show_package_info(self):
        selected_items = self.package_list.selectedItems()
        if not selected_items:
            QMessageBox.warning(self, "Error", "No package selected")
            return
        
        package_name = selected_items[0].text()
        success, info = self.package_manager.get_package_info(package_name)
        
        if success:
            info_text = f"""
            <b>Package Name:</b> {info['name']}<br>
            <b>Version:</b> {info['version']}<br>
            <b>UID:</b> {info['uid']}<br>
            <b>Path:</b> {info['path']}<br>
            <b>Status:</b> {'Enabled' if info['enabled'] else 'Disabled'}<br>
            <b>Permissions:</b><br>
            """
            
            for perm in info['permissions']:
                info_text += f"&nbsp;&nbsp;• {perm}<br>"
            
            self.info_text.setHtml(info_text)
        else:
            self.info_text.setPlainText(f"Error getting package info: {info}")
    
    def package_operation_result(self, success, message):
        if success:
            QMessageBox.information(self, "Success", message)
            self.refresh_packages()
        else:
            QMessageBox.warning(self, "Error", message)
    
    def show_package_context_menu(self, position):
        item = self.package_list.itemAt(position)
        if not item:
            return
        
        menu = QMenu()
        
        info_action = menu.addAction("Show Info")
        info_action.triggered.connect(self.show_package_info)
        
        menu.addSeparator()
        
        enable_action = menu.addAction("Enable")
        enable_action.triggered.connect(self.enable_package)
        
        disable_action = menu.addAction("Disable")
        disable_action.triggered.connect(self.disable_package)
        
        menu.addSeparator()
        
        uninstall_action = menu.addAction("Uninstall")
        uninstall_action.triggered.connect(self.uninstall_package)
        
        clear_action = menu.addAction("Clear Data")
        clear_action.triggered.connect(self.clear_package_data)
        
        menu.exec(self.package_list.mapToGlobal(position))

class BackupRestoreTab(QWidget):
    def __init__(self, device_manager, backup_manager):
        super().__init__()
        self.device_manager = device_manager
        self.backup_manager = backup_manager
        self.init_ui()
        
        # Connect signals
        self.backup_manager.backup_progress.connect(self.update_progress)
        self.backup_manager.backup_complete.connect(self.backup_completed)
    
    def init_ui(self):
        layout = QVBoxLayout()
        
        # Backup Group
        backup_group = QGroupBox("Backup")
        backup_layout = QVBoxLayout()
        
        self.backup_path_edit = QLineEdit()
        self.backup_path_edit.setPlaceholderText("Select backup file path...")
        
        self.backup_browse_btn = QPushButton("Browse...")
        self.backup_browse_btn.clicked.connect(self.select_backup_path)
        
        path_layout = QHBoxLayout()
        path_layout.addWidget(self.backup_path_edit)
        path_layout.addWidget(self.backup_browse_btn)
        
        self.include_apks_check = QCheckBox("Include APKs")
        self.include_shared_check = QCheckBox("Include Shared Storage")
        self.include_system_check = QCheckBox("Include System Apps")
        self.all_apps_check = QCheckBox("Backup All Apps")
        
        self.backup_btn = QPushButton("Create Backup")
        self.backup_btn.clicked.connect(self.create_backup)
        
        backup_layout.addLayout(path_layout)
        backup_layout.addWidget(self.include_apks_check)
        backup_layout.addWidget(self.include_shared_check)
        backup_layout.addWidget(self.include_system_check)
        backup_layout.addWidget(self.all_apps_check)
        backup_layout.addWidget(self.backup_btn)
        backup_group.setLayout(backup_layout)
        
        # Restore Group
        restore_group = QGroupBox("Restore")
        restore_layout = QVBoxLayout()
        
        self.restore_path_edit = QLineEdit()
        self.restore_path_edit.setPlaceholderText("Select backup file to restore...")
        
        self.restore_browse_btn = QPushButton("Browse...")
        self.restore_browse_btn.clicked.connect(self.select_restore_path)
        
        restore_path_layout = QHBoxLayout()
        restore_path_layout.addWidget(self.restore_path_edit)
        restore_path_layout.addWidget(self.restore_browse_btn)
        
        self.restore_btn = QPushButton("Restore Backup")
        self.restore_btn.clicked.connect(self.restore_backup)
        
        restore_layout.addLayout(restore_path_layout)
        restore_layout.addWidget(self.restore_btn)
        restore_group.setLayout(restore_layout)
        
        # Progress
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        self.progress_label = QLabel()
        self.progress_label.setVisible(False)
        
        # Add all groups to main layout
        layout.addWidget(backup_group)
        layout.addWidget(restore_group)
        layout.addWidget(self.progress_label)
        layout.addWidget(self.progress_bar)
        layout.addStretch()
        
        self.setLayout(layout)
    
    def select_backup_path(self):
        file_path, _ = QFileDialog.getSaveFileName(
            self, "Save Backup File", "", "AB Backup Files (*.ab);;All Files (*)"
        )
        
        if file_path:
            if not file_path.lower().endswith('.ab'):
                file_path += '.ab'
            self.backup_path_edit.setText(file_path)
    
    def select_restore_path(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Select Backup File", "", "AB Backup Files (*.ab);;All Files (*)"
        )
        
        if file_path:
            self.restore_path_edit.setText(file_path)
    
    def create_backup(self):
        backup_path = self.backup_path_edit.text()
        if not backup_path:
            QMessageBox.warning(self, "Error", "Please select a backup file path")
            return
        
        include_apks = self.include_apks_check.isChecked()
        include_shared = self.include_shared_check.isChecked()
        include_system = self.include_system_check.isChecked()
        all_apps = self.all_apps_check.isChecked()
        
        self.progress_bar.setValue(0)
        self.progress_bar.setVisible(True)
        self.progress_label.setText("Creating backup...")
        self.progress_label.setVisible(True)
        
        self.backup_manager.create_backup(
            backup_path,
            include_apks=include_apks,
            include_shared=include_shared,
            include_system=include_system,
            all_apps=all_apps
        )
    
    def restore_backup(self):
        restore_path = self.restore_path_edit.text()
        if not restore_path:
            QMessageBox.warning(self, "Error", "Please select a backup file to restore")
            return
        
        confirm = QMessageBox.question(
            self, "Confirm Restore", 
            "Restoring will overwrite existing data on the device. Continue?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        
        if confirm == QMessageBox.StandardButton.Yes:
            self.progress_bar.setValue(0)
            self.progress_bar.setVisible(True)
            self.progress_label.setText("Restoring backup...")
            self.progress_label.setVisible(True)
            
            self.backup_manager.restore_backup(restore_path)
    
    def update_progress(self, progress, message):
        self.progress_bar.setValue(progress)
        self.progress_label.setText(message)
    
    def backup_completed(self, success, message):
        self.progress_bar.setVisible(False)
        self.progress_label.setVisible(False)
        
        if success:
            QMessageBox.information(self, "Success", message)
        else:
            QMessageBox.warning(self, "Error", message)

class LogcatTab(QWidget):
    def __init__(self, device_manager, logcat_manager):
        super().__init__()
        self.device_manager = device_manager
        self.logcat_manager = logcat_manager
        self.init_ui()
        
        # Connect signals
        self.logcat_manager.log_received.connect(self.append_log)
        self.logcat_manager.log_cleared.connect(self.log_cleared)
    
    def init_ui(self):
        layout = QVBoxLayout()
        
        # Filter Controls
        filter_group = QGroupBox("Logcat Filters")
        filter_layout = QHBoxLayout()
        
        self.priority_combo = QComboBox()
        self.priority_combo.addItems(["Verbose", "Debug", "Info", "Warning", "Error", "Fatal", "Silent"])
        self.priority_combo.setCurrentText("Verbose")
        
        self.tag_edit = QLineEdit()
        self.tag_edit.setPlaceholderText("Tag filter (optional)")
        
        self.pid_edit = QLineEdit()
        self.pid_edit.setPlaceholderText("PID filter (optional)")
        
        filter_layout.addWidget(QLabel("Priority:"))
        filter_layout.addWidget(self.priority_combo)
        filter_layout.addWidget(QLabel("Tag:"))
        filter_layout.addWidget(self.tag_edit)
        filter_layout.addWidget(QLabel("PID:"))
        filter_layout.addWidget(self.pid_edit)
        
        filter_group.setLayout(filter_layout)
        
        # Log Controls
        control_group = QGroupBox("Logcat Controls")
        control_layout = QHBoxLayout()
        
        self.start_btn = QPushButton("Start")
        self.stop_btn = QPushButton("Stop")
        self.clear_btn = QPushButton("Clear")
        self.save_btn = QPushButton("Save")
        
        self.start_btn.clicked.connect(self.start_logcat)
        self.stop_btn.clicked.connect(self.stop_logcat)
        self.clear_btn.clicked.connect(self.clear_logcat)
        self.save_btn.clicked.connect(self.save_logcat)
        
        control_layout.addWidget(self.start_btn)
        control_layout.addWidget(self.stop_btn)
        control_layout.addWidget(self.clear_btn)
        control_layout.addWidget(self.save_btn)
        
        control_group.setLayout(control_layout)
        
        # Log Display
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setFont(QFont("Courier New", 10))
        
        # Add all groups to main layout
        layout.addWidget(filter_group)
        layout.addWidget(control_group)
        layout.addWidget(self.log_text)
        
        self.setLayout(layout)
    
    def start_logcat(self):
        priority = self.priority_combo.currentText().lower()[0]  # V, D, I, W, E, F, S
        tag = self.tag_edit.text().strip()
        pid = self.pid_edit.text().strip()
        
        filters = []
        
        if priority != 'v':  # Verbose is default
            filters.append(f"*:{priority}")
        
        if tag:
            filters.append(f"{tag}:{priority}")
        
        if pid:
            filters.append(f"--pid={pid}")
        
        self.logcat_manager.start_logcat(filters=" ".join(filters) if filters else None)
    
    def stop_logcat(self):
        self.logcat_manager.stop_logcat()
    
    def clear_logcat(self):
        self.logcat_manager.clear_logcat()
    
    def save_logcat(self):
        file_path, _ = QFileDialog.getSaveFileName(
            self, "Save Logcat", "", "Text Files (*.txt);;All Files (*)"
        )
        
        if file_path:
            priority = self.priority_combo.currentText().lower()[0]
            tag = self.tag_edit.text().strip()
            pid = self.pid_edit.text().strip()
            
            filters = []
            
            if priority != 'v':
                filters.append(f"*:{priority}")
            
            if tag:
                filters.append(f"{tag}:{priority}")
            
            if pid:
                filters.append(f"--pid={pid}")
            
            success, message = self.logcat_manager.save_logcat(file_path, filters=" ".join(filters) if filters else None)
            
            if success:
                QMessageBox.information(self, "Success", "Logcat saved successfully")
            else:
                QMessageBox.warning(self, "Error", f"Failed to save logcat: {message}")
    
    def append_log(self, log_line):
        cursor = self.log_text.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        cursor.insertText(log_line + "\n")
        self.log_text.setTextCursor(cursor)
        self.log_text.ensureCursorVisible()
    
    def log_cleared(self, success):
        if success:
            self.log_text.clear()

class FastbootTab(QWidget):
    def __init__(self, device_manager):
        super().__init__()
        self.device_manager = device_manager
        self.init_ui()
    
    def init_ui(self):
        layout = QVBoxLayout()
        
        # Flash Options Group
        flash_group = QGroupBox("Flash Options")
        flash_layout = QVBoxLayout()
        
        # Partitions to flash
        partition_group = QGroupBox("Partitions")
        partition_layout = QGridLayout()
        
        self.boot_check = QCheckBox("boot")
        self.system_check = QCheckBox("system")
        self.vendor_check = QCheckBox("vendor")
        self.recovery_check = QCheckBox("recovery")
        self.cache_check = QCheckBox("cache")
        self.userdata_check = QCheckBox("userdata")
        self.custom_part_edit = QLineEdit()
        self.custom_part_edit.setPlaceholderText("Custom partition")
        
        partition_layout.addWidget(self.boot_check, 0, 0)
        partition_layout.addWidget(self.system_check, 0, 1)
        partition_layout.addWidget(self.vendor_check, 0, 2)
        partition_layout.addWidget(self.recovery_check, 1, 0)
        partition_layout.addWidget(self.cache_check, 1, 1)
        partition_layout.addWidget(self.userdata_check, 1, 2)
        partition_layout.addWidget(QLabel("Custom:"), 2, 0)
        partition_layout.addWidget(self.custom_part_edit, 2, 1, 1, 2)
        
        partition_group.setLayout(partition_layout)
        
        # Image files
        image_group = QGroupBox("Image Files")
        image_layout = QVBoxLayout()
        
        self.boot_img_edit = QLineEdit()
        self.boot_img_edit.setPlaceholderText("boot.img path")
        self.boot_img_browse = QPushButton("Browse...")
        self.boot_img_browse.clicked.connect(lambda: self.browse_image(self.boot_img_edit))
        
        self.system_img_edit = QLineEdit()
        self.system_img_edit.setPlaceholderText("system.img path")
        self.system_img_browse = QPushButton("Browse...")
        self.system_img_browse.clicked.connect(lambda: self.browse_image(self.system_img_edit))
        
        self.vendor_img_edit = QLineEdit()
        self.vendor_img_edit.setPlaceholderText("vendor.img path")
        self.vendor_img_browse = QPushButton("Browse...")
        self.vendor_img_browse.clicked.connect(lambda: self.browse_image(self.vendor_img_edit))
        
        self.recovery_img_edit = QLineEdit()
        self.recovery_img_edit.setPlaceholderText("recovery.img path")
        self.recovery_img_browse = QPushButton("Browse...")
        self.recovery_img_browse.clicked.connect(lambda: self.browse_image(self.recovery_img_edit))
        
        self.cache_img_edit = QLineEdit()
        self.cache_img_edit.setPlaceholderText("cache.img path")
        self.cache_img_browse = QPushButton("Browse...")
        self.cache_img_browse.clicked.connect(lambda: self.browse_image(self.cache_img_edit))
        
        self.userdata_img_edit = QLineEdit()
        self.userdata_img_edit.setPlaceholderText("userdata.img path")
        self.userdata_img_browse = QPushButton("Browse...")
        self.userdata_img_browse.clicked.connect(lambda: self.browse_image(self.userdata_img_edit))
        
        self.custom_img_edit = QLineEdit()
        self.custom_img_edit.setPlaceholderText("Custom image path")
        self.custom_img_browse = QPushButton("Browse...")
        self.custom_img_browse.clicked.connect(lambda: self.browse_image(self.custom_img_edit))
        
        # Add image fields to layout with browse buttons
        def add_image_row(label, edit, browse):
            row = QHBoxLayout()
            row.addWidget(QLabel(label))
            row.addWidget(edit)
            row.addWidget(browse)
            return row
        
        image_layout.addLayout(add_image_row("Boot:", self.boot_img_edit, self.boot_img_browse))
        image_layout.addLayout(add_image_row("System:", self.system_img_edit, self.system_img_browse))
        image_layout.addLayout(add_image_row("Vendor:", self.vendor_img_edit, self.vendor_img_browse))
        image_layout.addLayout(add_image_row("Recovery:", self.recovery_img_edit, self.recovery_img_browse))
        image_layout.addLayout(add_image_row("Cache:", self.cache_img_edit, self.cache_img_browse))
        image_layout.addLayout(add_image_row("Userdata:", self.userdata_img_edit, self.userdata_img_browse))
        image_layout.addLayout(add_image_row("Custom:", self.custom_img_edit, self.custom_img_browse))
        
        image_group.setLayout(image_layout)
        
        # Flash buttons
        flash_btn_layout = QHBoxLayout()
        self.flash_selected_btn = QPushButton("Flash Selected")
        self.flash_selected_btn.clicked.connect(self.flash_selected)
        self.flash_all_btn = QPushButton("Flash All")
        self.flash_all_btn.clicked.connect(self.flash_all)
        
        flash_btn_layout.addWidget(self.flash_selected_btn)
        flash_btn_layout.addWidget(self.flash_all_btn)
        
        # Add to flash group
        flash_layout.addWidget(partition_group)
        flash_layout.addWidget(image_group)
        flash_layout.addLayout(flash_btn_layout)
        flash_group.setLayout(flash_layout)
        
        # Advanced Commands Group
        advanced_group = QGroupBox("Advanced Fastboot Commands")
        advanced_layout = QVBoxLayout()
        
        # Unlock/lock
        unlock_layout = QHBoxLayout()
        self.unlock_btn = QPushButton("Unlock Bootloader")
        self.lock_btn = QPushButton("Lock Bootloader")
        self.unlock_critical_btn = QPushButton("Unlock Critical")
        self.lock_critical_btn = QPushButton("Lock Critical")
        
        self.unlock_btn.clicked.connect(lambda: self.execute_fastboot_command("flashing unlock"))
        self.lock_btn.clicked.connect(lambda: self.execute_fastboot_command("flashing lock"))
        self.unlock_critical_btn.clicked.connect(lambda: self.execute_fastboot_command("flashing unlock_critical"))
        self.lock_critical_btn.clicked.connect(lambda: self.execute_fastboot_command("flashing lock_critical"))
        
        unlock_layout.addWidget(self.unlock_btn)
        unlock_layout.addWidget(self.lock_btn)
        unlock_layout.addWidget(self.unlock_critical_btn)
        unlock_layout.addWidget(self.lock_critical_btn)
        
        # Other commands
        other_layout = QHBoxLayout()
        self.erase_btn = QPushButton("Erase Partition")
        self.format_btn = QPushButton("Format Partition")
        self.boot_btn = QPushButton("Boot Image")
        self.set_active_btn = QPushButton("Set Active Slot")
        
        self.erase_btn.clicked.connect(self.erase_partition)
        self.format_btn.clicked.connect(self.format_partition)
        self.boot_btn.clicked.connect(self.boot_image)
        self.set_active_btn.clicked.connect(self.set_active_slot)
        
        other_layout.addWidget(self.erase_btn)
        other_layout.addWidget(self.format_btn)
        other_layout.addWidget(self.boot_btn)
        other_layout.addWidget(self.set_active_btn)
        
        # Add to advanced group
        advanced_layout.addLayout(unlock_layout)
        advanced_layout.addLayout(other_layout)
        advanced_group.setLayout(advanced_layout)
        
        # Output
        self.output_text = QTextEdit()
        self.output_text.setReadOnly(True)
        self.output_text.setFont(QFont("Courier New", 10))
        
        # Add all groups to main layout
        layout.addWidget(flash_group)
        layout.addWidget(advanced_group)
        layout.addWidget(self.output_text)
        
        self.setLayout(layout)
    
    def browse_image(self, target_edit):
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Select Image File", "", "Image Files (*.img);;All Files (*)"
        )
        
        if file_path:
            target_edit.setText(file_path)
    
    def flash_selected(self):
        partitions = []
        images = []
        
        if self.boot_check.isChecked() and self.boot_img_edit.text():
            partitions.append("boot")
            images.append(self.boot_img_edit.text())
        
        if self.system_check.isChecked() and self.system_img_edit.text():
            partitions.append("system")
            images.append(self.system_img_edit.text())
        
        if self.vendor_check.isChecked() and self.vendor_img_edit.text():
            partitions.append("vendor")
            images.append(self.vendor_img_edit.text())
        
        if self.recovery_check.isChecked() and self.recovery_img_edit.text():
            partitions.append("recovery")
            images.append(self.recovery_img_edit.text())
        
        if self.cache_check.isChecked() and self.cache_img_edit.text():
            partitions.append("cache")
            images.append(self.cache_img_edit.text())
        
        if self.userdata_check.isChecked() and self.userdata_img_edit.text():
            partitions.append("userdata")
            images.append(self.userdata_img_edit.text())
        
        custom_part = self.custom_part_edit.text().strip()
        custom_img = self.custom_img_edit.text().strip()
        if custom_part and custom_img:
            partitions.append(custom_part)
            images.append(custom_img)
        
        if not partitions:
            QMessageBox.warning(self, "Error", "No partitions selected or image paths not specified")
            return
        
        confirm = QMessageBox.question(
            self, "Confirm Flash", 
            f"Are you sure you want to flash {len(partitions)} partition(s)? This cannot be undone!",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        
        if confirm == QMessageBox.StandardButton.Yes:
            self.output_text.clear()
            
            for part, img in zip(partitions, images):
                self.append_output(f"Flashing {part} with {img}...")
                return_code, output = self.device_manager.execute_fastboot_command(f"flash {part} {img}")
                self.append_output(output)
                
                if return_code != 0:
                    self.append_output(f"Failed to flash {part}")
                    break
                else:
                    self.append_output(f"Successfully flashed {part}")
            
            self.append_output("Flash operation completed")
    
    def flash_all(self):
        partitions = ["boot", "system", "vendor", "recovery", "cache", "userdata"]
        images = [
            self.boot_img_edit.text(),
            self.system_img_edit.text(),
            self.vendor_img_edit.text(),
            self.recovery_img_edit.text(),
            self.cache_img_edit.text(),
            self.userdata_img_edit.text()
        ]
        
        # Check if all images are specified
        for img in images:
            if not img:
                QMessageBox.warning(self, "Error", "All image paths must be specified for flash all")
                return
        
        confirm = QMessageBox.question(
            self, "Confirm Flash All", 
            "Are you sure you want to flash ALL partitions? This will wipe your device!",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        
        if confirm == QMessageBox.StandardButton.Yes:
            self.output_text.clear()
            
            for part, img in zip(partitions, images):
                self.append_output(f"Flashing {part} with {img}...")
                return_code, output = self.device_manager.execute_fastboot_command(f"flash {part} {img}")
                self.append_output(output)
                
                if return_code != 0:
                    self.append_output(f"Failed to flash {part}")
                    break
                else:
                    self.append_output(f"Successfully flashed {part}")
            
            self.append_output("Flash all operation completed")
    
    def execute_fastboot_command(self, command):
        if not self.device_manager.current_device:
            QMessageBox.warning(self, "Error", "No device connected in fastboot mode")
            return
        
        confirm = QMessageBox.question(
            self, "Confirm Command", 
            f"Are you sure you want to execute: fastboot {command}?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        
        if confirm == QMessageBox.StandardButton.Yes:
            self.output_text.clear()
            self.append_output(f"Executing: fastboot {command}")
            
            return_code, output = self.device_manager.execute_fastboot_command(command)
            self.append_output(output)
            
            if return_code == 0:
                self.append_output("Command executed successfully")
            else:
                self.append_output("Command failed")
    
    def erase_partition(self):
        partition, ok = QInputDialog.getText(
            self, "Erase Partition", "Enter partition to erase:"
        )
        
        if ok and partition:
            self.execute_fastboot_command(f"erase {partition}")
    
    def format_partition(self):
        partition, ok = QInputDialog.getText(
            self, "Format Partition", "Enter partition to format:"
        )
        
        if ok and partition:
            self.execute_fastboot_command(f"format {partition}")
    
    def boot_image(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Select Boot Image", "", "Image Files (*.img);;All Files (*)"
        )
        
        if file_path:
            self.execute_fastboot_command(f"boot {file_path}")
    
    def set_active_slot(self):
        slot, ok = QInputDialog.getText(
            self, "Set Active Slot", "Enter slot (a or b):"
        )
        
        if ok and slot.lower() in ['a', 'b']:
            self.execute_fastboot_command(f"--set-active={slot.lower()}")
        elif ok:
            QMessageBox.warning(self, "Error", "Slot must be 'a' or 'b'")
    
    def append_output(self, text):
        cursor = self.output_text.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        cursor.insertText(text + "\n")
        self.output_text.setTextCursor(cursor)
        self.output_text.ensureCursorVisible()

class SideloadTab(QWidget):
    def __init__(self, device_manager):
        super().__init__()
        self.device_manager = device_manager
        self.init_ui()
    
    def init_ui(self):
        layout = QVBoxLayout()
        
        # Sideload Group
        sideload_group = QGroupBox("Sideload")
        sideload_layout = QVBoxLayout()
        
        self.sideload_path_edit = QLineEdit()
        self.sideload_path_edit.setPlaceholderText("Select ZIP file to sideload...")
        
        self.sideload_browse_btn = QPushButton("Browse...")
        self.sideload_browse_btn.clicked.connect(self.select_sideload_file)
        
        path_layout = QHBoxLayout()
        path_layout.addWidget(self.sideload_path_edit)
        path_layout.addWidget(self.sideload_browse_btn)
        
        self.sideload_btn = QPushButton("Start Sideload")
        self.sideload_btn.clicked.connect(self.start_sideload)
        
        self.output_text = QTextEdit()
        self.output_text.setReadOnly(True)
        self.output_text.setFont(QFont("Courier New", 10))
        
        sideload_layout.addLayout(path_layout)
        sideload_layout.addWidget(self.sideload_btn)
        sideload_layout.addWidget(self.output_text)
        sideload_group.setLayout(sideload_layout)
        
        # ADB Sideload Group
        adb_sideload_group = QGroupBox("ADB Sideload")
        adb_sideload_layout = QVBoxLayout()
        
        self.adb_sideload_path_edit = QLineEdit()
        self.adb_sideload_path_edit.setPlaceholderText("Select ZIP file for ADB sideload...")
        
        self.adb_sideload_browse_btn = QPushButton("Browse...")
        self.adb_sideload_browse_btn.clicked.connect(self.select_adb_sideload_file)
        
        adb_path_layout = QHBoxLayout()
        adb_path_layout.addWidget(self.adb_sideload_path_edit)
        adb_path_layout.addWidget(self.adb_sideload_browse_btn)
        
        self.adb_sideload_btn = QPushButton("Start ADB Sideload")
        self.adb_sideload_btn.clicked.connect(self.start_adb_sideload)
        
        adb_sideload_layout.addLayout(adb_path_layout)
        adb_sideload_layout.addWidget(self.adb_sideload_btn)
        adb_sideload_group.setLayout(adb_sideload_layout)
        
        # Add all groups to main layout
        layout.addWidget(sideload_group)
        layout.addWidget(adb_sideload_group)
        layout.addStretch()
        
        self.setLayout(layout)
    
    def select_sideload_file(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Select ZIP File", "", "ZIP Files (*.zip);;All Files (*)"
        )
        
        if file_path:
            self.sideload_path_edit.setText(file_path)
    
    def select_adb_sideload_file(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Select ZIP File", "", "ZIP Files (*.zip);;All Files (*)"
        )
        
        if file_path:
            self.adb_sideload_path_edit.setText(file_path)
    
    def start_sideload(self):
        file_path = self.sideload_path_edit.text()
        if not file_path:
            QMessageBox.warning(self, "Error", "No file selected")
            return
        
        if not os.path.isfile(file_path):
            QMessageBox.warning(self, "Error", "File does not exist")
            return
        
        confirm = QMessageBox.question(
            self, "Confirm Sideload", 
            "This will reboot your device to sideload mode and install the selected ZIP. Continue?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        
        if confirm == QMessageBox.StandardButton.Yes:
            self.output_text.clear()
            self.append_output("Rebooting to sideload mode...")
            
            # Reboot to sideload
            success, output = self.device_manager.reboot_device("sideload")
            self.append_output(output)
            
            if not success:
                self.append_output("Failed to reboot to sideload mode")
                return
            
            # Wait for device to enter sideload mode
            self.append_output("Waiting for device to enter sideload mode...")
            time.sleep(10)
            
            # Start sideload
            self.append_output(f"Sideloading {file_path}...")
            return_code, output = self.device_manager.execute_adb_command(f"sideload {file_path}", device_specific=False)
            self.append_output(output)
            
            if return_code == 0:
                self.append_output("Sideload completed successfully")
            else:
                self.append_output("Sideload failed")
    
    def start_adb_sideload(self):
        file_path = self.adb_sideload_path_edit.text()
        if not file_path:
            QMessageBox.warning(self, "Error", "No file selected")
            return
        
        if not os.path.isfile(file_path):
            QMessageBox.warning(self, "Error", "File does not exist")
            return
        
        confirm = QMessageBox.question(
            self, "Confirm ADB Sideload", 
            "This will install the selected ZIP using ADB sideload. Continue?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        
        if confirm == QMessageBox.StandardButton.Yes:
            self.output_text.clear()
            self.append_output(f"Sideloading {file_path}...")
            
            return_code, output = self.device_manager.execute_adb_command(f"sideload {file_path}", device_specific=False)
            self.append_output(output)
            
            if return_code == 0:
                self.append_output("ADB sideload completed successfully")
            else:
                self.append_output("ADB sideload failed")
    
    def append_output(self, text):
        cursor = self.output_text.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        cursor.insertText(text + "\n")
        self.output_text.setTextCursor(cursor)
        self.output_text.ensureCursorVisible()

class RootToolsTab(QWidget):
    def __init__(self, device_manager):
        super().__init__()
        self.device_manager = device_manager
        self.init_ui()
    
    def init_ui(self):
        layout = QVBoxLayout()
        
        # Root Access Group
        root_group = QGroupBox("Root Access")
        root_layout = QVBoxLayout()
        
        self.root_status_label = QLabel("Root status: Unknown")
        self.root_status_label.setStyleSheet("font-weight: bold;")
        
        self.check_root_btn = QPushButton("Check Root Access")
        self.check_root_btn.clicked.connect(self.check_root_access)
        
        self.grant_root_btn = QPushButton("Grant Temporary Root")
        self.grant_root_btn.clicked.connect(self.grant_temp_root)
        
        self.install_su_btn = QPushButton("Install SuperSU")
        self.install_su_btn.clicked.connect(self.install_supersu)
        
        self.install_magisk_btn = QPushButton("Install Magisk")
        self.install_magisk_btn.clicked.connect(self.install_magisk)
        
        self.unroot_btn = QPushButton("Remove Root")
        self.unroot_btn.clicked.connect(self.remove_root)
        
        root_btn_layout = QHBoxLayout()
        root_btn_layout.addWidget(self.check_root_btn)
        root_btn_layout.addWidget(self.grant_root_btn)
        
        install_btn_layout = QHBoxLayout()
        install_btn_layout.addWidget(self.install_su_btn)
        install_btn_layout.addWidget(self.install_magisk_btn)
        
        root_layout.addWidget(self.root_status_label)
        root_layout.addLayout(root_btn_layout)
        root_layout.addLayout(install_btn_layout)
        root_layout.addWidget(self.unroot_btn)
        root_group.setLayout(root_layout)
        
        # System Modification Group
        system_group = QGroupBox("System Modifications")
        system_layout = QVBoxLayout()
        
        self.mount_system_btn = QPushButton("Mount /system as RW")
        self.mount_system_btn.clicked.connect(self.mount_system_rw)
        
        self.remount_btn = QPushButton("Remount Partitions")
        self.remount_btn.clicked.connect(self.remount_partitions)
        
        self.push_system_btn = QPushButton("Push File to /system")
        self.push_system_btn.clicked.connect(self.push_to_system)
        
        self.pull_system_btn = QPushButton("Pull File from /system")
        self.pull_system_btn.clicked.connect(self.pull_from_system)
        
        system_btn_layout = QHBoxLayout()
        system_btn_layout.addWidget(self.mount_system_btn)
        system_btn_layout.addWidget(self.remount_btn)
        
        system_file_layout = QHBoxLayout()
        system_file_layout.addWidget(self.push_system_btn)
        system_file_layout.addWidget(self.pull_system_btn)
        
        system_layout.addLayout(system_btn_layout)
        system_layout.addLayout(system_file_layout)
        system_group.setLayout(system_layout)
        
        # Advanced Root Commands
        advanced_group = QGroupBox("Advanced Root Commands")
        advanced_layout = QVBoxLayout()
        
        self.root_shell_btn = QPushButton("Open Root Shell")
        self.root_shell_btn.clicked.connect(self.open_root_shell)
        
        self.fix_permissions_btn = QPushButton("Fix Permissions")
        self.fix_permissions_btn.clicked.connect(self.fix_permissions)
        
        self.install_busybox_btn = QPushButton("Install BusyBox")
        self.install_busybox_btn.clicked.connect(self.install_busybox)
        
        advanced_layout.addWidget(self.root_shell_btn)
        advanced_layout.addWidget(self.fix_permissions_btn)
        advanced_layout.addWidget(self.install_busybox_btn)
        advanced_group.setLayout(advanced_layout)
        
        # Output
        self.output_text = QTextEdit()
        self.output_text.setReadOnly(True)
        self.output_text.setFont(QFont("Courier New", 10))
        
        # Add all groups to main layout
        layout.addWidget(root_group)
        layout.addWidget(system_group)
        layout.addWidget(advanced_group)
        layout.addWidget(self.output_text)
        
        self.setLayout(layout)
    
    def check_root_access(self):
        return_code, output = self.device_manager.execute_adb_command("shell su -c 'echo Root check'")
        if return_code == 0 and "Root check" in output:
            self.root_status_label.setText("Root status: Root access available")
            self.root_status_label.setStyleSheet("color: green; font-weight: bold;")
        else:
            self.root_status_label.setText("Root status: No root access")
            self.root_status_label.setStyleSheet("color: red; font-weight: bold;")
    
    def grant_temp_root(self):
        return_code, output = self.device_manager.execute_adb_command("root")
        self.append_output(output)
        
        if return_code == 0:
            QMessageBox.information(self, "Success", "Temporary root access granted. Device may reboot.")
        else:
            QMessageBox.warning(self, "Error", "Failed to grant temporary root access")
    
    def install_supersu(self):
        # Check if SuperSU is already installed
        return_code, output = self.device_manager.execute_adb_command("shell su -c 'which su'")
        if return_code == 0 and "/su" in output:
            QMessageBox.information(self, "Info", "SuperSU is already installed")
            return
        
        # Download SuperSU
        url = "https://supersu.com/download"
        self.append_output(f"Downloading SuperSU from {url}...")
        
        try:
            response = requests.get(url)
            if response.status_code == 200:
                # Save to temp file
                temp_dir = tempfile.gettempdir()
                zip_path = os.path.join(temp_dir, "supersu.zip")
                
                with open(zip_path, "wb") as f:
                    f.write(response.content)
                
                self.append_output("SuperSU downloaded, installing...")
                
                # Push to device
                return_code, output = self.device_manager.execute_adb_command(f"push {zip_path} /sdcard/supersu.zip")
                self.append_output(output)
                
                if return_code != 0:
                    self.append_output("Failed to push SuperSU to device")
                    return
                
                # Flash in recovery
                success, output = self.device_manager.reboot_device("recovery")
                self.append_output(output)
                
                if not success:
                    self.append_output("Failed to reboot to recovery")
                    return
                
                # Wait for recovery
                self.append_output("Waiting for device to enter recovery...")
                time.sleep(10)
                
                # Install
                return_code, output = self.device_manager.execute_adb_command("shell twrp install /sdcard/supersu.zip", device_specific=False)
                self.append_output(output)
                
                if return_code == 0:
                    self.append_output("SuperSU installed successfully")
                else:
                    self.append_output("Failed to install SuperSU")
            else:
                self.append_output(f"Failed to download SuperSU: HTTP {response.status_code}")
        except Exception as e:
            self.append_output(f"Error installing SuperSU: {str(e)}")
    
    def install_magisk(self):
        # Check if Magisk is already installed
        return_code, output = self.device_manager.execute_adb_command("shell su -c 'which magisk'")
        if return_code == 0 and "/magisk" in output:
            QMessageBox.information(self, "Info", "Magisk is already installed")
            return
        
        # Download Magisk
        url = "https://github.com/topjohnwu/Magisk/releases/latest"
        self.append_output(f"Downloading Magisk from {url}...")
        
        try:
            response = requests.get(url)
            if response.status_code == 200:
                # Find latest release zip
                # Note: This is simplified - in reality you'd need to parse the releases page
                download_url = "https://github.com/topjohnwu/Magisk/releases/download/v23.0/Magisk-v23.0.apk"
                
                # Save to temp file
                temp_dir = tempfile.gettempdir()
                apk_path = os.path.join(temp_dir, "magisk.apk")
                
                with open(apk_path, "wb") as f:
                    f.write(requests.get(download_url).content)
                
                self.append_output("Magisk downloaded, installing...")
                
                # Install APK
                return_code, output = self.device_manager.execute_adb_command(f"install {apk_path}")
                self.append_output(output)
                
                if return_code == 0:
                    self.append_output("Magisk installed successfully")
                else:
                    self.append_output("Failed to install Magisk")
            else:
                self.append_output(f"Failed to download Magisk: HTTP {response.status_code}")
        except Exception as e:
            self.append_output(f"Error installing Magisk: {str(e)}")
    
    def remove_root(self):
        confirm = QMessageBox.question(
            self, "Confirm Remove Root", 
            "This will attempt to remove root access from your device. Continue?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        
        if confirm == QMessageBox.StandardButton.Yes:
            self.append_output("Attempting to remove root access...")
            
            # Try SuperSU uninstall
            return_code, output = self.device_manager.execute_adb_command("shell su -c 'echo \"pm uninstall eu.chainfire.supersu\" > /cache/uninstall.sh'")
            return_code, output = self.device_manager.execute_adb_command("shell su -c 'chmod 755 /cache/uninstall.sh'")
            return_code, output = self.device_manager.execute_adb_command("shell su -c '/cache/uninstall.sh'")
            self.append_output(output)
            
            # Try Magisk uninstall
            return_code, output = self.device_manager.execute_adb_command("shell su -c 'magisk --remove-modules'")
            self.append_output(output)
            
            # Remove su binaries
            return_code, output = self.device_manager.execute_adb_command("shell su -c 'rm -rf /system/bin/su /system/xbin/su /system/bin/.ext /system/etc/.installed_su_daemon'")
            self.append_output(output)
            
            self.append_output("Root removal attempted. Reboot your device to complete the process.")
    
    def mount_system_rw(self):
        self.append_output("Mounting /system as read-write...")
        return_code, output = self.device_manager.execute_adb_command("shell su -c 'mount -o remount,rw /system'")
        self.append_output(output)
        
        if return_code == 0:
            self.append_output("/system mounted as read-write")
        else:
            self.append_output("Failed to mount /system as read-write")
    
    def remount_partitions(self):
        self.append_output("Remounting partitions...")
        return_code, output = self.device_manager.execute_adb_command("shell su -c 'mount -o remount,rw /'")
        self.append_output(output)
        
        if return_code == 0:
            self.append_output("Partitions remounted successfully")
        else:
            self.append_output("Failed to remount partitions")
    
    def push_to_system(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Select File to Push", "", "All Files (*)"
        )
        
        if file_path:
            dest_path, ok = QInputDialog.getText(
                self, "Destination Path", "Enter destination path in /system:",
                QLineEdit.EchoMode.Normal, "/system/"
            )
            
            if ok and dest_path:
                self.append_output(f"Pushing {file_path} to {dest_path}...")
                return_code, output = self.device_manager.execute_adb_command(f"push {file_path} {dest_path}")
                self.append_output(output)
                
                if return_code == 0:
                    self.append_output("File pushed successfully")
                    
                    # Set permissions
                    perms, ok = QInputDialog.getText(
                        self, "Set Permissions", "Enter permissions (e.g. 644):",
                        QLineEdit.EchoMode.Normal, "644"
                    )
                    
                    if ok and perms:
                        return_code, output = self.device_manager.execute_adb_command(f"shell su -c 'chmod {perms} {dest_path}'")
                        self.append_output(output)
                else:
                    self.append_output("Failed to push file")
    
    def pull_from_system(self):
        src_path, ok = QInputDialog.getText(
            self, "Source Path", "Enter file path in /system to pull:",
            QLineEdit.EchoMode.Normal, "/system/"
        )
        
        if ok and src_path:
            dest_path, _ = QFileDialog.getSaveFileName(
                self, "Save File", os.path.basename(src_path), "All Files (*)"
            )
            
            if dest_path:
                self.append_output(f"Pulling {src_path} to {dest_path}...")
                return_code, output = self.device_manager.execute_adb_command(f"pull {src_path} {dest_path}")
                self.append_output(output)
                
                if return_code == 0:
                    self.append_output("File pulled successfully")
                else:
                    self.append_output("Failed to pull file")
    
    def open_root_shell(self):
        self.append_output("Opening root shell...")
        self.append_output("Type 'exit' to quit the shell")
        
        # Start a thread for the shell
        thread = threading.Thread(target=self.run_root_shell, daemon=True)
        thread.start()
    
    def run_root_shell(self):
        try:
            process = subprocess.Popen(
                [self.device_manager.adb_path, "-s", self.device_manager.current_device, "shell", "su"],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                universal_newlines=True
            )
            
            while True:
                command = input("root@android:# ")  # This won't work well with Qt, needs improvement
                if command.lower() == "exit":
                    break
                
                process.stdin.write(command + "\n")
                process.stdin.flush()
                
                output = process.stdout.readline()
                while output:
                    self.append_output(output.strip())
                    output = process.stdout.readline()
        except Exception as e:
            self.append_output(f"Shell error: {str(e)}")
    
    def fix_permissions(self):
        self.append_output("Fixing permissions on /system...")
        return_code, output = self.device_manager.execute_adb_command("shell su -c 'find /system -type d -exec chmod 755 {} \\;'")
        self.append_output(output)
        
        return_code, output = self.device_manager.execute_adb_command("shell su -c 'find /system -type f -exec chmod 644 {} \\;'")
        self.append_output(output)
        
        self.append_output("Permissions fixed")
    
    def install_busybox(self):
        self.append_output("Installing BusyBox...")
        
        # Download BusyBox
        url = "https://busybox.net/downloads/binaries/1.31.0-defconfig-multiarch-musl/busybox-armv7l"
        
        try:
            response = requests.get(url)
            if response.status_code == 200:
                # Save to temp file
                temp_dir = tempfile.gettempdir()
                busybox_path = os.path.join(temp_dir, "busybox")
                
                with open(busybox_path, "wb") as f:
                    f.write(response.content)
                
                # Push to device
                return_code, output = self.device_manager.execute_adb_command(f"push {busybox_path} /data/local/tmp/busybox")
                self.append_output(output)
                
                if return_code != 0:
                    self.append_output("Failed to push BusyBox to device")
                    return
                
                # Install
                return_code, output = self.device_manager.execute_adb_command("shell su -c 'mv /data/local/tmp/busybox /system/xbin/busybox'")
                return_code, output = self.device_manager.execute_adb_command("shell su -c 'chmod 755 /system/xbin/busybox'")
                return_code, output = self.device_manager.execute_adb_command("shell su -c '/system/xbin/busybox --install /system/xbin'")
                self.append_output(output)
                
                if return_code == 0:
                    self.append_output("BusyBox installed successfully")
                else:
                    self.append_output("Failed to install BusyBox")
            else:
                self.append_output(f"Failed to download BusyBox: HTTP {response.status_code}")
        except Exception as e:
            self.append_output(f"Error installing BusyBox: {str(e)}")
    
    def append_output(self, text):
        cursor = self.output_text.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        cursor.insertText(text + "\n")
        self.output_text.setTextCursor(cursor)
        self.output_text.ensureCursorVisible()

class BuildPropEditorTab(QWidget):
    def __init__(self, device_manager):
        super().__init__()
        self.device_manager = device_manager
        self.build_prop_content = ""
        self.init_ui()
    
    def init_ui(self):
        layout = QVBoxLayout()
        
        # Toolbar
        toolbar = QHBoxLayout()
        
        self.load_btn = QPushButton("Load build.prop")
        self.load_btn.clicked.connect(self.load_build_prop)
        
        self.save_btn = QPushButton("Save build.prop")
        self.save_btn.clicked.connect(self.save_build_prop)
        
        self.edit_btn = QPushButton("Edit Property")
        self.edit_btn.clicked.connect(self.edit_property)
        
        self.add_btn = QPushButton("Add Property")
        self.add_btn.clicked.connect(self.add_property)
        
        self.delete_btn = QPushButton("Delete Property")
        self.delete_btn.clicked.connect(self.delete_property)
        
        toolbar.addWidget(self.load_btn)
        toolbar.addWidget(self.save_btn)
        toolbar.addWidget(self.edit_btn)
        toolbar.addWidget(self.add_btn)
        toolbar.addWidget(self.delete_btn)
        
        # Build.prop display
        self.build_prop_table = QTreeWidget()
        self.build_prop_table.setHeaderLabels(["Property", "Value"])
        self.build_prop_table.setColumnWidth(0, 300)
        
        # Add to layout
        layout.addLayout(toolbar)
        layout.addWidget(self.build_prop_table)
        
        self.setLayout(layout)
    
    def load_build_prop(self):
        if not self.device_manager.current_device:
            QMessageBox.warning(self, "Error", "No device selected")
            return
        
        # Check root
        return_code, output = self.device_manager.execute_adb_command("shell su -c 'echo Root check'")
        if return_code != 0 or "Root check" not in output:
            QMessageBox.warning(self, "Error", "Root access is required to edit build.prop")
            return
        
        # Pull build.prop to temp file
        temp_dir = tempfile.gettempdir()
        temp_file = os.path.join(temp_dir, "build.prop")
        
        return_code, output = self.device_manager.execute_adb_command(f"pull /system/build.prop {temp_file}")
        
        if return_code != 0:
            QMessageBox.warning(self, "Error", f"Failed to pull build.prop: {output}")
            return
        
        # Read file
        try:
            with open(temp_file, "r", encoding="utf-8") as f:
                self.build_prop_content = f.read()
            
            self.parse_build_prop()
            QMessageBox.information(self, "Success", "build.prop loaded successfully")
        except Exception as e:
            QMessageBox.warning(self, "Error", f"Failed to read build.prop: {str(e)}")
    
    def save_build_prop(self):
        if not self.build_prop_content:
            QMessageBox.warning(self, "Error", "No build.prop content to save")
            return
        
        if not self.device_manager.current_device:
            QMessageBox.warning(self, "Error", "No device selected")
            return
        
        # Check root
        return_code, output = self.device_manager.execute_adb_command("shell su -c 'echo Root check'")
        if return_code != 0 or "Root check" not in output:
            QMessageBox.warning(self, "Error", "Root access is required to edit build.prop")
            return
        
        # Create temp file with new content
        temp_dir = tempfile.gettempdir()
        temp_file = os.path.join(temp_dir, "build.prop")
        
        try:
            with open(temp_file, "w", encoding="utf-8") as f:
                f.write(self.build_prop_content)
        except Exception as e:
            QMessageBox.warning(self, "Error", f"Failed to create temp file: {str(e)}")
            return
        
        # Remount /system as RW
        return_code, output = self.device_manager.execute_adb_command("shell su -c 'mount -o remount,rw /system'")
        if return_code != 0:
            QMessageBox.warning(self, "Error", f"Failed to remount /system as RW: {output}")
            return
        
        # Backup original build.prop
        return_code, output = self.device_manager.execute_adb_command("shell su -c 'cp /system/build.prop /system/build.prop.bak'")
        if return_code != 0:
            QMessageBox.warning(self, "Error", f"Failed to backup build.prop: {output}")
            return
        
        # Push new build.prop
        return_code, output = self.device_manager.execute_adb_command(f"push {temp_file} /system/build.prop")
        if return_code != 0:
            QMessageBox.warning(self, "Error", f"Failed to push new build.prop: {output}")
            
            # Restore backup
            self.device_manager.execute_adb_command("shell su -c 'mv /system/build.prop.bak /system/build.prop'")
            return
        
        # Set permissions
        return_code, output = self.device_manager.execute_adb_command("shell su -c 'chmod 644 /system/build.prop'")
        if return_code != 0:
            QMessageBox.warning(self, "Error", f"Failed to set permissions: {output}")
            return
        
        QMessageBox.information(
            self, "Success", 
            "build.prop updated successfully. Reboot your device for changes to take effect."
        )
    
    def parse_build_prop(self):
        self.build_prop_table.clear()
        
        for line in self.build_prop_content.splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                parts = line.split("=", 1)
                if len(parts) == 2:
                    prop = parts[0].strip()
                    value = parts[1].strip()
                    
                    item = QTreeWidgetItem()
                    item.setText(0, prop)
                    item.setText(1, value)
                    self.build_prop_table.addTopLevelItem(item)
    
    def edit_property(self):
        selected_items = self.build_prop_table.selectedItems()
        if not selected_items:
            QMessageBox.warning(self, "Error", "No property selected")
            return
        
        item = selected_items[0]
        prop = item.text(0)
        current_value = item.text(1)
        
        new_value, ok = QInputDialog.getText(
            self, "Edit Property", f"Enter new value for {prop}:",
            QLineEdit.EchoMode.Normal, current_value
        )
        
        if ok and new_value != current_value:
            item.setText(1, new_value)
            self.update_build_prop_content()
    
    def add_property(self):
        prop, ok1 = QInputDialog.getText(
            self, "Add Property", "Enter property name:",
            QLineEdit.EchoMode.Normal
        )
        
        if ok1 and prop:
            value, ok2 = QInputDialog.getText(
                self, "Add Property", "Enter property value:",
                QLineEdit.EchoMode.Normal
            )
            
            if ok2:
                # Add to tree
                item = QTreeWidgetItem()
                item.setText(0, prop)
                item.setText(1, value)
                self.build_prop_table.addTopLevelItem(item)
                
                # Add to content
                self.build_prop_content += f"\n{prop}={value}"
                self.update_build_prop_content()
    
    def delete_property(self):
        selected_items = self.build_prop_table.selectedItems()
        if not selected_items:
            QMessageBox.warning(self, "Error", "No property selected")
            return
        
        item = selected_items[0]
        prop = item.text(0)
        
        confirm = QMessageBox.question(
            self, "Confirm Delete", 
            f"Are you sure you want to delete property {prop}?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        
        if confirm == QMessageBox.StandardButton.Yes:
            self.build_prop_table.takeTopLevelItem(self.build_prop_table.indexOfTopLevelItem(item))
            self.update_build_prop_content()
    
    def update_build_prop_content(self):
        # Rebuild content from tree
        new_content = []
        comment_lines = []
        
        # Preserve comments and empty lines from original
        for line in self.build_prop_content.splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                comment_lines.append(line)
        
        # Add properties from tree
        prop_lines = []
        for i in range(self.build_prop_table.topLevelItemCount()):
            item = self.build_prop_table.topLevelItem(i)
            prop_lines.append(f"{item.text(0)}={item.text(1)}")
        
        # Combine comments and properties
        new_content.extend(comment_lines)
        new_content.extend(prop_lines)
        
        self.build_prop_content = "\n".join(new_content)

class RecoveryToolsTab(QWidget):
    def __init__(self, device_manager):
        super().__init__()
        self.device_manager = device_manager
        self.init_ui()
    
    def init_ui(self):
        layout = QVBoxLayout()
        
        # Recovery Control Group
        control_group = QGroupBox("Recovery Control")
        control_layout = QVBoxLayout()
        
        self.reboot_recovery_btn = QPushButton("Reboot to Recovery")
        self.reboot_recovery_btn.clicked.connect(lambda: self.device_manager.reboot_device("recovery"))
        
        self.reboot_bootloader_btn = QPushButton("Reboot to Bootloader")
        self.reboot_bootloader_btn.clicked.connect(lambda: self.device_manager.reboot_device("bootloader"))
        
        self.reboot_system_btn = QPushButton("Reboot to System")
        self.reboot_system_btn.clicked.connect(lambda: self.device_manager.reboot_device("system"))
        
        btn_layout = QHBoxLayout()
        btn_layout.addWidget(self.reboot_recovery_btn)
        btn_layout.addWidget(self.reboot_bootloader_btn)
        btn_layout.addWidget(self.reboot_system_btn)
        
        control_layout.addLayout(btn_layout)
        control_group.setLayout(control_layout)
        
        # TWRP Specific Group
        twrp_group = QGroupBox("TWRP Recovery")
        twrp_layout = QVBoxLayout()
        
        self.install_zip_btn = QPushButton("Install ZIP")
        self.install_zip_btn.clicked.connect(self.install_twrp_zip)
        
        self.wipe_cache_btn = QPushButton("Wipe Cache")
        self.wipe_cache_btn.clicked.connect(lambda: self.execute_twrp_command("wipe cache"))
        
        self.wipe_dalvik_btn = QPushButton("Wipe Dalvik")
        self.wipe_dalvik_btn.clicked.connect(lambda: self.execute_twrp_command("wipe dalvik"))
        
        self.wipe_data_btn = QPushButton("Wipe Data")
        self.wipe_data_btn.clicked.connect(lambda: self.execute_twrp_command("wipe data"))
        
        self.backup_btn = QPushButton("Create Backup")
        self.backup_btn.clicked.connect(self.create_twrp_backup)
        
        self.restore_btn = QPushButton("Restore Backup")
        self.restore_btn.clicked.connect(self.restore_twrp_backup)
        
        twrp_btn_layout1 = QHBoxLayout()
        twrp_btn_layout1.addWidget(self.install_zip_btn)
        twrp_btn_layout1.addWidget(self.wipe_cache_btn)
        twrp_btn_layout1.addWidget(self.wipe_dalvik_btn)
        
        twrp_btn_layout2 = QHBoxLayout()
        twrp_btn_layout2.addWidget(self.wipe_data_btn)
        twrp_btn_layout2.addWidget(self.backup_btn)
        twrp_btn_layout2.addWidget(self.restore_btn)
        
        twrp_layout.addLayout(twrp_btn_layout1)
        twrp_layout.addLayout(twrp_btn_layout2)
        twrp_group.setLayout(twrp_layout)
        
        # Output
        self.output_text = QTextEdit()
        self.output_text.setReadOnly(True)
        self.output_text.setFont(QFont("Courier New", 10))
        
        # Add all groups to main layout
        layout.addWidget(control_group)
        layout.addWidget(twrp_group)
        layout.addWidget(self.output_text)
        
        self.setLayout(layout)
    
    def install_twrp_zip(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Select ZIP File", "", "ZIP Files (*.zip);;All Files (*)"
        )
        
        if file_path:
            # Push to device
            return_code, output = self.device_manager.execute_adb_command(f"push {file_path} /sdcard/tmp_install.zip")
            self.append_output(output)
            
            if return_code != 0:
                self.append_output("Failed to push ZIP to device")
                return
            
            # Reboot to recovery
            success, output = self.device_manager.reboot_device("recovery")
            self.append_output(output)
            
            if not success:
                self.append_output("Failed to reboot to recovery")
                return
            
            # Wait for recovery
            self.append_output("Waiting for device to enter recovery...")
            time.sleep(10)
            
            # Install
            return_code, output = self.device_manager.execute_adb_command("shell twrp install /sdcard/tmp_install.zip", device_specific=False)
            self.append_output(output)
            
            if return_code == 0:
                self.append_output("ZIP installed successfully")
            else:
                self.append_output("Failed to install ZIP")
    
    def execute_twrp_command(self, command):
        # Reboot to recovery
        success, output = self.device_manager.reboot_device("recovery")
        self.append_output(output)
        
        if not success:
            self.append_output("Failed to reboot to recovery")
            return
        
        # Wait for recovery
        self.append_output("Waiting for device to enter recovery...")
        time.sleep(10)
        
        # Execute command
        return_code, output = self.device_manager.execute_adb_command(f"shell twrp {command}", device_specific=False)
        self.append_output(output)
        
        if return_code == 0:
            self.append_output("Command executed successfully")
        else:
            self.append_output("Command failed")
    
    def create_twrp_backup(self):
        # Get backup name
        name, ok = QInputDialog.getText(
            self, "Backup Name", "Enter backup name:",
            QLineEdit.EchoMode.Normal, datetime.now().strftime("%Y%m%d_%H%M%S")
        )
        
        if ok and name:
            # Reboot to recovery
            success, output = self.device_manager.reboot_device("recovery")
            self.append_output(output)
            
            if not success:
                self.append_output("Failed to reboot to recovery")
                return
            
            # Wait for recovery
            self.append_output("Waiting for device to enter recovery...")
            time.sleep(10)
            
            # Create backup
            return_code, output = self.device_manager.execute_adb_command(f"shell twrp backup {name}", device_specific=False)
            self.append_output(output)
            
            if return_code == 0:
                self.append_output("Backup created successfully")
            else:
                self.append_output("Failed to create backup")
    
    def restore_twrp_backup(self):
        # Get backup name
        name, ok = QInputDialog.getText(
            self, "Backup Name", "Enter backup name to restore:",
            QLineEdit.EchoMode.Normal
        )
        
        if ok and name:
            # Reboot to recovery
            success, output = self.device_manager.reboot_device("recovery")
            self.append_output(output)
            
            if not success:
                self.append_output("Failed to reboot to recovery")
                return
            
            # Wait for recovery
            self.append_output("Waiting for device to enter recovery...")
            time.sleep(10)
            
            # Restore backup
            return_code, output = self.device_manager.execute_adb_command(f"shell twrp restore {name}", device_specific=False)
            self.append_output(output)
            
            if return_code == 0:
                self.append_output("Backup restored successfully")
            else:
                self.append_output("Failed to restore backup")
    
    def append_output(self, text):
        cursor = self.output_text.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        cursor.insertText(text + "\n")
        self.output_text.setTextCursor(cursor)
        self.output_text.ensureCursorVisible()

class SettingsTab(QWidget):
    def __init__(self, device_manager):
        super().__init__()
        self.device_manager = device_manager
        self.init_ui()
        self.load_settings()
    
    def init_ui(self):
        layout = QVBoxLayout()
        
        # Path Settings Group
        path_group = QGroupBox("Path Settings")
        path_layout = QFormLayout()
        
        self.adb_path_edit = QLineEdit()
        self.adb_path_browse = QPushButton("Browse...")
        self.adb_path_browse.clicked.connect(lambda: self.browse_path(self.adb_path_edit))
        
        self.fastboot_path_edit = QLineEdit()
        self.fastboot_path_browse = QPushButton("Browse...")
        self.fastboot_path_browse.clicked.connect(lambda: self.browse_path(self.fastboot_path_edit))
        
        path_layout.addRow("ADB Path:", self.create_path_row(self.adb_path_edit, self.adb_path_browse))
        path_layout.addRow("Fastboot Path:", self.create_path_row(self.fastboot_path_edit, self.fastboot_path_browse))
        
        path_group.setLayout(path_layout)
        
        # UI Settings Group
        ui_group = QGroupBox("UI Settings")
        ui_layout = QFormLayout()
        
        self.theme_combo = QComboBox()
        self.theme_combo.addItems(["System Default", "Dark", "Light"])
        
        self.font_combo = QComboBox()
        self.font_combo.addItems(["Arial", "Courier New", "Times New Roman", "Verdana", "Segoe UI"])
        
        self.font_size_spin = QSpinBox()
        self.font_size_spin.setRange(8, 20)
        self.font_size_spin.setValue(10)
        
        ui_layout.addRow("Theme:", self.theme_combo)
        ui_layout.addRow("Font Family:", self.font_combo)
        ui_layout.addRow("Font Size:", self.font_size_spin)
        
        ui_group.setLayout(ui_layout)
        
        # Save Button
        self.save_btn = QPushButton("Save Settings")
        self.save_btn.clicked.connect(self.save_settings)
        
        # Add all groups to main layout
        layout.addWidget(path_group)
        layout.addWidget(ui_group)
        layout.addWidget(self.save_btn)
        layout.addStretch()
        
        self.setLayout(layout)
    
    def create_path_row(self, edit, browse):
        row = QHBoxLayout()
        row.addWidget(edit)
        row.addWidget(browse)
        return row
    
    def browse_path(self, target_edit):
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Select Executable", "", "Executable Files (*.exe);;All Files (*)"
        )
        
        if file_path:
            target_edit.setText(file_path)
    
    def load_settings(self):
        # Path settings
        self.adb_path_edit.setText(settings.value("adb_path", DEFAULT_ADB_PATH))
        self.fastboot_path_edit.setText(settings.value("fastboot_path", DEFAULT_FASTBOOT_PATH))
        
        # UI settings
        self.theme_combo.setCurrentText(settings.value("theme", "System Default"))
        self.font_combo.setCurrentText(settings.value("font_family", "Segoe UI"))
        self.font_size_spin.setValue(int(settings.value("font_size", 10)))
    
    def save_settings(self):
        # Path settings
        settings.setValue("adb_path", self.adb_path_edit.text())
        settings.setValue("fastboot_path", self.fastboot_path_edit.text())
        
        # Update device manager paths
        self.device_manager.adb_path = self.adb_path_edit.text()
        self.device_manager.fastboot_path = self.fastboot_path_edit.text()
        
        # UI settings
        settings.setValue("theme", self.theme_combo.currentText())
        settings.setValue("font_family", self.font_combo.currentText())
        settings.setValue("font_size", self.font_size_spin.value())
        
        QMessageBox.information(self, "Success", "Settings saved successfully")

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        
        # Initialize managers
        self.device_manager = DeviceManager()
        self.file_manager = FileManager(self.device_manager)
        self.package_manager = PackageManager(self.device_manager)
        self.backup_manager = BackupManager(self.device_manager)
        self.logcat_manager = LogcatManager(self.device_manager)
        
        self.init_ui()
        
        # Connect device manager signals
        self.device_manager.devices_updated.connect(self.update_device_list)
        self.device_manager.device_details_updated.connect(self.update_status_bar)
    
    def init_ui(self):
        self.setWindowTitle(f"{APP_NAME} v{VERSION}")
        self.setGeometry(100, 100, 1200, 800)
        
        # Set window icon
        self.setWindowIcon(QIcon("android_icon.png"))  # Replace with actual icon path
        
        # Create central widget and layout
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        main_layout = QVBoxLayout()
        central_widget.setLayout(main_layout)
        
        # Device selection toolbar
        toolbar = QHBoxLayout()
        
        self.device_combo = QComboBox()
        self.device_combo.currentIndexChanged.connect(self.device_selected)
        
        self.refresh_devices_btn = QPushButton("Refresh")
        self.refresh_devices_btn.clicked.connect(self.device_manager.update_devices)
        
        toolbar.addWidget(QLabel("Connected Devices:"))
        toolbar.addWidget(self.device_combo, 1)
        toolbar.addWidget(self.refresh_devices_btn)
        
        main_layout.addLayout(toolbar)
        
        # Create tab widget
        self.tab_widget = QTabWidget()
        
        # Add tabs
        self.tab_widget.addTab(DeviceControlTab(self.device_manager), "Device Control")
        self.tab_widget.addTab(FileExplorerTab(self.device_manager, self.file_manager), "File Explorer")
        self.tab_widget.addTab(PackageManagerTab(self.device_manager, self.package_manager), "Package Manager")
        self.tab_widget.addTab(BackupRestoreTab(self.device_manager, self.backup_manager), "Backup/Restore")
        self.tab_widget.addTab(LogcatTab(self.device_manager, self.logcat_manager), "Logcat")
        self.tab_widget.addTab(FastbootTab(self.device_manager), "Fastboot")
        self.tab_widget.addTab(SideloadTab(self.device_manager), "Sideload")
        self.tab_widget.addTab(RootToolsTab(self.device_manager), "Root Tools")
        self.tab_widget.addTab(BuildPropEditorTab(self.device_manager), "Build.prop Editor")
        self.tab_widget.addTab(RecoveryToolsTab(self.device_manager), "Recovery Tools")
        self.tab_widget.addTab(SettingsTab(self.device_manager), "Settings")
        
        main_layout.addWidget(self.tab_widget)
        
        # Status bar
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        
        self.device_status_label = QLabel("No device connected")
        self.status_bar.addPermanentWidget(self.device_status_label)
        
        # Create menu bar
        self.create_menu_bar()
        
        # Initial device refresh
        self.device_manager.update_devices()
    
    def create_menu_bar(self):
        menu_bar = self.menuBar()
        
        # File menu
        file_menu = menu_bar.addMenu("File")
        
        exit_action = QAction("Exit", self)
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)
        
        # Tools menu
        tools_menu = menu_bar.addMenu("Tools")
        
        adb_shell_action = QAction("ADB Shell", self)
        adb_shell_action.triggered.connect(self.open_adb_shell)
        tools_menu.addAction(adb_shell_action)
        
        screenshot_action = QAction("Take Screenshot", self)
        screenshot_action.triggered.connect(self.take_screenshot)
        tools_menu.addAction(screenshot_action)
        
        # Help menu
        help_menu = menu_bar.addMenu("Help")
        
        about_action = QAction("About", self)
        about_action.triggered.connect(self.show_about)
        help_menu.addAction(about_action)
        
        docs_action = QAction("Discord", self)
        docs_action.triggered.connect(self.show_documentation)
        help_menu.addAction(docs_action)
    
    def update_device_list(self, devices):
        self.device_combo.clear()
        
        for device in devices:
            device_text = f"{device['id']} ({device['type'].upper()})"
            self.device_combo.addItem(device_text, device['id'])
        
        if not devices:
            self.device_status_label.setText("No device connected")
    
    def device_selected(self, index):
        if index >= 0:
            device_id = self.device_combo.itemData(index)
            self.device_manager.set_current_device(device_id)
    
    def update_status_bar(self, details):
        if details:
            device_text = f"{details.get('model', 'Unknown')} | Android {details.get('android_version', 'Unknown')}"
            if details.get('type') == 'fastboot':
                device_text += " (Fastboot)"
            self.device_status_label.setText(device_text)
    
    def open_adb_shell(self):
        if not self.device_manager.current_device:
            QMessageBox.warning(self, "Error", "No device selected")
            return
        
        # This is a simplified version - in a real app you'd want a proper terminal emulator
        shell_dialog = QDialog(self)
        shell_dialog.setWindowTitle("ADB Shell")
        
        layout = QVBoxLayout()
        
        self.shell_output = QTextEdit()
        self.shell_output.setReadOnly(True)
        self.shell_output.setFont(QFont("Courier New", 10))
        
        self.shell_input = QLineEdit()
        self.shell_input.returnPressed.connect(self.execute_shell_command)
        
        layout.addWidget(self.shell_output)
        layout.addWidget(self.shell_input)
        
        shell_dialog.setLayout(layout)
        shell_dialog.resize(600, 400)
        shell_dialog.exec()
    
    def execute_shell_command(self):
        command = self.shell_input.text()
        self.shell_input.clear()
        
        self.shell_output.append(f"$ {command}")
        
        return_code, output = self.device_manager.execute_adb_command(f"shell {command}")
        self.shell_output.append(output)
    
    def take_screenshot(self):
        if not self.device_manager.current_device:
            QMessageBox.warning(self, "Error", "No device selected")
            return
        
        file_path, _ = QFileDialog.getSaveFileName(
            self, "Save Screenshot", "screenshot.png", "PNG Files (*.png);;All Files (*)"
        )
        
        if file_path:
            if not file_path.lower().endswith('.png'):
                file_path += '.png'
            
            return_code, output = self.device_manager.execute_adb_command(f"exec-out screencap -p > {file_path}", device_specific=False)
            
            if return_code == 0:
                QMessageBox.information(self, "Success", f"Screenshot saved to {file_path}")
            else:
                QMessageBox.warning(self, "Error", f"Failed to take screenshot: {output}")
    
    def show_about(self):
        about_text = f"""
        <h1>{APP_NAME}</h1>
        <p>Version: {VERSION}</p>
        <p>Developer: {DEVELOPER}</p>
        <p>A comprehensive Android device management tool with ADB, Fastboot, and root capabilities.</p>
        <p>Supported Android versions: {', '.join(SUPPORTED_ANDROID_VERSIONS)}</p>
        """
        
        QMessageBox.about(self, "About", about_text)
    
    def show_documentation(self):
        webbrowser.open("https://discord.gg/dDzZkCj95D")

def main():
    app = QApplication(sys.argv)
    
    # Apply dark theme if available
    try:
        from qdarktheme import setup_theme
        setup_theme()
    except ImportError:
        pass
    
    window = MainWindow()
    window.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
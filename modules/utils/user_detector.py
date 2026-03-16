# modules/utils/user_detector.py
# Automatically detects unique users based on machine fingerprint
# Allows multiple users to share the same Streamlit app with isolated data

from __future__ import annotations
import hashlib
import os
import socket
import uuid
from pathlib import Path
from typing import Optional
import config

log = config.get_logger(__name__)

# ── User Data Directory ────────────────────────────────────────────────────────
USERS_DIR = config.ROOT_DIR / "users"


def get_machine_id() -> str:
    """
    Generate a unique machine identifier.
    Combines multiple hardware identifiers for uniqueness.
    Returns a hashed string that's consistent for the same machine.
    """
    # Collect multiple identifiers
    identifiers = []
    
    # 1. MAC address (most reliable)
    try:
        mac = ':'.join(['{:02x}'.format((uuid.getnode() >> elements) & 0xff)
                       for elements in range(0, 2 * 6, 8)][::-1])
        identifiers.append(f"mac:{mac}")
    except Exception:
        pass
    
    # 2. Machine name
    try:
        identifiers.append(f"hostname:{socket.gethostname()}")
    except Exception:
        pass
    
    # 3. OS-specific identifiers
    if os.name == 'nt':  # Windows
        try:
            # Windows machine GUID from registry
            import winreg
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, 
                              r"SOFTWARE\Microsoft\Cryptography") as key:
                guid = winreg.QueryValueEx(key, "MachineGuid")[0]
                identifiers.append(f"guid:{guid}")
        except Exception:
            pass
    
    elif os.name == 'posix':  # Linux/Mac
        try:
            # Machine ID on Linux
            with open('/etc/machine-id', 'r') as f:
                identifiers.append(f"machine_id:{f.read().strip()}")
        except Exception:
            pass
        
        try:
            # Host ID on Mac/Linux
            host_id = os.popen('hostid').read().strip()
            if host_id:
                identifiers.append(f"hostid:{host_id}")
        except Exception:
            pass
    
    # 4. Fallback: IP address (least reliable but better than nothing)
    if not identifiers:
        try:
            ip = socket.gethostbyname(socket.gethostname())
            identifiers.append(f"ip:{ip}")
        except Exception:
            identifiers.append(f"fallback:{uuid.uuid4().hex}")
    
    # Combine and hash all identifiers
    combined = '|'.join(sorted(identifiers))
    machine_hash = hashlib.sha256(combined.encode()).hexdigest()[:16]
    
    log.info(f"Generated machine ID: {machine_hash} from {len(identifiers)} identifiers")
    return machine_hash


def get_user_folder(machine_id: str = None) -> Path:
    """
    Get or create the user's data folder based on machine ID.
    Returns the path to the user's isolated data directory.
    """
    if machine_id is None:
        machine_id = get_machine_id()
    
    user_dir = USERS_DIR / machine_id
    
    # Create user directory structure if it doesn't exist
    if not user_dir.exists():
        log.info(f"Creating new user folder: {user_dir}")
        user_dir.mkdir(parents=True, exist_ok=True)
        
        # Create subdirectories
        (user_dir / "data").mkdir(exist_ok=True)
        (user_dir / "resumes").mkdir(exist_ok=True)
        (user_dir / "resumes" / "tailored").mkdir(exist_ok=True)
        (user_dir / "resumes" / "cover_letters").mkdir(exist_ok=True)
        (user_dir / "logs").mkdir(exist_ok=True)
        
        # Copy default .env if available
        env_example = config.ROOT_DIR / ".env.example"
        if env_example.exists():
            import shutil
            shutil.copy(env_example, user_dir / ".env")
            log.info(f"Copied .env.example to {user_dir / '.env'}")
    
    return user_dir


def get_user_config(machine_id: str = None) -> dict:
    """
    Get configuration paths for the current user.
    Returns a dict with all user-specific paths.
    """
    user_dir = get_user_folder(machine_id)
    
    return {
        "user_id": machine_id or get_machine_id(),
        "user_dir": user_dir,
        "db_path": user_dir / "data" / "auto_apply.db",
        "log_path": user_dir / "logs" / "auto_apply.log",
        "master_resume": user_dir / "resumes" / "master_resume.pdf",
        "env_file": user_dir / ".env",
        "profile_cache": user_dir / ".profile_cache.json",
        "tracker_state": user_dir / "data" / "target_tracker_state.json",
    }


def get_current_user_info() -> dict:
    """
    Get information about the current user/machine.
    Returns user info for display in UI.
    """
    machine_id = get_machine_id()
    user_dir = get_user_folder(machine_id)
    
    # Try to get user-friendly name from .env if it exists
    env_file = user_dir / ".env"
    user_name = f"User-{machine_id[:8]}"  # Default name
    
    if env_file.exists():
        try:
            from dotenv import dotenv_values
            env_data = dotenv_values(env_file)
            first_name = env_data.get("APPLICANT_FIRST_NAME", "")
            last_name = env_data.get("APPLICANT_LAST_NAME", "")
            if first_name and last_name:
                user_name = f"{first_name} {last_name}"
        except Exception:
            pass
    
    # Check if user has uploaded a resume
    has_resume = (user_dir / "resumes" / "master_resume.pdf").exists()
    if not has_resume:
        # Check for .docx or other formats
        resumes_dir = user_dir / "resumes"
        if resumes_dir.exists():
            for ext in ["*.pdf", "*.docx", "*.doc"]:
                resumes = list(resumes_dir.glob(ext))
                if resumes:
                    has_resume = True
                    break
    
    return {
        "user_id": machine_id,
        "display_name": user_name,
        "user_dir": str(user_dir),
        "has_resume": has_resume,
        "is_new_user": not has_resume,
    }


def list_all_users() -> list:
    """
    List all users who have used this app.
    Returns list of user info dicts.
    """
    if not USERS_DIR.exists():
        return []
    
    users = []
    for user_dir in USERS_DIR.iterdir():
        if user_dir.is_dir() and not user_dir.name.startswith('.'):
            machine_id = user_dir.name
            user_info = get_current_user_info()
            # Temporarily override for this user
            user_info["user_id"] = machine_id
            user_info["display_name"] = f"User-{machine_id[:8]}"
            
            # Try to get name from .env
            env_file = user_dir / ".env"
            if env_file.exists():
                try:
                    from dotenv import dotenv_values
                    env_data = dotenv_values(env_file)
                    first_name = env_data.get("APPLICANT_FIRST_NAME", "")
                    last_name = env_data.get("APPLICANT_LAST_NAME", "")
                    if first_name and last_name:
                        user_info["display_name"] = f"{first_name} {last_name}"
                except Exception:
                    pass
            
            users.append(user_info)
    
    return sorted(users, key=lambda x: x.get("display_name", ""))


def switch_user_context(machine_id: str) -> dict:
    """
    Switch to a different user's context.
    Updates config paths to use the specified user's data.
    Returns the new config dict.
    """
    new_config = get_user_config(machine_id)
    
    # Update config module paths (this is a bit hacky but necessary)
    config.DB_PATH = new_config["db_path"]
    config.LOG_PATH = new_config["log_path"]
    config.MASTER_RESUME = new_config["master_resume"]
    
    log.info(f"Switched to user context: {machine_id}")
    return new_config


def initialize_user_session() -> dict:
    """
    Initialize the current user's session.
    Call this at the start of each Streamlit session.
    Returns user config and info.
    """
    machine_id = get_machine_id()
    user_config = get_user_config(machine_id)
    user_info = get_current_user_info()
    
    log.info(f"Initialized session for user: {user_info['display_name']} ({machine_id})")
    
    return {
        "config": user_config,
        "info": user_info,
    }
